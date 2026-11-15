# AI providers, AI Generate and the AI Agent (Milestone 2)

## Architecture
```text
AI Generate / AI Agent node        (executors/ai.py, registered like any other node)
        │  config validated by the planner (catalogue, capabilities, tools, output schema)
        ▼
ModelRouter (ai/router.py)                primary → bounded retries → eligible fallback, usage records
        ▼
Provider adapters (ai/providers.py)       ChatOpenAI (Responses API) / ChatAnthropic / ChatGoogleGenerativeAI
        ▼
Structured output (ai/structured.py)      native JSON-schema mode + jsonschema validation + bounded repair
Agent graph (ai/agent.py)                 LangGraph StateGraph: call_model ⇄ execute_tools → finalize
Tool registry (ai/tools/)                 built-in provider; Composio can be added as another ToolProvider
```
- **The workflow engine is unchanged.** An AI node is an ordinary node: retries, timeouts, cancellation, persistence, redaction and history all come from the existing runner. LangGraph runs only *inside* the AI Agent node.
- **Not used for AI nodes.** The Gemini workflow designer and Gemma reviewer (`services/llm_service.py`) keep their own REST/SDK path and settings.

## Providers and verified models

| Provider | Model ids | Verified how | Live-tested |
|---|---|---|---|
| OpenAI | `gpt-6-astra`, `gpt-6.1-sol` (recommended), `gpt-6.1-terra`, `gpt-6-luna` | OpenAI model docs (developers.openai.com/api/docs/models), 2026-11-15 | Only if `OPENAI_API_KEY` is present (see `IMPLEMENTATION_STATUS.md`) |
| Anthropic | `claude-opus-5-5` (recommended), `claude-sonnet-5-5`, `claude-haiku-5-5` | Anthropic models reference (cached 2026-11-03) | Only if `ANTHROPIC_API_KEY` is present |
| Google Gemini | `gemini-3.8-flash` (recommended), `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-pro`, `gemini-2.5-flash` | Live `models.list` with the configured key, 2026-11-15 | Yes, with `GEMINI_API_KEY` |

**Capabilities.** The capabilities are stored in `ai/catalog.py` and enforced by `ai/targets.py`. Requesting an option a model does not support is a validation error, never a silent no-op:

| | OpenAI | Anthropic | Gemini |
|---|---|---|---|
| Tool calling | ✓ (Responses API) | ✓ (`tool_choice` auto only; forced tool choice returns 400) | ✓ |
| Structured output | ✓ | ✓ | ✓ |
| Streaming | ✓ | ✓ | ✓ |
| Temperature | not documented for these reasoning models, so **rejected** | sampling parameters return 400, so **rejected** | ✓ |
| Reasoning effort option | ✓ (`reasoning_effort`) | ✓ (`output_config.effort`) | ✗ |
| Context / max output | 1.05M / 128K | 1M / 128K | 1,048,576 / 65,536 |

- **Extra models.** Operators can add models with `AI_EXTRA_MODELS` (JSON list of `{provider, model, label, capabilities}`). Such models are labelled "operator-configured" and are still limited to the three providers.
- **Packages** (pinned in `requirements.txt` and verified together on Python 3.13): langchain-core 1.8.0, langchain-openai 1.8.0, langchain-anthropic 1.7.10, langchain-google-genai 4.5.0, langgraph 1.2.22, openai 3.50.0, anthropic 2.8.0.

## API keys
- **User credentials (default).**
  - Open the editor's **Credentials** dialog and add an *OpenAI / Anthropic / Google Gemini API key*. Keys are Fernet-encrypted, owned by the user and write-only; the API shows only `••••last4`. They can be renamed or replaced (`PUT /api/credentials/{id}`).
  - **Test** (`POST /api/credentials/{id}/test`) makes a real `models.list` call. It does not run inference or bill tokens. It reports which supported models the key can use.
  - Then select the credential in the node's model picker. Other users cannot see, test, update or use it; the planner and the runtime both check ownership.
