# agentkit

[![CI](https://github.com/IbrahimHosseini/agentkit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/IbrahimHosseini/agentkit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/IbrahimHosseini/agentkit)](https://github.com/IbrahimHosseini/agentkit/releases/latest)
[![License: MIT](https://img.shields.io/github/license/IbrahimHosseini/agentkit)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

agentkit is a shared pack of agents for a team. It works with Claude Code and with Codex. It has 16 agents, three skills, a workflow block for CLAUDE.md or AGENTS.md and (for Claude Code) a hook that logs agent mistakes on POSIX systems. One command installs it. One command updates it.

The agents follow one workflow. A supervisor plans the work. You approve the plan. Workers do the parts. The supervisor reviews the result. The hook records when an agent breaks a rule, so the team can improve the agent files.

## Requirements

| Tool | Need | Used for |
|---|---|---|
| macOS, Linux, or native Windows | required | The platform. WSL2 is a separate Linux environment. |
| Bash 3.2 or newer | POSIX only | The shell installer and optional POSIX integrations. |
| PowerShell | native Windows bootstrap | Run `install.ps1`. Windows CI uses PowerShell 7. |
| `curl` | POSIX bootstrap command only | Download the shell installer. |
| `git` | required | Clone and update. |
| Python 3.9 or newer | required | The shared CLI. On POSIX, the command is `python3`. On Windows, the launcher checks `python`, `python3`, then `py -3`. |
| `claude` or `codex` | at least one is required | The agent CLI you install for. |
| `gh` | optional | `agentkit feedback`. |
| `bun` | optional | Install of gstack. |

On macOS and Linux, when a tool is missing, install does this:

1. It prints a list of all tools. `✓` means found. `✗` means missing or too old.
2. It suggests an install command for each missing tool.
3. It asks `y/N` before it runs a command.

These dependency-install rules apply to macOS and Linux. Native Windows reports missing requirements and asks you to install them yourself. It does not run `winget`, a package manager, or a remote installer.

Rules:

- With `--yes`, install accepts commands from a package manager (for example `brew install git`).
- With `--yes`, install never runs a remote script (`curl ... | bash`). You must answer the prompt yourself, in a terminal.
- With no terminal and without `--yes`, nothing is installed. Install prints the commands.
- With `--yes`, package-manager commands run. Remote scripts never run with `--yes`.
- The check follows `--target`. With `--target claude`, it needs `claude`. `codex` is then optional. With `--target codex`, it needs `codex`. `claude` is then optional. With `--target both`, it needs both. Without `--target`, one of the two is enough.
- With `--dry-run`, install only reports. It runs nothing.

### Platform status

The requirements check detects package managers, not distribution names.

| Environment | Dependency package manager | Verification coverage |
|---|---|---|
| macOS | Homebrew, if present | Existing CI job. |
| Debian / Ubuntu | `apt-get` | Existing Ubuntu CI job. |
| Fedora | `dnf` | Fedora 43 container CI passed at `bc897d1`. |
| Arch Linux | `pacman` | Arch base container CI passed at `bc897d1`. |
| openSUSE | `zypper` | Tumbleweed container CI passed at `bc897d1`. |
| Alpine Linux | `apk` | Alpine 3.22 container CI passed at `bc897d1`. See prerequisites below. |
| Native Windows | Manual prerequisite installation | Python 3.9/3.13 CI configured. Native verification is pending. |
| Windows with WSL2 | The Linux distribution's manager | Manual verification required. |
| Other Linux distributions | Manual prerequisite installation | No distribution-specific CI. |

The [Linux distribution run at `bc897d1`](https://github.com/IbrahimHosseini/agentkit/actions/runs/42948209369) passed on macOS, Ubuntu, Fedora, Arch, openSUSE, and Alpine. Each of the four container suites reported 81 passed, zero failed, and one known-bug XFAIL. This result predates the shared Python rewrite. The new workflow also tests the shared core on Linux, macOS, and Windows with Python 3.9 and 3.13. Results for that rewrite are pending. Tests use fake target CLIs and local Git repositories. They do not prove that real Claude Code, Codex, Bun, or gstack runs on each distribution. WSL2 has not been tested on a Windows machine.

If no supported package manager is found, install Bash, `curl`, `git`, Python 3.9 or newer, and your target CLI yourself. Then use the same Bash installer below. A missing optional tool does not prevent the core install. Non-root dependency installation requires `sudo`; on systems without it, install prerequisites as root first.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash
```

The script clones the repo to `~/.agentkit`. It links the CLI to `~/.local/bin/agentkit`. Then it runs `agentkit install`. Each change to your settings asks for a yes first.

### Alpine prerequisites

The bootstrap needs Bash before it can check dependencies. In an Alpine root shell, install the bootstrap tools first:

```sh
apk add --no-cache bash curl git python3
```

Then install a compatible target CLI and run the Bash install command above. [Alpine uses musl](https://www.alpinelinux.org/about/). A working agentkit shell/Python install does not establish compatibility for Claude Code, Codex, Bun, or gstack. Check each upstream tool's requirements. To check the core install without optional gstack or the Claude plugin, use:

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash -s -- --skip gstack --skip karpathy
```

### Native Windows

Native Windows support is under verification on this branch. Use a checkout that contains `install.ps1`, `bin/agentkit.cmd`, and `lib/agentkit.py`. The `main` bootstrap command does not install these unmerged changes.

Install Python 3.9 or newer, Git for Windows, and the native `claude` or `codex` CLI first. Add these tools to PATH and open a new terminal. The bootstrap prints guidance for missing prerequisites. It does not install them.

From that checkout, run in PowerShell:

```powershell
$env:AGENTKIT_HOME = (Get-Location).Path
& .\install.ps1 --target codex
& "$env:USERPROFILE\.local\bin\agentkit.cmd" doctor --target codex
```

Use `--target claude` or `--target both` when needed. Use `--dry-run` to inspect changes, or `--yes` to accept prompts. The script uses the checkout named by `AGENTKIT_HOME`. Without that variable, it uses `%USERPROFILE%\.agentkit` and clones there if the directory does not exist. A custom checkout is useful while native changes are unmerged.

The bootstrap writes an ordinary launcher to `%USERPROFILE%\.local\bin\agentkit.cmd`. It backs up an existing launcher before replacement. It does not need administrator access, WSL, Bash, or permission to create symlinks. It does not change PATH, the registry, or execution policy. Add the launcher directory to your user PATH yourself if you want to type `agentkit`. If local policy blocks PowerShell scripts, use your organization's approved process. The core can also run directly:

```powershell
python -I .\lib\agentkit.py install --target codex
python -I .\lib\agentkit.py doctor --target codex
```

Native Windows runs `install`, `update`, `doctor`, `uninstall`, `version`, and `help` through the same Python engine as macOS and Linux. Default target folders are `%USERPROFILE%\.claude` and `%USERPROFILE%\.codex`. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` override them. Keep Windows and WSL configurations separate.

The first native version does not install gstack, the Karpathy plugin, Bash hooks, or auto-update hooks. It prints this limit. `auto-update`, `log`, and `feedback` remain POSIX commands. Codex agents can still include the bundled Karpathy instruction text. A `.cmd` or `.bat` target command cannot use shell metacharacters in its executable path or arguments: `& | < > ^ % !`, carriage returns, or newlines. Use a native executable or a path without these characters.

### Upgrade an existing installation

Existing target manifests and backup folders keep the same layout. No manual configuration conversion is needed. After you update the agentkit checkout, run `agentkit update`. The shared engine reads the existing `agentkit/manifest.json`, keeps user-edited files, and writes a `.agentkit-new` file when an upstream change needs review. Files outside managed blocks stay in place. Keep your existing `CODEX_HOME` or `CLAUDE_CONFIG_DIR` overrides during the upgrade.

### Windows through WSL2

Use a Linux environment in WSL2. Follow the [Microsoft WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install). In an administrator PowerShell window:

```powershell
wsl --install
```

Restart if requested, then finish the Linux user's setup. Check that the distribution uses version 2 with `wsl --list --verbose` in PowerShell. The default installation uses Ubuntu and WSL2. See [Microsoft's command reference](https://learn.microsoft.com/en-us/windows/wsl/basic-commands) for existing installations and other distributions.

Inside the Linux shell, install the Linux version of your target CLI and run the agentkit install command above. Run both tools from that same Linux environment. Use the Linux home directory for `~/.claude` and `~/.codex`. Do not point `CLAUDE_CONFIG_DIR` or `CODEX_HOME` at your native Windows configuration. This installation does not configure a native Windows CLI or desktop app.

The [manual WSL2 checklist](CONTRIBUTING.md#manual-wsl2-verification) checks agentkit in a temporary home. A successful package-manager simulation is not a successful WSL2 test.

### What you see

Install prints a logo, then numbered steps such as `[2/6]`, with a progress line for long work such as `git clone`. At the end it prints a summary table. When the output is not a terminal, or `NO_COLOR` is set, or you pass `--quiet`, the output is plain text. `--quiet` prints only errors.

Pass flags after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash -s -- --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Show what would change. Write nothing. |
| `--yes`, `-y` | Answer yes to every question. |
| `--target claude\|codex\|both` | Choose the CLI to install for. See below. |
| `--project DIR` | Install into `DIR/.claude` and `DIR/CLAUDE.md`, not into `~/.claude`. Claude only. |
| `--skip STEP` | Skip a step. STEP is `gstack`, `karpathy`, `claude-md`, `hooks` or `skills`. Repeat the flag to skip more. |
| `--force` | Replace files that already exist and that agentkit did not install. A backup is made first. |
| `--quiet` | Print only errors. Questions still show. |

### Targets

`--target` sets which CLI gets the install.

- Without `--target`, `install` uses every CLI it finds: `claude`, `codex`, or both.
- `update`, `uninstall` and `doctor` use every target that is already installed.
- With `--target claude`, files go to `~/.claude` (or `CLAUDE_CONFIG_DIR`).
- With `--target codex`, files go to `~/.codex` (or `CODEX_HOME`).
- `--target both` does both.
- `--project` works only for Claude. `--project` with `--target codex` or `both` is an error.
- `auto-update` is for Claude on POSIX only.

### What install changes

The hooks, gstack, and Karpathy plugin rows below apply to POSIX systems only. Native Windows installs the agents, bundled skills, workflow blocks, and Codex configuration.

| Item | Where | Step name |
|---|---|---|
| 16 agent files | `~/.claude/agents/` | (always) |
| Skills `agent-report`, `security-audit`, `write-swift` | `~/.claude/skills/` | `skills` |
| Workflow block between `<!-- agentkit:start -->` and `<!-- agentkit:end -->` | `~/.claude/CLAUDE.md` | `claude-md` |
| SubagentStop hook (agent log) | `~/.claude/settings.json` | `hooks` |
| gstack (git clone, then its `./setup --host claude`) | `~/.claude/skills/gstack` | `gstack` |
| karpathy-guidelines plugin | through `claude plugin install` | `karpathy` |
| Codex agents (16 `.toml` files) | `~/.codex/agents/` | (always, target codex) |
| `[agents.<name>]` blocks between `# agentkit:start` and `# agentkit:end` | `~/.codex/config.toml` | (always, target codex) |
| Workflow block between `<!-- agentkit:start -->` and `<!-- agentkit:end -->` | `~/.codex/AGENTS.md` | `claude-md` |
| Skills `agent-report`, `security-audit`, `write-swift` | `~/.codex/skills/` | `skills` |
| gstack (`./setup --host codex`) | The setup writes `~/.codex/skills/gstack-*`. With a codex-only install, the clone is `~/gstack`. | `gstack` |

Safety rules:

- agentkit never overwrites a file that you own. It skips the file and says so. Use `--force` to replace it.
- A symlinked skill folder or agent file is never adopted and never written through. agentkit skips it. `--force` replaces only the link, after a backup.
- If `~/.local/bin/agentkit` already exists and is not the agentkit link, `install.sh` asks before it replaces it.
- If an unmarked hook in `settings.json` looks like the agentkit hook, install converts it. The prompt shows the old and the new entry.
- If CLAUDE.md already has a `# Multi-agent workflow` section outside the markers, install warns you. The block would duplicate it.
- Before agentkit changes or removes a file, it copies the file to `~/.claude/agentkit/backups/<timestamp>/`.
- agentkit only edits the block between its two markers in CLAUDE.md. The rest of the file stays as it is.
- agentkit keeps a manifest with file hashes in `~/.claude/agentkit/manifest.json`.

Run `agentkit doctor` after the install.

### Codex

With target codex, agentkit converts each `agents/<name>.md` to a Codex custom agent.

- It writes `~/.codex/agents/<name>.toml`.
- It adds an `[agents.<name>]` block to `~/.codex/config.toml`. All blocks sit between `# agentkit:start` and `# agentkit:end`. The rest of the file stays as it is.
- It maps the Claude `model:` to a Codex model and effort with `codex/models.map`:

| Claude model | Codex model | Effort |
|---|---|---|
| `opus` | `gpt-6.1-sol` | `high` |
| `sonnet` | `gpt-6-luna` | `medium` |

- An `effort:` line in the agent file overrides the effort. To change a model, edit `codex/models.map`.
- Sandbox rule: if `tools` has `Edit` or `Write`, the sandbox is `workspace-write`. If not, it is `read-only`. The `security` agent is always `read-only`.
- Agents that list `karpathy-guidelines` get the text of `codex/karpathy-guidelines.md` at the end of their instructions. It is the Codex equivalent of the plugin.
- The workflow block goes to `~/.codex/AGENTS.md`. It tells the main session to start workers as Codex subagents.
- The three skills are copied to `~/.codex/skills`.
- gstack uses `./setup --host codex`. This is experimental. Where the clone lives:
  - If `~/.claude/skills/gstack` has a clone, agentkit reuses it.
  - With target claude, the clone is `~/.claude/skills/gstack`. One install runs the setup for each host that needs it.
  - With a codex-only install, agentkit reuses `~/gstack` if it has a clone. If not, it clones gstack to `~/gstack`.
  - agentkit never clones gstack under `~/.codex/skills`. Doctor treats gstack as installed on Codex when `~/.codex/skills/gstack-*` exists.
   The safety skills (`careful`, `guard`, `freeze`) are advice only on Codex.
- If `~/.codex/agents/<name>.toml` exists and agentkit did not install it, agentkit skips it. It also leaves that agent out of `config.toml`. Use `--force` to replace it, after a backup.

Limits on Codex:

- There is no SubagentStop hook on Codex, so nothing is logged automatically. The `supervisor` agent file still tells the supervisor to run `agentkit log add` for each FIX. Codex may or may not follow this. Rules such as `scope` or `git-write` are never checked on Codex.
- There is no auto-update hook.
- Agent bodies describe capabilities using the host's native mechanisms. Claude frontmatter tool lists are unchanged. Matching runtime behavior across hosts has not been verified.
- `doctor`, `update` and `uninstall` cover both targets.

### Alternative: plugin install

Inside Claude Code:

```bash
/plugin marketplace add IbrahimHosseini/agentkit
/plugin install agentkit@agentkit
```

Plugin mode adds the agents, the skills and the agent-log hook. It does not add the CLAUDE.md workflow block. It does not add the `agentkit` CLI. Plugin agent names may get the prefix `agentkit:`. The agent log handles this.

Do not use both modes at once. You would get two copies of the hook.

## Usage

The workflow block in CLAUDE.md tells the main session how to work on tasks that change code or have several steps.

1. The supervisor agent runs in PLAN mode. It splits the task into parts and waves.
2. The main session shows you the plan: the number of agents, the waves, and the work of each agent. You approve it or change it. If a part needs an install, you approve the packages.
3. Workers run. Parts in the same wave run in parallel. Two parts never edit the same file.
4. The supervisor runs in REVIEW mode. It checks the worker reports against the task.
5. Each fix goes back to the worker that owns the part. REVIEW runs again. The loop stops after 2 rounds.
6. You get the result, the verdict, and anything that is still open.

The supervisor is skipped for small tasks: 3 files or fewer, one area, no schema or auth change.

Example prompt:

```text
Add a "last login" column to the users table and show it on the admin page.
```

The supervisor can split this into a database part (migration), a backend part (API field), a frontend part (column) and a tester part. The plan shows you this split before any worker starts.

### Agents

| Agent | What it does | Model | Skills it uses |
|---|---|---|---|
| `backend` | Server code, APIs, business logic (Go, Python, Node/TypeScript) | sonnet | karpathy-guidelines |
| `database` | Schema, migrations, queries, indexes | sonnet | karpathy-guidelines, careful |
| `debugger` | Finds the root cause of a bug and makes a minimal fix | opus | karpathy-guidelines |
| `design` | UI/UX design, design systems, visual review | opus | karpathy-guidelines, animate, animate-expo, apple-design, emil-design-eng |
| `devops` | CI/CD, deployment files, Docker | sonnet | karpathy-guidelines, careful |
| `docs` | README, CLAUDE.md and project docs. Never edits source code. | sonnet | karpathy-guidelines, asd-ste100 |
| `frontend` | Web UI in React, Next.js, Vue/Nuxt, HTML, CSS | sonnet | karpathy-guidelines, browse |
| `marketing` | Strategy, positioning, campaigns, launch plans | sonnet | (none listed) |
| `mobile` | Swift/SwiftUI, Kotlin/Compose, Flutter/Dart apps | opus | karpathy-guidelines, write-swift |
| `planner` | PRDs, specs, technical plans | opus | karpathy-guidelines, asd-ste100 |
| `researcher` | Read-only research in code and on the web | sonnet | browse |
| `security` | Security review. Does not edit project files. | opus | karpathy-guidelines, cso, security-review, security-audit |
| `seo` | Keywords, on-page and technical SEO, page speed | sonnet | karpathy-guidelines, browse, benchmark |
| `supervisor` | PLAN mode and REVIEW mode for multi-step work | opus | asd-ste100 |
| `tester` | Writes and runs tests. Edits test files only. | sonnet | karpathy-guidelines |
| `writing` | Posts and copy for Telegram, LinkedIn and other channels | opus | (none listed) |

Some skills come from gstack and the karpathy plugin (see Dependencies). An agent lists a skill in its file. If the skill is not installed, the agent reports it.

## Updating

```bash
agentkit update
```

This runs `git pull --ff-only` in `~/.agentkit`. Then it syncs the files.

- A file you did not edit is updated.
- A file you edited is kept. The new version is written next to it as `<file>.agentkit-new`. Compare the two and merge by hand.
- A file you deleted stays deleted across updates.
- Hook entries that agentkit marked are refreshed when their path changed.
- A file removed upstream is removed, if you did not edit it.
- `agentkit update --force` replaces your edited files, after a backup.
- `agentkit update --dry-run` shows what would happen.

If `git pull` fails (local commits or changes in `~/.agentkit`), fix the clone by hand: `cd ~/.agentkit && git status`.

### Auto-update

This section applies to Claude on macOS and Linux. Native Windows does not write or run this Bash hook.

```bash
agentkit auto-update on
agentkit auto-update off
agentkit auto-update status
```

`on` adds a SessionStart hook to `settings.json`. At session start, the hook checks if the last check is older than one day. If yes, it starts `agentkit update --quiet` in the background. The log is `~/.claude/agentkit/update.log`. When it grows over 256 KB, the hook keeps only the last 100 KB. The update is fast-forward only. The hook never blocks the session. If the last background update needs attention, the hook prints one line at the next session start.

To change the interval, set `AGENTKIT_UPDATE_INTERVAL` (seconds).

## Agent log

Automatic logging and the `agentkit log` and `feedback` commands in this section are POSIX features. Native Windows does not install the Bash integration.

The SubagentStop hook runs `hooks/agent-log.py check` when a subagent ends. It reads the transcript of the subagent. It never blocks the agent. It writes findings to `~/.claude/agent-log/issues.jsonl`. Set `AGENT_LOG_DIR` to use another folder.

Rules the hook checks:

| Rule | Severity | Meaning |
|---|---|---|
| `install-unapproved` | warn | The agent ran a package install, and the assignment did not list the package as approved. |
| `install-outside-list` | warn | The agent installed a package that is not in the approved list. |
| `install-restore` | info | The agent ran an install command with no package name (for example `npm install`). |
| `git-write` | warn | The agent ran `git commit`, `push`, `clean`, `reset --hard`, `stash` or `checkout --`. |
| `destructive` | warn | The agent ran `rm -rf`, `kill -9`, `pkill`, `killall`, `--force`, `prune` or `DROP TABLE`/`DROP DATABASE`. |
| `scope` | warn | The agent edited a file that the assignment did not name. |
| `secret-in-code` | warn | The agent wrote a secret-like value into a file. |
| `browser-not-stopped` | warn | The agent started the gstack browser and did not run its `stop` command. |
| `skill-missing` | warn | A `seo` agent measured a page without the `benchmark` skill. |
| `cso-before-audit` | warn | A `security` agent did not load `cso` as its first tool call. |
| `tool-error` | info | A tool call returned an error. |
| `report-incomplete` | info | The final report lacks "files changed" or a verification result (checked for worker agents). |
| `spawned-agent` | info | The agent started another agent. |

When an issue is new, the hook shows a short message in the session.

To review the log, type `/agent-report` in Claude Code. The skill shows open issues by agent and rule. It proposes diffs for the agent files. It edits nothing without your yes.

The same data is available from the CLI:

```bash
agentkit log report          # open issues
agentkit log report --all    # also resolved issues
agentkit log resolve ID...   # mark issues as resolved (12-hex ids from the report)
```

### Share your log with the maintainer

```bash
agentkit feedback
```

This builds an anonymized export and prints it. If the log has no open issues, nothing is sent. Else it saves the export to `~/.claude/agentkit/feedback-<timestamp>.json` and asks before it creates a GitHub issue in `IbrahimHosseini/agentkit` (label `agent-log`). Without `gh`, it prints the text so you can paste it into a new issue by hand.

`agentkit log export [--out FILE] [--all]` makes the same export without the issue.

What the export contains:

- agent name, rule name, severity
- counts, and the first and last date
- up to 3 short samples for each agent and rule (200 characters at most), scrubbed
- the agentkit version
- a random reporter id, made once and stored in `~/.claude/agent-log/reporter-id`

The scrub masks secrets, Bearer and Basic tokens, GitHub tokens, AWS keys and Slack tokens. It cuts URLs to the host. It replaces emails, IP addresses and your home folder. It shortens absolute paths to the last two parts.

Some rules share less than a command sample:

- `spawned-agent` keeps only the subagent type.
- `scope` keeps only the path.
- `secret-in-code` keeps only `path:line`.
- `tool-error` keeps only the count.
- Other rules keep the scrubbed command text. It can still contain project names and short paths (a path with 2 parts or fewer is kept, for example `~/a/b`).

The export never contains session ids, transcripts, paths to your session files, or your name. Task descriptions are dropped, but `review-fix` samples keep the supervisor's issue text, which can name the task.

Scrubbing is best effort. You see the export before it is sent. Read it first.

### For the maintainer

Save the export from each issue to a file. Then:

```bash
agentkit log merge issue1.json issue2.json
agentkit log merge issue1.json --include-local
```

`merge` counts reporters for each agent and rule. A rule with 2 or more reporters is a good reason to change an agent file. Bad files are skipped with a message.

## doctor

```bash
agentkit doctor
```

It checks installed target manifests, agent files, skills, the target CLI, and workflow blocks. For Codex it also checks the managed `config.toml` block. POSIX requirements use the shell requirements checker. Native Windows does not require the skipped POSIX integrations. Use `--target` to check one target. `FAIL` lines make the exit code 1. `warn` lines are advice.

## Uninstall

```bash
agentkit uninstall            # remove files, hooks and the CLAUDE.md block
agentkit uninstall --purge    # also remove backups, the CLI link and ~/.agentkit (see below)
agentkit uninstall --dry-run  # show only
```

It removes only files that you did not edit. It keeps edited files and tells you. It removes only hook entries that agentkit marked. It keeps symlinks.

Backups and the CLI launcher stay unless you use `--purge`. With `--purge`, agentkit removes the POSIX `~/.local/bin/agentkit` link only if it points into `AGENTKIT_HOME`. On native Windows, purging the default clone removes `%USERPROFILE%\.local\bin\agentkit.cmd` only when its bytes exactly match the generated launcher for that clone. Edited or foreign launchers stay unchanged. Launchers under linked directories also stay unchanged. The clone is removed only when `AGENTKIT_HOME` is the default user-home `.agentkit` Git clone. Any other `AGENTKIT_HOME` (for example a dev checkout) is kept. With `--project`, `--purge` removes only the project state. It does not remove gstack or the karpathy plugin. The command prints how to remove them. For gstack it names `~/.claude/skills/gstack` and the `_gstack_source` entries in `settings.json` (Claude), and `~/.codex/skills/gstack-*` (Codex). The clone in `~/gstack` is yours to delete.

## Troubleshooting

| Problem | Fix |
|---|---|
| `agentkit: command not found` | Add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile. Open a new shell. |
| `only one agentkit marker found` | Someone deleted one marker line in CLAUDE.md. Fix the file by hand: keep both `<!-- agentkit:start -->` and `<!-- agentkit:end -->`, or delete both. |
| `bun not found`, gstack skipped | Install bun from https://bun.sh. Then run the printed `git clone ... && cd ... && ./setup --host ...` command, or run `agentkit install` again. |
| gstack skipped without a message | You answered no, or there was no terminal. Use `--yes` or run the printed command. |
| An agent file shows `modified` in doctor | You edited it. That is fine. Update keeps your file and writes `.agentkit-new`. |
| `skills/NAME exists and is not managed by agentkit` | A skill with that name exists. Use `--force` to replace it (with a backup), or keep yours. |
| Duplicate hook runs | You used both install modes. Remove one: `agentkit uninstall`, or `/plugin uninstall agentkit@agentkit`. |
| `settings.json` not changed, "invalid JSON?" | Fix the JSON in `settings.json`. Run `agentkit install` again. |
| `Codex agent(s) ... not installed: ... exists and is not managed by agentkit` | A Codex agent file with that name exists. Use `--force` to replace it (with a backup), or keep yours. The agent is then not in `config.toml`. |
| `--project` fails with `--target codex` | `--project` is for Claude only. Remove `--project`, or use `--target claude`. |
| Install asks to install git, python3 or an agent CLI | A requirement is missing. Answer `y`, or install it yourself and run `agentkit install` again. A remote script is never run with `--yes`. |
| Update fails: not a git clone | `~/.agentkit` must be a git clone. Run the curl installer again. |

## Dependencies and credits

agentkit vendors two skills and installs two third-party components. `codex/karpathy-guidelines.md` is adapted from the karpathy plugin. See [THIRD_PARTY.md](THIRD_PARTY.md) for sources and licenses.

## License

MIT. See [LICENSE](LICENSE).
