# Current work: prepare agentkit 0.4.0

Work date: 2026-11-17 (Asia/Tehran). Installer work was committed independently during this task as `001e3f0`; those changes are preserved. The user has authorized committing, release preparation and pushing. Follow CONTRIBUTING.md: open the version PR, wait for the user to merge, then tag the merged main commit and publish the GitHub release.

The approved implementation adds `agentkit models`, `--agent`, a post-prerequisite installation picker, per-target versioned preferences, and update-time rendering of saved model/effort choices. No supervisor or workers were used. The model picker changes only managed agent files and its own preferences/manifest, with backups and rollback on save errors. Existing manual edits and linked agents are skipped. Provider/account management is out of scope.

Codex model discovery uses bounded app-server `model/list`, not inference. Claude and offline Codex use explicitly unverified fallback catalogs. Unknown manual model IDs inherit effort from the CLI. Catalog test processes are fake Python CLIs; no real model service or user configuration is modified.

## Release status

Version `0.4.0` is prepared in `VERSION`, plugin metadata and the changelog. The release includes the installer improvements from `001e3f0` and per-agent model selection. Release branch: `codex/release-0.4.0`. The branch includes `origin/main` (`0951981`) and is pushed in PR #8: https://github.com/IbrahimHosseini/agentkit/pull/8. Publication remains pending the user's merge of the version PR and verification of merged-main CI; no release tag has been created.

## Windows CI follow-up

The first release CI passed Linux and macOS, but Windows revealed two backup-path assertion failures (POSIX separators in test filtering) and stalled at the first native lifecycle installation. The duplicate runs were cancelled for diagnosis. The follow-up fixes backup filtering using path components and prevents reopening CONIN$ when Windows stdin is redirected. Interactive Windows stdin remains supported. Two regression tests cover both terminal cases; CI now prints test names and bounds native steps to 20 minutes. Local validation passed after the fix: all 111 Python tests (seven skipped), the 20 desktop and 32 model tests, validate.sh and diff checks. Updated CI results are pending.

## Verification

- The focused model suite passes all 32 tests, including rollback across both targets, CLI entrypoint behavior, process timeout/cleanup and update persistence. The resource-warning check also passed.
- `bash scripts/validate.sh` passed; shellcheck is unavailable and was skipped.
- `python3 -I -m unittest discover -s tests -p "test_*.py"` passed: 109 tests, seven skipped (54.041 seconds).
- `bash tests/run.sh` passed in one uninterrupted final run: 84 passed, zero failed, one known trailing-newline XFAIL (85 total). The run used direct Xcode Git in PATH to avoid the macOS system shim cache restriction. The sole failure in the earlier run was the converter's effort error contract; it was fixed in code, with the original test preserved.
- `git diff --check` passed before release preparation.
- The optional gstack `verify` aggregator could not fingerprint the tree because the sandbox refused its temporary Git writes (`WTREE_UNAVAILABLE`). The repository's three required checks are run directly instead. Skill state/logging used a temporary home.
- Native PowerShell is unavailable here. Native Windows, WSL2 and real authenticated target-agent execution still require separate verification.

## Implementation notes

- Preferences live in each target's `agentkit/model-overrides.json`, separate from upstream sources and preserved by update.
- Keep `effort: null` as inheritance when Enter keeps the same model. Do not silently turn an inherited setting into an explicit effort.
- Codex `config.toml` may legitimately be a symlink: the picker reads its registration conflicts but never edits it. Agent files and preference/state paths must not be linked.
- Tests must use scratch homes and fake catalog processes. Keep the known trailing-newline XFAIL.
- Keep live catalog effort validation separate from the existing source converter's effort schema/error contract.
- On this sandbox, signaling an already-exited process group can return EPERM rather than ESRCH. Model discovery still needs to reap the launcher and close its pipes; the reader owns closing stdout to avoid a cross-thread close/read lock hang.

---

# Previous work: installation prerequisites and reporting

Work date: 2026-11-17 (Asia/Tehran). Base commit: `d5091a0403199590327c699c6e90ae4dd2c4b480`.

The user approved implementation of desktop detection, optional desktop installation, progress reporting, required Bun for gstack, and clearer installation instructions. The final prerequisite policy requires the CLI for every selected target. A detected desktop app does not replace its CLI.

Implementation is complete. Supervisor review returned **APPROVED**, with no unresolved FIX items. Do not treat the historical verification results below as results for this change. Tests use temporary homes and fake installers. No real desktop app, CLI, Bun, or gstack installation was performed on this machine. Do not commit or push.

## Installation behavior

- Detect desktop apps separately from their CLIs. Select automatic targets from either installed form, then require each selected CLI.
- Recognize Claude, older Codex, and the new ChatGPT app that contains Codex. Exclude ChatGPT Classic from Codex detection.
- Ask separately before optional desktop installation. `--yes` alone does not authorize it. Check the installed app after an automatic or manual installer completes.
- Show progress or a waiting indicator for downloads, dependency installation, Git operations, plugin operations, and setup.
- Require and check Bun for accepted gstack installation. Do not require Bun when gstack is declined, skipped, or unavailable on native Windows.
- Report failures with the stage, known cause, output or log path, and a next action. Preserve nonzero status for failed required steps and accepted installations.

## Verification for this change

