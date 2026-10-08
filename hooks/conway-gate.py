#!/usr/bin/env python3
"""conway-gate: Claude Code hook that makes the conway-law gate run before multi-agent work.

A skill description alone does not load conway-law at the moment it matters.
Claude Code decides to spawn workers by itself, and under ultracode the harness
force-loads workflow-authoring with a direct "use the Workflow tool" instruction.
This hook adds a deterministic route to the gate.

One script, dispatched on hook_event_name:

  UserPromptSubmit
      If the prompt has the "ultracode" keyword (port of the harness rule) or
      session ultracode is on (transcript records), add a short directive:
      load Skill conway-law and write the gate line before the first Workflow or
      Agent call. Other prompts: no output.

  PreToolUse, tool "Skill"
      When the main thread invokes conway-law, write a per-session "loaded" marker.

  PreToolUse, tools "Workflow" | "Agent"
      Main thread only. If conway-law is not loaded in this session, deny the
      spawn. Claude Code runs this hook per tool call as each call finishes
      streaming, so the calls of one parallel batch arrive seconds apart (up to
      about 17 s observed). The hook denies every call inside a sliding window
      after the last deny (30 s default). Each deny extends the window.
      Bounds: denied calls per prompt, and prompts per session. No deny loop.

Guarantees:
  - Never returns "allow". It never auto-approves a tool call.
  - Fails open. Any internal error gives exit 0 with no output.
  - Skips subagents (agent_id present), Workflow resumes and run operations,
    saved workflows called by name, and exempt read-only agent types.

Env:
  CONWAY_GATE=off                     disable all behavior
  CONWAY_GATE_PRETOOL=off             disable the PreToolUse deny only
  CONWAY_GATE_DENY_WINDOW_S           sliding deny window in seconds (default 30)
  CONWAY_GATE_MAX_DENY_CALLS          denied calls per prompt (default 16)
  CONWAY_GATE_MAX_DENY_PROMPTS        prompts per session that can get a deny (default 2)
  CONWAY_GATE_EXEMPT_AGENT_TYPES      comma list of Agent subagent_type values to skip,
                                      case-insensitive
                                      (default "Explore,Plan,claude-code-guide,statusline-setup")
  CONWAY_GATE_SKIP_ENTRYPOINTS        comma list of CLAUDE_CODE_ENTRYPOINT values to skip
                                      (default "sdk-cli,sdk-ts,sdk-py": claude -p and SDK runs)
  CONWAY_GATE_LOCAL=on                keep the gate on when ANTHROPIC_BASE_URL is a local
                                      host (default: skip local model backends)
  CONWAY_GATE_STATE_DIR               absolute parent directory for the state subdirectory
                                      "claude-conway-gate-<uid>" (default $TMPDIR).
                                      The subdirectory has mode 0700. The hook does
                                      nothing if it is a symlink or belongs to another user.
"""
import bisect
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from urllib.parse import urlparse

SKILL = "conway-law"

DIRECTIVE_NOT_LOADED = (
    "conway-gate: this prompt may start multi-agent work (ultracode keyword or "
    "session ultracode). Before the first Workflow or Agent call, invoke Skill "
    "conway-law, pick the shape from its section 1, and write one line "
    "'Conway gate: <shape> - <reason>'. The gate shapes the workflow. It does not "
    "forbid it. Conversational or trivial turns stay solo."
)

DIRECTIVE_LOADED = (
    "conway-gate: before the first Workflow or Agent call of this task, write one "
    "line 'Conway gate: <shape> - <reason>' (shapes: conway-law section 1) and "
    "shape the work to match it."
)

DENY_REASON = (
    "conway-gate (automated pre-flight check, not a user rejection): the "
    "conway-law topology gate is not loaded in this session. Invoke Skill "
    "conway-law now. Pick the shape for this work from its section 1. Write one "
    "line 'Conway gate: <shape> - <reason>'. Then re-issue this {tool} call, "
    "reshaped if the Conway gate line requires it."
)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
STATE_TTL_S = 3 * 24 * 3600
LOG_MAX_BYTES = 1000000
CLOCK_SKEW_S = 5
MARKER_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(loaded|denied\.[A-Za-z0-9_.-]+)$|^\..+\.tmp\d+$")

# ---------------------------------------------------------------- utilities


def env_off(name):
    return os.environ.get(name, "").strip().lower() in ("off", "0", "false", "no")


def env_list(name, default):
    return {x.strip().lower() for x in os.environ.get(name, default).split(",") if x.strip()}


