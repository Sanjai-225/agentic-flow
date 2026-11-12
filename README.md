# AI Workflow Designer

An AI-first, full-stack workflow design system that converts natural-language requirements into complete, structured workflow designs and visualizes them as interactive node graphs.

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
│   └── .env.local.example
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
copy .env.local.example .env.local    # Windows
# cp .env.local.example .env.local    # macOS/Linux

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

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes* | — | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model name |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated CORS origins |
| `MAX_GENERATION_RETRIES` | No | `2` | Max validation retry attempts |
| `ENABLE_WORKFLOW_REVIEW` | No | `false` | Enable LLM self-review |
| `MOCK_DEV_MODE` | No | Auto | Force mock mode on/off |

*\*Without a key, the backend runs in Mock Dev Mode automatically.*

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |

---

## 🎨 Design Philosophy

- **AI-First**: The LLM independently determines workflow architecture — no hardcoded templates
- **Dynamic Node Types**: No fixed enum; the LLM proposes suitable node types per requirement
- **Design-Only**: Tools are identified and visualized but not executed (marked `not_connected`)
- **Validated**: Every workflow passes Pydantic schema + graph topology validation before display

---

## ⚠️ Known Limitations

- This is the **initial design and visualization milestone** — workflows are not executed
- Tool integrations are conceptual (`not_connected`) — no actual API connections
- No database persistence, authentication, or user management
- No multi-agent orchestration or execution monitoring
- Frontend auto-layout is basic (top-to-bottom with branch spreading); complex graphs may need manual adjustment

---

## 📜 Branch Strategy

See [agent.md](agent.md) for contributor and AI agent rules.

- `main` — Production (owner-only merge via PR)
- `testing` — Development (all new work goes here)