- **Platform keys.** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in `backend/.env` are used only when a node selects no credential **and** `AI_ALLOW_PLATFORM_KEYS` is true (default: true in development, false in production). Traces record `credential_source: user|platform`. Platform keys are never returned to the browser; `/api/ai/providers` exposes only a boolean.
- **Secrets never persist.** Every key resolved for a node is added to that node's secret set. The runner scrubs those values from outputs, metadata, logs and errors before anything is stored. Provider errors also go through a key-pattern scrubber.

## Primary / fallback routing (`ai/router.py`)
1. Both the primary and the fallback are validated against the catalogue, and both keys are resolved **before** the first call. A missing credential or unsupported model fails immediately, with no fallback.
2. Transient failures (429, 5xx/overloaded, timeouts, connection errors) are retried up to `AI_MODEL_MAX_RETRIES` times with backoff. AI Generate has its own `max_retries`.
3. Only availability failures switch to `fallback_model`. Auth, permission, bad-request, unsupported-model, cancellation, tool and output-validation errors never do.
4. The switch is sticky for the rest of the node run. The actual provider/model, the fallback reason and every attempt are recorded (`metadata.ai`, `metadata.model_calls`).
5. Tools never re-run because of a model failure: tool execution happens outside the router.
6. AI Generate has **no** fallback; it never substitutes another model.

## Usage and cost
- **Tokens.** Provider-reported tokens (`usage_metadata`) are stored per model call in `ai_usage_records`, together with the execution, node, user, provider, model, credential source, status, fallback flag and duration. `GET /api/ai/usage?execution_id=…` lists them, scoped to the current user.
- **Missing data.** Tokens the provider does not report are stored as null, not estimated.
- **Cost.** No cost is calculated, because pricing data is not verified in this repository.

## AI Generate (`ai.generate`)
- **Purpose:** one bounded model call. It has no tools, no loop and no fallback.
- **Config:**
  - `model {provider, model, credential_id?, max_output_tokens, timeout_seconds, temperature?, reasoning_effort?}`
  - `system_prompt`, `prompt` (expressions allowed), `inputs` (named values sent as JSON)
  - `output_format text|json`, `output_schema` (an object JSON Schema)
  - `max_retries`, `max_repair_attempts`, `max_input_chars`
- **Output:** `{result, provider, model, usage, finish_reason}`. `result` is the parsed, schema-validated object, never a JSON string. Read it downstream with `{{nodes.ai_generate_1.output.result.category}}`.

## AI Agent (`ai.agent`)
- **One node type.** Instructions, tools and output schema define the task.
- **Config:**
  - `model`, optional `fallback_model`
  - `instructions`, `task`, `inputs`
  - `tools` (explicit allowlist, empty by default)
  - `output_schema`
  - `limits {max_iterations, max_tool_calls, max_tool_errors, tool_timeout_seconds, timeout_seconds, max_input_chars, max_output_chars, max_total_tokens, max_repair_attempts}`

  The backend enforces every limit.
- **Graph:** `call_model` (iteration and token-budget checks, only allowed tools bound) → `execute_tools` (each call goes through registry lookup → node allowlist + server policy → pydantic argument validation with extra fields forbidden → tool-call limit → per-tool timeout → output validation and truncation) → back to the model, or `finalize`.
  - **Rejected calls** (unknown, unauthorized or invalid) are never executed. The model receives a tool error. After `max_tool_errors` rejected or failed calls the node fails with `TOOL_NOT_ALLOWED`, `TOOL_ARGS_INVALID`, `TOOL_FAILED` or `TOOL_TIMEOUT`.
