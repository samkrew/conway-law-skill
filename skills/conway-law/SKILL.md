---
name: conway-law
description: "Conway's Law topology gate. Use BEFORE spawning or planning subagents or workers (Workflow, Agent, spawn_agent), under ultracode, and when asked to parallelize, fan out, delegate, or split a monorepo refactor. RU: 'параллельно', 'делегируй', 'субагенты', 'закон Конвея'. Picks the shape of the fan-out. Not for routine edits of 1-2 files."
---

# Conway's Law: Topology Gate for Agents and Workflows

**Agent topology becomes code topology.** Each boundary between agents becomes a seam in the output. Keep coupled decisions in one context. Fan out only work that is independent by contract.

- **Intra-context reasoning:** fast, full fidelity, shared invariants.
- **Inter-agent delegation:** lossy summaries, interface bloat, compounding drift.

This skill picks the **shape** of multi-agent work. It does not forbid orchestration. Some harnesses make orchestration the default (for example Claude Code ultracode). There, this skill decides which parts fan out and which parts stay in one context.

## Output contract

Before the first worker spawn of a task, write one line:

`Conway gate: <shape> - <one-clause reason>`

`<shape>` is one of `solo`, `read-fanout`, `verify-panel`, `single-writer`, `contract-writes`, or a sequence such as `read-fanout -> single-writer -> verify-panel`.

---

## 0. Exit fast (solo)

Stay in the current context and spawn no workers if one condition is true:
- The turn is conversational, or the edit is trivial and mechanical.
- The task is a routine edit of 1-2 files.
- Each step needs the output of the step before it, and no step is read-only research or independent verification.

> **Tool concurrency is not delegation.** Parallel tool calls in one turn (file reads, searches, web fetches, read-only shell commands) are cheap. Use them freely. This skill governs worker spawns: subagents, workflow agents, background sessions, and agent teams.

---

## 1. Shape table

Use this table for every fan-out. When the task has phases, pick a shape for each phase.

| Work type | Shape | Pattern |
|---|---|---|
| Wide research, codebase discovery, source lookup, audits | `read-fanout` | Independent read-only workers with structured output. Merge in a later stage or in the main context. |
| Review, verification, fact-check of a FROZEN artifact | `verify-panel` | N independent verifiers or judges, each with a distinct lens. Structured verdicts, majority or union. No file writes. |
| Architecture, domain model, DB schema, API contract, design choice | `single-writer` | Optional panel of N independent drafts (no file writes). ONE agent or the main context writes the design artifact (contract, schema, ADR). The main context approves the choice. Then `verify-panel`. |
| Debugging with an unknown root cause | `single-writer` | `read-fanout` for evidence (logs, code paths, candidate hypotheses). ONE context holds the hypothesis and runs the experiments. |
| Refactor that changes a shared invariant (rename, core type, protocol) | `single-writer` | `read-fanout` impact scan. Then ONE writer applies the change. Then `verify-panel`. |
| Mechanical migration of N independent sites with a frozen transform rule | `contract-writes` | Discover the sites. Group small sites into units that pass section 2, Q5. Transform each unit. Use isolated copies only when units share a writable file. One integrator stage merges and verifies. |
| N modules or adapters against a frozen interface | `contract-writes` | Stage 1: one agent writes the contract to disk. Stage 2: parallel writers, each with disjoint OWNED FILES. Stage 3: one integrator stage runs the full build and tests. |
| Unit tests for decoupled modules | `contract-writes` | One test-suite owner per module. |
| Merge, dedup, scoring of worker results | stage inside the workflow | Allowed as a workflow stage. |
| Final decision, user-facing verdict, recommendation | main context | The workflow returns structured data. The main context decides. |

---

## 2. Decision gate for parallel WRITES

Apply this gate when two or more agents would create or edit files in the same run. Answer in order. At the first "NO" that has no alternative, use `single-writer` for that part.

