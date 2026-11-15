# Deploying Agentic Flow on free tiers: Vercel + Render + Supabase

| Part | Service (free tier) | What runs there | Configured by |
|---|---|---|---|
| Database | **Supabase Free** | PostgreSQL: all saved data | Dashboard (project + password); tables are created automatically by the backend |
| Backend | **Render Free** web service | FastAPI API, workflow runs, Schedule Trigger loop, webhook + form endpoints | `render.yaml` (Blueprint) |
| Frontend | **Vercel Hobby** | Next.js editor and hosted form pages | `frontend/vercel.json` + "Root Directory = frontend" |

There is no Docker, no Redis, no separate worker and no paid add-on. Total cost is $0.

> Dashboard button names change from time to time. If a label differs slightly, look for the closest
> equivalent in the same area. Commands are **Windows PowerShell**.

---

## Free-tier limitations (read first)

| Limitation | Effect on Agentic Flow | What you can do |
|---|---|---|
| **Render Free sleeps** after ~15 minutes with no incoming HTTP requests | The first request after a sleep takes ~1 minute (the editor shows "Cannot reach the backend" until it wakes; refresh). Webhooks and form submissions sent while it sleeps wake it, but the first one is slow. Most senders retry; very short sender timeouts may fail. | Open the app / backend URL to wake it before demos. |
| **Schedule Triggers do not fire while the backend sleeps** | The scheduler runs inside the backend. Asleep = no schedule checks. When it wakes, missed times follow the trigger's *misfire policy*: `skip` (default: missed runs are dropped, the next future time is used) or `run_once` (one catch-up run). A schedule is never run twice. | Treat schedules as best-effort. Optionally keep the service awake with an external uptime monitor that calls `https://<backend>.onrender.com/health` every 10–14 minutes, which costs nothing extra. One always-awake service fits inside Render's monthly free instance hours. Check Render's current free-tier terms before relying on this. |
| **Runs are interrupted by sleep, restarts and deploys** | A run still executing when the service stops is marked failed "interrupted by a server restart"; there is no automatic resume. | Re-run it. Long AI-agent runs are the most exposed. |
| **Render Free restarts / redeploys** | Saved data is safe (it lives in Supabase). In-memory rate-limit counters reset. | None needed. |
| **Supabase Free pauses inactive projects** (no database activity for about a week) | When paused, the backend cannot start or answer. | Restore the project from the Supabase dashboard (one click). Regular use or an uptime monitor prevents it. |
| **Supabase Free has no downloadable backups** | You cannot restore from a daily backup on the free plan. | Take your own backup when you have important data (section 9). |
| **Supabase Free database size** (500 MB at the time of writing) | Execution history grows over time. | Delete old workflows/executions if you approach the limit. |
| **Vercel Hobby** | Intended for personal, non-commercial use. | Upgrade if this becomes a commercial product. |
| **One backend instance** | The free plan has one instance, which is also what the app requires (runs and rate limits are in-process). | Do not scale out. |

All features remain available: editor, AI designer, all nodes, AI Agent, AI Generate, credentials,
webhooks, forms, schedules and execution history. The limits above only affect **availability and timing**.

---

## Step 0: Put the deployment files on GitHub (you do this)

Render and Vercel deploy from GitHub, and `render.yaml` deploys the **`main`** branch. The prepared files are
in your working copy on branch `testing`, uncommitted.

1. Review the changes (`git status`), then commit them on `testing`.
2. Merge `testing` into `main` the way you normally do (pull request, or local merge), and push `main` to
   GitHub.
3. On GitHub, open `main` and confirm that `render.yaml` is at the repository root and
   `frontend/vercel.json` exists.

---

## Step 1: Generate the encryption key (one command)

```powershell
cd D:\Oneinfer\Project\agentic-flow\backend
python scripts\generate_secrets.py
```

It prints two lines:
- **`CREDENTIALS_ENCRYPTION_KEY`:** you need this value in Step 4. **Save it in a password manager.** If it is
  ever lost or changed, all stored provider keys (credentials) become unreadable.
- **`JWT_SECRET`:** you can ignore it, because Render generates its own.

Never commit these values or put them in any file in the repository.

---

## Step 2: Create the Supabase database

1. Go to <https://supabase.com> and sign in (GitHub login is fine).
2. Click **New project**, then:
   - **Organization:** your personal org (Free plan).
   - **Project name:** `agentic-flow`.
   - **Database password:** click *Generate a password* (or type a strong one) and **save it** in your
     password manager.
   - **Region:** pick a region close to the Render region you will use in Step 4 (Render offers Oregon,
     Ohio, Virginia, Frankfurt and Singapore). For example, choose a US West region with Render Oregon, or a
     Frankfurt region with Render Frankfurt.
   - Click **Create new project** and wait until the project is ready (1–2 minutes).
