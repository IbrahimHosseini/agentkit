# Maintenance

## Updating

```bash
agentkit update
```

This fetches and fast-forwards `main` in `~/.agentkit`, then applies the update with the fetched version of Agentkit.

- A file you did not edit is updated.
- A file you edited is kept. The new version is written next to it as `<file>.agentkit-new`. Compare the two and merge by hand.
- A file you deleted stays deleted across updates.
- Hook entries that agentkit marked are refreshed when their path changed.
- The managed workflow block in `CLAUDE.md` or `AGENTS.md` is refreshed for each updated provider. Personal content outside the block is preserved. To add a missing block, confirm the prompt or pass `--yes`.
- A file removed upstream is removed, if you did not edit it.
- Agents you excluded stay excluded. If an update makes an excluded agent a dependency of an enabled role, agentkit installs it and explains which role needs it.
- `agentkit update --force` replaces your edited files, after a backup.
- `agentkit update --dry-run` shows what would happen.

If `git pull` fails (local commits or changes in `~/.agentkit`), fix the clone by hand: `cd ~/.agentkit && git status`.

### Auto-update

Auto-update is enabled by default for user-level Claude installations on macOS and Linux. Install shows the SessionStart hook and asks before adding it. `--yes` accepts the prompt. `--skip hooks` skips both Claude hooks, and `--dry-run` writes nothing.

Project installations with `--project` do not add the auto-update hook by default. The hook updates user-level installations. Codex and native Windows do not install this hook.

```bash
agentkit auto-update on
agentkit auto-update off
agentkit auto-update status
```

In 0.3.1 and later, `off` removes the managed hook and saves your choice. Updates and repeated installations keep auto-update off until you enable it with `on`.

Existing installations keep their current hook state during `agentkit update`. An older installation with no auto-update hook stays off. Run `agentkit auto-update on` to enable it. A repeated user-level `install` offers the hook unless you saved an `off` choice with 0.3.1 or later.

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

The export never contains session ids, transcripts, paths to your session files, or your name. Task descriptions are dropped, but `review-fix` samples keep the reviewer's issue text, which can name the task.

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

## Development checks

From the repository root, run these checks on macOS or Linux:

```bash
bash scripts/validate.sh
bash tests/run.sh
python3 -I -m unittest discover -s tests -p "test_*.py"
```

The tests use temporary homes and fake target CLIs. They do not need a package install. See [../CONTRIBUTING.md](../CONTRIBUTING.md#native-windows-checks) for native Windows checks.

## Troubleshooting

| Problem | Fix |
|---|---|
| `agentkit: command not found` | Add `export PATH="$HOME/.local/bin:$PATH"` to your shell profile. Open a new shell. |
| `only one agentkit marker found` | Someone deleted one marker line in CLAUDE.md. Fix the file by hand: keep both `<!-- agentkit:start -->` and `<!-- agentkit:end -->`, or delete both. |
| Bun installation failed | Read the displayed error or log. Fix the reported problem, then run `agentkit install` again. Use `--skip gstack` to install without gstack. |
| Desktop app installed, CLI missing | Install the CLI named in the requirements report. A desktop app does not satisfy the CLI requirement. |
| Desktop installer opened, app still missing | Complete the official installer, then repeat the check. Check the error details for unsupported systems or architectures. |
| An installation step failed | Read the stage name, command output or log path, and suggested action. Fix the reported problem, then repeat the installation. |
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

agentkit vendors two skills and installs two third-party components. `codex/karpathy-guidelines.md` is adapted from the karpathy plugin. See [../THIRD_PARTY.md](../THIRD_PARTY.md) for sources and licenses.

## License

MIT. See [../LICENSE](../LICENSE).
