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
    && rm -rf /var/lib/apt/lists/*

# GeoDjango library paths (Debian bookworm)
# GDAL/GEOS libraries are in standard Debian paths; Django finds them automatically

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Download Tailwind standalone binary
RUN curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 \
    && chmod +x tailwindcss-linux-x64

# Copy project code
COPY . .

# Compile Tailwind CSS (standalone binary, no Node.js)
RUN ./tailwindcss-linux-x64 -i static/css/input.css -o static/css/output.css --minify

EXPOSE 8000

CMD ["sh", "-c", "python manage.py collectstatic --noinput --clear && python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
