# NowIGetIt

[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Manim](https://img.shields.io/badge/Manim-GL-e07a5f?logo=python&logoColor=white)](https://3b1b.github.io/manim/)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/)
[![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-6366f1)](https://openrouter.ai/)
[![License](https://img.shields.io/badge/License-Proprietary-red)](./LICENSE)

Turn a natural-language prompt into an educational video — or upload a PDF/deck and interrogate every section with an LLM.

## Features

- **Create (video)** — LLM scene planning, Manim codegen, VLM review, TTS narration
- **Understand (documents)** — Docling converts PDF/PPTX/DOCX/… into interactive HTML slides; click any block for explanations, quizzes, figure readouts, and more
- **ChatGPT / Claude connector** — same Create + Understand tools in chat via remote MCP (`/api/mcp`); setup at `/connect`
- **Live progress** — streaming events while pipelines run
- **Debug artifacts** — full job history scoped per user
- **Google sign-in** — Auth.js sessions; jobs and media are scoped per user, including videos created through the ChatGPT/Claude connector

## Architecture

**Create**
```
Prompt → Plan → [Generate → Render → VLM → Revise] × N → TTS → Video
```

**Understand**
```
Upload → Docling (local or Railway) → HTML slides + block ids → LLM/VLM ask on selection
```

**Deploy split**
- **Vercel** — Next.js UI + FastAPI orchestration
- **Railway (Manim)** — `Dockerfile.railway` / `POST /render`
- **Railway (Docling)** — `Dockerfile.docling` / `POST /convert`
- **Local** — Manim via `ENABLE_MANIM_RENDER=true`; Docling via `pip install -r requirements-docling.txt` or `DOCLING_WORKER_URL`

**Stack:** Next.js · FastAPI · OpenRouter · Manim CE · Docling · SQLite + local files

## Project layout

```
├── src/                    # Next.js App Router UI (/ = Create, /understand)
├── api/index.py            # FastAPI entry (Vercel)
├── render_worker/          # Manim HTTP worker (Railway)
├── docling_worker/         # Docling HTTP worker (Railway)
├── backend/                # Video pipeline + documents/ (Understand)
├── Dockerfile.railway      # Railway Manim image
├── Dockerfile.docling      # Railway Docling image
├── requirements-render.txt
├── requirements-docling.txt
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
| `OPENROUTER_MODEL` | No | General text LLM (documents / Understand) |
| `OPENROUTER_MODEL_MANIM` | No | Manim pipeline LLM (planning, codegen, code QA; falls back to `OPENROUTER_MODEL`) |
| `OPENROUTER_VLM_MODEL` | No | Vision model for frame review |
| `TTS_*` | No | OpenRouter TTS (defaults to Gemini 3.1 Flash TTS / voice `Kore`; key falls back to `OPENROUTER_API_KEY`) |
| `ENABLE_MANIM_RENDER` | No | `true` for local video output |
| `NEXT_PUBLIC_API_BASE_URL` | No | API origin (local: `http://127.0.0.1:8000`) |
| `AUTH_SECRET` | Yes | Shared secret for Auth.js + API JWTs (`openssl rand -hex 32`) |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | Yes | Google OAuth client credentials |
| `MONGODB_URI` | No | Atlas connection string. When set, users/Library/usage go to MongoDB |
| `MONGODB_DB` | No | Database name (default `nowigetit`) |
| `USE_SUPABASE` | No | Keep `false` unless you opt back into Supabase |
| `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` | No | Unused unless you opt back into Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | No | Unused unless you opt back into Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | No | Unused unless you opt back into Supabase |

Default storage is **MongoDB Atlas + local files** when `MONGODB_URI` is set: users, Library, and usage live in MongoDB; videos stay under `ARTIFACTS_ROOT`. Without a URI, SQLite on disk is the fallback. Supabase remains optional.

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
# Vercel uses pyproject.toml + uv.lock (API only). Manim is requirements-local.txt.

# macOS (if missing):
# brew install ffmpeg cairo pango pkg-config glew

npm run dev:api
```

### 3. Next.js

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), sign in with Google, then generate. In development, Next rewrites job/generate/health routes to uvicorn when `NEXT_PUBLIC_API_BASE_URL` is unset; `/api/auth/*` and `/api/mcp` stay on Next.js.

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
| `GET/POST` | `/api/mcp` | ChatGPT/Claude MCP connector (Streamable HTTP) |

**Example request body:**

```json
{
  "prompt": "Explain gradient descent on a parabola",
  "resolution": "720p",
  "skip_render": false
}
```

## ChatGPT and Claude

The same Create + Understand APIs are exposed as a remote MCP server at **`/api/mcp`**. ChatGPT (Developer Mode custom connector) and Claude (Customize → Connectors) both speak Streamable HTTP over HTTPS.

1. Deploy (or run locally with a public HTTPS tunnel).
2. Open **`/connect`** on your deployment — it shows the exact connector URL.
3. Add the connector in ChatGPT or Claude. Auth is **OAuth** (Google), not a pasted API key. In Claude’s OAuth modal choose **No client ID — register automatically** and leave client ID/secret/headers empty.
4. Sign in with the same Google account you use on the website. Jobs created in chat appear in **Library**.
5. Add this app’s `/api/auth/callback/google` URL to your Google OAuth client (listed on `/connect`).

Local Inspector:

```bash
npx @modelcontextprotocol/inspector@latest
```

Transport: Streamable HTTP, URL: `http://localhost:3000/api/mcp`.

### Railway (public connector)

The Manim worker stays on the `NowIGetIt` Railway service. The chat connector is a **separate** `app` service (`Dockerfile.app` + `railway.app.toml`): Next.js + FastAPI, calling `RENDER_WORKER_URL` for video.

Current production URL: `https://app-production-5eb7.up.railway.app/api/mcp`  
Setup page: `https://app-production-5eb7.up.railway.app/connect`

Auth is **Google OAuth**. ChatGPT/Claude open this site to sign in; leave client ID/secret empty. Optional `MCP_CONNECTOR_TOKEN` still works as a shared key for Inspector. Redeploy from this repo:

```bash
railway up --service app --environment production --ci
```

Video: the chat model writes a storyboard, **shows it to the user for approval**, then writes Manim and renders (`create_video` with a `plan` object → wait → `submit_scene_code` → `render_video`). Poll `get_job` while `poll_again` is true. Documents: `upload_document` then `get_document`.

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
