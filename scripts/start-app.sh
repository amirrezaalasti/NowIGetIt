#!/bin/sh
set -eu

API_PORT="${API_PORT:-8000}"
WEB_PORT="${PORT:-3000}"

python -m uvicorn api.index:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

python - <<'PY'
import time, urllib.request, sys
url = "http://127.0.0.1:8000/api/health"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as res:
            if 200 <= res.status < 300:
                sys.exit(0)
    except Exception:
        time.sleep(0.5)
print("FastAPI did not become ready on :8000", file=sys.stderr)
sys.exit(1)
PY

trap 'kill $API_PID 2>/dev/null || true' INT TERM EXIT
exec npx next start --hostname 0.0.0.0 --port "$WEB_PORT"