def env_num(name, default, cast=float):
    try:
        value = cast(os.environ.get(name, default))
        return value if math.isfinite(value) else cast(default)
    except Exception:
        return cast(default)


class UnsafeStateDir(Exception):
    pass


_STATE_DIR = None


def state_dir():
    """Per-user private state subdirectory. Refuses a symlink or a foreign owner.

    /tmp is shared on Linux. A per-uid name, mode 0700, and an lstat check stop
    another local user from planting a symlink or reading the markers. The hook
    always uses its own subdirectory, so cleanup never touches other files.
    """
    global _STATE_DIR
    if _STATE_DIR:
        return _STATE_DIR
    uid = os.getuid() if hasattr(os, "getuid") else None
    parent = os.environ.get("CONWAY_GATE_STATE_DIR") or ""
    if not os.path.isabs(parent):
        parent = tempfile.gettempdir()  # a relative value would follow the hook cwd
    d = os.path.join(parent, "claude-conway-gate-%s" % (uid if uid is not None else "user"))
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode):
        raise UnsafeStateDir(d)  # a symlink or a file in place of the directory
    if uid is not None:
        if st.st_uid != uid:
            raise UnsafeStateDir(d)
        if st.st_mode & 0o077:
            os.chmod(d, 0o700)  # own real directory: tighten it
    _STATE_DIR = d
    return d


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def write_file(path, text, append=False):
    flags = os.O_WRONLY | os.O_CREAT | _NOFOLLOW | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)


def write_atomic(path, text):
    tmp = os.path.join(os.path.dirname(path), ".%s.tmp%d" % (os.path.basename(path), os.getpid()))
    write_file(tmp, text)
    os.replace(tmp, path)


def safe_id(value):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "none"))[:128]


def marker_path(session_id, kind, suffix=""):
    name = safe_id(session_id) + "." + kind
    if suffix:
        name += "." + safe_id(suffix)
    return os.path.join(state_dir(), name)


def touch(path):
    write_file(path, str(time.time()))


def log(event, **fields):
    try:
        path = os.path.join(state_dir(), "log.jsonl")
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
        rec = {"ts": int(time.time()), "event": event}
        rec.update(fields)
        write_file(path, json.dumps(rec) + "\n", append=True)
    except Exception:
        pass


def cleanup_state():
    """Remove own markers older than STATE_TTL_S. Runs at most once per hour."""
    try:
        d = state_dir()
        stamp = os.path.join(d, ".cleanup")
        now = time.time()
        if os.path.exists(stamp) and now - os.path.getmtime(stamp) < 3600:
            return
        touch(stamp)
        names = os.listdir(d)
    except Exception:
        return
    for name in names:
        try:
            if not MARKER_RE.match(name):
                continue
            p = os.path.join(d, name)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and now - st.st_mtime > STATE_TTL_S:
                os.remove(p)
        except Exception:
            continue


def lines_with(data, needle):
    """Yield each full line of data that contains needle, once per line.

    Uses find on the bytes, so a large transcript is not split into a list of lines.
    """
    pos = 0
    while True:
        i = data.find(needle, pos)
        if i < 0:
            return
        start = data.rfind(b"\n", 0, i) + 1
        end = data.find(b"\n", i)
        end = len(data) if end < 0 else end
        pos = end + 1
        yield data[start:end]


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""


def local_backend():
    host = urlparse(os.environ.get("ANTHROPIC_BASE_URL", "")).hostname or ""
    return host.lower() in LOCAL_HOSTS


# ------------------------------------------------------- transcript checks


def is_skill_name(name):
    if not isinstance(name, str):
        return False
    name = name.strip().lstrip("/")
    return name == SKILL or name.endswith(":" + SKILL)


_COMMAND_RE = re.compile(r"<command-name>/?(?:[\w.-]+:)?" + re.escape(SKILL) + r"</command-name>")


def transcript_has_skill(data):
    """True if the transcript shows a real conway-law load.

    Accepts a Skill tool_use with input.skill == conway-law, an invoked_skills
    attachment that lists conway-law (re-attached after compaction), or a
    user-typed /conway-law command. Each candidate line is parsed as JSON and
    checked by structure, so quoted mentions do not match.
    """
    for line in lines_with(data, SKILL.encode()):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        rtype = rec.get("type")
        if rtype == "assistant":
            for c in (rec.get("message") or {}).get("content") or []:
                if (
                    isinstance(c, dict)
                    and c.get("type") == "tool_use"
                    and c.get("name") == "Skill"
                    and is_skill_name((c.get("input") or {}).get("skill"))
                ):
                    return True
        elif rtype == "attachment":
            att = rec.get("attachment") or {}
            if att.get("type") == "invoked_skills":
                for s in att.get("skills") or []:
                    if isinstance(s, dict) and is_skill_name(s.get("name")):
                        return True
        elif rtype == "user":
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
            if isinstance(content, str) and _COMMAND_RE.search(content):
                return True
    return False


