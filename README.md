# Agentic Flow

An AI-assisted, n8n-inspired workflow automation builder: design workflows with natural language or on a canvas, then execute them on a real backend engine and inspect every node's input, output and errors.

> **Example:** *"Create a workflow that receives customer emails, identifies the issue, checks order status from a database, generates a response using an LLM, and sends the response."*
>
> → The LLM independently understands the requirement, determines nodes, identifies tools, designs the execution flow, validates it, and renders it visually.

---

## 🏗️ Architecture

```
┌──────────────────────┐         REST API          ┌──────────────────────────┐
│     Next.js Frontend │  ◄──── JSON ────►         │   FastAPI Backend        │
│     React Flow       │   POST /api/workflows/    │   Gemini API (LLM)      │
│     TypeScript       │        generate           │   Pydantic Validation   │
│     Tailwind CSS     │                           │   Graph Validator       │
└──────────────────────┘                           └──────────────────────────┘
```

## 📂 Project Structure

```
agentic-flow/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app, CORS, router
│   │   ├── api/
│   │   │   └── workflow.py             # GET /health, POST /api/workflows/generate
│   │   ├── core/
│   │   │   └── config.py               # Environment config (dotenv)
│   │   ├── schemas/
│   │   │   └── workflow.py             # Pydantic models (flexible, no fixed enums)
│   │   ├── services/
│   │   │   ├── llm_service.py          # Gemini API integration (google-genai SDK)
│   │   │   ├── workflow_generator.py   # Orchestrator: generate → validate → retry
│   │   │   ├── workflow_reviewer.py    # LLM self-review for requirement coverage
│   │   │   └── mock_workflow_generator.py  # Dev mode fallback (no API key)
│   │   └── validators/
│   │       └── graph_validator.py      # Graph topology checks
│   ├── tests/
│   │   └── test_workflow.py            # 12 tests (health, validator, 5 prompts, API)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── page.tsx                    # Main page layout
│   │   ├── layout.tsx                  # Root layout
│   │   └── globals.css                 # Dark theme + React Flow styles
│   ├── components/
│   │   ├── CustomNode.tsx              # Dynamic node component (all types)
│   │   ├── PromptInput.tsx             # Prompt input + generate button
│   │   ├── WorkflowCanvas.tsx          # React Flow canvas + auto-layout
│   │   └── WorkflowToolbar.tsx         # Header + controls
│   ├── services/
│   │   └── workflowApi.ts              # API client
│   ├── types/
│   │   └── workflow.ts                 # TypeScript interfaces
│   ├── package.json
│   └── .env.example
├── agent.md                            # AI agent instructions for contributors
├── .gitignore
└── README.md
```

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+**
- **Node.js 18+** (recommended: 20+)
- **Gemini API Key** (from [Google AI Studio](https://aistudio.google.com/apikey))

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux

# Edit .env and add your Gemini API key
# GEMINI_API_KEY=your_actual_key_here

# Start the backend
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment
copy .env.example .env.local    # Windows
# cp .env.example .env.local    # macOS/Linux

# Start the frontend
npm run dev
```

### 3. Open the App

Visit **http://localhost:3000** and enter a workflow requirement!

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/health` | Returns `{"status": "healthy"}` |
| `POST` | `/api/workflows/generate` | Generates workflow from prompt |

### Generate Workflow Request

```json
POST /api/workflows/generate
{
  "prompt": "Create an email automation that filters alerts, posts to Slack, and creates Jira tickets.",
  "review": false
}
```

### Response Schema

```json
{
  "workflow_id": "email-alert-triage-abc123",
  "workflow_name": "Email Alert Triage & Escalation",
  "description": "...",
  "nodes": [
    {
      "id": "node_1",
      "type": "trigger",
      "label": "Inbound Email",
      "description": "Monitors inbox for incoming alert emails.",
      "config": { "inbox": "alerts@company.com" },
      "tool": { "name": "Gmail", "operation": "receive", "status": "not_connected" }
    }
  ],
  "edges": [
    { "id": "edge_1", "source": "node_1", "target": "node_2", "label": "...", "condition": "..." }
  ],
  "start_nodes": ["node_1"],
  "end_nodes": ["node_5"]
}
```

---

## 🧪 Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

**12 tests covering:**
- Health check endpoint
- Graph validator (sequential, branching, orphan detection, dead-end detection)
- 5 diverse workflow prompts (customer support, email+Slack, invoices, documents, research)
- API endpoint integration (success + validation error)

---

## 🔧 Mock Dev Mode

When `GEMINI_API_KEY` is not configured, the backend automatically runs in **Mock Dev Mode**:
- Returns domain-aware pre-built workflows (clearly labeled `[MOCK DEV MODE]`)
- Supports 4 workflow categories: invoices, research, email/Slack, and customer support
- All mock workflows pass Pydantic + graph validation
- Useful for frontend development and testing without API costs

---

## ⚙️ Environment Variables

### Backend (`backend/.env`, see `.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Gemini key for the AI designer (mock designer when unset) |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` / `GEMINI_REVIEWER_MODEL` | `gemini-3.8-flash` / `gemini-3.5-flash-lite` / `gemma-4-31b-it` | Designer and reviewer models |
| `ENABLE_WORKFLOW_REVIEW` | `true` | Semantic review of generated workflows |
| `DATABASE_URL` | `sqlite+aiosqlite:///backend/agentic_flow.db` | Persistence (migrated on startup) |
| `JWT_SECRET` | dev fallback | **Required in production** |
| `CREDENTIALS_ENCRYPTION_KEY` | derived in dev | Fernet key, **required in production** |
| `HTTP_ALLOW_PRIVATE_NETWORKS` | `false` | Allow HTTP nodes to call localhost/private IPs (dev only) |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build webhook URLs |
| `EXECUTION_MAX_DURATION_SECONDS` | `900` | Hard cap per execution |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed browser origins |

### Frontend (`frontend/.env.local`)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Call the backend directly (e.g. `http://localhost:8000`). Leave empty to use the built-in `/api` proxy, which forwards to `BACKEND_URL` |

---

## ▶️ Executing workflows (Milestone 1)

1. Sign up at `http://localhost:3000/login`.
2. Create a workflow manually (node library → canvas → connect → configure), or describe it to the **AI Designer**.
3. **Validate** to see blocking problems per node. Design-only nodes (agents, integrations, loops…) are flagged and rejected before execution.
4. **Run** with a JSON payload. Node statuses, inputs, outputs, errors and logs come from the backend execution record.

Executable operations: Manual Trigger, Webhook Trigger, Set Variable, JSON Parse, Filter, Transform, If/Else, End, HTTP Request.
Reference upstream data with `{{nodes.<id>.output.<field>}}`, `{{trigger.<field>}}` or `{{input.<field>}}`.

See `IMPLEMENTATION_STATUS.md` for the current capability list and known limitations, and `docs/MASTER_IMPLEMENTATION_PLAN.md` for the roadmap (AI agents, Composio integrations, reliability features).

---

## 📜 Branch Strategy

See [agent.md](agent.md) for contributor and AI agent rules.

- `main` — Production (owner-only merge via PR)
- `testing` — Development (all new work goes here)
