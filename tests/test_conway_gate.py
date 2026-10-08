#!/usr/bin/env python3
"""Offline tests for hooks/conway-gate.py. No Claude Code session needed.

Run:  python3 -I tests/test_conway_gate.py [path/to/conway-gate.py]
Exit code 0 = all pass.
"""
import json
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "conway-gate.py")

TMP = tempfile.mkdtemp(prefix="conway-gate-test-")
atexit.register(shutil.rmtree, TMP, True)
STATE = os.path.join(TMP, "state")
FAILS = []
CLEAN_ENV = (
    "CONWAY_GATE", "CONWAY_GATE_PRETOOL", "CONWAY_GATE_EXEMPT_AGENT_TYPES",
    "CONWAY_GATE_SKIP_ENTRYPOINTS", "CONWAY_GATE_DENY_WINDOW_S",
    "CONWAY_GATE_MAX_DENY_PROMPTS", "CONWAY_GATE_MAX_DENY_CALLS", "CONWAY_GATE_LOCAL",
    "ANTHROPIC_BASE_URL",
)


def run(payload, env_extra=None, raw=None):
    env = dict(os.environ)
    for k in CLEAN_ENV:
        env.pop(k, None)
    env["CONWAY_GATE_STATE_DIR"] = STATE
    env["CLAUDE_CONFIG_DIR"] = TMP  # no settings.json there: hermetic fallback
    env["CLAUDE_CODE_ENTRYPOINT"] = "cli"
    if env_extra:
        env.update(env_extra)
    data = raw if raw is not None else json.dumps(payload)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-I", HOOK], input=data, capture_output=True, text=True, env=env, timeout=20)
    dt = time.time() - t0
    out = p.stdout.strip()
    return p.returncode, (json.loads(out) if out else None), dt


def transcript(name, records):
    path = os.path.join(TMP, name + ".jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
    return path


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(detail)))
    if not cond:
        FAILS.append(name)


def ups(sid, prompt, tpath="", **kw):
    d = {"session_id": sid, "transcript_path": tpath, "cwd": TMP, "hook_event_name": "UserPromptSubmit", "prompt": prompt}
    d.update(kw)
    return d


def pre(sid, tool, tin, tpath="", prompt_id="p1", tool_use_id="tu1", **kw):
    d = {"session_id": sid, "prompt_id": prompt_id, "transcript_path": tpath, "cwd": TMP,
         "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tin, "tool_use_id": tool_use_id}
    d.update(kw)
    return d


def ctx(out):
    return ((out or {}).get("hookSpecificOutput") or {}).get("additionalContext", "")


def decision(out):
    return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


def stdout_rec(text):
    return {"type": "user", "message": {"role": "user", "content": "<local-command-stdout>" + text + "</local-command-stdout>"}}


AGENT = {"prompt": "x", "subagent_type": "general-purpose"}
WF = {"script": "export const meta = {}"}

empty = transcript("empty", [])
uc_on = transcript("uc_on", [{"type": "attachment", "attachment": {"type": "ultra_effort_enter", "reminderType": "full"}}])
uc_off = transcript("uc_off", [
    {"type": "attachment", "attachment": {"type": "ultra_effort_enter", "reminderType": "full"}},
    {"type": "attachment", "attachment": {"type": "ultra_effort_exit"}},
])
uc_cmd_new = transcript("uc_cmd_new", [stdout_rec("Ultracode on (this session only): dynamic workflows on every task. Effort stays xhigh.")])
uc_cmd_old = transcript("uc_cmd_old", [stdout_rec("Set effort level to ultracode (this session only): xhigh + dynamic workflow orchestration")])
uc_slider_off = transcript("uc_slider_off", [
    stdout_rec("Ultracode on (this session only): dynamic workflows on every task. Effort stays xhigh."),
    stdout_rec("Set effort level to high · Ultracode off"),
])
uc_level_change = transcript("uc_level_change", [
    {"type": "attachment", "attachment": {"type": "ultra_effort_enter", "reminderType": "full"}},
    stdout_rec("Set effort level to max"),
])
quoted_marker = transcript("quoted_marker", [
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "grep: Set effort level to ultracode ... Ultracode on"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "The marker is 'Set effort level to ultracode'."}]}},
])
loaded_tu = transcript("loaded_tu", [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "conway-law"}}]}}])
loaded_compact = transcript("loaded_compact", [{"type": "attachment", "attachment": {"type": "invoked_skills", "skills": [{"name": "conway-law", "path": "userSettings:conway-law", "content": "..."}]}}])
loaded_slash = transcript("loaded_slash", [{"type": "user", "message": {"role": "user", "content": "<command-message>conway-law</command-message>\n<command-name>/conway-law</command-name>"}}])
escaped_only = transcript("escaped_only", [{"type": "user", "message": {"content": [{"type": "tool_result", "content": "grep found 0 files with \"skill\":\"conway-law\" in them"}]}}])