3. Get the connection string:
   1. Click the **Connect** button at the top of the project page.
   2. Choose the **Session pooler** connection. **Not** "Direct connection" (that needs IPv6, which Render
      does not have) and **not** "Transaction pooler".
   3. Copy the URI. It looks like this:
      ```
      postgresql://postgres.abcdefghijkl:[YOUR-PASSWORD]@aws-0-us-west-1.pooler.supabase.com:5432/postgres
      ```
   4. Replace `[YOUR-PASSWORD]` (including the brackets) with your database password.
      - If the password contains any of `@ # % / : ? &`, replace them: `@`→`%40`, `#`→`%23`, `%`→`%25`,
        `/`→`%2F`, `:`→`%3A`, `?`→`%3F`, `&`→`%26`. Or generate a password without symbols.
   5. Keep this final string private. It is your **`DATABASE_URL`**.
4. You do **not** need to create tables, run SQL, or enable Supabase Auth. The backend creates and upgrades
   its tables automatically on startup. It also enables row level security on every table, which blocks
   Supabase's public Data API from reading your data.

---

## Step 3: Create the Render account and connect GitHub

1. Go to <https://render.com> and sign up / sign in with **GitHub**.
2. When asked, allow Render's GitHub app to access your **agentic-flow** repository (or all repositories).
3. No credit card is needed for free services.

---

## Step 4: Deploy the backend on Render (Blueprint)

1. In the Render dashboard, click **New +** → **Blueprint**.
2. Select the **agentic-flow** repository and click **Connect**.
3. **Blueprint Name:** `agentic-flow`. **Branch:** `main`.
4. Render reads `render.yaml` and shows one service: **agentic-flow-api** (Web Service, **Free**).
5. Render asks for the values marked secret in the Blueprint. Fill them in:

   | Variable | What to enter |
   |---|---|
   | `DATABASE_URL` | the Supabase session pooler string from Step 2 (with your password) |
   | `CREDENTIALS_ENCRYPTION_KEY` | the value from Step 1 |
   | `PUBLIC_APP_URL` | temporarily `https://example.com` (you set the real Vercel URL in Step 6) |
   | `CORS_ORIGINS` | temporarily `https://example.com` |
   | `GEMINI_API_KEY` | your Google AI Studio key for the AI workflow designer. Without one, enter `your_gemini_api_key_here` and the designer runs in a clearly labelled mock mode. |

   Everything else is pre-set by `render.yaml`:
   - `APP_ENV=production`, `DB_AUTO_MIGRATE=true`
   - `JWT_SECRET` (auto-generated)
   - `SCHEDULER_ENABLED=true`, `HTTP_ALLOW_PRIVATE_NETWORKS=false`, `AI_ALLOW_PLATFORM_KEYS=false`
   - `PYTHON_VERSION=3.13`
6. Click **Apply** (or **Deploy Blueprint**). Render now builds (`pip install -r requirements.txt`, a few
   minutes) and starts the service.
7. Open **agentic-flow-api** → **Logs**. A good start looks like:
   - Alembic lines `Running upgrade -> 0001`, `0001 -> 0002` and `0002 -> 0003` (first start only: tables created)
   - `Application startup complete`
   - "Configuration:" warnings are fine. You may see `DB_AUTO_MIGRATE is on`, and the Gemini warning if you
     used the placeholder.
8. **Copy the service URL** shown at the top of the service page, e.g. `https://agentic-flow-api.onrender.com`
   (Render may add a suffix if the name is taken; use exactly what it shows).
9. Check it in your browser:
   - `https://<backend>/health` should show `{"status":"healthy"}`.
   - `https://<backend>/health/ready` should show `"status":"ready"`, `"database":true`,
     `"schema_up_to_date":true` and `"scheduler":"running"`.

If the deploy fails, see **Troubleshooting** (section 10). The most common causes are a wrong `DATABASE_URL`
password and the wrong Supabase connection type.

---

## Step 5: Deploy the frontend on Vercel

1. Go to <https://vercel.com> and sign up / sign in with **GitHub** (Hobby plan).
2. Click **Add New…** → **Project**, find **agentic-flow** and click **Import**.
3. On the configuration screen:
   - **Project Name:** e.g. `agentic-flow`. This becomes your URL, `https://agentic-flow.vercel.app`, if the
     name is free.
   - **Root Directory:** click **Edit** and select **`frontend`**. This is required.
   - **Framework Preset:** **Next.js** (detected automatically).
   - Build / install commands: leave the defaults. `frontend/vercel.json` sets `npm ci` and
     `npm run build`.
