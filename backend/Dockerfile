FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories and non-root user
RUN mkdir -p data/face_images data/raw_videos && \
    addgroup --system sentinelcv && \
    adduser --system --ingroup sentinelcv sentinelcv && \
    chown -R sentinelcv:sentinelcv /app

USER sentinelcv

EXPOSE 8000

# Use Gunicorn with Uvicorn workers in production.
# GUNICORN_WORKERS defaults to 4; override via env for smaller machines.
CMD gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${GUNICORN_WORKERS:-4} \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
