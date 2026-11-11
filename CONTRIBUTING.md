# Contributing

Thank you for helping. This file explains how to change agentkit.

## Repo layout

| Path | Content |
|---|---|
| `agents/*.md` | One file for each agent. |
| `skills/<name>/` | Skills. Each has a `SKILL.md`. |
| `bin/agentkit` | The CLI (bash 3.2 compatible, python3 stdlib for JSON). |
| `install.sh` | Bootstrap script for the curl install. |
| `hooks/agent-log.py` | The agent log: `check`, `add`, `report`, `resolve`, `export`, `merge`. |
| `hooks/test_agent_log.py` | Unit tests for the hook. |
| `hooks/hooks.json` | SubagentStop hook for plugin mode. |
| `hooks/update-check.sh` | SessionStart hook for auto-update. |
| `templates/CLAUDE.md.snippet` | The workflow block that install puts in CLAUDE.md. |
| `templates/AGENTS.md.snippet` | The workflow block that install puts in `~/.codex/AGENTS.md`. |
| `lib/` | Shell and Python helpers for the CLI: `requirements.sh`, `ui.sh`, `codex.py`. |
| `codex/` | Codex files: `models.map` and `karpathy-guidelines.md`. |
| `.claude-plugin/` | `plugin.json` and `marketplace.json` for plugin mode. |
| `scripts/validate.sh` | Repo checks. |
| `scripts/sync.sh` | Maintainer tool: copy agents from `~/.claude/agents` into `agents/`. |
| `tests/` | Shell tests (`tests/run.sh`). |
| `THIRD_PARTY.md` | Sources and licenses of third-party parts. |
| `VERSION` | The version. |

## Add or change an agent

An agent file has a frontmatter block and a body:

```markdown
---
name: tester
description: Writes and runs tests. Edits test files only.
model: sonnet
tools: Read, Edit, Write, Grep, Glob, Bash, Skill
skills:
  - andrej-karpathy-skills:karpathy-guidelines
---
- Edit only test files. If the code under test is wrong, report the bug. Do not fix it.
- Use the test framework of the project. No live network in tests. Use fakes.

Rules for every task:
- ...
```

Rules:

- The file name must equal `name`. `agents/tester.md` has `name: tester`. `scripts/validate.sh` checks this.
- `description` and `tools` are required.
- `model` is `sonnet` or `opus`. `effort` is optional.
- `skills` is optional. List only skills that exist after install.
- Write in English. Use short, imperative sentences. One rule for each line.
- Do not put personal paths in the file. `scripts/validate.sh` fails on them.
- End the body with the shared "Rules for every task" block. Copy it from a worker agent such as `agents/backend.md`. Keep the wording the same. The agent-report skill and the hook rules depend on these sentences.
- If you add or remove an agent, update the agent list in `templates/CLAUDE.md.snippet` and the table in `README.md`.

## Add a skill

1. Create `skills/<name>/SKILL.md`. The frontmatter `name` must equal the folder name.
2. For a vendored skill (copied from another project):
   - Copy the folder without changes.
   - Keep the upstream `LICENSE` file in the folder.
   - Add a row to the "Vendored" table in `THIRD_PARTY.md`: path, source URL, license.
3. Skills from other places (gstack, plugins) are installed by `bin/agentkit`. Do not copy them. Add them to the "Installed by the installer" table in `THIRD_PARTY.md`.

## Check before you open a PR

```bash
scripts/validate.sh
bash tests/run.sh
```

`validate.sh` checks agent and skill frontmatter, personal paths, Python compile, the hook unit tests, JSON files, that `plugin.json` version equals `VERSION`, `bash -n` on the scripts, and shellcheck (with `--severity=warning`) when it is installed. CI runs the same two commands on Ubuntu and macOS. The workflow also defines container jobs for Fedora 43, Arch base, openSUSE Tumbleweed, and Alpine 3.22. These jobs install test prerequisites inside disposable containers. The container jobs have not been run as part of this change. They test agentkit with fake target CLIs, not real Claude Code, Codex, Bun, or gstack installations.

You can run the hook tests alone:

```bash
python3 -I hooks/test_agent_log.py
```

