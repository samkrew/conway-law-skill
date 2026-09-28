# Conway's Law Skill for AI Coding Agents

A universal AI agent skill defining **when to keep tasks in a single context vs. when to delegate to subagents**, grounded in **Conway's Law**.

Compatible with **Claude Code**, **Codex CLI**, **Cursor**, **Aider**, **Hermes**, or any AI coding agent. Completely model-agnostic.

---

## 💡 The Core Principle

> *"Agent topology becomes code topology. Each boundary between agents becomes a seam in the code."*

Splitting a single complex feature across micro-agent pipelines creates interface bloat, loses context, and freezes iteration speed.

This skill equips agents with:
1. **The Monolithic Core:** Keep architecture, schemas, and tightly-coupled refactoring inside a single context.
2. **The Exit-Fast Gate:** Instant negative check to avoid over-delegation on routine or single-file edits.
3. **Contract-First Delegation:** Lock interfaces and schemas in the main context *before* dispatching workers.
4. **Standardized Worker Brief:** Explicit boundaries (`GOAL`, `CONTRACT`, `OWNED FILES`, `DONE WHEN`, `GAP REPORT`).
5. **Reconvergence & Verification:** Integrate and verify via real test suites and compilers in the main context.

---

## 📦 Usage

Install via `npx`:

```bash
npx skills add samkrew/conway-law-skill
```

Or copy `skills/conway-law` directly into your agent's skills directory:
- `~/.claude/skills/conway-law/`
- `~/.codex/skills/conway-law/`
- `~/.hermes/skills/conway-law/`

---

## ⚖️ License

The Unlicense. Public domain.
