FROM python:3.11-slim

WORKDIR /app

# System dependencies
# libgl1 + libglib2.0-0 + libsm6 + libxext6 + libxrender1 : OpenCV (cv2) headless
# libgomp1                                                  : OpenMP for torch / mediapipe
# gcc + g++                                                 : build wheels (scipy, scikit-learn)
# curl                                                      : docker-compose health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# DATA_DIR must match the volume mount in docker-compose.prod.yml
# (backend_data:/app/data). processor.py defaults to /backend/data which is
# wrong inside the container; this env var overrides that default.
ENV DATA_DIR=/app/data

# Pre-create the data directories the backend and AI service both expect.
# The docker-compose volume is bind-mounted here at runtime, so these are
# effectively no-ops once the volume is populated — but they ensure the image
# works standalone too.
RUN mkdir -p /app/data/face_images/known \
             /app/data/face_images/unknown \
             /app/data/raw_videos

# Non-root user
RUN addgroup --system sentinelcv \
 && adduser --system --ingroup sentinelcv sentinelcv \
 && chown -R sentinelcv:sentinelcv /app

USER sentinelcv

EXPOSE 8001

# Entrypoint confirmed: processor.py defines app = FastAPI() at module level.
# __main__ block uses uvicorn.run("processor:app", host="0.0.0.0", port=8001).
CMD ["uvicorn", "processor:app", "--host", "0.0.0.0", "--port", "8001"]
