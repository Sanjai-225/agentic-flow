# 🤖 Agent Instructions — agentic-flow Repository.

> **This file governs all AI agents (Antigravity, Copilot, Cursor, Cline, Devin, etc.) and collaborators working on this repository.**
> Every collaborator and AI agent **must** read and follow these rules before making any changes.

---

## 🏗️ Branch Strategy

| Branch    | Purpose                                  | Who can push / merge                                  |
|-----------|------------------------------------------|-------------------------------------------------------|
| `main`    | **Production** — stable, deployed code   | **Repository owner only** (@Sanjai-225 via approved PR) |
| `testing` | **Development** — all new work goes here | Collaborators & agents (**requires human confirmation**) |

### Core Rules

1. **Never push directly to `main`.** All commits go to `testing` (or a feature branch off `testing`).
2. **All work starts from `testing`.** Before starting any task, ensure you are on the `testing` branch.
3. **Pull before you push.** Always `git pull origin testing` before committing to avoid merge conflicts.
4. **Mandatory Human Confirmation Before Push:**
   - **No agent or automated script may run `git push` autonomously.**
   - Before pushing to any remote branch, the agent **must** present a summary of changes to the human user and receive **explicit human approval** to proceed.
5. **Merging to `main` requires:**
   - A Pull Request from `testing` → `main`
   - Explicit approval and merge by the repository owner (@Sanjai-225)
   - No agent or collaborator may approve or merge PRs into `main` without owner authorization

---

## 📝 Commit Guidelines

- Write clear, descriptive commit messages (e.g., `Add user authentication module`, not `update`).
- Keep commits atomic — one logical change per commit.
- Do not commit secrets, API keys, tokens, or credentials.
- Do not commit large binary files or build artifacts.

---

## 🔀 Workflow for Agents & Collaborators

```
1. git checkout testing
2. git pull origin testing
3. <make changes & verify locally>
4. git add <files>
5. git commit -m "Descriptive commit message"
6. [MANDATORY STEP] Ask human user: "Here is what will be pushed: <summary>. Confirm push to remote?"
7. Once human explicitly confirms: git push origin testing
```

> **To promote changes to production:**
> Create a PR from `testing` → `main` on GitHub. Only the repo owner can review, approve, and merge it.

---

## 🚫 Prohibited Actions

- ❌ **Do NOT** push to `main` directly
- ❌ **Do NOT** execute `git push` without prior explicit confirmation from the human user
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
4. Follow the commit, human-confirmation, and branching rules above

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
