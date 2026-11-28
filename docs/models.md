# Models and effort

Interactive `agentkit models` first offers Claude, Codex, both, or cancel when both targets are installed. A single installed target is selected automatically. `--target` selects it explicitly. Selection happens before reading target preferences or fetching catalogs. During installation, the model picker offers the agents selected for each target. Choosing a model target leaves the installation selection in effect.

After target selection, the picker displays each agent's model and effort and asks:

```text
Do you want to change these models or effort levels? [y/N]
```

Enter or `n` keeps the displayed settings. With `y`, select a numbered model for each agent, then a supported effort level. Enter keeps the current value when it is compatible; a different model may require a new default effort. `m` accepts a model ID manually, and `r` restores the agentkit default. Unknown manual models inherit effort from the target CLI. Review the final table and confirm before any model choices are saved. Declining or ending input discards the selections; Ctrl-C stops the command. Prerequisites already installed remain installed.

## OpenAI models for Claude agents

The Claude picker also lists OpenAI models (from Codex when installed, otherwise the bundled mapping). Claude Code cannot run an OpenAI model itself, so a Claude agent set to one stays a Claude agent (`model: sonnet`) and becomes a relay: agentkit adds a marker-managed block at the top of the installed agent that tells it to pass the task and its worker instructions to `codex exec -m <model> -c model_reasoning_effort=<effort>` and return the result unchanged. The sandbox is `workspace-write` for agents with `Edit` or `Write`, otherwise `read-only` (`security` is always read-only). `Bash` is added to the agent's tools when missing and removed again when you switch back to a Claude model.

Requirements: the Codex CLI on `PATH` and `codex login`. If Codex is missing or fails, the relay reports the error and does no work. The Codex run is a separate process, so the OpenAI model does not see Claude Code's own skills or MCP tools, and its usage counts against your Codex or OpenAI limits. Choose `r` to restore the agentkit default.

## Claude models for Codex agents

The Codex picker also lists Claude models (`opus`, `sonnet`, `haiku` from the bundled list, unverified; use `m` for another ID). A Codex agent set to one keeps its own Codex model as the host and becomes a relay: agentkit adds a marker-managed block at the start of its `developer_instructions` that tells it to pass the task and its worker instructions to `claude -p --model <model> [--effort <effort>]` and return the result unchanged. Agents with `Edit` or `Write` run Claude with `--permission-mode acceptEdits --allowedTools Bash`; the others (and `security`) run with `--permission-mode plan`.

The default Codex sandbox blocks the network and writes to `~/.claude`, which `claude` needs. A relay agent therefore gets `sandbox_mode = "danger-full-access"`. Its limits come from Claude's permission mode, not from the operating system. Other agents keep their sandbox. Switching back to a Codex model restores the host model, effort and sandbox.

Requirements: the Claude Code CLI on `PATH` and a logged-in session. If it is missing or fails, the relay reports the error and does no work. The Claude run is a separate process, so it does not see Codex skills or MCP tools, and its usage counts against your Claude limits. Start a new Codex session after changing agent files.

## Set one agent

Use `--agent` to change one installed agent. For example, this opens the Codex picker for `backend`:

```bash
agentkit models --target codex --agent backend
```

Choose a model and effort, review the displayed settings, then confirm to save.

Change choices later, without reinstalling skills, hooks or workflow instructions:

```bash
agentkit models
agentkit models --target codex --agent backend
agentkit models --target claude
agentkit models --target both
agentkit models --project /path/to/project
agentkit models --dry-run
```

`--agent` limits the picker to one agent. `--project` is Claude-only. Without a terminal, or with `--yes`, settings are displayed and kept; no catalog request or selection prompt runs. `--dry-run` previews selections without saving. `--quiet` still displays the interactive choices and confirmation. Start a new Claude Code or Codex session after changing agent files.

Codex queries its current provider through the official app-server `model/list` interface. Visible models appear first; `a` refetches all models and labels hidden entries. Claude uses the official Claude Agent SDK's initialization and `supportedModels()` metadata with the installed Claude Code CLI and existing login. Discovery has a ten-second deadline, sends no user messages and requests no inference. Model names, IDs and advertised effort levels appear together; missing capabilities inherit CLI effort. Safe new effort names from live catalogs survive saving and updates.

Live Claude discovery requires an existing Node.js (18.14+) and npm. Agentkit never installs Node. On the first interactive request, npm installs the pinned SDK and locked dependencies only in the selected target's `agentkit/runtime/claude-catalog`, with install scripts and optional binaries disabled. The existing CLI supplies the executable; nothing is installed globally. `--dry-run` uses the local Claude fallback and never sets up that runtime. No runtime setup runs with `--yes` or without a terminal. The helper disables session persistence, user/project settings, ordinary hooks, MCP servers, tools and cloud skill/plugin syncing while preserving login. Organization-managed policy and hooks can still apply.

Failures report a safe reason and next action, then use a clearly labeled local, unverified fallback. Codex fallback efforts come only from the bundled mapping; Claude fallback aliases are `opus`, `sonnet` and `haiku`. Both pickers support manually entered IDs. A listed model is **not a guarantee of access**: login, an eligible subscription or API credits may be required, depending on the provider. This command does not switch providers, sign in or purchase access.

Choices are saved per target in `agentkit/model-overrides.json` (under `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, or the project's `.claude` directory). That file stores model IDs and effort, never credentials. Updates apply saved choices over the latest agent instructions. Restore-default removes an agent's override so future upstream defaults apply again. Ordinary uninstall retains these preferences with other state; `uninstall --purge` removes them.

The picker skips unmanaged, manually edited, missing installed, or linked agent files, even with an install's `--force`; it does not save an unapplied choice. The normal installer retains its existing `--force` behavior. Only the selected target preferences, manifest and agent files are read and changed after selection. Selected files, preferences and manifest hashes are validated and backed up before saving. A failed save attempts to restore the entire selection, including changes across both targets, and reports backup paths if recovery fails.

Catalog tests use fake CLIs and a fake SDK. Real authenticated Claude/Codex catalog discovery, native Windows helper execution and WSL2 remain unverified.

## Related guides

- [Install](install.md)
- [Workflow and agent catalog](workflow.md)
