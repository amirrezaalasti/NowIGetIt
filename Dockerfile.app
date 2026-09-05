# Railway app: Next.js (MCP + UI) + FastAPI orchestration.
# Manim stays on the existing worker (RENDER_WORKER_URL). Do not replace Dockerfile.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    ENABLE_MANIM_RENDER=false \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json next.config.ts postcss.config.mjs ./
COPY src ./src
COPY public ./public
COPY api ./api
COPY backend ./backend
COPY scripts/start-app.sh ./scripts/start-app.sh
RUN chmod +x ./scripts/start-app.sh \
    && npm run build \
    && npm prune --omit=dev

ENV NODE_ENV=production

EXPOSE 8080
CMD ["./scripts/start-app.sh"]
