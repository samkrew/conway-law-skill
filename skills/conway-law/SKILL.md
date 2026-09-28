---
name: conway-law
description: "Choose one context vs subagents (Conway's Law): complex planning, monorepo refactor; parallelize, delegate, subagents; параллельно, делегируй, субагенты, закон Конвея. Gate before spawning workers. Not for 1-file edits."
---

# Conway's Law: Agent Parallel Orchestration & Workflow Protocol

**Agent topology becomes code topology.** Each boundary between agents becomes a seam in the code. Keep coupled decisions in one coordinating context; delegate bounded work only when benefits exceed coordination overhead.

- **Intra-context reasoning:** Fast, full fidelity, shared memory invariants.
- **Inter-agent delegation:** Slow, lossy summaries, interface bloat, compounding drift.

---

## 0. Exit Fast (Negative Gate)

Stay in the current context and stop assessing this skill if:
- The task touches ≤ 2 files or requires routine linear edits.
- Steps are sequential: step N strictly depends on step N-1 output.
- Shared interfaces (types, schema, API, core invariants) are still evolving.

> **Tool concurrency is not delegation.** Parallel tool calls (`read_file`, `search_files`, `web_search`) in a single turn are lightweight and encouraged. This skill governs spawning subagents, background sessions, and parallel worker processes.

---

## 1. Decision Gate

Answer in order. At the first "NO", keep the work in the current context.

1. **Contract frozen?** Types, signatures, schema, and file layout are written to disk and stable.
2. **Units independent?** Each unit can complete using only the contract and its own files without waiting for another worker.
3. **Files disjoint?** No two units share writable files. Check hidden shared files: lockfiles, package manifests, barrel `index.ts` files, route tables, and migrations.
4. **Own verification command?** Each unit has an isolated test or build command that proves success/failure ($rc=0$).
5. **Worth the cold start?** The unit requires substantial isolated work (≥ 1 full file or ≥ 15 tool turns). Otherwise, implement inline.

---

## 2. Decision Matrix

| Work Type | Strategy | Reason |
|---|---|---|
| **Architecture, domain models, DB schemas** | **One context** | Tightly-coupled decisions; splitting causes conflicting abstractions. |
| **Cross-cutting changes (renames, refactors)** | **One context** | Shared invariant; mechanical edits best executed in single pass. |
| **Debugging unknown root cause** | **One context** | Shared hypothesis testing. Read-only search fan-out is permitted. |
| **N modules/adapters against frozen interface** | **Parallel write** | Clear contract; disjoint file sets. |
| **Unit test suites for decoupled modules** | **Parallel write** | Test suites for Module A do not affect Module B. |
| **Wide codebase research & doc lookup** | **Parallel read-only** | Gathers evidence without polluting main reasoning context. |
| **Post-implementation review / audit** | **One fresh reviewer** | Independent verification pass over completed code. |

---

## 3. Protocol for Safe Delegation

### Step 1: Lock the Boundary (Main Context)
1. Write and save contract files (interfaces, types, DB schemas, signatures).
2. Stabilize only the boundary required by the worker. Do not invent artificial abstractions merely to force parallelism.

### Step 2: Dispatch Bounded Workers
- Maximum depth is 1: workers must not spawn additional workers.
- Assign an exclusive file ownership set to each worker.
- Use this explicit worker brief:

```text
GOAL: <one-sentence objective>
CONTRACT: <path/to/contract> (read-only; do not modify)
OWNED FILES: <exact paths/globs to create or edit>
DONE WHEN: <test or build command> exits 0
ON CONTRACT GAP: stop and report immediately; do not invent workarounds
RETURN: modified file list, command output summary, unresolved issues (no conversational fluff)
```

### Step 3: Reconverge & Verify (Main Context)
1. Wait for worker completion; inspect actual file diffs, not self-reported claims.
2. Run full project build, linter, and cross-module test suites in the main context.
3. If a worker reports a contract gap or conflict, resolve it centrally in the main context and re-dispatch only affected units.

---

## 4. Golden Rules

1. **If in doubt, stay in one context.** Parallelization adds coordination overhead.
2. **No frozen contract means no parallel writes.**
3. **One file, one owner.** Never allow two parallel processes or subagents to edit the same file.
4. **Verify execution.** A worker claiming "complete" is a self-report. Always verify exit codes and test output.