_UC_HINT = (b"ultra_effort_", b"Ultracode o", b"Set effort level to")
_STDOUT_ON = re.compile(r"^<local-command-stdout>.*?(Ultracode on\b|Set effort level to ultracode\b)", re.S)
_STDOUT_OFF = re.compile(r"^<local-command-stdout>.*?Ultracode off\b", re.S)


def session_ultracode_on(data):
    """Last ultracode state in the transcript, by structure (not raw bytes).

    Enter: attachment ultra_effort_enter, or /effort stdout with "Ultracode on"
    (2.1.287+) or "Set effort level to ultracode" (older versions).
    Exit: attachment ultra_effort_exit, or /effort stdout with "Ultracode off".
    """
    state = None
    for line in data.splitlines():
        if not any(h in line for h in _UC_HINT):
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") == "attachment":
            t = (rec.get("attachment") or {}).get("type")
            if t == "ultra_effort_enter":
                state = True
            elif t == "ultra_effort_exit":
                state = False
        elif rec.get("type") == "user":
            c = (rec.get("message") or {}).get("content")
            if isinstance(c, str):
                if _STDOUT_ON.search(c):
                    state = True
                elif _STDOUT_OFF.search(c):
                    state = False
    if state is not None:
        return state
    # No transcript signal: fall back to the "ultracode" settings key.
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        with open(os.path.join(cfg, "settings.json")) as f:
            return json.load(f).get("ultracode") is True
    except Exception:
        return False


# ------------------------------------------------------- keyword detection

_PAIRS = {"`": "`", '"': '"', "<": ">", "{": "}", "[": "]", "(": ")", "'": "'"}


def _word(c):
    return bool(c) and bool(re.match(r"\w", c))


def keyword_in_prompt(e):
    """Port of the Claude Code 2.1.295 keyword rule for "ultracode".

    Linear scan. Skips a prompt that starts with "/", task notifications, and
    compaction summaries. Ignores the word inside backticks, quotes, brackets,
    braces, parentheses, and tags, and next to / \\ - ? characters.
    """
    if not isinstance(e, str) or "ultracode" not in e.lower() or e.startswith("/"):
        return False
    if e.lstrip().startswith(("<task-notification>", "This session is being continued from a previous")):
        return False
    starts, ends, h, y = [], [], None, 0
    for a, m in enumerate(e):
        nxt = e[a + 1] if a + 1 < len(e) else ""
        if h:
            if h == "[" and m == "[":
                y = a
                continue
            if m != _PAIRS[h]:
                continue
            if h == "'" and _word(nxt):
                continue
            starts.append(y)
            ends.append(a + 1)
            h = None
        elif (
            (m == "<" and re.match(r"[a-zA-Z/]", nxt or " "))
            or (m == "'" and not _word(e[a - 1] if a else ""))
            or (m not in "<'" and m in _PAIRS)
        ):
            h, y = m, a
    for mo in re.finditer(r"(?<![A-Za-z0-9_])ultracode(?![A-Za-z0-9_])", e, re.I):
        st, en = mo.start(), mo.end()
        i = bisect.bisect_right(starts, st) - 1  # spans are sorted and disjoint
        if i >= 0 and st < ends[i]:
            continue
        before = e[st - 1] if st else ""
        after = e[en] if en < len(e) else ""
        if before and before in "/\\-":
            continue
        if after in ("/", "\\", "-", "?"):
            continue
        if after == "." and _word(e[en + 1] if en + 1 < len(e) else ""):
            continue
        return True
    return False


# ---------------------------------------------------------------- handlers


def on_user_prompt(inp, state_ok):
    if state_ok:
        cleanup_state()
    sid = inp.get("session_id")
    tpath = inp.get("transcript_path") or ""
    keyword = keyword_in_prompt(inp.get("prompt"))
    data = read_bytes(tpath) if tpath else b""
    if not keyword and not session_ultracode_on(data):
        return
    loaded = (state_ok and os.path.exists(marker_path(sid, "loaded"))) or transcript_has_skill(data)
    if loaded and state_ok:
        touch(marker_path(sid, "loaded"))
    log("ups", sid=sid, keyword=keyword, loaded=loaded)
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": DIRECTIVE_LOADED if loaded else DIRECTIVE_NOT_LOADED,
            }
        }
    )