# 01-14: UserPromptSubmit keyword and session detection
rc, out, _ = run(ups("s1", "Помоги настроить, особенно conway law в режиме ultracode", empty))
check("01 keyword (RU prompt) -> directive to load skill", rc == 0 and "invoke Skill conway-law" in ctx(out), out)
rc, out, _ = run(ups("s2", "what does `ultracode` do?", empty))
check("02 keyword in backticks -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s3", "/effort ultracode", empty))
check("03 slash-prefixed prompt -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s4", "fix the parser", uc_on))
check("04 session ultracode via ultra_effort_enter -> directive", rc == 0 and "conway-law" in ctx(out), out)
rc, out, _ = run(ups("s5", "fix the parser", uc_off))
check("05 enter then exit -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s6", "fix the parser", uc_cmd_new))
check("06 2.1.287+ stdout 'Ultracode on' -> directive", rc == 0 and "conway-law" in ctx(out), out)
rc, out, _ = run(ups("s6b", "fix the parser", uc_cmd_old))
check("06b legacy stdout 'Set effort level to ultracode' -> directive", rc == 0 and "conway-law" in ctx(out), out)
rc, out, _ = run(ups("s6c", "fix the parser", uc_slider_off))
check("06c slider 'Ultracode off' -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s6d", "fix the parser", uc_level_change))
check("06d level change without 'Ultracode off' keeps state on", rc == 0 and "conway-law" in ctx(out), out)
rc, out, _ = run(ups("s6e", "fix the parser", quoted_marker))
check("06e marker text in tool_result/assistant text -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s7", "fix the parser", empty))
check("07 no ultracode -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s8", "<task-notification>ultracode audit X done</task-notification>", empty))
check("08 task-notification prompt -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s9", "re-run ultracode-style", empty))
check("09 keyword followed by '-' -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s10", "ultracode: audit X", loaded_tu))
check("10 keyword + skill already loaded -> short directive", rc == 0 and "write one line" in ctx(out) and "invoke Skill" not in ctx(out), out)
rc, out, _ = run(ups("s11", "сделай «ultracode» прогон", empty))
check("11 guillemets are not a harness pair -> directive (parity)", rc == 0 and "conway-law" in ctx(out), out)
rc, out, _ = run(ups("s12", "what is ultracode? explain", empty))
check("12 keyword followed by '?' -> no output", rc == 0 and out is None, out)
rc, out, _ = run(ups("s13", "check (ultracode) and \"ultracode\" and [ultracode]", empty))
check("13 keyword only inside brackets/quotes -> no output", rc == 0 and out is None, out)
big_prompt = "<br>" * 40000 + " ultracode"
rc, out, dt = run(ups("s14", big_prompt, empty))
check("14 160KB prompt of unclosed tags < 2s (got %.2fs)" % dt, rc == 0 and dt < 2.0, out)