- `bash scripts/validate.sh` passed, including shell syntax and embedded requirements-block identity checks. Shellcheck was unavailable and skipped.
- `python3 -I -m unittest discover -s tests -p "test_*.py"` passed: 77 tests, seven skipped (53.687 seconds).
- The focused installation-feedback suite passed all 11 tests.
- Shell coverage totals 84 passing cases and one known trailing-newline XFAIL across runs. The earlier full run had 82 passes, one stale assertion failure, one XFAIL, and a final terminal-fixture hang. After fixture and assertion corrections, all three affected cases passed in a focused rerun. No single uninterrupted final full-suite pass is claimed. Tests used direct Xcode Git in `PATH` to avoid the system Git shim cache restriction.
- Read-only discovery on this Mac found the installed Claude app and the ChatGPT app that contains Codex.
- `git diff --check` and `bash bin/agentkit help` passed.

Supervisor independently checked the corrected shell cases and approved the result. Native PowerShell was unavailable. Native Windows and WSL2 verification remain pending. Real app, CLI, Bun, and gstack installation were not tested. The three required POSIX checks and native Windows checks remain listed under **Current checks** below. Keep the known trailing-newline XFAIL.

---

# Previous work: prepare agentkit 0.3.1

Release preparation date: 2026-11-14 (Asia/Tehran).

Branch: `codex/default-auto-update-0.3.1`. Base commit: `96023b1`. Version [0.3.0](https://github.com/IbrahimHosseini/agentkit/releases/tag/v0.3.0) was published on 2026-11-11 after PR #4 merged. README improvements merged through PR #5 on 2026-11-14.

This branch prepares default auto-update for user-level Claude installations on macOS and Linux. Install still asks before adding the hook. Project installations with `--project` do not add this hook by default because it updates user-level installations. Explicit `auto-update off` choices saved with 0.3.1 survive updates and repeated installations. Updates do not add absent hooks to older installations. Codex and native Windows behavior stays unchanged.

Version 0.3.1 is not published. The user approved implementation and release preparation. The user must merge the version PR before tagging the merged commit and publishing the GitHub release. The original 0.2.0 handoff below is historical.

## Scope and layout

- `lib/agentkit.py` and `lib/agentkit_core/` implement shared `install`, `update`, `doctor`, `uninstall`, `version`, and `help` commands.
- `bin/agentkit` is the POSIX launcher. `lib/legacy-cli.sh` provides POSIX ancillary commands and integration helpers.
- `bin/agentkit.cmd` and `install.ps1` are native Windows entry points. They need Python 3.9 or newer and native Git. The target CLI must already be installed.
- Native Windows skips gstack, the Karpathy plugin, Bash hooks, and auto-update. It does not require Bash, WSL, administrator rights, or symlink privileges.
- Existing manifests, backup folders, target overrides, and marker-managed configuration retain their layout. Do not change the real user configuration for testing.

## Current verification

Local verification for 0.3.1:

- `bash scripts/validate.sh` passed. Shellcheck was unavailable and skipped.
- `python3 -I -m unittest discover -s tests -p "test_*.py"` passed: 48 tests, seven skipped.
- `bash tests/run.sh` passed: 84 passed, zero failed, one known-bug XFAIL, 85 total. The macOS run used direct Xcode Git in `PATH` to avoid the system shim's temporary cache file.
- Nine focused shell tests passed, including the project-install check.
- CI for the new release PR is pending.

The results below describe earlier work, not this release change.

The [base-main CI run at `96023b1`](https://github.com/IbrahimHosseini/agentkit/actions/runs/43590866404) passed before this branch started.

The [Linux CI run at `bc897d1`](https://github.com/IbrahimHosseini/agentkit/actions/runs/42948209369) passed macOS, Ubuntu, Fedora, Arch, openSUSE, and Alpine before the shared-core rewrite. The four distro suites each reported 81 passed, zero failed, and one known-bug XFAIL. The container setup uses `tar --no-same-owner` so root does not restore checkout ownership into the scratch Git upstream.

The [shared-core CI run at `9cb96b4`](https://github.com/IbrahimHosseini/agentkit/actions/runs/42972579681) passed all 12 jobs. It covered the existing Ubuntu and macOS shell checks, Fedora 43, Arch base, openSUSE Tumbleweed, and Alpine 3.22 containers, and Python 3.9 and 3.13 on Linux, macOS, and native Windows.

Each Windows Python suite reported 48 tests: 38 passed and ten skipped for platform or privilege limits. Each Windows PowerShell suite reported 12 passed, zero failed, and 12 total. The PowerShell cases include owned launcher self-purge, junction guards, preservation of foreign or edited launchers, and removal of read-only Git objects.

Fake target CLIs and local Git upstreams verify agentkit behavior. They do not verify a real custom-agent session. WSL2 testing on Windows remains pending. PowerShell is not available on the local macOS host.

The CI result above covers the native Windows work before its merge. CI for this version PR remains pending. Keep the known trailing-newline XFAIL. Real Claude Code, Codex, Bun, and gstack execution remains unverified by these fake-CLI tests.

## Current checks

On POSIX:

```bash
bash scripts/validate.sh
bash tests/run.sh
python3 -I -m unittest discover -s tests -p "test_*.py"
```

On Windows, from PowerShell 7:

```powershell
python -I -m unittest discover -s tests -p "test_*.py"
& .\tests\test_bootstrap.ps1
```

Use the [native Windows instructions](README.md#native-windows). The native files are available on `main`. No local package installation is needed for the tests. Do not commit, push, or use a real user home without authorization.

---

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
