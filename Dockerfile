FROM python:3.12-slim

# System dependencies for GeoDjango (GDAL, GEOS, PROJ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gettext \
    gcc \
    python3-dev \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# GeoDjango library paths (Debian bookworm)
# GDAL/GEOS libraries are in standard Debian paths; Django finds them automatically

WORKDIR /app

# Install Python dependencies from the hash-locked lockfile. --require-hashes
# makes the build reproducible and tamper-evident: pip refuses any wheel whose
# hash is not pinned in requirements.lock, so a rebuild can never silently pull a
# newer or compromised release. Regenerate the lock after changing pyproject with:
#   uv pip compile pyproject.toml --extra dev --generate-hashes --universal \
#     --python-version 3.12 -o requirements.lock
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Download Tailwind standalone binary
RUN curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 \
    && chmod +x tailwindcss-linux-x64

# Copy project code
COPY . .

# Compile Tailwind CSS (standalone binary, no Node.js)
RUN ./tailwindcss-linux-x64 -i static/css/input.css -o static/css/output.css --minify

# Build version stamp (git describe, passed at build time) — baked into the image
# so the running app can report exactly which commit it is. Defaults to "dev" for
# un-stamped local builds. See the Makefile `deploy` target and core.context_processors.app_version.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

# Unprivileged runtime user. The image builds as root (apt, pip, collectstatic);
# the entrypoint drops to this user before exec-ing gunicorn so the request-serving
# process that touches untrusted uploads never runs as root. Own the writable dirs
# in the image so a FRESH named volume inherits app ownership (existing volumes are
# re-chowned at startup by the entrypoint).
RUN useradd --system --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles /app/logs \
    && chown -R app:app /app/media /app/staticfiles /app/logs \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000

# Liveness: 200 the moment gunicorn is serving. Caddy's readiness gate
# (depends_on: service_healthy) and any restart key off this, so a boot never
# forwards traffic to a not-yet-listening web container (no boot-time 502s).
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/live/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
