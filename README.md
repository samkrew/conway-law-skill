# Conway's Law Skill for AI Coding Agents

A universal AI agent skill defining **when to keep tasks in a single context vs. when to delegate to subagents**, grounded in **Conway's Law**.

Compatible with **Claude Code**, **Codex CLI**, **Cursor**, **Aider**, **Hermes**, or any AI coding agent. Completely model-agnostic.

---

## 💡 The Core Principle

> *"Agent topology becomes code topology. Each boundary between agents becomes a seam in the code."*

Splitting a single complex feature across micro-agent pipelines creates interface bloat, loses context, and freezes iteration speed.

This skill equips agents with:
1. **The Monolithic Core:** Keep architecture, schemas, and tightly-coupled refactoring inside a single context.
2. **The Exit-Fast Gate:** Instant negative check to avoid over-delegation on routine edits of 1-2 files.
3. **The Shape Table:** Pick the shape of multi-agent work: `solo`, `read-fanout`, `verify-panel`, `single-writer`, or `contract-writes`.
4. **Contract-First Delegation:** Lock interfaces and schemas in the main context or one contract stage *before* dispatching workers.
5. **Standardized Worker Brief:** Explicit boundaries (`GOAL`, `CONTRACT`, `OWNED FILES`, `DONE WHEN`, `ON CONTRACT GAP`, `RETURN`).
6. **Reconvergence & Verification:** Integrate and verify via real test suites and compilers. The main context checks the exit codes.

The gate shapes orchestration. It does not forbid it. Some harnesses make orchestration the default (for example Claude Code ultracode). There, read-only fan-out and verify panels stay cheap. Parallel writes still need a frozen contract.

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

`SKILL.md` frontmatter uses only `name` and `description`, so it passes the Codex skill validator.

---

## 🚦 Claude Code: enforcement hook

A skill description alone does not load the gate at the moment it matters:
- Claude Code decides to spawn workers by itself. Users rarely type "parallelize" or "delegate".
- Under ultracode, the harness force-loads `workflow-authoring` and says "use the Workflow tool". The model makes no skill-selection step.
- On small context windows the skill listing can drop descriptions to names only.

`hooks/conway-gate.py` adds a deterministic route:

| Event | Behavior |
|---|---|
| `UserPromptSubmit` | On an ultracode prompt (keyword or session mode), adds a short directive: load `conway-law`, write `Conway gate: <shape> - <reason>`. Other prompts: no output. |
| `PreToolUse` `Skill` | Records that the main thread loaded `conway-law` in this session. |
| `PreToolUse` `Workflow` / `Agent` | Main thread only. If the gate is not loaded, denies the spawn. The deny reason tells the model to load the skill and retry. |

Parallel batches: Claude Code runs this hook per tool call as each call finishes streaming. The calls of one batch can arrive seconds apart. The hook denies every call inside a sliding window after the last deny (30 s default). Each deny extends the window.

Safety:
- The hook never returns `allow`. It fails open on any error.
- After 16 denied calls per prompt, or 2 denied prompts per session, calls pass. No deny loop.
- It skips subagents, Workflow resumes and run operations, saved workflows called by name, and read-only agent types (`Explore`, `Plan`, `claude-code-guide`, `statusline-setup`).
- It skips `claude -p` and SDK runs, and local model backends (`ANTHROPIC_BASE_URL` on localhost).

### Install as a plugin

```bash
claude plugin marketplace add samkrew/conway-law-skill
claude plugin install conway-law-skill@conway-law-skill
```

The plugin install adds the skill and registers `hooks/hooks.json`. `npx skills add` installs the skill only, with no hook.

### Install manually

1. Copy `hooks/conway-gate.py` to `~/.claude/hooks/conway-gate.py`.
2. Merge this block into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python3 -I ~/.claude/hooks/conway-gate.py", "timeout": 10 }] }
    ],
    "PreToolUse": [
      { "matcher": "Workflow|Agent|Skill",
        "hooks": [{ "type": "command", "command": "python3 -I ~/.claude/hooks/conway-gate.py", "timeout": 10 }] }
    ]
  }
}
```

3. Start a new session. Hooks load at startup.

Use one install method, not both.

### Settings

| Env var | Default | Effect |
|---|---|---|
| `CONWAY_GATE=off` | on | Disable all behavior. |
| `CONWAY_GATE_PRETOOL=off` | on | Disable the `PreToolUse` deny only. |
| `CONWAY_GATE_DENY_WINDOW_S` | `30` | Sliding deny window after the last deny, in seconds. |
| `CONWAY_GATE_MAX_DENY_CALLS` | `16` | Denied calls per prompt. |
| `CONWAY_GATE_MAX_DENY_PROMPTS` | `2` | Prompts per session that can get a deny. |
| `CONWAY_GATE_EXEMPT_AGENT_TYPES` | `Explore,Plan,claude-code-guide,statusline-setup` | Agent types that pass without the gate. Case-insensitive. |
| `CONWAY_GATE_SKIP_ENTRYPOINTS` | `sdk-cli,sdk-ts,sdk-py` | `CLAUDE_CODE_ENTRYPOINT` values to skip. |
| `CONWAY_GATE_LOCAL=on` | off | Keep the gate on for local model backends. |
| `CONWAY_GATE_STATE_DIR` | `$TMPDIR` | Absolute parent of the `claude-conway-gate-<uid>` subdirectory for markers and `log.jsonl`. The subdirectory has mode 0700. The hook does nothing if it is a symlink or belongs to another user. |

Tip: the bare word `ultracode` in a Claude Code prompt turns on ultracode for that prompt. Write it in backticks or quotes to mention it without that effect.

### Tests

```bash
python3 -I tests/test_conway_gate.py
```

Offline. No Claude Code session needed. Exit code 0 means all cases pass.

Live check (Claude Code 2.1.295, `claude -p --settings` with `CONWAY_GATE_SKIP_ENTRYPOINTS=none`): a batch of 5 `Agent` calls in one message arrived 7-8 s apart. The hook denied all 5 with the default window. The model loaded `conway-law`, wrote the `Conway gate:` line, and re-issued the 5 calls. They passed.

---

## ⚖️ License

The Unlicense. Public domain.
