# NowIGetIt

Turn a natural-language prompt into an educational video pipeline:

1. **Plan** — LLM writes a JSON multi-scene description  
2. **Build each scene** — ManimGL code → optional render → **VLM check** → revise  
3. **Voice** — text-to-speech for each scene’s narration  
4. **Final debug** — model reviews the full set of scenes again  

**Frontend:** Next.js (Vercel)  
**Backend:** FastAPI / Python (Vercel Python runtime)  
**Default LLM / VLM:** `google/gemini-3.6-flash` via [OpenRouter](https://openrouter.ai)

## Project layout

```
├── src/                 # Next.js App Router UI
├── api/index.py         # FastAPI entry (Vercel)
├── backend/             # Pipeline: plan → generate → VLM → TTS → debug
├── legacy/              # Previous Streamlit / ManimForge app
├── pyproject.toml
└── vercel.json
```

## Pipeline details

| Step | What happens |
|------|----------------|
| Plan | Prompt → structured `ScenePlan` JSON (title, scenes, narration, visuals) |
| Per scene | Generate Manim code → render (local only) → Gemini VLM review → revise up to `MAX_SCENE_REVISIONS` |
| TTS | Narration → speech audio (`TTS_*` OpenAI-compatible API; OpenRouter has no TTS) |
| Final | Cross-scene debug pass; optional last code fixes |

> **Manim on Vercel:** Serverless cannot run ManimGL/OpenGL. On Vercel the API produces the scene plan, code, VLM feedback, and TTS. Set `ENABLE_MANIM_RENDER=true` locally (with `manimgl` + ffmpeg) to produce video files.

## Debug artifacts

Every run writes a folder under `artifacts/{job_id}/`:

```
artifacts/{job_id}/
├── meta.json
├── scene_plan.json          # full JSON scene description
├── events.jsonl
├── final_debug.json
├── result.json
└── scenes/{scene_id}/
    ├── section.json
    ├── code_r0.py … code_final.py
    ├── vlm_r0.json          # VLM review payload
    └── vlm_r0_frame.png     # exact frame the VLM inspected
```

When Manim is off, a **storyboard frame** is generated so the VLM still receives an image and you can inspect what it saw.

Browse via the UI debug inspector, or:

- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/file/scene_plan.json`
- `GET /api/jobs/{job_id}/file/scenes/{scene_id}/vlm_r0_frame.png`

## Local development

### 1. Env

```bash
cp .env.example .env.local
# also export the same vars for the API process, or:
cp .env.example .env
```

Required:

- `OPENROUTER_API_KEY`

Optional:

- `TTS_API_KEY` / `TTS_BASE_URL` / `TTS_MODEL` / `TTS_VOICE`
- `ENABLE_MANIM_RENDER=true` for local video output

### 2. Python API (Python 3.12 + Manim)

```bash
# Prefer Homebrew Python 3.12 — Manim does not support 3.14 yet
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools==70.3.0 wheel
pip install -r requirements.txt

# macOS system deps (if missing):
# brew install ffmpeg cairo pango pkg-config glew

# Enable local video rendering in .env:
# ENABLE_MANIM_RENDER=true

npm run dev:api
```

### 3. Next.js

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). In development, Next rewrites `/api/*` to `http://127.0.0.1:8000` when `NEXT_PUBLIC_API_BASE_URL` is unset.

## Deploy on Vercel

Deploy this repo as one Vercel project (Next.js + `api/index.py`):

1. Set env vars in the Vercel project: `OPENROUTER_API_KEY`, optional `TTS_*`, `OPENROUTER_MODEL=google/gemini-3.6-flash`
2. Leave `NEXT_PUBLIC_API_BASE_URL` empty in production (same-origin `/api`)
3. `maxDuration` for the Python function is `300`s in `vercel.json` (raise on Pro if needed)

Alternatively, deploy **frontend** and **API** as two Vercel projects and point `NEXT_PUBLIC_API_BASE_URL` at the FastAPI deployment URL.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Config / readiness |
| POST | `/api/generate` | Full pipeline → JSON result |
| POST | `/api/generate/stream` | NDJSON live progress events |

Example body:

```json
{
  "prompt": "Explain gradient descent on a parabola",
  "resolution": "720p",
  "skip_render": false
}
```

## Legacy

The previous Streamlit app lives under `legacy/` for reference.
