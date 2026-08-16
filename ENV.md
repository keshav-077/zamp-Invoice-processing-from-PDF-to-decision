# Environment Variables Reference

Complete list for **Vercel deployment**. Import [`.env.example`](./.env.example) in the Vercel dashboard.

---

## Quick import (Vercel)

1. **Project → Settings → Environment Variables**
2. Click **Import .env** (or paste file contents)
3. Select **Production** and **Preview**
4. Fill the **4 required secrets** (below)
5. **Redeploy**

---

## Every key explained

### Required — you must fill these

| Key | Required | Where to get it | Example |
|-----|----------|-----------------|---------|
| `GEMINI_API_KEY` | **Yes** | [Google AI Studio](https://aistudio.google.com/apikey) | `AIza...` |
| `DATABASE_URL` | **Yes** | [Neon](https://neon.tech) → Project → Connection string | `postgresql://user:pass@ep-xxx.neon.tech/neondb?sslmode=require` |
| `BLOB_READ_WRITE_TOKEN` | **Yes** | Vercel Dashboard → **Storage** → **Blob** → connect to project | `vercel_blob_rw_...` |
| `AUTO_SEED_ON_STARTUP` | **Yes** | Set manually (not a secret) | `false` |
| `VERCEL_SUPPORT_LARGE_FUNCTIONS` | **Yes** | Set manually — enables Large Functions for OpenCV/PyMuPDF bundle | `1` |

After first deploy, seed the database once from your PC:

```bash
set DATABASE_URL=postgresql://...
python scripts/reset_db.py
```

---

### LLM fallbacks — fill API keys; defaults are fine

| Key | Required | Where to get it | Default |
|-----|----------|-----------------|---------|
| `GROQ_API_KEY` | Recommended | [console.groq.com](https://console.groq.com) | _(empty)_ |
| `OPENROUTER_API_KEY` | Recommended | [openrouter.ai/keys](https://openrouter.ai/keys) | _(empty)_ |
| `PROVIDER_PRIORITY` | No | Order of try/fallback | `gemini,groq,openrouter` |
| `GEMINI_MODEL` | No | — | `gemini-flash-latest` |
| `GROQ_MODEL` | No | — | `qwen/qwen3.6-27b` |
| `OPENROUTER_MODEL` | No | — | `google/gemini-2.5-flash` |

---

### Frontend build — usually keep defaults

| Key | Required | Notes | Default |
|-----|----------|-------|---------|
| `VITE_API_BASE_URL` | Yes | Same-origin API on Vercel | `/api` |
| `VITE_USE_ASYNC_JOBS` | Yes | Async upload + job polling | `true` |
| `VITE_UPLOAD_TIMEOUT_MS` | No | Client timeout (ms) | `300000` |

Also set in `vercel.json` `build.env` — dashboard values override at build time.

---

### Async jobs (Inngest) — recommended for production

| Key | Required | Where to get it | Default |
|-----|----------|-----------------|---------|
| `INNGEST_EVENT_KEY` | Recommended | [inngest.com](https://www.inngest.com) → App → Keys | _(empty)_ |
| `INNGEST_SIGNING_KEY` | Recommended | Inngest dashboard | _(empty)_ |
| `INNGEST_APP_ID` | No | Must match code | `invoiceflow-ai` |

After deploy, sync Inngest serve URL:  
`https://YOUR-APP.vercel.app/api/inngest`

Without Inngest, jobs use serverless background tasks (300s max).

---

### Optional — leave blank unless needed

| Key | Purpose |
|-----|---------|
| `CLERK_JWT_ISSUER` | Clerk authentication |
| `UPSTASH_REDIS_REST_URL` | Rate limiting (Redis) |
| `UPSTASH_REDIS_REST_TOKEN` | Rate limiting (Redis) |
| `RESEND_WEBHOOK_SECRET` | Inbound email invoice ingestion |

---

## Local development

Copy [`.env.local.example`](./.env.local.example) → `.env` — only LLM keys needed.

```bash
cp .env.local.example .env
cp frontend/.env.example frontend/.env
uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Do **not** set `DATABASE_URL` or `BLOB_READ_WRITE_TOKEN` locally unless testing production paths.

---

## Verify deployment

```text
GET https://YOUR-APP.vercel.app/api/health
```

Expect:

```json
{
  "status": "healthy",
  "deploy": { "ready": true, "platform": "vercel" },
  "available_providers": ["gemini", "groq", "openrouter"]
}
```

---

## Summary checklist (20 keys in .env.example)

| # | Key | Fill? |
|---|-----|-------|
| 1 | `GEMINI_API_KEY` | ✅ secret |
| 2 | `DATABASE_URL` | ✅ secret |
| 3 | `BLOB_READ_WRITE_TOKEN` | ✅ secret |
| 4 | `AUTO_SEED_ON_STARTUP` | ✅ `false` |
| 5 | `GROQ_API_KEY` | ✅ secret |
| 6 | `OPENROUTER_API_KEY` | ✅ secret |
| 7 | `PROVIDER_PRIORITY` | default OK |
| 8 | `GEMINI_MODEL` | default OK |
| 9 | `GROQ_MODEL` | default OK |
| 10 | `OPENROUTER_MODEL` | default OK |
| 11 | `VITE_API_BASE_URL` | default OK |
| 12 | `VITE_USE_ASYNC_JOBS` | default OK |
| 13 | `VITE_UPLOAD_TIMEOUT_MS` | default OK |
| 14 | `INNGEST_EVENT_KEY` | recommended |
| 15 | `INNGEST_SIGNING_KEY` | recommended |
| 16 | `INNGEST_APP_ID` | default OK |
| 17 | `CLERK_JWT_ISSUER` | optional |
| 18 | `UPSTASH_REDIS_REST_URL` | optional |
| 19 | `UPSTASH_REDIS_REST_TOKEN` | optional |
| 20 | `RESEND_WEBHOOK_SECRET` | optional |
