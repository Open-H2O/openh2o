# SPDX-License-Identifier: AGPL-3.0-or-later
"""The file attached to a correction: stored under a random name, served only to a signed-in user.

A correction may carry one file, a photo of the meter or a scanned page.
:func:`check_upload` refuses anything that is not an image or a PDF by what the
file's first bytes say AND by its extension, so an executable renamed ``.png``
is refused as surely as a ``.exe``. :func:`store` writes it under
``MEDIA_ROOT/corrections/`` with a random name exactly as
``core/pending_imports.py`` stores an import (the uploaded name is kept only as
a label and as the download name), and records it as a
:class:`core.models.RecordAttachment` on the new record. ``core:record_attachment``
streams it to a signed-in user; no static path ever points at the folder.
"""

import uuid
from pathlib import Path

from django.conf import settings
from core.models import RecordAttachment

FOLDER = "corrections"

#: The one sentence beside the field for a file that is not a photo or a PDF.
NOT_A_PHOTO_OR_PDF = "Attach a photo or a PDF."

#: The sentence for a file over the upload ceiling.
TOO_LARGE = "That file is too large. Attach one under {limit} MB."

#: Extensions allowed per kind of file; the first bytes must agree.
_EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/gif": {".gif"},
    "image/webp": {".webp"},
    "image/heic": {".heic", ".heif"},
    "application/pdf": {".pdf"},
}

_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def sniff(head):
    """The content type the first bytes say, or ``""`` for a file that is neither an image nor a PDF."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "image/heic"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return ""


def check_upload(uploaded):
    """``(content_type, "")`` for a good file, ``("", sentence)`` for one to refuse."""
    limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
    if uploaded.size > limit:
        return "", TOO_LARGE.format(limit=limit // (1024 * 1024))
    uploaded.seek(0)
    head = uploaded.read(16)
    uploaded.seek(0)
    content_type = sniff(head)
    extension = Path(uploaded.name).suffix.lower()
    if not content_type or extension not in _EXTENSIONS[content_type]:
        return "", NOT_A_PHOTO_OR_PDF
    return content_type, ""


def store(uploaded, content_type, *, kind, record, user):
    """Save ``uploaded`` under a random name and record it on the new record. Returns the row."""
    extension = Path(uploaded.name).suffix.lower()
    relative = f"{FOLDER}/{uuid.uuid4().hex}{extension}"
    destination = Path(settings.MEDIA_ROOT) / relative
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with open(destination, "wb") as handle:
            for chunk in uploaded.chunks():
                handle.write(chunk)
        return RecordAttachment.objects.create(
            kind=kind,
            record_pk=record.pk,
            stored_path=relative,
            original_name=uploaded.name[:255],
            content_type=content_type,
            size_bytes=uploaded.size,
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def path_of(attachment):
    return Path(settings.MEDIA_ROOT) / attachment.stored_path


def attachment_for(kind, record_pk):
    """The file attached to the correction that wrote this record, or None."""
    return RecordAttachment.objects.filter(kind=kind, record_pk=record_pk).first()


def word(attachment):
    """The link word on a replaced record's line: Photo for an image, PDF for a PDF."""
    return "PDF" if attachment.content_type == "application/pdf" else "Photo"


def remove_file(attachment):
    """Delete the stored file; one already gone is fine."""
    path_of(attachment).unlink(missing_ok=True)
