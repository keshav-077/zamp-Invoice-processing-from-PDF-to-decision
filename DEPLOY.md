# Deploy to Vercel

One-command deploy after env vars are set. The repo ships with `vercel.json` (React SPA + Python FastAPI serverless).

**Live checklist:** `GET /api/health` → `deploy.ready: true`

---

## 1. Create Vercel project

1. Go to [vercel.com/new](https://vercel.com/new) and import  
   `keshav-077/zamp-Invoice-processing-from-PDF-to-decision`
2. **Root directory:** leave as repo root (contains `vercel.json`)
3. Framework preset: **Other** (config is in `vercel.json`)

---

## 2. Required services

| Service | Purpose | Get it |
|---------|---------|--------|
| **Neon Postgres** | Persistent DB (SQLite does not work on Vercel) | [neon.tech](https://neon.tech) |
| **Vercel Blob** | Invoice file storage | Vercel dashboard → Storage → Blob |
| **Gemini API** | Vision LLM extraction | [Google AI Studio](https://aistudio.google.com/apikey) |

### Recommended

| Service | Purpose |
|---------|---------|
| **Inngest** | Durable async jobs beyond 300s / retries | [inngest.com](https://www.inngest.com) |
| Groq / OpenRouter | LLM fallbacks |

---

## 3. Environment variables (Vercel → Settings → Environment Variables)

### Required

```env
GEMINI_API_KEY=...
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_...
AUTO_SEED_ON_STARTUP=false
```

### Frontend build (set for Production + Preview)

```env
VITE_API_BASE_URL=/api
VITE_USE_ASYNC_JOBS=true
```

> Also defined in `vercel.json` `build.env` — override in dashboard if needed.

### Inngest (recommended for production)

```env
INNGEST_EVENT_KEY=...
INNGEST_SIGNING_KEY=...
INNGEST_APP_ID=invoiceflow-ai
```

After deploy, register Inngest app URL:  
`https://YOUR-DOMAIN.vercel.app/api/inngest`

### Optional fallbacks

```env
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
PROVIDER_PRIORITY=gemini,groq,openrouter
```

---

## 4. Initialize production database (one time)

From your machine with `DATABASE_URL` set to Neon:

```bash
cd invoiceflow-ai
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
python scripts/reset_db.py
```

This creates schema + seeds demo PO master from `data/PO.xlsx`.

---

## 5. Deploy

```bash
npm i -g vercel
vercel login
vercel --prod
```

Or push to `main` if GitHub integration is connected.

---

## 6. Verify

```bash
curl https://YOUR-APP.vercel.app/api/health
```

Expect:

```json
{
  "status": "healthy",
  "deploy": {
    "ready": true,
    "platform": "vercel",
    "checks": [ ... ]
  }
}
```

Upload an invoice at `https://YOUR-APP.vercel.app/`

---

## Architecture on Vercel

```
Browser → Vercel CDN (React SPA)
       → /api/* → Python serverless (FastAPI)
       → Neon Postgres (DATABASE_URL)
       → Vercel Blob (uploads)
       → Inngest (optional async pipeline)
       → Gemini / Groq / OpenRouter
```

---

## Limits

| Limit | Value |
|-------|-------|
| Serverless max duration | **300s** (`vercel.json`) |
| Without Inngest | Jobs run as **background tasks** in same invocation (300s cap) |
| With Inngest | Long pipelines + retries |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| UI calls `localhost:8000` | Set `VITE_API_BASE_URL=/api` and **redeploy** (build-time var) |
| Upload 501 | Add `BLOB_READ_WRITE_TOKEN` |
| Data disappears | Set `DATABASE_URL` (Neon) — not SQLite |
| Extraction fails | Check `GEMINI_API_KEY`; see provider errors in `/api/health` |
| Job stuck queued | Check function logs; add Inngest keys |
| `deploy.ready: false` | Open `/api/health` → fix failed `checks` |

---

## Local development (unchanged)

```bash
uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Uses SQLite + local `uploads/` — no Vercel services required.
