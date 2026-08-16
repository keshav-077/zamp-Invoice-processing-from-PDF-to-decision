<div align="center">

<!-- 3D-style animated header -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,50:764ba2,100:06b6d4&height=220&section=header&text=InvoiceFlow%20AI&fontSize=72&fontAlignY=38&animation=twinkling&fontColor=ffffff&desc=From%20PDF%20%26%20Image%20%E2%86%92%20Pay%20or%20Reject&descAlignY=62&descSize=18" width="100%" alt="InvoiceFlow AI header"/>

<!-- Typing animation -->
<img src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&weight=600&size=22&duration=3000&pause=800&color=06B6D4&center=true&vCenter=true&width=700&lines=Upload+invoice+PDF+or+photo;Vision+LLM+extracts+fields+%26+line+items;Match+to+PO+master+%E2%80%94+even+crumpled+scans;Validate+tax%2C+duplicates%2C+budget;Auto-approve+or+route+to+human+review;Audit-ready+explanation+%26+decision+trail" alt="Pipeline tagline animation"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Gemini](https://img.shields.io/badge/VLM-Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://ai.google.dev/)

<br/>

**Intelligent accounts-payable pipeline — extract, match, validate, decide, explain.**

[Quick Start](#-quick-start) · [Pipeline](#-the-5-stage-pipeline) · [Demo](#-demo-scenarios) · [API](#-api) · [Tests](#-tests)

</div>

---

## ✨ What it does

InvoiceFlow AI turns **messy invoice PDFs and phone photos** into a structured **pay / don't pay / needs review** decision with a full audit trail.

| You upload | The system returns |
|------------|-------------------|
| Crumpled scan, no PO on page | Ranked PO suggestions + human confirm |
| Clean invoice with PO number | Auto-match → validate → auto-approve (when policy allows) |
| Duplicate or tax mismatch | Block with specific reason codes |
| CSV master data | Unified PO + vendor mirror for matching |

Built for **PS-1 / Zamp-style AP automation**: deterministic rules where it matters, vision LLMs where humans used to squint at pixels.

---

## 🎬 The 5-stage pipeline

```mermaid
flowchart LR
    subgraph S1["① Extract & Verify"]
        A[📄 PDF / Image] --> B[Vision LLM]
        B --> C[Verify + Reconcile]
    end
    subgraph S2["② PO Matching"]
        C --> D{PO on invoice?}
        D -->|Yes| E[Exact match]
        D -->|No| F[Vendor + amount heuristics]
    end
    subgraph S3["③ Validation"]
        E --> G[Tax · Duplicates · Budget]
        F --> G
    end
    subgraph S4["④ Decision"]
        G --> H{Policy engine}
        H -->|Low $ + clean| I[AUTO APPROVED]
        H -->|Flags| J[REVIEW / REJECT]
    end
    subgraph S5["⑤ Explanation"]
        I --> K[Audit narrative + hash chain]
        J --> K
    end

    style S1 fill:#667eea22,stroke:#667eea
    style S2 fill:#764ba222,stroke:#764ba2
    style S3 fill:#06b6d422,stroke:#06b6d4
    style S4 fill:#10b98122,stroke:#10b981
    style S5 fill:#f59e0b22,stroke:#f59e0b
```

<details>
<summary><b>Stage breakdown (click to expand)</b></summary>

| Stage | Name | What happens |
|-------|------|----------------|
| **1** | Extract & Verify | Gemini / Groq / OpenRouter vision models read the document; second LLM pass challenges extraction; arithmetic reconciliation |
| **2** | PO Matching | Candidate discovery, evidence scoring (vendor, lines, amount, balance), ambiguity detection, human confirm when uncertain |
| **3** | Validation | Tax, duplicates, vendor checks, receipt/budget tolerance, fraud signals |
| **4** | Business Decision | Hard controls → policy → authority → routing (auto-approve limits) |
| **5** | Explanation | Immutable narrative, rule trace, upstream artifact hashes, audit ledger |

</details>

---

## 🏗 Architecture

```mermaid
flowchart TB
    UI["React SPA :5173<br/>Framer Motion · Tailwind"]
    API["FastAPI :8000<br/>353+ pytest tests"]
    PIPE["Pipeline Orchestrator"]
    DB[("SQLite / Postgres")]
    LLM["LLM Providers<br/>Gemini → Groq → OpenRouter"]

    UI <-->|REST| API
    API --> PIPE
    PIPE --> LLM
    PIPE --> DB
    UI -->|Upload| API

    style UI fill:#61DAFB33,stroke:#61DAFB
    style API fill:#00968833,stroke:#009688
    style LLM fill:#4285F433,stroke:#4285F4
```

---

## 🚀 Quick start

### Prerequisites

- **Python 3.11+**
- **Node.js 20+**
- At least one LLM API key (**Gemini** recommended)

### 1 · Backend

```bash
git clone https://github.com/keshav-077/zamp-Invoice-processing-from-PDF-to-decision.git
cd zamp-Invoice-processing-from-PDF-to-decision

pip install -r requirements.txt
cp .env.example .env
# Add GEMINI_API_KEY (and optional GROQ / OPENROUTER fallbacks)

uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive API docs.

### 2 · Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open **http://localhost:5173**

### 3 · Seed demo PO data (optional)

```bash
python scripts/build_po_xlsx.py
python scripts/reset_db.py
python scripts/verify_demo_matrix.py --offline
```

---

## 🎯 Demo scenarios

See [`DEMO_MATRIX.md`](DEMO_MATRIX.md) for the full matrix.

| Scenario | Example | Expected |
|----------|---------|----------|
| Happy path | Invoice with PO on page | Auto-match → AUTO_APPROVED |
| Crumpled scan | Rogers / Harrington demos | Vendor + amount match without printed PO |
| Ambiguous | No PO, two similar open POs | Human picks candidate |
| Split PO | Second bill on consumed PO | Suggestion + overbilling warning |
| Non-PO | Restaurant receipt | Limited validation path |

Reset everything for a clean demo:

```bash
python scripts/reset_demo_environment.py
```

---

## 📁 Project structure

```
invoiceflow-ai/
├── app/
│   ├── api/              # FastAPI routes
│   ├── pipeline/         # Stages 1–5 orchestrators
│   ├── providers/        # Gemini, Groq, OpenRouter adapters
│   └── services/         # Import, review, rerun
├── frontend/             # React + Vite + Tailwind UI
├── config/               # matching_policy.yaml, validation_policy.yaml
├── scripts/              # Demo reset, PO seed, diagnostics
├── tests/                # 350+ automated tests
└── docs/                 # Glossary & pipeline status docs
```

---

## 🔌 API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload/async` | Upload invoice (background job) |
| `GET` | `/api/jobs/{id}` | Poll processing status |
| `GET` | `/api/invoices/{id}` | Full pipeline result + audit |
| `GET` | `/api/invoices/{id}/original` | Download source file |
| `POST` | `/api/reviews/{id}/actions` | Confirm PO / correct fields |
| `GET` | `/api/health` | Provider connectivity |

---

## 🧠 LLM provider chain

Configured in `.env` — tries providers in order with automatic fallback on overload:

```
PROVIDER_PRIORITY=gemini,groq,openrouter
```

| Provider | Role |
|----------|------|
| **Gemini** | Primary vision extraction (best for images) |
| **Groq** | Fast fallback (watch payload size on free tier) |
| **OpenRouter** | Secondary fallback |

---

## 🧪 Tests

```bash
pytest tests/ -q
```

---

## 🛡 Security notes

- **Never commit `.env`** — API keys stay local (see `.gitignore`)
- Upload directory and SQLite DB are gitignored
- Production can use Neon Postgres + Vercel (see existing deploy section in repo docs)

---

## 📜 License & attribution

Built as an intelligent invoice processing demo — **PDF/image → structured extraction → PO match → validation → pay/reject decision** with human-in-the-loop when confidence is insufficient.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:667eea,50:764ba2,100:06b6d4&height=100&section=footer&text=Built%20with%20%E2%9D%A4%EF%B8%8F%20for%20AP%20automation&fontSize=24&fontAlignY=55&animation=twinkling&fontColor=ffffff" width="100%" alt="Footer"/>

**⭐ Star this repo if it helped you automate invoice processing**

</div>