# 20-27: PreToolUse batch-aware deny
rc, out, _ = run(pre("s20", "Workflow", WF, empty, "pA"))
check("20 Workflow, gate not loaded -> deny", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s20", "Agent", AGENT, empty, "pA"))
check("21 same prompt inside window -> deny again", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s20", "Agent", AGENT, empty, "pA"), env_extra={"CONWAY_GATE_DENY_WINDOW_S": "0"})
check("22 same prompt after window -> pass (no loop)", rc == 0 and out is None, out)
rc, out, _ = run(pre("s20", "Agent", AGENT, empty, "pB"))
check("23 second prompt, still not loaded -> deny", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s20", "Agent", AGENT, empty, "pC"))
check("24 third prompt beyond cap 2 -> pass", rc == 0 and out is None, out)

with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(lambda i: run(pre("s25", "Agent", AGENT, empty, "pBatch")), range(8)))
denied = sum(1 for r in res if decision(r[1]) == "deny")
check("25 parallel batch of 8 Agent calls -> all 8 denied (got %d)" % denied, denied == 8, denied)

run(pre("s26", "Skill", {"skill": "conway-law"}, empty, "pX"))
rc, out, _ = run(pre("s26", "Workflow", WF, empty, "pX"))
check("26 Skill then Workflow in one message -> Workflow passes", rc == 0 and out is None, out)

win2 = {"CONWAY_GATE_DENY_WINDOW_S": "2"}
res = []
for i in range(4):
    res.append(run(pre("s27", "Agent", AGENT, empty, "pS", "tb%d" % i), env_extra=win2))
    time.sleep(1.2)
denied = sum(1 for r in res if decision(r[1]) == "deny")
check("27 streamed batch, gaps 1.2 s, window 2 s sliding (span > 3.6 s) -> all 4 denied (got %d)" % denied, denied == 4, denied)
time.sleep(2.2)
rc, out, _ = run(pre("s27", "Agent", AGENT, empty, "pS", "tc0"), env_extra=win2)
check("28 call after the window -> pass", rc == 0 and out is None, out)
res = [run(pre("s28", "Agent", AGENT, empty, "pT", "tb%d" % i), env_extra={"CONWAY_GATE_MAX_DENY_CALLS": "3"}) for i in range(5)]
denied = sum(1 for r in res if decision(r[1]) == "deny")
check("29 denied calls per prompt capped at 3 (got %d)" % denied, denied == 3, denied)

# 30-33: Skill marker path
rc, out, _ = run(pre("s30", "Skill", {"skill": "conway-law"}, empty, "pA"))
check("30 Skill conway-law -> no output", rc == 0 and out is None, out)
rc, out, _ = run(pre("s30", "Workflow", WF, empty, "pA"))
check("31 Workflow after Skill marker -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s31", "Skill", {"skill": "/conway-law"}, empty))
rc, out, _ = run(pre("s31", "Agent", AGENT, empty))
check("32 Skill '/conway-law' sets marker", rc == 0 and out is None, out)
rc, out, _ = run(pre("s32", "Skill", {"skill": "conway-law-skill:conway-law"}, empty))
rc, out, _ = run(pre("s32", "Agent", AGENT, empty))
check("33 plugin-qualified skill name sets marker", rc == 0 and out is None, out)
rc, out, _ = run(pre("s33", "Skill", {"skill": "conway-law"}, empty, agent_id="agent-9"))
rc, out, _ = run(pre("s33", "Workflow", WF, empty))
check("34 subagent Skill load does not mark main thread", rc == 0 and decision(out) == "deny", out)

# 40-50: exemptions and switches
rc, out, _ = run(pre("s40", "Agent", AGENT, empty, agent_id="agent-1"))
check("40 inside subagent -> pass", rc == 0 and out is None, out)
for i, t in enumerate(("Explore", "Plan", "claude-code-guide", "statusline-setup")):
    rc, out, _ = run(pre("s41%d" % i, "Agent", {"prompt": "x", "subagent_type": t}, empty))
    check("41 exempt agent type %s -> pass" % t, rc == 0 and out is None, out)
rc, out, _ = run(pre("s42", "Workflow", {"scriptPath": "/x.js", "resumeFromRunId": "wf_1"}, empty))
check("42 Workflow resume -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s43", "Workflow", {"name": "deep-research"}, empty))
check("43 saved workflow by name -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s44", "Workflow", {"runId": "wf_1", "op": "stop"}, empty))
check("44 Workflow run operation -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s45", "Workflow", {"scriptPath": "/x.js"}, empty))
check("45 Workflow scriptPath without resume -> deny", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s45b", "Workflow", {"scriptPath": "/x.js", "name": "deep-research"}, empty))
check("45b Workflow scriptPath + name -> deny (scriptPath wins)", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s45c", "Agent", {"prompt": "x", "subagent_type": "explore"}, empty))
check("45c exempt agent types are case-insensitive", rc == 0 and out is None, out)
rc, out, _ = run(pre("s46", "Workflow", WF, empty), env_extra={"CONWAY_GATE": "off"})
check("46 CONWAY_GATE=off -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s47", "Workflow", WF, empty), env_extra={"CONWAY_GATE_PRETOOL": "off"})
check("47 CONWAY_GATE_PRETOOL=off -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s48", "Agent", AGENT, empty), env_extra={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})
check("48 claude -p / SDK entrypoint -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s49", "Agent", AGENT, empty), env_extra={"ANTHROPIC_BASE_URL": "http://127.0.0.1:8080"})
check("49 local model backend -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s50", "Agent", AGENT, empty), env_extra={"ANTHROPIC_BASE_URL": "http://localhost:9000", "CONWAY_GATE_LOCAL": "on"})
check("50 local backend with CONWAY_GATE_LOCAL=on -> deny", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s51", "Agent", AGENT, empty), env_extra={"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
check("51 remote base URL -> gate stays on", rc == 0 and decision(out) == "deny", out)

# 60-63: transcript fallback detection
rc, out, _ = run(pre("s60", "Workflow", WF, loaded_tu))
check("60 transcript Skill tool_use -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s61", "Workflow", WF, loaded_compact))
check("61 invoked_skills after compaction -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s62", "Workflow", WF, loaded_slash))
check("62 user typed /conway-law -> pass", rc == 0 and out is None, out)
rc, out, _ = run(pre("s63", "Workflow", WF, escaped_only))
check("63 escaped mention only -> still deny", rc == 0 and decision(out) == "deny", out)