Test the CLI in a temporary home. Never test against your real `~/.claude`:

```bash
HOME="$(mktemp -d)" bin/agentkit install --dry-run
```

### Manual WSL2 verification

This is a manual checklist, not a report of a completed WSL2 test. Use a WSL2 Linux shell with Bash, Git, Python 3.9 or newer, and a working Linux `codex` CLI already installed. Run from a repository checkout. The clone below tests its committed revision; it does not copy uncommitted edits.

The subshell uses a temporary home and a separate clone. Its update pulls from the original checkout without changing that checkout. Optional integrations are skipped. Do not add `--force` or `--purge`.

```bash
(
  set -eu
  agentkit_source="$PWD"
  agentkit_scratch=$(mktemp -d)
  export HOME="$agentkit_scratch/home"
  export CODEX_HOME="$HOME/.codex"
  export CLAUDE_CONFIG_DIR="$HOME/.claude"
  export AGENTKIT_HOME="$agentkit_scratch/agentkit"
  mkdir -p "$HOME"
  git clone --no-hardlinks "$agentkit_source" "$AGENTKIT_HOME"
  bash "$AGENTKIT_HOME/bin/agentkit" install --target codex --dry-run --skip gstack --skip karpathy
  bash "$AGENTKIT_HOME/bin/agentkit" install --target codex --yes --skip gstack --skip karpathy
  test -s "$CODEX_HOME/config.toml"
  test -s "$CODEX_HOME/agents/backend.toml"
  bash "$AGENTKIT_HOME/bin/agentkit" doctor --target codex
  bash "$AGENTKIT_HOME/bin/agentkit" update --target codex
  bash "$AGENTKIT_HOME/bin/agentkit" doctor --target codex
  bash "$AGENTKIT_HOME/bin/agentkit" uninstall --target codex --yes
  test ! -e "$CODEX_HOME/agents/backend.toml"
  printf 'Inspect the test files in %s\n' "$agentkit_scratch"
)
```

Check that each command succeeds. Doctor can report that the skipped gstack integration is absent. Inspect the temporary configuration and backups after uninstall. Repeat with `--target claude` if Claude Code is the target, and inspect the temporary `.claude` files instead. Keep the WSL version, distribution version, target CLI version, commit, command output, and exit status with the test report. A CLI that exists only through Windows PATH forwarding does not verify the Linux target.

For a real agent session, use the temporary target configuration explicitly and verify that a custom agent can run. File installation alone does not verify agent execution. Keep the temporary home until you have inspected it; delete it manually afterward.

## Sync agents (maintainer)

To copy your edited agents from `~/.claude/agents` into the repo:

```bash
scripts/sync.sh          # changed agents that are already in the repo
scripts/sync.sh --new    # also agents that are not yet in the repo
```

It shows a diff for each file and asks y/N before it writes. It never writes to `~/.claude`.

The maintainer's own `~/.claude/agents/supervisor.md` has a different agent-log path. Answer n to that hunk.

## Release

1. Change `VERSION`.
2. Change `version` in `.claude-plugin/plugin.json` to the same value.
3. Add an entry to `CHANGELOG.md` (Keep a Changelog format).
4. Run `scripts/validate.sh`.

## Pull requests

1. Make a branch. Keep one change in each PR.
2. Run the checks above.
3. In the PR text, say what changed and why. For an agent change, name the log rule or the problem it fixes.
4. Add a line to `CHANGELOG.md` under `Unreleased`.

## Handle agent-log feedback

Users send anonymized exports with `agentkit feedback`. Each one is a GitHub issue with the label `agent-log`.

1. Save the export text of each issue to a file.
2. Merge them:
   ```bash
   agentkit log merge issue-12.json issue-15.json
   ```
   Add `--include-local` to add your own log.
3. Read the output. Two or more reporters for the same agent and rule is a good reason for a change. One reporter with a high count is still one reporter.
4. Change the agent file (or the hook, if the rule gives false positives). The `/agent-report` skill can propose the diff. Run it in this repo for maintainer mode.
5. Run the checks, then open a PR. Close the issues with a link to the PR.
