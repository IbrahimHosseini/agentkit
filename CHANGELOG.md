# Changelog

All notable changes to this project are in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/IbrahimHosseini/agentkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/IbrahimHosseini/agentkit/releases/tag/v0.1.0
