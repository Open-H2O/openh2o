# SPDX-License-Identifier: AGPL-3.0-or-later
"""A use area redrawn takes its shares of OpenET's fields again."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


@receiver(pre_save, sender="parcels.Parcel")
def note_geometry_change(sender, instance, raw=False, **kwargs):
    """Read the stored outline before the save and note whether the save changes it."""
    instance._outline_changed = False
    if raw or instance.pk is None:
        return
    stored = sender.objects.filter(pk=instance.pk).values_list("geometry", flat=True).first()
    new = instance.geometry
    if stored is None and new is None:
        return
    instance._outline_changed = stored is None or new is None or stored.wkb != new.wkb


@receiver(post_save, sender="parcels.Parcel")
def recompute_shares(sender, instance, created=False, raw=False, **kwargs):
    if raw or created or not getattr(instance, "_outline_changed", False):
        return
    from datasync import field_list
    from datasync.models import OpenETField

    instance._outline_changed = False
    if OpenETField.objects.filter(geometry__isnull=False).exists():
        field_list.compute_shares(instance)