# 70-74: robustness
rc, out, _ = run(None, raw="not json")
check("70 garbage stdin -> exit 0, no output", rc == 0 and out is None, out)
rc, out, _ = run(pre("s71", "Bash", {"command": "ls"}, empty))
check("71 other tool -> no output", rc == 0 and out is None, out)
rc, out, _ = run(pre("s72", "Workflow", WF, "/nonexistent/path.jsonl"))
check("72 missing transcript -> deny, no crash", rc == 0 and decision(out) == "deny", out)
rc, out, _ = run(pre("s73", "Workflow", WF, empty))
check("73 never returns allow", decision(out) != "allow", out)

LEAF = "claude-conway-gate-%d" % os.getuid()
target = os.path.join(TMP, "attacker-target")
os.makedirs(target)
p75 = os.path.join(TMP, "parent75")
os.makedirs(p75)
os.symlink(target, os.path.join(p75, LEAF))
rc, out, _ = run(pre("s75", "Workflow", WF, empty), env_extra={"CONWAY_GATE_STATE_DIR": p75})
check("75 symlinked state subdir -> no output, no writes", rc == 0 and out is None and not os.listdir(target), (out, os.listdir(target)))
p76 = os.path.join(TMP, "parent76")
os.makedirs(os.path.join(p76, LEAF))
os.chmod(os.path.join(p76, LEAF), 0o777)
rc, out, _ = run(pre("s76", "Workflow", WF, empty), env_extra={"CONWAY_GATE_STATE_DIR": p76})
leaf = os.path.join(p76, LEAF)
mode = os.stat(leaf).st_mode & 0o777
files_ok = all(os.stat(os.path.join(leaf, n)).st_mode & 0o077 == 0 for n in os.listdir(leaf))
check("76 own loose state subdir -> tightened to 0700, files 0600, gate works", rc == 0 and decision(out) == "deny" and mode == 0o700 and files_ok, (out, oct(mode)))

