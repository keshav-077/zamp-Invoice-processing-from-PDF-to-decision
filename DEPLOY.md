# Deploy to Vercel

**Full env reference:** [ENV.md](./ENV.md) (every key explained)

**Import file:** [`.env.example`](./.env.example) → 20 keys for Vercel

**Live check:** `GET /api/health` → `deploy.ready: true`

---

## 1. Import environment variables

1. Open [vercel.com](https://vercel.com) → your project → **Settings → Environment Variables**
2. **Import `.env`** → choose `.env.example` from this repo (or paste contents)
3. Select **Production** + **Preview**
4. Fill secrets for keys marked in [ENV.md](./ENV.md#required--you-must-fill-these)

### Minimum secrets to fill (4)

| Key | Get it from |
|-----|-------------|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `DATABASE_URL` | [neon.tech](https://neon.tech) → connection string |
| `BLOB_READ_WRITE_TOKEN` | Vercel → **Storage** → **Blob** |
| `AUTO_SEED_ON_STARTUP` | Type `false` |

### Recommended secrets (+5)

| Key | Get it from |
|-----|-------------|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `INNGEST_EVENT_KEY` | [inngest.com](https://www.inngest.com) |
| `INNGEST_SIGNING_KEY` | Inngest dashboard |

All other imported keys can keep their **default values** from `.env.example`.

---

## 2. Connect GitHub & deploy

1. Import repo: `keshav-077/zamp-Invoice-processing-from-PDF-to-decision`
2. Root directory: repo root (contains `vercel.json`)
3. Deploy — or push to `main` for auto-deploy

---

## 3. Seed production database (one time)

```bash
cd invoiceflow-ai
pip install -r requirements.txt
set DATABASE_URL=postgresql://YOUR_NEON_URL
python scripts/reset_db.py
```

---

## 4. Sync Inngest (if using async jobs)

Inngest dashboard → App URL:

```text
https://YOUR-APP.vercel.app/api/inngest
```

---

## 5. Verify

Open `https://YOUR-APP.vercel.app/api/health`

Upload a test invoice at `https://YOUR-APP.vercel.app/`

---

## Local dev (separate from Vercel)

Use [`.env.local.example`](./.env.local.example) → `.env` — not `.env.example`.

```bash
uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bundle size > 225 MB | **Redeploy latest `main`** (not an old failed deployment). In Vercel → **Settings → Build** set **Install Command** to empty (our `vercel.json` sets `"installCommand": ""`). Add env `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` and redeploy. OpenCV/PyMuPDF need Large Functions on Vercel. |
| Only 4 env vars detected | Re-import latest `.env.example` from GitHub (20 keys) |
| `deploy.ready: false` | Fill `DATABASE_URL` + `BLOB_READ_WRITE_TOKEN` |
| UI hits localhost | Redeploy after setting `VITE_API_BASE_URL=/api` |
| Upload 501 | Add Blob token |
| Extraction fails | Check LLM keys in `/api/health` |

See [ENV.md](./ENV.md) for the complete key list.
