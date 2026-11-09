# agentkit

Shared pack of Claude Code agents with a Bash CLI. Version 0.2.0 adds Codex support. Branch: `feat/0.2.0-codex`, nothing committed.

**Read `HANDOFF.md` first.** It has the scope, test commands, real-machine state and open items.

## Layout
- `bin/agentkit`: CLI (Bash 3.2 compatible). `install.sh`: bootstrap installer.
- `lib/ui.sh`, `lib/requirements.sh`, `lib/codex.py`: terminal UI, requirements check, Codex converter.
- `codex/`: `models.map`, `karpathy-guidelines.md`. `templates/AGENTS.md.snippet`: workflow block for Codex.
- `agents/*.md`: agent sources. `tests/run.sh`, `scripts/validate.sh`: checks.

## Rules
- Bash 3.2 only (no associative arrays, no `mapfile`). Python via `python3 -I`.
- Marker-managed blocks: `<!-- agentkit:start/end -->` (md), `# agentkit:start/end` (toml). Never edit outside the markers.
- Tests must use a scratch `HOME`/`CODEX_HOME`. Do not touch the real `~/.codex` or `~/.claude` without asking.
- Do not commit or push unless asked. Do not use `--force` on the real `~/.codex` without asking (it replaces the user's 16 existing agents).

## Check before finishing
```bash
bash scripts/validate.sh
bash tests/run.sh    # expect 77 passed, 0 failed, 1 xfail
```
