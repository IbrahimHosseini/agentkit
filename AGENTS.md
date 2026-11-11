# agentkit

Shared agents and skills for Claude Code and Codex. A Python 3.9+ core runs the lifecycle commands on macOS, Linux, and native Windows.

**Read `HANDOFF.md` first.** It has the scope, test commands, real-machine state and open items.

## Layout
- `lib/agentkit.py`, `lib/agentkit_core/`: shared Python entry point and lifecycle engine.
- `bin/agentkit`, `install.sh`: POSIX launcher and bootstrap. `lib/legacy-cli.sh`: POSIX ancillary commands.
- `bin/agentkit.cmd`, `install.ps1`: native Windows launcher and bootstrap.
- `lib/ui.sh`, `lib/requirements.sh`, `lib/codex.py`: terminal UI, requirements check, Codex converter.
- `codex/`: `models.map`, `karpathy-guidelines.md`. `templates/AGENTS.md.snippet`: workflow block for Codex.
- `agents/*.md`: agent sources. `tests/run.sh`, `scripts/validate.sh`: checks.

## Rules
- Keep shell code compatible with Bash 3.2. No associative arrays or `mapfile`.
- Keep Python compatible with 3.9. Use `python3 -I` on POSIX and `python -I` on Windows.
- Native Windows skips gstack, the Karpathy plugin, Bash hooks, and auto-update.
- Marker-managed blocks: `<!-- agentkit:start/end -->` (md), `# agentkit:start/end` (toml). Never edit outside the markers.
- Tests must use a scratch `HOME`/`CODEX_HOME`. Do not touch the real `~/.codex` or `~/.claude` without asking.
- Do not commit or push unless asked. Do not use `--force` on the real `~/.codex` without asking (it replaces the user's 16 existing agents).

## Check before finishing
```bash
bash scripts/validate.sh
bash tests/run.sh
python3 -I -m unittest discover -s tests -p "test_*.py"
```

For native Windows, run in PowerShell 7:

```powershell
python -I -m unittest discover -s tests -p "test_*.py"
& .\tests\test_bootstrap.ps1
```

Keep the known trailing-newline XFAIL. Tests use fake target CLIs. Real target-agent sessions and WSL2 verification remain pending.
