# Railway Manim render worker (Manim Community Edition + ffmpeg)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENABLE_MANIM_RENDER=true \
    RENDER_WORKER_MODE=true \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    pkg-config \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpango1.0-dev \
    libffi-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-bin \
    fontconfig \
    fonts-noto-core \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-render.txt ./
RUN pip install --no-cache-dir -r requirements-render.txt

COPY backend ./backend
COPY render_worker ./render_worker

EXPOSE 8080
CMD sh -c "uvicorn render_worker.main:app --host 0.0.0.0 --port ${PORT:-8080}"