4. Open **Environment Variables** and add both (environment: Production, and Preview too if offered):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | your Render URL from Step 4, e.g. `https://agentic-flow-api.onrender.com` (no trailing slash, no `/api`) |
   | `BACKEND_URL` | the same Render URL |

   Never add API keys, database URLs or other secrets to Vercel. The frontend does not need any.
5. Click **Deploy** and wait for the build. It first runs a check that fails the build if the backend URL is
   missing, not `https`, or points at localhost.
6. When it finishes, click **Continue to Dashboard** and copy the **production domain**, e.g.
   `https://agentic-flow.vercel.app`.

---

## Step 6: Connect frontend and backend (CORS + links)

1. Render → **agentic-flow-api** → **Environment**.
2. Edit these two variables:

   | Variable | New value |
   |---|---|
   | `PUBLIC_APP_URL` | your Vercel domain, e.g. `https://agentic-flow.vercel.app` |
   | `CORS_ORIGINS` | the same Vercel domain (exactly; no trailing slash) |

3. Click **Save Changes**. Render redeploys the backend automatically (or choose *Save, rebuild and deploy*).
   Wait until the deploy shows **Live**.

Where each value ends up:
- Webhook URLs use the Render URL automatically.
- Hosted form links use `PUBLIC_APP_URL`.
- The browser calls the backend at `NEXT_PUBLIC_API_URL`; the backend only accepts it because it is listed
  in `CORS_ORIGINS`.

If you later add a custom domain on Vercel, add it to `CORS_ORIGINS` (comma-separated) and set
`PUBLIC_APP_URL` to it.

---

## Step 7: Check that everything works

Open your Vercel URL. If the backend was asleep, wait ~1 minute and refresh.

1. **Sign up** with an email and password, then sign in.
2. **Workflow:** create one (AI designer, or add nodes from the library), **Save**, then **Run**. The run
   appears in execution history with each node's output.
3. **Credentials:** open the Credentials dialog, add an OpenAI/Anthropic/Gemini key, then **Test
   connection**.
4. **Webhook:** add a Webhook Trigger, save, and generate the webhook URL. It must start with your Render URL.
   Then from PowerShell:
   ```powershell
   Invoke-RestMethod -Method Post -Uri "<webhook-url>" -ContentType "application/json" -Body '{"hello":"world"}'
   ```
   A run with trigger **webhook** appears.
5. **Form:** add a Form Submission Trigger and save. Copy the form link (it must start with your Vercel URL)
   and open it in a private window. An invalid value shows field errors; a valid submit starts a run with
   trigger **form**.
6. **Schedule:** add a Schedule Trigger (every 1 minute) and save. With the app open (backend awake), a run
   with trigger **schedule** appears within ~2 minutes. Deactivate the workflow afterwards.

Optional automatic checks (read-only, from your PC):

```powershell
cd D:\Oneinfer\Project\agentic-flow\backend
python scripts\verify_production.py --backend https://<backend>.onrender.com --frontend https://<project>.vercel.app
```

---

## Step 8 (optional): Keep the backend awake for schedules

Only if you need Schedule Triggers to fire while nobody is using the app:
1. Create a free account at an uptime-monitoring service (any HTTP monitor works).
2. Add an HTTP monitor for `https://<backend>.onrender.com/health` with an interval of **10–14 minutes**.
3. This keeps one free service awake within Render's monthly free hours. It also keeps the Supabase project
   active.

---

## Environment reference

### Render (backend)

| Variable | Set by | Secret | Value / behaviour |
|---|---|---|---|
| `DATABASE_URL` | you (Step 4) | **yes** | Supabase session pooler URI (port 5432). TLS is enforced automatically. |
| `CREDENTIALS_ENCRYPTION_KEY` | you (Step 4) | **yes** | Fernet key from `generate_secrets.py`; **never change it** |
| `JWT_SECRET` | Render (auto-generated) | **yes** | signs login tokens; changing it signs everyone out |
| `PUBLIC_APP_URL` | you (Step 6) | no | Vercel URL; used in hosted form links |
| `CORS_ORIGINS` | you (Step 6) | no | Vercel URL(s), comma-separated, exact |
| `GEMINI_API_KEY` | you (Step 4) | **yes** | AI designer; placeholder = labelled mock mode |
| `APP_ENV` | render.yaml | no | `production`: refuses to start on unsafe settings and names them in the log |
| `DB_AUTO_MIGRATE` | render.yaml | no | `true`: creates/upgrades tables at startup |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | render.yaml | no | 3 / 2 (small, for the free pooler) |
| `AI_ALLOW_PLATFORM_KEYS` | render.yaml | no | `false`: users use their own encrypted keys |
| `HTTP_ALLOW_PRIVATE_NETWORKS` | render.yaml | no | `false` (SSRF protection) |
| `SCHEDULER_ENABLED` | render.yaml | no | `true` |
| `PYTHON_VERSION` | render.yaml | no | `3.13` |
| `PUBLIC_BASE_URL` | automatic | no | from Render's `RENDER_EXTERNAL_URL`; set it only for a custom backend domain |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CORS_ORIGIN_REGEX` | optional (dashboard) | keys: yes | not needed for the standard setup |