def cap_reached(sid, key):
    """True if earlier prompts of this session used up the deny cap."""
    if os.path.exists(key):
        return False
    cap = env_num("CONWAY_GATE_MAX_DENY_PROMPTS", "2", int)
    prefix, own = safe_id(sid) + ".denied.", os.path.basename(key)
    episodes = sum(1 for n in os.listdir(state_dir()) if n.startswith(prefix) and n != own)
    return episodes >= cap


def should_deny(key):
    """Deny decision for one gated call of a prompt.

    Deny when the call comes inside the sliding window after the last deny.
    Each deny extends the window, so a streamed batch with gaps shorter than
    the window is denied as a whole. Stop after CONWAY_GATE_MAX_DENY_CALLS
    denied calls. A marker that cannot be
    read, or holds a time in the future, never extends a deny.
    """
    window = env_num("CONWAY_GATE_DENY_WINDOW_S", "30")
    max_calls = env_num("CONWAY_GATE_MAX_DENY_CALLS", "16", int)
    now = time.time()
    state = {"first": now, "last": now, "calls": 1}
    try:
        fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600)
        try:
            os.write(fd, json.dumps(state).encode())
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        pass
    try:
        with open(key) as f:
            old = json.loads(f.read())
        last = float(old["last"])
        calls = int(old["calls"])
    except Exception:
        # Empty or corrupt marker. A concurrent first call may still be writing it.
        try:
            age = now - os.lstat(key).st_mtime
        except Exception:
            return False
        return -CLOCK_SKEW_S <= age <= window
    if not math.isfinite(last) or last > now + CLOCK_SKEW_S or calls >= max_calls:
        return False
    if now - last > window:
        return False
    old.update({"last": now, "calls": calls + 1})
    try:
        write_atomic(key, json.dumps(old))
    except Exception:
        pass
    return True


def on_pre_tool(inp):
    tool = inp.get("tool_name")
    tin = inp.get("tool_input") or {}
    sid = inp.get("session_id")

    if tool == "Skill":
        # Only a main-thread load counts. A subagent context is not the main one.
        if is_skill_name(tin.get("skill")) and not inp.get("agent_id"):
            touch(marker_path(sid, "loaded"))
            log("skill_loaded", sid=sid)
        return

    if tool not in ("Workflow", "Agent") or env_off("CONWAY_GATE_PRETOOL"):
        return
    if inp.get("agent_id"):
        return  # inside a subagent: the depth rule lives in the skill text
    if tool == "Workflow":
        has_script = bool(tin.get("script") or tin.get("scriptPath"))
        if tin.get("resumeFromRunId"):
            return  # resume of a gated run
        if not has_script and (tin.get("name") or tin.get("runId")):
            return  # saved workflow by name, or an operation on an existing run
    if tool == "Agent":
        exempt = env_list("CONWAY_GATE_EXEMPT_AGENT_TYPES", "Explore,Plan,claude-code-guide,statusline-setup")
        if str(tin.get("subagent_type") or "").lower() in exempt:
            return
    if os.path.exists(marker_path(sid, "loaded")):
        return
    key = marker_path(sid, "denied", inp.get("prompt_id") or "noprompt")
    if cap_reached(sid, key):
        log("cap", sid=sid, tool=tool)
        return
    data = read_bytes(inp.get("transcript_path") or "")
    if transcript_has_skill(data):
        touch(marker_path(sid, "loaded"))
        return
    if not should_deny(key):
        log("bypass", sid=sid, tool=tool)
        return
    log("deny", sid=sid, tool=tool)
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON.format(tool=tool),
            }
        }
    )


def main():
    if env_off("CONWAY_GATE"):
        return
    skip = env_list("CONWAY_GATE_SKIP_ENTRYPOINTS", "sdk-cli,sdk-ts,sdk-py")
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").lower() in skip:
        return  # headless, SDK, and eval runs
    if local_backend() and os.environ.get("CONWAY_GATE_LOCAL", "").strip().lower() != "on":
        return  # local model backends
    try:
        state_dir()
        state_ok = True
    except Exception:
        state_ok = False
    try:
        inp = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    if not isinstance(inp, dict):
        return
    event = inp.get("hook_event_name")
    if event == "UserPromptSubmit":
        on_user_prompt(inp, state_ok)
    elif event == "PreToolUse" and state_ok:
        # No safe place for markers: without them no deny is bounded, so no deny.
        on_pre_tool(inp)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)  # exit 0 even if Claude Code closed the stdout pipe