1. **Contract frozen?** Types, signatures, schema, and file layout are written to disk and stable.
2. **Units independent?** Each unit can finish with only the contract and its own files. It does not wait for another worker.
3. **Files disjoint?** No two units share a writable file. Check hidden shared files: lockfiles, package manifests, barrel `index.ts` files, route tables, migrations. Alternative: each unit runs in an isolated copy (for example a git worktree), and the integrator stage merges the shared files.
4. **Verification exists?** Each unit has its own test or build command (exit code 0). Alternative: the integrator stage verifies all units, and a failed unit is cheap to redo.
5. **Worth the cold start?** Each unit needs substantial isolated work (1 full file or more, or 15 tool turns or more). This question does not apply to read-only or verify stages.

---

## 3. Protocol for safe delegation

### Step 1: Lock the boundary (main context or one contract stage)
1. Write and save the contract files (interfaces, types, DB schemas, signatures).
2. Stabilize only the boundary that the workers need. Do not invent abstractions only to force parallelism.

### Step 2: Dispatch bounded workers
- **Depth limit:** workers do not spawn workers. One orchestrator owns all spawns: the main context, or one workflow script together with its inline child workflows. Stages inside one orchestrator (sequential or pipelined phases) are not depth.
- **One file, one owner:** give each worker an exclusive set of files.
- Use this worker brief:

```text
GOAL: <one-sentence objective>
CONTRACT: <path/to/contract> (read-only, do not modify)
OWNED FILES: <exact paths/globs to create or edit>
DONE WHEN: <test or build command> exits 0
ON CONTRACT GAP: stop and report immediately. Do not invent workarounds.
RETURN: modified file list, command output summary, unresolved issues (no conversational fluff)
```

### Step 3: Reconverge and verify
1. Wait for the workers. Inspect the real file diffs, not the self-reports.
2. If workers ran in isolated copies, merge each copy into the main tree first.
3. Run the full build, linter, and cross-module tests. An integrator stage can run them. The main context then checks the exit codes.
4. If a worker reports a contract gap or conflict, resolve it in the main context. Re-dispatch only the affected units.

---

## 4. Harness mapping

### Claude Code
- Worker spawns are the `Agent` tool and the `Workflow` tool (`agent()` calls inside the script).
- `read-fanout`: `pipeline()` by default. Use `parallel()` only when a stage needs all prior results (dedup, early exit). Give each agent a `schema`.
- `contract-writes`: use `isolation: 'worktree'` only when units share a writable file (section 2, Q3 alternative). With disjoint OWNED FILES, use no isolation. Merge each returned worktree branch before the full build.
- Ultracode tells the model to use the Workflow tool on every substantive task, says token cost is not a constraint, and allows solo work only on conversational or trivial turns. Map it to this skill:
  - Substantive task: use a workflow. Pick the shape of each phase from section 1.
  - Cost: cost does not limit `read-fanout` and `verify-panel` stages. Coupling still limits parallel writes. Cost never unlocks parallel writes.
  - Solo: section 0 lists all solo cases.
- A deny from the `conway-gate` hook is an automated pre-flight check, not a user rejection. Load this skill, write the `Conway gate:` line, then re-issue the call, reshaped if the `Conway gate:` line requires it.

### Codex
- Worker spawns are `spawn_agent` calls. Apply the gate before the first `spawn_agent` call of a task.
- The main thread is the orchestrator. Spawned agents do not spawn agents.
- For post-implementation review, default to one fresh reviewer. Use a larger `verify-panel` only when the user asks for depth.

---

## 5. Golden rules

1. **If in doubt, keep decisions and writes in one context.** Read-only evidence gathering and independent verification can fan out.
2. **No frozen contract means no parallel writes.**
3. **One file, one owner.** Two parallel agents never edit the same file in the same working tree.
4. **Verify execution.** "Complete" from a worker is a self-report. Check exit codes, diffs, and test output.
5. **The final call stays in the main context.** Merge and scoring stages can run inside a workflow. The decision and the user-facing verdict do not.