All other tuning variables have safe defaults; see `backend/.env.example`.

### Vercel (frontend)

| Variable | Value | Exposure |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Render URL | public (built into the browser code; changing it needs a redeploy) |
| `BACKEND_URL` | Render URL | server-only (used by the frontend's `/health`) |

### Supabase

Nothing is configured inside Supabase beyond creating the project. You only copy the session pooler
connection string and your database password into `DATABASE_URL`.

---

## 9. Backups (free tier)

Supabase Free has no restorable daily backups, so take your own when you have data worth keeping. Install
the PostgreSQL client once with `winget install PostgreSQL.PostgreSQL.17`, then:

```powershell
$env:PGPASSWORD = Read-Host "Supabase database password"
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" --format=custom --no-owner --no-privileges `
    --host aws-0-<region>.pooler.supabase.com --port 5432 --username postgres.<project-ref> `
    --dbname postgres --schema public --file "agentic-flow-$(Get-Date -Format yyyyMMdd).dump"
Remove-Item Env:PGPASSWORD
```

Keep the `CREDENTIALS_ENCRYPTION_KEY` together with the backup. Without it, stored credentials in the backup
cannot be decrypted.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Render log: `Refusing to start with APP_ENV=production: invalid configuration for X, Y` | The named variables are wrong. Common: `CORS_ORIGINS`/`PUBLIC_APP_URL` must start with `https://` and must not be localhost; `CREDENTIALS_ENCRYPTION_KEY` must be the exact value from `generate_secrets.py`. |
| Render log: `Network is unreachable` / timeout to `db.<ref>.supabase.co` | You used the **Direct connection**. Use the **Session pooler** string (host `*.pooler.supabase.com`, port 5432). |
| Render log: `password authentication failed` | Wrong password, `[YOUR-PASSWORD]` brackets left in, or special characters not encoded. The user must be `postgres.<project-ref>`. |
| Render log: `prepared statement ... already exists` | Transaction pooler (port 6543) used; switch to the session pooler (5432). |
| Render log: `Tenant or user not found` | The project ref or region in the URI is wrong. Copy the string again from **Connect**. |
| Supabase project shows **Paused** | Inactive for about a week. Click **Restore** in the Supabase dashboard, then reopen the app. |
| App says "Cannot reach the backend" | The backend is waking up (~1 min). Refresh. If it persists, check Render **Logs**. |
| Browser console shows a CORS error | `CORS_ORIGINS` on Render must equal your Vercel URL exactly (`https://…vercel.app`, no `/` at the end). Save and wait for the redeploy. |
| Vercel build fails at `[check-env] FAIL ...` | Set `NEXT_PUBLIC_API_URL` to the `https://…onrender.com` URL in Vercel → Settings → Environment Variables, then **Redeploy**. |
| Form links point to `example.com` or localhost | `PUBLIC_APP_URL` on Render is not set to the Vercel URL (Step 6). |
| A scheduled run did not happen | The backend was asleep at that time (free-tier limit), or the workflow is inactive. Check `/health/ready` → `"scheduler":"running"`. |
| Saved credentials fail after a change | `CREDENTIALS_ENCRYPTION_KEY` was changed. Put the original value back. |
| A run shows "interrupted by a server restart" | The backend slept, restarted or redeployed during the run. Run it again. |

---

## 11. Updating and rolling back

- **Update:** merge your changes into `main` and push.
  - Render redeploys the backend automatically, but only when files under `backend/` change. New migrations
    are applied at startup.
  - Vercel redeploys the frontend automatically.
- **Changed a `NEXT_PUBLIC_*` variable?** Vercel → Deployments → ⋯ → **Redeploy**, because it is built into
  the browser code.
- **Roll back the backend:** Render → service → **Events** / deploy history → choose a previous deploy →
  **Rollback**.
- **Roll back the frontend:** Vercel → **Deployments** → a previous production deployment → **Promote to
  Production** / **Instant Rollback**.
- **Database:** migrations only add tables and columns, so an older backend version still runs on the newer
  schema (the app logs a warning). Take a backup (section 9) before deploying a release that changes the
  schema.