- **Structured result.** It is produced by a separate structured-output call over a condensed transcript (task, tool results, final answer). It is validated with `jsonschema`, with bounded repair; otherwise it fails with `STRUCTURED_OUTPUT_INVALID`.
- **Output:** `{result, provider, model, fallback_used, fallback_reason, iterations, tool_calls[], usage}`.
- **Trace:** `metadata.agent_trace` holds model calls (iteration, provider/model, requested tools, usage), tool calls (redacted arguments, status, duration, result summary) and structured-output attempts. Hidden reasoning is never stored.
- **Error categories:**
  - Model errors: `MODEL_UNAVAILABLE`, `MODEL_AUTH`, `MODEL_TIMEOUT`, `UNSUPPORTED_MODEL`, `MODEL_ERROR`, `INVALID_MODEL_OUTPUT`
  - Output: `STRUCTURED_OUTPUT_INVALID`
  - Tool errors: `TOOL_*`
  - Limits: `ITERATION_LIMIT`, `USAGE_LIMIT`, `TIMEOUT`
  - `CANCELLED`
  - Permission and credential errors: `MISSING_CREDENTIALS`, `TOOL_NOT_ALLOWED`
- **Checkpointing:** the agent state holds no secrets and is serialisable, but it is **not** checkpointed. Durable pause/resume and human approval are Milestone 4.

## Built-in tools (`ai/tools/builtin.py`)

| id | Permission | What it does |
|---|---|---|
| `calculator` | read_only | Arithmetic through a hand-written parser (never `eval`), with bounded size, depth, exponent and magnitude |
| `datetime` | read_only | now / parse / format / add / diff in IANA time zones |
| `json_tools` | read_only | Parse JSON, read a dot path, validate against a JSON Schema |
| `text_tools` | read_only | Length, word count, case, trim, find/replace, split, truncate, contains, count. No regex (avoids ReDoS) |
| `data_aggregate` | read_only | sum / avg / min / max / count, count/sum grouped by a field, over up to 10k records |
| `http_get` | network | Read-only GET without credentials. http/https only. Private, loopback and link-local targets are blocked after DNS resolution and on every redirect hop (shared `core/net.py`). 3 redirects, 8 s timeout, 1 MB body, 20k chars returned |

- **No side effects.** No built-in tool changes external state. Side-effecting tools would need explicit authorization (`ToolPolicy`).
- **Server switches:** `AGENT_DISABLED_TOOLS` disables listed tools; `AGENT_ALLOW_NETWORK_TOOLS=false` disables `http_get`.

## Adding keys, choosing models and running live tests
1. **Add the keys.** `backend/.env` contains `OPENAI_API_KEY=your_openai_api_key_here` and `ANTHROPIC_API_KEY=your_anthropic_api_key_here`; replace the placeholders with real keys. Placeholder values (anything starting with `your_`) are treated as "no key" everywhere: the backend never sends them, and the live tests skip that provider.
2. **Compare the models** with real calls and get a recommended primary and fallback per provider:
   ```bash
   cd backend
   python scripts/compare_ai_models.py --providers openai anthropic           # add --repeat 3 for steadier latency
   ```
   - **Checks per model:**
     - availability for the key (`models.list`)
     - schema-validated structured output (needed by AI Generate and the Agent's final answer)
     - a valid calculator tool call (needed by the Agent)
   - **Primary:** the most capable model that passed everything.
   - **Fallback:** the fastest *other* passing model of the same provider.
   - **Output:** copy-ready `model` / `fallback_model` JSON, plus a cross-provider option.
   - **Cost:** a few cents of tokens per model.
3. **Run the live workflow tests** (one AI Generate and one tool-using Agent per provider):
   ```bash
   python -m pytest -m live tests/test_ai_live.py -s
   ```
   - The live tests use `gpt-6.1-sol` (OpenAI), `claude-sonnet-5-5` (Anthropic) and `gemini-3.5-flash`.
   - To test others, edit the `LIVE` table at the top of `tests/test_ai_live.py`.
   - Restart the backend after changing `.env`.
- **Skipping:** each provider is skipped (not failed) when its key is missing.
- **Default suite:** it never sees provider keys and never calls a real provider. All AI tests there are marked as mocked: `tests/fake_llm.py` replaces only the provider client.
