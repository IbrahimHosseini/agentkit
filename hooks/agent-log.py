#!/usr/bin/env python3
"""Agent log: SubagentStop hook (check), plus add, report, resolve, export and merge.

Python 3.9, stdlib only. Run with: python3 -I agent-log.py <check|add|report|resolve|export|merge>
Log folder: env AGENT_LOG_DIR, else ~/.claude/agent-log (issues.jsonl, hook-errors.log, reporter-id).
export writes an anonymized summary to share. merge combines export files (maintainer).
check never blocks the subagent: it always exits 0 and never exits 2.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

SECRET = re.compile(r"""(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*["'][A-Za-z0-9_\-\.]{8,}["']""")
MASKS = [
    (re.compile(r"""(?i)(\w*(?:api[_-]?key|secret|token|password|passwd)\w*\s*[:=]\s*)["']?\S{8,}"""), r"\1***"),
    (re.compile(r"(?i)(Bearer\s+)\S+"), r"\1***"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "***"),
    (re.compile(r"\b(Basic\s+)[A-Za-z0-9+/=]{8,}"), r"\1***"),
    (re.compile(r"gh[pousr]_\w{20,}"), "***"),
    (re.compile(r"github_pat_\w{20,}"), "***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "***"),
    (re.compile(r"xox[abposr]-[\w-]+"), "***"),
]
HEREDOC = re.compile(r"""(?<!<)<<(?!<)-?\s*(?:'([^']+)'|"([^"]+)"|(\w+))""")
QUOTED = re.compile(r"""'([^']*)'|"([^"]*)\"""")
SIMPLE = re.compile(r"^[A-Za-z0-9@./:=^~<>!+\-_$\[\]{},]+$")
SPLIT = re.compile(r"\n|;|&&|\|\||\||\$\(|\(|\)|`|(?<![>&])&(?![>&])")
PREFIX = re.compile(r"^\s*(?:(?:\w+=\S*|sudo|env|command|nohup|time|timeout\s+\S+|rtk(?:\s+(?:bypass|proxy))?|then|do|else|if|while|until|!|\{)\s+)*")
SKIP_FIRST = {"grep", "rg", "echo", "printf", "cat"}
INSTALL = [re.compile(p) for p in (
    r"go\s+(?:get|install)\b", r"npm\s+(?:install|i|add|ci)\b", r"pnpm\s+(?:add|install)\b",
    r"yarn\s+add\b", r"(?:python3?\s+-m\s+)?pip3?\s+install\b", r"uv\s+(?:add|pip\s+install)\b",
    r"cargo\s+add\b", r"brew\s+install\b", r"gem\s+install\b",
    r"swift\s+package\s+(?:add-dependency|resolve|update)\b")]
VALUE_FLAGS = {"-r", "-c", "-e", "--requirement", "--constraint", "--editable"}
REDIR = re.compile(r"^(?:\d*|&)[<>]{1,2}&?\S*$")
REDIR_OP = re.compile(r"^(?:\d*|&)[<>]{1,2}$")
GIT = r"git(?:\s+-C\s+\S+)?\s+"
GIT_WRITE = re.compile(GIT + r"(?:(?:commit|push|clean)\b|reset\s+--hard\b|stash\b(?!\s+(?:list|show)\b)|checkout\s+--(?:\s|$))")
GIT_PUSH = re.compile(GIT + r"push\b")
DESTR_RM = re.compile(r"rm\s+-[a-zA-Z]*(?:[rR]f|f[rR])[a-zA-Z]*\b")
DESTR_START = re.compile(r"(?:kill\s+-9|pkill|killall)\b")
DESTR_ANY = re.compile(r"(?<![\w-])--force(?!\w)|(?<!\S)prune(?!\S)")
DROP_SQL = re.compile(r"(?i)DROP\s+(?:TABLE|DATABASE)\b")
BROWSE = re.compile(r"gstack/browse(?![\w.-])|/browse/dist/browse")
AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
RULE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]{0,60}$")
SCHEMA = "agentkit-log-export/1"
URL = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*)://([^/\s?#'\"<>]*)[^\s'\"<>]*")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w])")
USER_HOME = re.compile(r"/(?:Users|home)/[^/\s'\"]+")
TILDE_PATH = re.compile(r"(?<![\w~.:/-])~((?:/[^\s/'\"`,;:()<>|]+){3,})")
ABS_PATH = re.compile(r"(?<![\w~\u2026.:/-])((?:/[^\s/'\"`,;:()<>|]+){2,})")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
REPORT_TYPES = {"backend", "frontend", "mobile", "database", "devops", "debugger", "tester", "docs", "seo", "design"}


def strip_plugin(name):
    """Plugin mode names agents agentkit:<name>. Use the bare name."""
    name = str(name)
    return name[len("agentkit:"):] if name.startswith("agentkit:") else name


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_dir():
    return os.environ.get("AGENT_LOG_DIR") or os.path.expanduser("~/.claude/agent-log")


def ensure_dir():
    d = log_dir()
    if not os.path.isdir(d):
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def append(name, text):
    d = ensure_dir()
    fd = os.open(os.path.join(d, name), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def mask(s):
    for pat, rep in MASKS:
        s = pat.sub(rep, s)
    return s


def ev(s, n=300):
    # Mask first, then cut, so a cut never leaves a part of a secret.
    return mask(s)[:n]


def read_log():
    """Return (issues, resolved ids). Bad lines are skipped."""
    issues, resolved = [], set()
    try:
        with open(os.path.join(log_dir(), "issues.jsonl"), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return issues, resolved
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and "resolves" in r:
            resolved.update(r["resolves"])
        elif isinstance(r, dict) and "id" in r:
            issues.append(r)
    return issues, resolved


# ---- command text (D3) ----

def prep(cmd, quotes=True):
    """Drop heredoc bodies, join continuation lines, mask quoted strings."""
    out, end = [], None
    for line in cmd.replace("\\\n", " ").split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(1) or m.group(2) or m.group(3)

    def q(m):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        return inner if SIMPLE.match(inner) else "_Q_"
    return QUOTED.sub(q, "\n".join(out)) if quotes else "\n".join(out)


def segments(text):
    """Yield (segment, segment without prefix words)."""
    for seg in SPLIT.split(text):
        seg = seg.strip()
        if seg:
            yield seg, seg[PREFIX.match(seg).end():]


def expand(w, env):
    return re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), w)


def bare(w):
    w = w.strip("'\"`").lower()
    i = w.find("@", 1)
    if i > 0:
        w = w[:i]
    return re.split(r"==|>=|<=|~=|!=|[<>\[;]", w)[0]


def packages(words):
    out, skip = [], False
    for w in words:
        if skip:
            skip = False
        elif w in VALUE_FLAGS:
            skip = True
        elif REDIR.match(w):
            skip = bool(REDIR_OP.match(w))
        elif w.startswith("-") or w in ("_Q_", ".") or w.startswith(("./", "../", "/")):
            continue
        else:
            out.append(bare(w))
    return out


def approved_list(assignment):
    m = re.search(r"(?m)^[ \t]*Install approved:(.*)$", assignment)
    if not m:
        return None
    names = []
    for t in re.split(r"[,\s]+", m.group(1)):
        t = t.strip("`'\"").rstrip(".").strip("`'\"")
        if t:
            names.append(bare(t))
    return names


def rm_in_scratch(words, env, base, scratch):
    """True when every rm target resolves strictly under the scratchpad (D4)."""
    if not scratch:
        return False
    root, targets, skip = os.path.realpath(scratch), [], False
    for w in words[1:]:
        if skip:
            skip = False
        elif REDIR.match(w):
            skip = bool(REDIR_OP.match(w))
        elif not w.startswith("-"):
            targets.append(expand(os.path.expanduser(w), env))
    return bool(targets) and all(
        "$" not in t and t != "_Q_" and os.path.realpath(os.path.join(base or "", t)).startswith(root + "/")
        for t in targets)


def command_issues(idx, cmd, approved, cwd, scratch=None):
    found = []
    cur, env = None, {}  # folder of the last "cd" in this command; VAR=value words seen so far
    for seg, rest in segments(prep(cmd)):
        for w in seg.split():
            m = re.match(r"(\w+)=(.*)$", w)
            if not m:
                break
            env[m.group(1)] = expand(m.group(2), env)
        words = rest.split()
        if not words or words[0] in SKIP_FIRST:
            continue
        first = words[0]
        if first == "cd" and len(words) > 1:
            d = expand(os.path.expanduser(words[1]), env)
            cur = None if ("$" in d or d == "_Q_") else os.path.join(cur or cwd or "", d)
            continue
        e = ev(seg)
        # R1 installs
        pk = None
        if first == "npx":
            args = words[1:]
            name = next((w for w in args if not w.startswith("-")), None)
            if name and "--no-install" not in args and "--no" not in args:
                b = bare(name).split("/")[-1]
                dirs = [x for x in (cur, cwd) if x]
                if not any(os.path.exists(os.path.join(x, "node_modules", ".bin", b)) for x in dirs):
                    pk = [bare(name)]
        else:
            for pat in INSTALL:
                m = pat.match(rest)
                if m:
                    pk = packages(rest[m.end():].split())
                    break
        if pk is not None:
            if not pk:
                found.append(("install-restore", "info", e, idx))
            elif approved is None:
                found.append(("install-unapproved", "warn", e, idx))
            else:
                bad = [p for p in pk if p not in approved]
                if bad:
                    found.append(("install-outside-list", "warn", ev(", ".join(bad) + " | " + seg), idx))
        # R2 git writes
        if GIT_WRITE.match(rest):
            found.append(("git-write", "warn", e, idx))
        # R3 destructive
        rm_hit = DESTR_RM.match(rest) and not rm_in_scratch(words, env, cur or cwd, scratch)
        if (rm_hit or DESTR_START.match(rest) or DESTR_ANY.search(rest)
                or (GIT_PUSH.match(rest) and re.search(r"(?<!\S)-f(?!\S)", rest))):
            found.append(("destructive", "warn", e, idx))
    m = DROP_SQL.search(prep(cmd, False))
    if m:
        found.append(("destructive", "warn", ev(prep(cmd, False)[m.start():]), idx))
    return found


# ---- scope (R4) ----

def scope_entries(assignment):
    m = re.search(r"(?m)^[ \t]*(?:[-*][ \t]+)?(?:Files in scope|Files):(.*)$", assignment)
    if not m:
        return None, []
    out = []
    for t in m.group(1).split(","):
        t = t.strip(" \t`'\"").replace("(new)", "").strip(" \t`'\"")
        t = t.rstrip(".").strip(" \t`'\"")
        if t:
            out.append(os.path.expanduser(t))
    return m.group(0).strip(), out


def in_scope(path, entries, cwd):
    rp = os.path.realpath(os.path.join(cwd or "", path))
    for e in entries:
        er = os.path.realpath(os.path.join(cwd or "", e))
        if rp == er:
            return True
        if rp.startswith(er + "/") and (e.endswith("/") or os.path.isdir(er)):
            return True
        if not os.path.isabs(e) and path.endswith("/" + e.rstrip("/")):
            return True
    return False


# ---- transcript ----

def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def load(path):
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                r = None
            recs.append(r if isinstance(r, dict) else {})
    return recs


def run_checks(inp):
    path = inp["agent_transcript_path"]
    recs = load(path)
    cwd = inp.get("cwd") or ""
    meta = {}
    try:
        with open(re.sub(r"\.jsonl$", "", path) + ".meta.json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass
    atype = strip_plugin(inp.get("agent_type") or meta.get("agentType") or "unknown")

    assignment, uses, seen, errors, last_text = "", [], set(), [], ""
    for i, r in enumerate(recs):
        content = (r.get("message") or {}).get("content")
        if r.get("type") == "user" and not assignment:
            assignment = text_of(content)
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if r.get("type") == "assistant" and b.get("type") == "tool_use":
                key = b.get("id") or (i, len(uses))
                if key not in seen:
                    seen.add(key)
                    uses.append((i, b.get("name"), b.get("input") if isinstance(b.get("input"), dict) else {}))
            elif r.get("type") == "user" and b.get("type") == "tool_result" and b.get("is_error"):
                errors.append(text_of(b.get("content")))
            elif r.get("type") == "assistant" and b.get("type") == "text" and b.get("text"):
                last_text = b["text"]

    found = []
    approved = approved_list(assignment)
    cmds = [(i, u["command"]) for i, n, u in uses if n == "Bash" and isinstance(u.get("command"), str)]
    for i, c in cmds:  # R1, R2, R3
        found += command_issues(i, c, approved, cwd, inp.get("scratchpad_dir"))

    # R4 scope
    line, entries = scope_entries(assignment)
    if entries:
        ignore = [os.path.realpath("/tmp")]
        if inp.get("scratchpad_dir"):
            ignore.append(os.path.realpath(inp["scratchpad_dir"]))
        for i, n, u in uses:
            p = u.get("file_path")
            if n in ("Edit", "Write") and isinstance(p, str):
                rp = os.path.realpath(os.path.join(cwd, p))
                rc = os.path.realpath(cwd or ".")
                # /tmp is ignored only outside the project, so a project under /tmp is still checked.
                if any((rp == g or rp.startswith(g + "/")) and not (g == ignore[0] and rp.startswith(rc + "/"))
                       for g in ignore):
                    continue
                if not in_scope(p, entries, cwd):
                    found.append(("scope", "warn", ev(p + " | " + line), i))

    # R5 secrets
    for i, n, u in uses:
        text = u.get("content") if n == "Write" else u.get("new_string") if n == "Edit" else None
        if isinstance(text, str):
            for ln in sorted({text.count("\n", 0, m.start()) + 1 for m in SECRET.finditer(text)}):
                found.append(("secret-in-code", "warn",
                              ev("%s:%d %s" % (u.get("file_path"), ln, text.split("\n")[ln - 1].strip())), i))

    # R6 browser not stopped: last segment that names the browse binary, no later " stop"
    flat = [(i, seg) for i, c in cmds for seg, rest in segments(prep(c))
            if (rest.split() or [""])[0] not in SKIP_FIRST]
    hits = [k for k, (i, seg) in enumerate(flat) if BROWSE.search(seg)]
    if hits:
        i, seg = flat[hits[-1]]
        m = list(BROWSE.finditer(seg))[-1]
        if " stop" not in seg[m.end():] + "\n".join(t for _, t in flat[hits[-1] + 1:]):
            found.append(("browser-not-stopped", "warn", ev(seg[max(0, m.start() - 80):]), i))

    # R7 skills
    skills = {str(u.get("skill", "")).split(":")[-1] for i, n, u in uses if n == "Skill"}
    if atype == "seo" and re.search(r"(?i)measure|speed|performance|vitals|benchmark", assignment) \
            and "benchmark" not in skills:
        found.append(("skill-missing", "warn", "measure task, benchmark skill not loaded", None))
    if atype == "security" and uses:
        i, n, u = uses[0]
        if not (n == "Skill" and str(u.get("skill", "")).split(":")[-1] == "cso"):
            found.append(("cso-before-audit", "warn", ev("first tool_use: %s" % n), i))

    # R8 tool errors
    if errors:
        found.append(("tool-error", "info", "%d error(s): %s" % (len(errors), ev(errors[0], 150)), None))

    # R9 report
    if atype in REPORT_TYPES:
        handback = [u.get("message") for i, n, u in uses if n == "SubagentHandback"]
        final = "\n".join(t for t in (inp.get("last_assistant_message"),
                                      handback[-1] if handback else None) if isinstance(t, str) and t)
        final = (final or last_text).lower()
        checks = (("files changed", r"files? changed|changed (?:files|paths)|files (?:edited|touched)"),
                  ("verif", r"verif|\btests?\b|\blint\b|\bpassed\b"))
        miss = [w for w, rx in checks if not re.search(rx, final)]
        if miss:
            found.append(("report-incomplete", "info", "final report lacks: " + ", ".join(miss), None))

    # R10 spawned agents
    if atype not in ("security", "supervisor"):
        for i, n, u in uses:
            if n == "Agent":
                found.append(("spawned-agent", "info",
                              ev("%s: %s" % (u.get("subagent_type"), u.get("description"))), i))
    return found, atype, meta


def cmd_check():
    try:
        inp = json.load(sys.stdin)
        found, atype, meta = run_checks(inp)
        aid = inp.get("agent_id")
        known = {r["id"] for r in read_log()[0]}
        new, rules = 0, []
        for rule, sev, evidence, rec in found:
            iid = hashlib.sha256(("%s|%s|%s|%s" % (aid, rule, rec, evidence)).encode()).hexdigest()[:12]
            if iid in known:
                continue
            known.add(iid)
            append("issues.jsonl", json.dumps({
                "id": iid, "ts": now(), "source": "hook", "session_id": inp.get("session_id"),
                "cwd": inp.get("cwd"), "agent_id": aid, "agent_type": atype,
                "description": meta.get("description", ""), "rule": rule, "severity": sev,
                "evidence": evidence, "record": rec, "transcript": inp["agent_transcript_path"]}))
            new += 1
            if rule not in rules:
                rules.append(rule)
        if new:
            print(json.dumps({"systemMessage": "agent-log: %s: %d issue(s): %s" % (atype, new, ", ".join(rules))}))
    except Exception as e:
        try:
            append("hook-errors.log", "%s %s: %s" % (now(), type(e).__name__, ev(str(e))))
        except Exception:
            pass
    return 0


def cmd_add(a):
    iid = uuid.uuid4().hex[:12]
    append("issues.jsonl", json.dumps({
        "id": iid, "ts": now(), "source": "supervisor-review", "session_id": None, "cwd": os.getcwd(),
        "agent_id": None, "agent_type": a.agent, "description": "", "rule": a.rule, "severity": "warn",
        "evidence": ev(a.evidence), "record": None, "transcript": None}))
    print(iid)
    return 0


def cmd_report(a):
    issues, resolved = read_log()
    groups = {}
    for r in issues:
        if a.all or r["id"] not in resolved:
            groups.setdefault((str(r.get("agent_type")), str(r.get("rule"))), []).append(r)
    last_agent = None
    for (agent, rule), rs in sorted(groups.items()):
        rs.sort(key=lambda r: r.get("ts", ""))
        if agent != last_agent:
            print("agent: " + agent)
            last_agent = agent
        sev = "warn" if any(r.get("severity") == "warn" for r in rs) else "info"
        print("  rule: %s (%s)  count: %d  first: %s  last: %s" % (rule, sev, len(rs), rs[0].get("ts"), rs[-1].get("ts")))
        for r in rs:
            tag = " [resolved]" if r["id"] in resolved else ""
            print("    - %s%s %s %s | %s | %s" % (r["id"], tag, r.get("ts"), r.get("source"),
                                                 r.get("description") or "-", " ".join(str(r.get("evidence")).split())))
    return 0


def cmd_resolve(a):
    known = {r["id"] for r in read_log()[0]}
    unknown = [i for i in a.ids if i not in known]
    if unknown:
        print("unknown id: " + " ".join(unknown), file=sys.stderr)
        return 1
    append("issues.jsonl", json.dumps({"resolves": a.ids, "ts": now()}))
    return 0


# ---- export / merge ----

def scrub(s):
    """Remove private data from evidence text. Order matters: URLs first, paths last."""
    s = mask(str(s))
    s = URL.sub(lambda m: "%s://%s" % (m.group(1), m.group(2).rsplit("@", 1)[-1]), s)
    s = EMAIL.sub("<email>", s)
    s = IPV4.sub("<ip>", s)
    home = os.path.expanduser("~")
    if len(home) > 1:
        s = re.sub(re.escape(home.rstrip("/")) + r"(?![\w.-])", "~", s)
    s = USER_HOME.sub("~", s)
    s = TILDE_PATH.sub(lambda m: "~/\u2026/" + "/".join(m.group(1).split("/")[-2:]), s)
    s = ABS_PATH.sub(lambda m: "\u2026/" + "/".join(m.group(1).split("/")[-2:]), s)
    return " ".join(CONTROL.sub(" ", s).split())[:200]


def reporter_id():
    path = os.path.join(ensure_dir(), "reporter-id")
    try:
        with open(path, encoding="utf-8") as f:
            rid = f.read().strip()
        return str(uuid.UUID(rid))
    except (OSError, ValueError):
        rid = str(uuid.uuid4())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rid + "\n")
        return rid


def version():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "unknown"
    except OSError:
        return "unknown"


def export_part(rule, evidence):
    """Keep only the command or rule part of the evidence. Task, prompt and error text stays local."""
    e = str(evidence)
    if rule == "spawned-agent":
        return e.split(": ", 1)[0]
    if rule == "scope":
        return e.split(" | ", 1)[0]
    if rule == "secret-in-code":
        return e.split(" ", 1)[0]
    if rule == "tool-error":
        m = re.match(r"\d+ error\(s\)", e)
        return m.group(0) if m else ""
    return e


def build_export(include_all):
    issues, resolved = read_log()
    groups = {}
    for r in issues:
        agent, rule = strip_plugin(r.get("agent_type")), str(r.get("rule"))
        if (include_all or r["id"] not in resolved) and AGENT_NAME.match(agent) and RULE_NAME.match(rule):
            groups.setdefault((agent, rule), []).append(r)
    out = []
    for (agent, rule), rs in sorted(groups.items()):
        rs.sort(key=lambda r: str(r.get("ts", "")))
        samples = []
        for r in rs:
            t = scrub(export_part(rule, r.get("evidence", "")))
            if t and t not in samples and len(samples) < 3:
                samples.append(t)
        out.append({"agent": agent, "rule": rule,
                    "severity": "warn" if any(r.get("severity") == "warn" for r in rs) else "info",
                    "count": len(rs), "first": str(rs[0].get("ts")), "last": str(rs[-1].get("ts")),
                    "samples": samples})
    return {"schema": SCHEMA, "agentkit_version": version(), "generated": now(),
            "reporter": reporter_id(), "groups": out}


def cmd_export(a):
    text = json.dumps(build_export(a.all), indent=2, ensure_ascii=False)
    if a.out:
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("wrote " + a.out, file=sys.stderr)
    else:
        print(text)
    return 0


def valid_group(g):
    return (isinstance(g, dict) and isinstance(g.get("agent"), str) and AGENT_NAME.match(g["agent"])
            and isinstance(g.get("rule"), str) and RULE_NAME.match(g["rule"])
            and isinstance(g.get("count"), int) and not isinstance(g["count"], bool) and g["count"] >= 0
            and isinstance(g.get("first"), str) and isinstance(g.get("last"), str)
            and isinstance(g.get("samples", []), list))


def cmd_merge(a):
    exports = []
    for path in a.files:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            print("skip %s: %s" % (path, type(e).__name__), file=sys.stderr)
            continue
        if not (isinstance(d, dict) and d.get("schema") == SCHEMA and isinstance(d.get("reporter"), str)
                and isinstance(d.get("groups"), list)):
            print("skip %s: not an %s file" % (path, SCHEMA), file=sys.stderr)
            continue
        exports.append(d)
    nfiles = len(exports)
    if a.include_local:
        exports.append(build_export(a.all))
    if not exports:
        print("no valid export file", file=sys.stderr)
        return 1
    merged = {}
    for d in exports:
        for g in d["groups"]:
            if not valid_group(g):
                continue
            m = merged.setdefault((g["agent"], g["rule"]), {
                "reporters": set(), "count": 0, "first": g["first"], "last": g["last"], "sev": "info", "samples": []})
            m["reporters"].add(d["reporter"])
            m["count"] += g["count"]
            m["first"], m["last"] = min(m["first"], g["first"]), max(m["last"], g["last"])
            if g.get("severity") == "warn":
                m["sev"] = "warn"
            for t in g.get("samples", []):
                t = " ".join(CONTROL.sub(" ", t).split())[:200] if isinstance(t, str) else ""
                if t and t not in m["samples"] and len(m["samples"]) < 3:
                    m["samples"].append(t)
    print("files: %d  reporters: %d" % (nfiles, len({d["reporter"] for d in exports})))
    last_agent = None
    order = sorted(merged.items(), key=lambda kv: (-len(kv[1]["reporters"]), -kv[1]["count"], kv[0]))
    for (agent, rule), m in order:
        if agent != last_agent:
            print("agent: " + agent)
            last_agent = agent
        print("  rule: %s (%s)  count: %d  reporters: %d  first: %s  last: %s" % (
            rule, m["sev"], m["count"], len(m["reporters"]), m["first"], m["last"]))
        for t in m["samples"]:
            print("    - " + t)
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="agent-log.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    s = sub.add_parser("add")
    s.add_argument("--agent", required=True)
    s.add_argument("--rule", required=True)
    s.add_argument("--evidence", required=True)
    s = sub.add_parser("report")
    s.add_argument("--all", action="store_true")
    s = sub.add_parser("resolve")
    s.add_argument("ids", nargs="+")
    s = sub.add_parser("export")
    s.add_argument("--out")
    s.add_argument("--all", action="store_true")
    s = sub.add_parser("merge")
    s.add_argument("files", nargs="*")
    s.add_argument("--include-local", action="store_true")
    s.add_argument("--all", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "check":
        return cmd_check()
    return {"add": cmd_add, "report": cmd_report, "resolve": cmd_resolve,
            "export": cmd_export, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
