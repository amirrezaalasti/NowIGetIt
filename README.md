# NowIGetIt

[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Manim](https://img.shields.io/badge/Manim-GL-e07a5f?logo=python&logoColor=white)](https://3b1b.github.io/manim/)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/)
[![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-6366f1)](https://openrouter.ai/)
[![License](https://img.shields.io/badge/License-Proprietary-red)](./LICENSE)

Turn a natural-language prompt into an educational video — plan scenes with an LLM, generate Manim animations, review frames with a VLM, and narrate with TTS.

## Features

- **LLM scene planning** — structured multi-scene JSON from a single prompt
- **Manim code generation** — per-scene animation scripts with iterative revision
- **VLM frame review** — vision model checks rendered (or storyboard) frames for accuracy
- **Text-to-speech** — narration audio via any OpenAI-compatible TTS API
- **Live progress** — streaming NDJSON events while the pipeline runs
- **Debug artifacts** — full job history: plans, code revisions, VLM frames, and results
- **Google sign-in** — Auth.js sessions; jobs and media are scoped per user

## Architecture

```
Prompt → Plan → [Generate → Render → VLM → Revise] × N → TTS → Final Debug → Video
```

| Step | Description |
|------|-------------|
| **Plan** | Prompt → structured `ScenePlan` (title, scenes, narration, visuals) |
| **Per scene** | Manim code → render → VLM review → revise up to `MAX_SCENE_REVISIONS` |
| **TTS** | Narration → speech via OpenRouter (`google/gemini-3.1-flash-tts-preview`) |
| **Final** | Cross-scene debug pass with optional last code fixes |

**Deploy split**
- **Vercel** — Next.js UI + FastAPI orchestration (plan, codegen, VLM, TTS, quotas)
- **Railway** — Manim Community Edition render worker (`Dockerfile.railway`, `POST /render`)
- **Local** — set `ENABLE_MANIM_RENDER=true` to render in-process (no Railway needed)

Set `RENDER_WORKER_URL` + `RENDER_WORKER_SECRET` on Vercel to offload Manim to Railway.

**Stack:** Next.js · FastAPI · OpenRouter · Manim CE (Railway/local) · Supabase

## Project layout

```
├── src/                    # Next.js App Router UI
├── api/index.py            # FastAPI entry (Vercel)
├── render_worker/          # Manim HTTP worker (Railway)
├── backend/                # Pipeline: plan → generate → VLM → TTS
├── Dockerfile.railway      # Railway Manim image
├── railway.toml
├── requirements-render.txt # Worker deps
└── vercel.json
```

## Getting started

### Prerequisites

- Node.js 20+
- Python 3.12 (Manim does not support 3.14 yet)
- [OpenRouter API key](https://openrouter.ai/)
- Optional: ffmpeg, cairo, pango, glew (for local Manim renders)

### 1. Environment

```bash
cp .env.example .env.local
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `OPENROUTER_MODEL` | No | Text LLM (default in `.env.example`) |
| `OPENROUTER_VLM_MODEL` | No | Vision model for frame review |
| `TTS_*` | No | OpenRouter TTS (defaults to Gemini 3.1 Flash TTS / voice `Kore`; key falls back to `OPENROUTER_API_KEY`) |
| `ENABLE_MANIM_RENDER` | No | `true` for local video output |
| `NEXT_PUBLIC_API_BASE_URL` | No | API origin (local: `http://127.0.0.1:8000`) |
| `AUTH_SECRET` | Yes | Shared secret for Auth.js + API JWTs (`openssl rand -hex 32`) |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Yes | Google OAuth client credentials |
| `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes (API) | Service role key for user/quota writes ([API settings](https://supabase.com/dashboard/project/rhoulajitzoaxivyfvxn/settings/api)) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Optional | Publishable/anon key (frontend; usage still goes through the API) |

Default monthly quotas per user: **40 generations**, **500k LLM tokens**, **500 MB** artifact storage (reset each calendar month).

#### Google OAuth setup

1. Create an OAuth client in [Google Cloud Console](https://console.cloud.google.com/apis/credentials) (type: Web application).
2. Authorized redirect URI: `http://localhost:3000/api/auth/callback/google` (and your production `https://…/api/auth/callback/google`).
3. Put the client ID/secret in `.env` and `.env.local` as `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET`.
4. Use the **same** `AUTH_SECRET` in both Next.js and the FastAPI process (Python loads `.env`).

### 2. Python API

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools==70.3.0 wheel
pip install -r requirements-local.txt   # API + Manim (local)
# Vercel uses requirements.txt (API only, no Manim)

# macOS (if missing):
# brew install ffmpeg cairo pango pkg-config glew

npm run dev:api
```

### 3. Next.js

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), sign in with Google, then generate. In development, Next rewrites job/generate/health routes to uvicorn when `NEXT_PUBLIC_API_BASE_URL` is unset; `/api/auth/*` stays on Next.js.

Run both with `npm run dev:all`.

## API

Protected routes (except health) require `Authorization: Bearer <token>` from `GET /api/auth/api-token` after Google sign-in. Media file URLs may use `?access_token=`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Config / readiness |
| `GET` | `/api/auth/*` | Auth.js (Next.js) |
| `POST` | `/api/generate` | Full pipeline → JSON result |
| `POST` | `/api/generate/stream` | SSE live progress events |
| `GET` | `/api/jobs` | List **your** jobs |
| `GET` | `/api/jobs/{job_id}` | Job detail (owner only) |
| `GET` | `/api/jobs/{job_id}/file/...` | Artifact files |

**Example request body:**

```json
{
  "prompt": "Explain gradient descent on a parabola",
  "resolution": "720p",
  "skip_render": false
}
```

## Debug artifacts

Every run writes under `artifacts/{job_id}/`:

```
artifacts/{job_id}/
├── meta.json
├── scene_plan.json
├── events.jsonl
├── final_debug.json
├── result.json
└── scenes/{scene_id}/
    ├── section.json
    ├── code_r0.py … code_final.py
    ├── vlm_r0.json
    └── vlm_r0_frame.png
```

When Manim is off, a **storyboard frame** is generated so the VLM still receives an image. Browse via the UI debug inspector or the job file endpoints above.

## Deploy on Vercel

Deploy as one Vercel project (Next.js + `api/index.py`):

1. Set `OPENROUTER_API_KEY`, optional `TTS_*`, and model overrides
2. Leave `NEXT_PUBLIC_API_BASE_URL` empty in production (same-origin `/api`)
3. `maxDuration` for the Python function is `300`s in `vercel.json`

Or split frontend and API into two projects and point `NEXT_PUBLIC_API_BASE_URL` at the FastAPI URL.

## Legacy

The previous Streamlit app lives under [`legacy/`](./legacy/) for reference.

## License

**Proprietary — all rights reserved.** See [`LICENSE`](./LICENSE).

This project is **not** free to use. Company, commercial, organizational, and unpaid personal use are prohibited without a written paid license from the copyright holder. For licensing: amirrezaalasti@gmail.com

---

Built with Next.js, FastAPI, Manim, and OpenRouter.
