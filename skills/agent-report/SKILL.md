---
name: agent-report
description: "Read the agent log, show open issues by agent and rule, and propose diffs for the agent definitions. Use when the user types /agent-report or asks to review the agent log."
---

# Agent report

The SubagentStop hook writes issues to the agent log. This skill reads the log. It proposes changes to `~/.claude/agents/<agent>.md`. It never edits a file without a yes from the user.

agentkit installs the agent files in `~/.claude/agents/`. A local edit is kept by `agentkit update`, but that file then stops getting upstream changes. The new version lands as `<name>.md.agentkit-new`.

## Commands

Use `agentkit log <subcommand>` when `agentkit` is on PATH. Else use `python3 -I "${AGENTKIT_HOME:-$HOME/.agentkit}/hooks/agent-log.py" <subcommand>`. In plugin mode, find the script with `ls ~/.claude/plugins/cache/*/agentkit/*/hooks/agent-log.py`. Below, `<dir>` is the folder that holds `hooks/`.

- `report` prints the open issues. `--all` also prints resolved issues.
- `resolve <id> [<id>...]` marks issues as resolved. It exits 0 on success. It exits 1 and prints the unknown ids on stderr when an id is unknown. In that case it changes nothing.
- `merge FILE... [--include-local] [--all]` combines export files from other users (maintainer mode). It prints the same format as `report`, plus `files: N  reporters: M` and `reporters: K` on each rule line. It skips bad files with a message on stderr. It exits 1 when no input is valid.
- `export [--out FILE] [--all]` prints an anonymized summary. `agentkit feedback` runs it. You do not need to run it.
- `python3 -I <dir>/hooks/test_agent_log.py` runs the unit tests of the hook.

## Report format

Empty output means there is no open issue. Else the output has groups, one group for each agent and rule:

```
agent: backend
  rule: install-unapproved (warn)  count: 2  first: 2026-11-01T14:30:00Z  last: 2026-11-02T09:01:00Z
    - 3f9a1c0b7d2e 2026-11-01T14:30:00Z hook | Backend test: split endpoint | go get github.com/google/uuid@v1.6.0
```

- The agent line is the agent type.
- The rule line has the rule, the highest severity, the count, and the first and last time. Without `--all`, the count includes open issues only.
- Each issue line has the 12-hex id, the time, the source (`hook` or `supervisor-review`), the description and the evidence. The description is `-` when it is empty.
- With `--all`, `[resolved]` follows the id of each resolved issue.

## Steps

1. Run the report command. If the output is empty, tell the user "No open issues in the agent log." Stop.
2. For each group, show the agent, the rule, the count and the evidence lines with their ids.
3. Open `~/.claude/agents/<agent>.md`. If the file does not exist, say so and give a note only. Built-in agents such as general-purpose and claude-code-guide have no file.
4. Find the line that the rule belongs to. Use the rule-to-line table below. Use grep to find the line. If grep finds no line, say so. Propose a new sentence in "Rules for every task".
5. Decide if the issue is a note or a change.
   - One issue in one run is a note. It is not a rule change.
   - Propose a change to the definition only if the count for the same agent and rule is 2 or more.
   - Also propose a change if the rule is a rule violation. These rules are install-unapproved, install-outside-list, git-write, destructive, secret-in-code and scope.
6. For a change, show a unified diff. Add or change one short sentence. Write it in the style of the file: short imperative sentences. Do not edit any file in this step.
7. Ask the user which diffs to apply.
8. For each approved diff, offer three options: (a) apply it locally, (b) send it upstream with `agentkit feedback` (it shares the anonymized export), or both. Say that a local edit stops upstream changes for that file.
9. For (a), apply the diff with Edit. Use grep to check that the new sentence is in the file. Then run `resolve` with the ids of that group. Check that the exit code is 0. For (b), tell the user to run `agentkit feedback`. Do not run it for them.
10. If an issue is a false positive of the hook, do not change the agent file. In maintainer mode, propose a change to `hooks/agent-log.py` in the repo. After a yes, apply it and run the unit tests. Resolve the ids only if the tests pass. Else tell the user to report it upstream.
11. For notes, ask the user if you can resolve their ids. Resolve them only after a yes.
12. Never edit an agent file without a yes from the user. Never print a token or the env block of `settings.json`.

## Maintainer mode

Use it when the current folder has `.claude-plugin/plugin.json` with `"name": "agentkit"` and an `agents/` folder. Check both before you start.

- Edit `agents/<agent>.md` in that repo, not `~/.claude/agents`.
- The user names export files, for example from GitHub issues. Run `merge` on them. Add `--include-local` only if the user asks.
- The thresholds in the steps above still apply. Count reporters, not only issues: 2 or more reporters for the same agent and rule is a change. One reporter with a high count is still one reporter.
- Do not use `resolve` for issues that come from export files. They are not in the local log.

## Rule-to-line table

Search for the quoted text with grep in `~/.claude/agents`. Most agent files have the same sentences in "Rules for every task". "Do not commit. Do not push." and "Do not run destructive commands ..." are in all files. "Edit only the files named in your assignment." is not in debugger.md, researcher.md, security.md and supervisor.md. "An install is risky unless ..." is not in supervisor.md.

| Rule | Where the rule lives |
|---|---|
| install-unapproved, install-outside-list, install-restore | The "An install is risky unless ..." sentence in "Rules for every task". supervisor.md: no line yet. Propose one. |
| git-write | "Do not commit. Do not push." |
| destructive | "Do not run destructive commands ..." |
| scope | "Edit only the files named in your assignment." Exceptions: debugger.md: "If the assignment names files, edit only those files." security.md and supervisor.md: "Do not edit project files." researcher.md: "Do not edit files." |
| secret-in-code | backend.md: "Never put secrets in code ...". devops.md: "Do not add secrets to files." Other agents: no line yet. Propose one in "Rules for every task". |
| browser-not-stopped | frontend.md and seo.md: "After a browser check, run the skill's stop command." |
| skill-missing | seo.md: "To measure a page, load the benchmark skill ..." |
| cso-before-audit | security.md: "Load cso before you run any audit command." |
| report-incomplete | The line that starts with "Report:". Most agents have "Report: what you did, files changed, verification result ...". debugger.md, researcher.md and security.md have their own wording. supervisor.md has no such line. |
| spawned-agent | The `tools:` line in the frontmatter |
| tool-error | No fixed line. Note only, unless the count is 2 or more. |
| review-fix | The file and line that the evidence names |
