# agentkit

agentkit is a shared pack of Claude Code agents for a team. It has 16 agents, three skills, a CLAUDE.md workflow block and a hook that logs agent mistakes. One command installs it. One command updates it.

The agents follow one workflow. A supervisor plans the work. You approve the plan. Workers do the parts. The supervisor reviews the result. The hook records when an agent breaks a rule, so the team can improve the agent files.

## Requirements

- macOS or Linux
- git
- python3 3.9 or newer
- Claude Code CLI (`claude`)
- Optional: `gh` (used by `agentkit feedback`), `bun` (needed to install gstack)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash
```

The script clones the repo to `~/.agentkit`. It links the CLI to `~/.local/bin/agentkit`. Then it runs `agentkit install`. Each change to your settings asks for a yes first.

Pass flags after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash -s -- --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Show what would change. Write nothing. |
| `--yes`, `-y` | Answer yes to every question. |
| `--project DIR` | Install into `DIR/.claude` and `DIR/CLAUDE.md`, not into `~/.claude`. |
| `--skip STEP` | Skip a step. STEP is `gstack`, `karpathy`, `claude-md`, `hooks` or `skills`. Repeat the flag to skip more. |
| `--force` | Replace files that already exist and that agentkit did not install. A backup is made first. |
| `--quiet` | Print less. |

### What install changes

| Item | Where | Step name |
|---|---|---|
| 16 agent files | `~/.claude/agents/` | (always) |
| Skills `agent-report`, `security-audit`, `write-swift` | `~/.claude/skills/` | `skills` |
| Workflow block between `<!-- agentkit:start -->` and `<!-- agentkit:end -->` | `~/.claude/CLAUDE.md` | `claude-md` |
| SubagentStop hook (agent log) | `~/.claude/settings.json` | `hooks` |
| gstack (git clone, then its `./setup`) | `~/.claude/skills/gstack` | `gstack` |
| karpathy-guidelines plugin | through `claude plugin install` | `karpathy` |

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

```bash
agentkit auto-update on
agentkit auto-update off
agentkit auto-update status
```

`on` adds a SessionStart hook to `settings.json`. At session start, the hook checks if the last check is older than one day. If yes, it starts `agentkit update --quiet` in the background. The log is `~/.claude/agentkit/update.log`. When it grows over 256 KB, the hook keeps only the last 100 KB. The update is fast-forward only. The hook never blocks the session. If the last background update needs attention, the hook prints one line at the next session start.

To change the interval, set `AGENTKIT_UPDATE_INTERVAL` (seconds).

## Agent log

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

It checks python3, git, `claude`, `gh`, PATH, the clone, the installed version, each agent and skill, gstack, the karpathy plugin, both hooks and the CLAUDE.md block. `FAIL` lines make the exit code 1. `warn` lines are advice.

## Uninstall

```bash
agentkit uninstall            # remove files, hooks and the CLAUDE.md block
agentkit uninstall --purge    # also remove backups, the CLI link and ~/.agentkit (see below)
agentkit uninstall --dry-run  # show only
```

It removes only files that you did not edit. It keeps edited files and tells you. It removes only hook entries that agentkit marked. It keeps symlinks.

Backups stay unless you use `--purge`. With `--purge`, agentkit removes the `~/.local/bin/agentkit` link only if it points into `AGENTKIT_HOME`. It removes `~/.agentkit` only if that is the default git clone. Any other `AGENTKIT_HOME` (for example a dev checkout) is kept. With `--project`, `--purge` removes only the project state. It does not remove gstack or the karpathy plugin. The command prints how to remove them.

## Troubleshooting

| Problem | Fix |
|---|---|
| `agentkit: command not found` | Add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile. Open a new shell. |
| `only one agentkit marker found` | Someone deleted one marker line in CLAUDE.md. Fix the file by hand: keep both `<!-- agentkit:start -->` and `<!-- agentkit:end -->`, or delete both. |
| `bun not found`, gstack skipped | Install bun from https://bun.sh. Then run the printed `git clone ... && ./setup` command, or run `agentkit install` again. |
| gstack skipped without a message | You answered no, or there was no terminal. Use `--yes` or run the printed command. |
| An agent file shows `modified` in doctor | You edited it. That is fine. Update keeps your file and writes `.agentkit-new`. |
| `skills/NAME exists and is not managed by agentkit` | A skill with that name exists. Use `--force` to replace it (with a backup), or keep yours. |
| Duplicate hook runs | You used both install modes. Remove one: `agentkit uninstall`, or `/plugin uninstall agentkit@agentkit`. |
| `settings.json` not changed, "invalid JSON?" | Fix the JSON in `settings.json`. Run `agentkit install` again. |
| Update fails: not a git clone | `~/.agentkit` must be a git clone. Run the curl installer again. |

## Dependencies and credits

agentkit vendors two skills and installs two third-party components. See [THIRD_PARTY.md](THIRD_PARTY.md) for sources and licenses.

## License

MIT. See [LICENSE](LICENSE).
