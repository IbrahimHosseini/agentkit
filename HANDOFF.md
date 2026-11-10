# Handoff: agentkit 0.2.0 (Codex support) — for testing in Codex

Historical snapshot from before the 0.2.0 release branch was merged. Completed items below may no longer describe the current checkout.

Repo: project root · Branch at handoff: `feat/0.2.0-codex` · **Nothing was committed at this snapshot.**
Stack: Bash 3.2-compatible CLI (`bin/agentkit`), `install.sh`, `python3 -I` helper (`lib/codex.py`). No other deps.

## What this release adds
1. **Requirements check** (`lib/requirements.sh`, embedded in `install.sh` between `# >>> agentkit:requirements` / `# <<< agentkit:requirements`): reports missing tools, offers to install. Package managers accept `--yes`; remote `curl | bash` is never run with `--yes`. No Homebrew (cancelled by the user).
2. **Terminal UI** (`lib/ui.sh`): logo, step/item lines, spinner, summary. Plain output when not a TTY, `NO_COLOR` set, or `--quiet`. Real progress only for `git clone` (no curl progress).
3. **Codex target**: `agentkit install --target claude|codex|both`.
   - Converts `~/.claude/agents/*.md` -> `$CODEX_HOME/agents/<name>.toml` and registers `[agents.<name>]` in `config.toml` (inside `# agentkit:start/end`).
   - Model map `codex/models.map`: opus -> `gpt-6.1-sol` (high), sonnet -> `gpt-6-luna` (medium); frontmatter `effort:` overrides.
   - Sandbox: `Edit`/`Write` in `tools:` -> `workspace-write`, else `read-only`; `security` forced read-only.
   - Workflow text for Codex: `templates/AGENTS.md.snippet` -> block in `$CODEX_HOME/AGENTS.md` (`<!-- agentkit:start/end -->`).
   - Karpathy text for Codex: `codex/karpathy-guidelines.md`, appended to agents that list `karpathy-guidelines`.
   - Skills copied to `$CODEX_HOME/skills/`. gstack installed via `./setup --host codex` (clones to `~/gstack` on codex-only installs).
   - No agent-log, no auto-update hook, no `--project` for Codex.
4. Version 0.2.0 in `VERSION` and `.claude-plugin/plugin.json`; README, CHANGELOG, THIRD_PARTY, CONTRIBUTING updated.

## Run the checks (safe, no machine changes)
```bash
bash scripts/validate.sh        # structure + lib/codex checks
bash tests/run.sh               # expected: 77 passed, 0 failed, 1 xfail
shellcheck bin/agentkit install.sh lib/*.sh scripts/*.sh tests/run.sh   # NOT run locally yet
```
Tests use scratch `HOME`/`CODEX_HOME` and PATH stubs; they never touch the real `~/.codex`.

## Manual test in a scratch Codex home
```bash
export CODEX_HOME=$(mktemp -d)
bin/agentkit install --target codex --dry-run
bin/agentkit install --target codex --yes
ls "$CODEX_HOME/agents" "$CODEX_HOME/skills"
codex doctor                    # expect no agent/skill warnings
bin/agentkit uninstall --target codex
```
Then run a real Codex session with `CODEX_HOME` set and invoke a custom agent (e.g. ask it to use `backend`). **This has never been done**; only file format + `codex doctor` (codex 0.167.0) were verified.

## State of the real machine (`~/.codex`)
- Installed: skills `agent-report`, `security-audit`, `write-swift`; agentkit block in `~/.codex/AGENTS.md`; gstack symlinks `~/.codex/skills/gstack-*` -> `~/.claude/skills/gstack/.agents/skills` (gstack 1.98.0.0); `~/.codex/agentkit/` (manifest, logs).
- **Not installed:** agentkit's agents. 16 existing user agents in `~/.codex/agents/*.toml` were kept ("skip"). `config.toml` is untouched. To activate agentkit's agents: `bin/agentkit install --target codex --force` (backs up the foreign files to `$CODEX_HOME/agentkit/backups` and replaces them) — ask the owner first.

## Gotchas
- Codex custom-agent format: per-agent file has `developer_instructions`, `model`, `model_reasoning_effort`, `sandbox_mode` and **no `name` key**; a `name` key plus a config entry = duplicate-name error.
- Foreign agent files with the same name are skipped and excluded from the managed block.
- `effort` must be one of low, medium, high, xhigh, max. `lib/codex.py` has a TOML validator fallback for Python < 3.11.

## Known open items (not blocking)
- Agent bodies still mention Claude tool names (`Skill`, `WebFetch`, ...); Codex may misread them.
- `security` and `supervisor` are read-only on Codex.
- xfail: uninstall adds a trailing newline to files that had none (backup keeps exact bytes).
- `--quiet` still prints the requirements list after install.
- Empty `$CODEX_HOME/agents` remains after a `codex_prepare` failure.
- `--target both --yes` with claude missing installs codex first, then fails.
- `ui_curl_progress_flag` is unused.
- Skip warning prints literal `<name>.toml`.
- Not tested: literal Ctrl-C mid-install, a real gstack clone from scratch.
- gstack Codex tier is experimental; its safety skills are advisory only.

## Suggested next steps
1. Run the checks above (and shellcheck).
2. Scratch-home install + a real Codex session using a converted agent.
3. Decide on `--force` for the real `~/.codex`.
4. Commit / PR when satisfied (commit message ends with the Co-Authored-By line; PR body with the Claude Code line).
