# Changelog

All notable changes to this project are in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The Claude model picker lists OpenAI models. A Claude agent set to one relays its task to `codex exec` with the chosen model and effort. Switching back to a Claude model restores the agent.

### Fixed

- Generated Codex agent files now start with `name` and `description`. Current Codex versions ignore a standalone role file without them. Reinstall or update to regenerate the files.

## [0.6.0] - 2026-11-19

### Changed

- Model settings and interactive choices use aligned terminal tables, with clay-orange Claude labels and teal Codex labels. The model picker shows advertised effort levels and proposed changes in the same format.
- Application detection, installation summaries, `doctor`, uninstall plans, and POSIX log reports display structured lists with separators.
- Narrow terminals use compact layouts, and `NO_COLOR` keeps the table structure in monochrome. Redirected output keeps its existing plain format.

## [0.5.0] - 2026-11-18

### Added

- Live Claude model and effort discovery through the official Agent SDK and the existing Claude Code login, without sending prompts or requesting inference. The optional SDK is pinned and installed in an isolated target runtime; Node.js is never installed automatically.
- A target picker for Claude, Codex or both before configuring models, plus an explicit option to show hidden Codex models.

### Changed

- Model choices display names, IDs and advertised effort levels. Safe new effort values such as `ultra` survive saving and updates; unknown capabilities inherit the CLI setting.
- Discovery failures show an actionable reason and label the local fallback as unverified. Interrupted Claude SDK setup is retried on the next request.

### Fixed

- Linux and WSL installations no longer offer or launch Claude Desktop installation. Claude Code CLI remains required for the Claude target.
- Model configuration reads and changes only the selected target's settings. Dry runs never install the Claude SDK runtime.

## [0.4.0] - 2026-11-17

### Added

- Per-agent model and effort selection for Claude Code and Codex after installation prerequisites, with a final confirmation before saving.
- `agentkit models` to change installed agents independently, including `--agent`, `--target`, Claude project installations and dry runs. Saved choices survive updates; unmanaged, edited and linked agents are skipped.
- Bounded Codex model discovery through app-server, offline catalogs, manual model IDs, and access guidance. Model preferences contain no credentials; saves back up files and roll back on failure.
- Separate desktop-app detection and optional desktop installation. A desktop app does not replace its required target CLI.

### Changed

- Installation reports progress, completed/skipped stages and actionable failures. Accepted gstack installation requires Bun and propagates setup errors.
- Unattended installation and `--yes` preserve existing/default model settings. Interactive model selection supports keeping inherited effort and restoring upstream defaults.

### Fixed

- README icon rendering now uses a local PNG asset.
- Noninteractive Windows installs skip optional desktop prompts instead of reopening a console that may wait indefinitely for input.

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

[Unreleased]: https://github.com/IbrahimHosseini/agentkit/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/IbrahimHosseini/agentkit/compare/dc29d80cfa3dd02991f5eeeeeb13c51e88cf555a...v0.5.0
[0.4.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/IbrahimHosseini/agentkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/IbrahimHosseini/agentkit/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/IbrahimHosseini/agentkit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/IbrahimHosseini/agentkit/releases/tag/v0.1.0