p77 = os.path.join(TMP, "parent77")
os.makedirs(os.path.join(p77, LEAF))
old_t = time.time() - 10 * 24 * 3600
for n in ("notes.md", os.path.join(LEAF, "notes.md"), os.path.join(LEAF, "sOld.loaded")):
    with open(os.path.join(p77, n), "w") as f:
        f.write("x")
    os.utime(os.path.join(p77, n), (old_t, old_t))
rc, out, _ = run(ups("s77", "hello", empty), env_extra={"CONWAY_GATE_STATE_DIR": p77})
kept = os.path.exists(os.path.join(p77, "notes.md")) and os.path.exists(os.path.join(p77, LEAF, "notes.md"))
gone = not os.path.exists(os.path.join(p77, LEAF, "sOld.loaded"))
check("77 cleanup removes only own old markers, keeps foreign files", rc == 0 and kept and gone, (kept, gone))

p78 = os.path.join(TMP, "parent78")
os.makedirs(os.path.join(p78, LEAF))
for i, content in enumerate(("", "nan", json.dumps({"first": 0, "last": time.time() + 3600, "msg": None, "calls": 1}), "garbage")):
    mk = os.path.join(p78, LEAF, "s78_%d.denied.pZ" % i)
    with open(mk, "w") as f:
        f.write(content)
    os.utime(mk, (old_t, old_t))
    rc, out, _ = run(pre("s78_%d" % i, "Agent", AGENT, empty, "pZ"), env_extra={"CONWAY_GATE_STATE_DIR": p78})
    check("78.%d stale corrupt or future marker %r -> pass, no persistent deny" % (i, content[:12]), rc == 0 and out is None, out)

p80 = os.path.join(TMP, "parent80")
os.makedirs(p80)
os.chmod(p80, 0o500)
rc, out, _ = run(ups("s80", "ultracode audit X", empty), env_extra={"CONWAY_GATE_STATE_DIR": p80})
rc2, out2, _ = run(pre("s80", "Agent", AGENT, empty), env_extra={"CONWAY_GATE_STATE_DIR": p80})
os.chmod(p80, 0o700)
check("80 unusable state dir -> directive still sent, no deny", "conway-law" in ctx(out) and out2 is None, (out, out2))
cwd_before = os.listdir(TMP)
sid81 = "s81-" + os.path.basename(TMP)
real_leaf = os.path.join(tempfile.gettempdir(), "claude-conway-gate-%d" % os.getuid())
existed = os.path.exists(real_leaf)
rc, out, _ = run(pre(sid81, "Agent", AGENT, empty), env_extra={"CONWAY_GATE_STATE_DIR": "relstate"})
check("81 relative CONWAY_GATE_STATE_DIR ignored (no dir in cwd), gate works", decision(out) == "deny" and not os.path.exists(os.path.join(os.getcwd(), "relstate")), out)
if existed:
    for n in os.listdir(real_leaf):
        if n.startswith(sid81 + "."):
            os.remove(os.path.join(real_leaf, n))
else:
    shutil.rmtree(real_leaf, True)

paste = "\n".join('{"k": "ultracode", "v": %d}' % i for i in range(20000)) + "\n"
rc, out, dt = run(ups("s79", paste, empty))
check("79 1MB paste with 20k quoted keywords < 2s (got %.2fs), no directive" % dt, rc == 0 and dt < 2.0 and out is None, out)

big = os.path.join(TMP, "big.jsonl")
with open(big, "w") as f:
    line = json.dumps({"type": "user", "message": {"content": "x" * 2000}}, separators=(",", ":")) + "\n"
    for _ in range(15000):
        f.write(line)
    f.write(json.dumps({"type": "attachment", "attachment": {"type": "ultra_effort_enter", "reminderType": "full"}}, separators=(",", ":")) + "\n")
rc, out, dt = run(ups("s74", "fix it", big))
check("74 30MB transcript UPS < 2s (got %.2fs)" % dt, rc == 0 and dt < 2.0 and "conway-law" in ctx(out), out)

print()
print("FAILED: %d" % len(FAILS) if FAILS else "ALL PASS")
print("state dir:", STATE)
sys.exit(1 if FAILS else 0)
