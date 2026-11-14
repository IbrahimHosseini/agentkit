# Changelog

All notable changes to this project are in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.1] - 2026-11-14

### Changed

- User-level Claude installation on macOS and Linux includes the SessionStart auto-update hook by default. Install still requires confirmation or `--yes` before adding it. `--project` does not add this hook by default. `--skip hooks` and `--dry-run` retain their behavior.
- `agentkit auto-update off` saves the choice across updates and repeated installations. `agentkit auto-update on` enables the hook again.
- Updates preserve existing hook state. Older installations without an auto-update hook stay off until the user enables it. Codex and native Windows still have no auto-update hook.

## [0.3.0] - 2026-11-11

### Added

- A local cat icon for the README, based on the terminal logo.
- Linux dependency installation through `zypper` and `apk`, including the Alpine `github-cli` package name.
- Isolated package-manager regression tests and container CI jobs for Fedora, Arch, openSUSE Tumbleweed, and Alpine. The pre-rewrite run at `bc897d1` passed all four containers and the existing Ubuntu/macOS jobs.
- Platform status, Alpine bootstrap prerequisites, and Windows WSL2 setup and manual verification instructions. Actual WSL2 verification remains pending.
- Native Windows launcher and PowerShell bootstrap for the shared Python lifecycle. Lifecycle and PowerShell bootstrap tests passed with Python 3.9 and 3.13 in the [12-job CI run at `9cb96b4`](https://github.com/IbrahimHosseini/agentkit/actions/runs/42972579681).
- Offline lifecycle, path, managed-file, and bootstrap tests. CI includes Python 3.9 and 3.13 on Linux, macOS, and Windows.

### Changed

- Lifecycle commands use a common Python stdlib engine on all platforms. POSIX ancillary commands and optional integrations retain their shell helpers. Native Windows skips gstack, the Karpathy plugin, Bash hooks, and auto-update.
- Agent body instructions use host-native skill, web and delegation capabilities instead of Claude tool names. Claude tool lists and Codex sandbox rules are unchanged.

## [0.2.0] - 2026-11-09

### Added

- Codex support. `agentkit install --target claude|codex|both`. Without `--target`, install uses every CLI it finds. `update`, `uninstall` and `doctor` use every installed target.
- Conversion of `agents/*.md` to `~/.codex/agents/<name>.toml` and `[agents.<name>]` blocks in `~/.codex/config.toml` (between `# agentkit:start` and `# agentkit:end`). `codex/models.map` maps `opus` and `sonnet` to Codex models and efforts. An `effort:` line in the agent file overrides it.
- Sandbox rule for Codex agents: `workspace-write` when `tools` has `Edit` or `Write`, else `read-only`. `security` is always `read-only`.
- `codex/karpathy-guidelines.md`: a Codex equivalent of the karpathy plugin, adapted from andrej-karpathy-skills and appended to agents that use it.
- Workflow block for `~/.codex/AGENTS.md` (`templates/AGENTS.md.snippet`). Skills are copied to `~/.codex/skills`. gstack installs with `./setup --host codex` (experimental). A codex-only install clones gstack to `~/gstack`. With claude as a target, one clone in `~/.claude/skills/gstack` serves both hosts.
- Requirements check at install: tool list, suggested commands, y/N prompts. The check follows `--target`. `--yes` accepts package-manager installs, never remote scripts. `--dry-run` only reports.
- New install output: logo, `[i/N]` steps, progress, summary table. Plain output without a terminal, with `NO_COLOR`, or with `--quiet`.
- `CODEX_HOME` environment variable.

### Changed

- `doctor` checks `codex` and the Codex files.
- Codex agent files that agentkit did not install are skipped and left out of `config.toml`. `--force` replaces them.

### Limits

- No automatic agent log (no SubagentStop hook) and no auto-update hook for Codex. `--project` is for Claude only.

## [0.1.1] - 2026-11-07

### Fixed

- Agent log scope rule: edits under `/tmp` were always ignored, so a project inside `/tmp` was never checked. `/tmp` is now ignored only outside the project. This also fixes the Linux CI run.
- `tests/run.sh`: replaced `ls | grep` with `find` (shellcheck SC2010).

## [0.1.0] - 2026-11-07

### Added

- 16 agents: backend, database, debugger, design, devops, docs, frontend, marketing, mobile, planner, researcher, security, seo, supervisor, tester, writing.
- Skills: `agent-report` (review the agent log), and vendored `security-audit` (Cloudflare) and `write-swift` (Emil Kowalski).
- `agentkit` CLI: `install`, `update`, `auto-update on|off|status`, `uninstall`, `doctor`, `log`, `feedback`, `version`, `help`.
- `install.sh` bootstrap for `curl | bash` install, with `--dry-run`, `--yes`, `--project`, `--skip` and `--force`.
- Safe file sync: manifest with hashes, backups, `.agentkit-new` files for edited files, no overwrite of files that agentkit did not install. Deleted files stay deleted. Symlinked skills and agent files are skipped, not written through.
- `uninstall` removes only hook entries that agentkit marked. `--purge` removes `~/.agentkit` only when it is the default git clone.
- `install` converts an unmarked agentkit-looking hook, warns about an existing `# Multi-agent workflow` section outside the markers, and `install.sh` asks before it replaces a different `~/.local/bin/agentkit`.
- `update` refreshes marked hook entries whose path changed.
- CLAUDE.md workflow block (supervisor PLAN, approval, waves, REVIEW, fixes) between `agentkit` markers.
- SubagentStop agent-log hook (`hooks/agent-log.py`) with 13 rules, and `report`, `resolve`, `export` and `merge` commands.
- Anonymized sharing of the agent log with `agentkit feedback` and `agentkit log export`. Some rules export less than a command sample. Masks cover Bearer, Basic, GitHub, AWS and Slack tokens. `feedback` sends nothing when there are no open issues and keeps unsent exports in the state folder.
- SessionStart auto-update hook (`hooks/update-check.sh`): daily, in the background, fast-forward only.
- Optional install of gstack and the karpathy-guidelines plugin.
- Claude Code plugin mode: `.claude-plugin/plugin.json` and `marketplace.json`. The agent log handles agent names with the `agentkit:` prefix.
- `scripts/validate.sh`, `scripts/sync.sh` and a CI workflow for Ubuntu and macOS.

[Unreleased]: https://github.com/IbrahimHosseini/agentkit/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/IbrahimHosseini/agentkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/IbrahimHosseini/agentkit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/IbrahimHosseini/agentkit/releases/tag/v0.1.0
