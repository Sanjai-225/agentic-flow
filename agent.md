# 🤖 Agent Instructions — agentic-flow Repository

> **This file governs all AI agents (Antigravity, Copilot, Cursor, Cline, Devin, etc.) working on this repository.**
> Every collaborator's agent **must** read and follow these rules before making any changes.

---

## 🏗️ Branch Strategy

| Branch    | Purpose                        | Who can merge to it              |
|-----------|--------------------------------|----------------------------------|
| `main`    | **Production** — stable, deployed code | **Repository owner only** (via approved PR) |
| `testing` | **Development** — all new work goes here | All collaborators and agents     |

### Rules

1. **Never push directly to `main`.** All commits go to `testing` (or a feature branch off `testing`).
2. **All work starts from `testing`.** Before starting any task, ensure you are on the `testing` branch (or a feature branch created from `testing`).
3. **Pull before you push.** Always `git pull origin testing` before committing to avoid conflicts.
4. **Merging to `main` requires:**
   - A Pull Request from `testing` → `main`
   - Explicit approval from the repository owner (@Sanjai-225)
   - No agent may approve or merge PRs into `main`

---

## 📝 Commit Guidelines

- Write clear, descriptive commit messages (e.g., `Add user authentication module`, not `update`).
- Keep commits atomic — one logical change per commit.
- Do not commit secrets, API keys, tokens, or credentials.
- Do not commit large binary files or build artifacts.

---

## 🔀 Workflow for Agents

```
1. git checkout testing
2. git pull origin testing
3. <make changes>
4. git add <files>
5. git commit -m "Descriptive commit message"
6. git push origin testing
```

> **To promote changes to production:**
> Create a PR from `testing` → `main` on GitHub. Only the repo owner can review, approve, and merge it.

---

## 🚫 Prohibited Actions

- ❌ **Do NOT** push to `main` directly
- ❌ **Do NOT** force-push (`git push --force`) to any branch
- ❌ **Do NOT** delete branches without owner approval
- ❌ **Do NOT** modify this `agent.md` file without owner approval
- ❌ **Do NOT** merge PRs into `main` (only the owner can)
- ❌ **Do NOT** commit `.env` files, secrets, or credentials
- ❌ **Do NOT** bypass branch protection rules

---

## ✅ Before Every Session

1. Read this `agent.md` file
2. Confirm you are on the correct branch (`testing`)
3. Pull the latest changes
4. Follow the commit and branching rules above

---

## 📂 Repository Structure

- `main` — Production-ready code only
- `testing` — Active development, new features, bug fixes

---

## 👤 Repository Owner

- **GitHub:** [@Sanjai-225](https://github.com/Sanjai-225)
- Only the owner has authority to merge into `main` and modify protection rules.

---

*Last updated: 2026-11-12*
