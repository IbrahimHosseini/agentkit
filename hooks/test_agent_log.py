"""Tests for agent-log.py. Run: python3 -I hooks/test_agent_log.py (from the agentkit folder)"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "agent-log.py")
USERS = "/" + "Users"  # built here so no home-style path is written literally
HOMES = "/" + "home"
GOOD = "Files changed: a.py. Verification: tests pass."


def user(text):
    return {"type": "user", "message": {"content": text}}


def use(name, **inp):
    return {"type": "tool_use", "id": "t%d" % (hash((name, json.dumps(inp, sort_keys=True))) & 0xffffff),
            "name": name, "input": inp}


def bash(cmd):
    return use("Bash", command=cmd)


def asst(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = os.path.realpath(self._tmp.name)
        self.logdir = os.path.join(self.tmp, "log")
        self.cwd = os.path.join(self.tmp, "proj")
        os.makedirs(self.cwd)

    def run_script(self, *args, stdin=""):
        env = dict(os.environ, AGENT_LOG_DIR=self.logdir)
        return subprocess.run([sys.executable, "-I", SCRIPT] + list(args), input=stdin,
                              capture_output=True, text=True, env=env)

    def write_transcript(self, records, name="agent-aaa.jsonl"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
        return p

    def check(self, assignment, uses=(), atype="backend", extra=(), msg=GOOD, **stdin):
        recs = [user(assignment)] + [asst(u) for u in uses] + list(extra)
        inp = {"session_id": "s1", "cwd": self.cwd, "agent_id": "aaa", "agent_type": atype,
               "agent_transcript_path": self.write_transcript(recs), "last_assistant_message": msg}
        inp.update(stdin)
        r = self.run_script("check", stdin=json.dumps(inp))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r, self.issues()

    def issues(self):
        p = os.path.join(self.logdir, "issues.jsonl")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def raw(self):
        with open(os.path.join(self.logdir, "issues.jsonl"), encoding="utf-8") as f:
            return f.read()

    def of(self, issues, rule):
        return [i for i in issues if i["rule"] == rule]


class TestInstall(Base):
    def test_01_unapproved_after_heredoc(self):
        cmd = "cat > f.txt <<'EOF'\nnpm install zzz\nEOF\ngo get x@v1"
        r, iss = self.check("do it", [bash(cmd)])
        self.assertEqual([i["rule"] for i in iss], ["install-unapproved"])
        self.assertIn("go get x@v1", iss[0]["evidence"])
        self.assertEqual(iss[0]["severity"], "warn")
        self.assertEqual(iss[0]["record"], 1)

    def test_02_outside_list(self):
        r, iss = self.check("Install approved: a\nGo.", [bash("npm install a b@2"), bash("npm i -D @types/a")])
        out = self.of(iss, "install-outside-list")
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["evidence"].startswith("b |"))
        self.assertTrue(out[1]["evidence"].startswith("@types/a |"))
        self.assertEqual(self.of(iss, "install-unapproved"), [])

    def test_02b_in_list_is_clean(self):
        r, iss = self.check("Install approved: `a`, B@1.", [bash("npm install a@2 b"), bash("pip install -r req.txt")])
        self.assertEqual([i["rule"] for i in iss], ["install-restore"])

    def test_03_restore(self):
        r, iss = self.check("go", [bash("npm ci")])
        self.assertEqual([(i["rule"], i["severity"]) for i in iss], [("install-restore", "info")])
        r, iss = self.check("Install approved: a", [bash("npm install --save-dev")])
        self.assertEqual(len(self.of(iss, "install-restore")), 2)

    def test_04_no_false_hit(self):
        cmds = ["grep -l 'go get' f", "grep -E 'go get|brew install' f", "echo \"npm install x\"",
                "cat <<EOF\nnpm install x\nEOF", "git log --grep='go get' | wc -l"]
        r, iss = self.check("go", [bash(c) for c in cmds])
        self.assertEqual(iss, [])
        self.assertEqual(r.stdout, "")

    def test_05_npx(self):
        os.makedirs(os.path.join(self.cwd, "node_modules", ".bin"))
        os.makedirs(os.path.join(self.cwd, "sub", "node_modules", ".bin"))
        for p in ("node_modules/.bin/tool", "sub/node_modules/.bin/tool2"):
            open(os.path.join(self.cwd, p), "w").close()
        cmds = ["npx --no-install cowsay", "npx tool", "cd %s/sub && npx tool2" % self.cwd,
                "cd %s && npx tool2" % self.tmp]
        r, iss = self.check("go", [bash(c) for c in cmds])
        self.assertEqual([i["rule"] for i in iss], ["install-unapproved"])
        self.assertIn("npx tool2", iss[0]["evidence"])
        r, iss = self.check("Install approved: cowsay", [bash("npx -y cowsay@1 hi")], agent_id="bbb")
        self.assertEqual([i for i in iss if i["agent_id"] == "bbb"], [])


class TestCommands(Base):
    def test_06_git_write(self):
        r, iss = self.check("go", [bash("git push origin main"), bash("git stash list"), bash("git stash show -p"),
                                   bash("git -C /x commit -m msg"), bash("git status")])
        self.assertEqual([i["rule"] for i in iss], ["git-write", "git-write"])
        self.assertEqual(self.check("go", [bash("git stash")], agent_id="c")[1][-1]["rule"], "git-write")
        for n, cmd in enumerate(("rtk bypass git push origin main", "timeout 5 git push origin main")):
            r, iss = self.check("go", [bash(cmd)], agent_id="w%d" % n)
            self.assertEqual([i["rule"] for i in iss if i["agent_id"] == "w%d" % n], ["git-write"])

    def test_07_destructive(self):
        r, iss = self.check("go", [bash("cd /x && rm -rf build"), bash("git push -f"),
                                   bash("find . -name x -prune"), bash("echo 'rm -rf x'")])
        d = self.of(iss, "destructive")
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["evidence"], "rm -rf build")
        self.assertEqual(json.loads(r.stdout)["systemMessage"], "agent-log: backend: 3 issue(s): destructive, git-write")
        r, iss = self.check("go", [bash("pkill -f vite"), bash("psql -c 'drop table x'"), bash("docker system prune")],
                            agent_id="d")
        self.assertEqual(len(self.of([i for i in iss if i["agent_id"] == "d"], "destructive")), 3)
        r, iss = self.check("go", [bash("ls src/prune.ts"), bash("python3 scripts/prune.py")], agent_id="r")
        self.assertEqual([i for i in iss if i["agent_id"] == "r"], [])
        r, iss = self.check("go", [bash("rm -Rf build")], agent_id="s")
        self.assertEqual([i["rule"] for i in iss if i["agent_id"] == "s"], ["destructive"])

    def test_07b_rm_in_scratchpad(self):
        sp = os.path.join(self.tmp, "scratch")
        os.makedirs(sp)
        cmd = "S=%s; rm -rf $S/dd $S/dd-ds" % sp
        r, iss = self.check("go", [bash(cmd)], agent_id="u1", scratchpad_dir=sp)
        self.assertEqual(iss, [])
        for n, (c, kw) in enumerate(((cmd + " $S/../other", {"scratchpad_dir": sp}), (cmd, {}),
                                     ("S=%s; rm -fR $S" % sp, {"scratchpad_dir": sp}),
                                     ("S=%s; rm -rf $S/a $T/b" % sp, {"scratchpad_dir": sp}),
                                     ("S=%s; pkill -f $S/x" % sp, {"scratchpad_dir": sp}))):
            aid = "u%d" % (n + 2)
            r, iss = self.check("go", [bash(c)], agent_id=aid, **kw)
            self.assertEqual([i["rule"] for i in iss if i["agent_id"] == aid], ["destructive"], c)

    def test_06b_quotes_and_subshell(self):
        r, iss = self.check("go", [bash("echo hi; (cd x && git commit -m \"a; git push\")")])
        self.assertEqual([i["rule"] for i in iss], ["git-write"])


class TestScopeSecret(Base):
    def test_08_scope(self):
        c = self.cwd
        scratch = os.path.join(self.tmp, "scratch")
        assignment = "Files in scope: %s/src/a.py (new), `%s/lib/`, rel/b.py." % (c, c)
        edits = [use("Edit", file_path=p, new_string="x") for p in (
            c + "/src/a.py", c + "/lib/deep/z.py", "rel/b.py", c + "/rel/b.py", scratch + "/note.txt", "/tmp/x.txt")]
        r, iss = self.check(assignment, edits, scratchpad_dir=scratch)
        self.assertEqual(iss, [])
        r, iss = self.check(assignment, [use("Write", file_path=c + "/other.py", content="x")], agent_id="e")
        self.assertEqual([i["rule"] for i in iss], ["scope"])
        self.assertIn(c + "/other.py", iss[0]["evidence"])
        r, iss = self.check("no scope here", [use("Write", file_path=c + "/other.py", content="x")], agent_id="f")
        self.assertEqual([i for i in iss if i["agent_id"] == "f"], [])

    def test_09_secret(self):
        text = 'x = 1\napi_key = "abcdef123456"\n'
        r, iss = self.check("go", [use("Write", file_path="/p/c.py", content=text)])
        self.assertEqual([i["rule"] for i in iss], ["secret-in-code"])
        self.assertIn("***", iss[0]["evidence"])
        self.assertIn("/p/c.py:2 ", iss[0]["evidence"])
        with open(os.path.join(self.logdir, "issues.jsonl")) as f:
            self.assertNotIn("abcdef123456", f.read())
        r, iss = self.check("go", [use("Edit", file_path="/p/d.py", new_string='token: "short"')], agent_id="g")
        self.assertEqual(len(iss), 1)


class TestBrowserSkills(Base):
    B = "~/.claude/skills/gstack/browse/dist/browse"

    def test_10_browser(self):
        r, iss = self.check("go", [bash("B=%s; $B goto http://x" % self.B)])
        self.assertEqual([i["rule"] for i in iss], ["browser-not-stopped"])
        r, iss = self.check("go", [bash("B=%s; $B goto http://x" % self.B), bash("$B stop")], agent_id="h")
        self.assertEqual([i for i in iss if i["agent_id"] == "h"], [])
        r, iss = self.check("go", [bash("%s goto x && %s stop" % (self.B, self.B))], agent_id="i")
        self.assertEqual([i for i in iss if i["agent_id"] == "i"], [])

    def test_11_skills(self):
        r, iss = self.check("سلام متن", [], atype="writing")
        self.assertEqual(iss, [])
        r, iss = self.check("measure the page", [use("Read", file_path="/x")], atype="seo", agent_id="k")
        self.assertEqual([i["rule"] for i in iss if i["agent_id"] == "k"], ["skill-missing"])
        r, iss = self.check("measure", [use("Skill", skill="benchmark")], atype="seo", agent_id="l")
        self.assertEqual([i for i in iss if i["agent_id"] == "l"], [])
        r, iss = self.check("audit", [use("Read", file_path="/x")], atype="security", agent_id="m")
        self.assertEqual([i["rule"] for i in iss if i["agent_id"] == "m"], ["cso-before-audit"])
        r, iss = self.check("audit", [use("Skill", skill="cso"), use("Read", file_path="/x")],
                            atype="security", agent_id="n")
        self.assertEqual([i for i in iss if i["agent_id"] == "n"], [])


class TestOther(Base):
    def test_12_tool_error(self):
        res = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "1", "is_error": True, "content": "boom api_key=abcdef123456789 end"},
            {"type": "tool_result", "tool_use_id": "2", "is_error": True,
             "content": [{"type": "text", "text": "second"}]},
            {"type": "tool_result", "tool_use_id": "3", "is_error": False, "content": "fine"}]}}
        r, iss = self.check("go", [bash("ls")], extra=[res])
        self.assertEqual([(i["rule"], i["severity"]) for i in iss], [("tool-error", "info")])
        self.assertTrue(iss[0]["evidence"].startswith("2 error(s): boom api_key=***"))
        self.assertNotIn("abcdef123456789", json.dumps(iss))

    def test_13_report(self):
        r, iss = self.check("go", [], msg="I changed things. Files changed: a.py")
        self.assertEqual([i["rule"] for i in iss], ["report-incomplete"])
        self.assertIn("verif", iss[0]["evidence"])
        hb = use("SubagentHandback", message="Report. Files changed: a. Verification: ok.")
        r, iss = self.check("go", [hb], msg="", agent_id="o")
        self.assertEqual([i for i in iss if i["agent_id"] == "o"], [])
        r, iss = self.check("go", [], msg="", atype="writing", agent_id="p", extra=[asst({"type": "text", "text": "x"})])
        self.assertEqual([i for i in iss if i["agent_id"] == "p"], [])
        r, iss = self.check("go", [], msg="Done. **Changed files** a.swift. Tests: 12 passed. Lint clean.", agent_id="q")
        self.assertEqual([i for i in iss if i["agent_id"] == "q"], [])
        r, iss = self.check("go", [], msg="Done. Changed paths: a.py. I ran nothing.", agent_id="s")
        self.assertEqual([i["evidence"] for i in iss if i["agent_id"] == "s"], ["final report lacks: verif"])

    def test_14_spawned_agent(self):
        a = use("Agent", description="d", prompt="p", subagent_type="backend")
        r, iss = self.check("go", [a])
        self.assertEqual([(i["rule"], i["severity"]) for i in iss], [("spawned-agent", "info")])
        r, iss = self.check("go", [a], atype="security", agent_id="q")
        self.assertEqual([i for i in iss if i["agent_id"] == "q" and i["rule"] == "spawned-agent"], [])

    def test_15_no_issues(self):
        r, iss = self.check("go", [bash("ls -la"), use("Read", file_path="/x")])
        self.assertEqual((r.stdout, iss), ("", []))

    def test_16_broken_transcript(self):
        inp = {"cwd": self.cwd, "agent_id": "z", "agent_type": "backend", "last_assistant_message": GOOD,
               "agent_transcript_path": self.write_transcript(["not json", "{", json.dumps(user("go")), "[1]"])}
        r = self.run_script("check", stdin=json.dumps(inp))
        self.assertEqual((r.returncode, r.stdout, self.issues()), (0, "", []))
        inp["agent_transcript_path"] = os.path.join(self.tmp, "missing.jsonl")
        inp["last_assistant_message"] = "api_key=abcdef123456789"
        r = self.run_script("check", stdin=json.dumps(inp))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        with open(os.path.join(self.logdir, "hook-errors.log")) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("FileNotFoundError", lines[0])
        r = self.run_script("check", stdin="not json")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_16b_meta_fallback(self):
        p = self.write_transcript([user("go"), asst(bash("git commit -m x"))])
        with open(p.replace(".jsonl", ".meta.json"), "w") as f:
            json.dump({"agentType": "frontend", "description": "Meta desc"}, f)
        r = self.run_script("check", stdin=json.dumps({"cwd": self.cwd, "agent_id": "m", "agent_transcript_path": p}))
        iss = self.issues()
        self.assertEqual((iss[0]["agent_type"], iss[0]["description"]), ("frontend", "Meta desc"))

    def test_17_duplicates(self):
        tu = bash("git push origin main")
        blob = {"type": "api-request-blob", "message": {"content": [tu]}}
        r, iss = self.check("go", [tu], extra=[blob, asst(tu)])
        self.assertEqual(len(iss), 1)
        self.assertIn("systemMessage", r.stdout)
        r, iss = self.check("go", [tu], extra=[blob, asst(tu)])
        self.assertEqual((r.stdout, len(iss)), ("", 1))
        self.assertEqual(len(iss[0]["id"]), 12)

    def test_18_add_report_resolve(self):
        self.assertEqual(self.run_script("report").stdout, "")
        ids = []
        for ev in ("first", "second api_key=abcdef123456789"):
            r = self.run_script("add", "--agent", "backend", "--rule", "review-fix", "--evidence", ev)
            self.assertEqual(r.returncode, 0)
            ids.append(r.stdout.strip())
            self.assertRegex(ids[-1], r"^[0-9a-f]{12}$")
        out = self.run_script("report").stdout
        self.assertIn("agent: backend\n  rule: review-fix (warn)  count: 2  first: ", out)
        for i in ids:
            self.assertIn("- " + i + " ", out)
        self.assertNotIn("abcdef123456789", out)
        before = self.raw()
        r = self.run_script("resolve", ids[0], "deadbeef0000")
        self.assertEqual(r.returncode, 1)
        self.assertIn("deadbeef0000", r.stderr)
        self.assertEqual(self.raw(), before)
        self.assertEqual(self.run_script("resolve", ids[0]).returncode, 0)
        out = self.run_script("report").stdout
        self.assertIn("count: 1", out)
        self.assertNotIn(ids[0], out)
        out = self.run_script("report", "--all").stdout
        self.assertIn("- %s [resolved] " % ids[0], out)
        self.assertIn("count: 2", out)
        self.assertEqual(self.run_script("resolve", ids[1]).returncode, 0)
        self.assertEqual(self.run_script("report").stdout, "")

    def test_19_modes(self):
        self.run_script("add", "--agent", "x", "--rule", "r", "--evidence", "e")
        self.assertEqual(oct(os.stat(self.logdir).st_mode & 0o777), "0o700")
        self.assertEqual(oct(os.stat(os.path.join(self.logdir, "issues.jsonl")).st_mode & 0o777), "0o600")

    def test_20_pure_functions(self):
        spec = importlib.util.spec_from_file_location("agent_log", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.bare("@Types/X@1.0"), "@types/x")
        self.assertEqual(m.bare("requests[sec]>=2"), "requests")
        self.assertEqual(m.mask("Bearer abc123 sk-abcdefghijklmnop1234"), "Bearer *** ***")
        self.assertEqual(m.mask("SECRET_KEY=abcdef123456"), "SECRET_KEY=***")
        self.assertEqual(m.mask("AWS_SECRET_ACCESS_KEY=abcdefgh12345 git push"), "AWS_SECRET_ACCESS_KEY=*** git push")
        self.assertEqual(m.prep("echo 'a b' \"c\" <<E\nbody\nE\nls"), "echo _Q_ c <<E\nls")


class TestPluginAndMasks(Base):
    def test_32_plugin_prefix(self):
        r, iss = self.check("measure the page", [use("Read", file_path="/x")], atype="agentkit:seo")
        self.assertEqual([(i["agent_type"], i["rule"]) for i in iss], [("seo", "skill-missing")])
        r, iss = self.check("audit", [use("Read", file_path="/x")], atype="agentkit:security", agent_id="b")
        self.assertEqual([(i["agent_type"], i["rule"]) for i in iss if i["agent_id"] == "b"],
                         [("security", "cso-before-audit")])
        r, iss = self.check("go", [], msg="done", atype="agentkit:backend", agent_id="c")
        self.assertEqual([i["rule"] for i in iss if i["agent_id"] == "c"], ["report-incomplete"])
        r, iss = self.check("go", [use("Agent", description="d", prompt="p", subagent_type="x")],
                            atype="agentkit:supervisor", agent_id="d")
        self.assertEqual([i for i in iss if i["agent_id"] == "d"], [])

    def test_33_export_accepts_prefix(self):
        os.makedirs(self.logdir)
        rec = {"id": "a1", "ts": "2026-01-01T00:00:00Z", "agent_type": "agentkit:backend", "rule": "r",
               "severity": "warn", "evidence": "e"}
        with open(os.path.join(self.logdir, "issues.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\n")
        g = json.loads(self.run_script("export").stdout)["groups"]
        self.assertEqual([(x["agent"], x["rule"]) for x in g], [("backend", "r")])

    def test_34_export_drops_task_text(self):
        os.makedirs(self.logdir)
        evs = [("spawned-agent", "general-purpose: Fix login bug for ClientCorp payroll"),
               ("scope", "src/a.py | Files in scope: ClientCorp/payroll.py"),
               ("secret-in-code", "src/a.py:3 password = ClientCorpSecretValue"),
               ("tool-error", "2 error(s): ClientCorp connection refused"),
               ("git-write", "git push origin main")]
        with open(os.path.join(self.logdir, "issues.jsonl"), "w") as f:
            for n, (rule, e) in enumerate(evs):
                f.write(json.dumps({"id": "i%d" % n, "ts": "2026-01-01T00:00:00Z", "agent_type": "backend",
                                    "rule": rule, "severity": "warn", "evidence": e}) + "\n")
        out = self.run_script("export").stdout
        self.assertNotIn("ClientCorp", out)
        samples = {g["rule"]: g["samples"] for g in json.loads(out)["groups"]}
        self.assertEqual(samples["spawned-agent"], ["general-purpose"])
        self.assertEqual(samples["scope"], ["src/a.py"])
        self.assertEqual(samples["secret-in-code"], ["src/a.py:3"])
        self.assertEqual(samples["tool-error"], ["2 error(s)"])
        self.assertEqual(samples["git-write"], ["git push origin main"])

    def test_35_new_masks(self):
        m = load_module()
        cases = [("Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: Basic ***"),
                 ("x ghp_" + "a1B2" * 6 + " y", "x *** y"),
                 ("x gho_" + "a1B2" * 6 + " y", "x *** y"),
                 ("github_pat_" + "A1b2C3d4E5" * 3, "***"),
                 ("key AKIAIOSFODNN7EXAMPLE end", "key *** end"),
                 ("tok xoxb-123456-abcDEF-ghi end", "tok *** end"),
                 ("a basic idea", "a basic idea")]
        for src, want in cases:
            self.assertEqual(m.mask(src), want, src)


def load_module():
    spec = importlib.util.spec_from_file_location("agent_log", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestExport(Base):
    def add(self, agent, rule, evidence):
        r = self.run_script("add", "--agent", agent, "--rule", rule, "--evidence", evidence)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def export(self, *args):
        r = self.run_script("export", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_21_scrub_kinds(self):
        m = load_module()
        home = os.path.expanduser("~")
        cases = [
            ("api_key=abcdef123456789 x", "api_key=*** x"),
            ("see %s/proj/a.py now" % home, "see ~/proj/a.py now"),
            ("see %s/work/secret-proj/src/x.py now" % home, "see ~/\u2026/src/x.py now") if len(home) > 1 else ("x", "x"),
            (USERS + "/bob/code/app/main.go", "~/\u2026/app/main.go"),
            (USERS + "/bob/work/secret-proj/src/x.py", "~/\u2026/src/x.py"),
            (USERS + "/bob/a/b.py", "~/a/b.py"),
            ("in " + HOMES + "/alice/x/y failed", "in ~/x/y failed"),
            ("edit /opt/data/deep/file.txt", "edit \u2026/deep/file.txt"),
            ("mail bob.k+x@ex-ample.co.uk please", "mail <email> please"),
            ("host 10.1.20.255 down", "host <ip> down"),
            ("GET https://user:pw@api.example.com:8443/v1/x?token=1#f ok", "GET https://api.example.com:8443 ok"),
            ("a and/or b 1/2", "a and/or b 1/2"),
        ]
        for src, want in cases:
            self.assertEqual(m.scrub(src), want, src)
        self.assertEqual(len(m.scrub("x" * 500)), 200)
        self.assertNotIn("\x1b", m.scrub("a\x1b[31mb"))

    def test_22_fields_and_filter(self):
        self.add("backend", "install-unapproved", "go get x " + USERS + "/bob/p/q/r.go a@b.io 1.2.3.4")
        self.add("Bad Name", "r", "e")
        self.add("x" * 50, "r", "e")
        self.add("backend", "bad rule!", "e")
        ex = self.export()
        self.assertEqual(ex["schema"], "agentkit-log-export/1")
        self.assertRegex(ex["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        with open(os.path.join(HERE, "..", "VERSION")) as f:
            self.assertEqual(ex["agentkit_version"], f.read().strip())
        self.assertEqual([(g["agent"], g["rule"]) for g in ex["groups"]], [("backend", "install-unapproved")])
        g = ex["groups"][0]
        self.assertEqual(set(g), {"agent", "rule", "severity", "count", "first", "last", "samples"})
        self.assertEqual(g["samples"], ["go get x ~/\u2026/q/r.go <email> <ip>"])
        self.assertEqual(set(ex), {"schema", "agentkit_version", "generated", "reporter", "groups"})

    def test_23_no_leak(self):
        rec = {"id": "abc123abc123", "ts": "2026-01-01T00:00:00Z", "source": "hook", "session_id": "SESS-1",
               "cwd": USERS + "/zed/secretproj", "agent_id": "AGENT-9", "agent_type": "backend",
               "description": "DESC-PRIVATE", "rule": "git-write", "severity": "warn",
               "evidence": "git push", "record": 4, "transcript": USERS + "/zed/.claude/TRANSCRIPT.jsonl"}
        os.makedirs(self.logdir)
        with open(os.path.join(self.logdir, "issues.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\n")
        out = self.run_script("export").stdout
        for bad in ("SESS-1", "secretproj", "AGENT-9", "DESC-PRIVATE", "TRANSCRIPT", "abc123abc123", "zed"):
            self.assertNotIn(bad, out)
        self.assertEqual(json.loads(out)["groups"][0]["count"], 1)

    def test_24_all_and_samples(self):
        ids = [self.add("backend", "destructive", "rm -rf d%d" % n) for n in range(5)]
        self.add("backend", "destructive", "rm -rf d0")
        self.run_script("resolve", ids[0], ids[1])
        g = self.export()["groups"][0]
        self.assertEqual((g["count"], g["severity"], len(g["samples"])), (4, "warn", 3))
        self.assertEqual(self.export("--all")["groups"][0]["count"], 6)
        self.assertEqual(len(set(self.export("--all")["groups"][0]["samples"])), 3)
        self.run_script("resolve", *ids[2:])
        self.assertEqual(self.export()["groups"][0]["count"], 1)

    def test_25_reporter_stable(self):
        a, b = self.export(), self.export()
        self.assertEqual(a["reporter"], b["reporter"])
        self.assertEqual(a["groups"], [])
        self.assertEqual(oct(os.stat(os.path.join(self.logdir, "reporter-id")).st_mode & 0o777), "0o600")
        other = os.path.join(self.tmp, "other")
        env = dict(os.environ, AGENT_LOG_DIR=other)
        r = subprocess.run([sys.executable, "-I", SCRIPT, "export"], capture_output=True, text=True, env=env)
        self.assertNotEqual(json.loads(r.stdout)["reporter"], a["reporter"])

    def test_26_out_file(self):
        self.add("backend", "r", "e")
        p = os.path.join(self.tmp, "out.json")
        r = self.run_script("export", "--out", p)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        with open(p) as f:
            self.assertEqual(json.load(f)["groups"][0]["agent"], "backend")


class TestMerge(Base):
    def write(self, name, reporter, groups, schema="agentkit-log-export/1"):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            json.dump({"schema": schema, "agentkit_version": "0.1.0", "generated": "2026-01-01T00:00:00Z",
                       "reporter": reporter, "groups": groups}, f)
        return p

    def grp(self, agent, rule, count, first, last, sev="warn", samples=("s",)):
        return {"agent": agent, "rule": rule, "severity": sev, "count": count, "first": first, "last": last,
                "samples": list(samples)}

    def test_27_aggregate(self):
        f1 = self.write("a.json", "R1", [self.grp("backend", "git-write", 2, "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z",
                                                  "info", ["a", "b"]),
                                         self.grp("seo", "skill-missing", 5, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")])
        f2 = self.write("b.json", "R2", [self.grp("backend", "git-write", 1, "2026-01-01T00:00:00Z", "2026-01-09T00:00:00Z",
                                                  "warn", ["b", "c", "d"])])
        r = self.run_script("merge", f1, f2)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "files: 2  reporters: 2")
        self.assertEqual(lines[1], "agent: backend")
        self.assertEqual(lines[2], "  rule: git-write (warn)  count: 3  reporters: 2  first: 2026-01-01T00:00:00Z"
                                   "  last: 2026-01-09T00:00:00Z")
        self.assertEqual(lines[3:6], ["    - a", "    - b", "    - c"])
        self.assertEqual(lines[6], "agent: seo")
        self.assertIn("count: 5  reporters: 1", lines[7])

    def test_28_bad_files_skipped(self):
        good = self.write("g.json", "R1", [self.grp("backend", "r", 1, "t1", "t2")])
        bad_json = os.path.join(self.tmp, "bad.json")
        with open(bad_json, "w") as f:
            f.write("{nope")
        wrong = self.write("w.json", "R2", [], schema="other/1")
        r = self.run_script("merge", bad_json, wrong, os.path.join(self.tmp, "missing.json"), good)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines()[0], "files: 1  reporters: 1")
        for name in ("bad.json", "w.json", "missing.json"):
            self.assertIn("skip", r.stderr)
            self.assertIn(name, r.stderr)

    def test_29_no_valid_input(self):
        wrong = self.write("w.json", "R2", [], schema="other/1")
        for args in ([wrong], [], [os.path.join(self.tmp, "missing.json")]):
            r = self.run_script("merge", *args)
            self.assertEqual((r.returncode, r.stdout), (1, ""))
            self.assertIn("no valid export file", r.stderr)

    def test_30_include_local_and_sort(self):
        self.run_script("add", "--agent", "backend", "--rule", "git-write", "--evidence", "git push " + USERS + "/q/a/b/c")
        self.run_script("add", "--agent", "docs", "--rule", "scope", "--evidence", "x")
        self.run_script("add", "--agent", "docs", "--rule", "scope", "--evidence", "y")
        f1 = self.write("a.json", "R1", [self.grp("backend", "git-write", 1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                                         self.grp("seo", "skill-missing", 9, "t", "t")])
        r = self.run_script("merge", f1, "--include-local")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "files: 1  reporters: 2")
        rules = [l.split()[1] for l in lines if l.startswith("  rule:")]
        self.assertEqual(rules, ["git-write", "skill-missing", "scope"])
        self.assertIn("count: 2  reporters: 2", [l for l in lines if "git-write" in l][0])
        self.assertIn("    - git push ~/\u2026/b/c", lines)
        r = self.run_script("merge", "--include-local")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines()[0], "files: 0  reporters: 1")

    def test_31_untrusted_text(self):
        f = self.write("a.json", "R1", [self.grp("backend", "r", 1, "t", "t", samples=["a\x1b[2Jb\nc", 5, None])])
        self.assertNotIn("\x1b", self.run_script("merge", f).stdout)


if __name__ == "__main__":
    unittest.main()
