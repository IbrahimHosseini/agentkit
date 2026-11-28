# agentkit

<p align="center">
  <img src="assets/agentkit-icon.png" alt="agentkit cat" width="96" height="96">
</p>

<p align="center">
  <a href="https://github.com/IbrahimHosseini/agentkit/actions/workflows/ci.yml"><img src="https://github.com/IbrahimHosseini/agentkit/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/IbrahimHosseini/agentkit/releases/latest"><img src="https://img.shields.io/github/v/release/IbrahimHosseini/agentkit" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/IbrahimHosseini/agentkit" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey" alt="Platforms">
</p>

agentkit installs a shared team of agents for Claude Code and Codex.

- **Manage token budgets:** Set a model and reasoning effort for each agent. Use a lighter model or lower effort on routine work to manage its token budget.
- **Use both model providers:** Run OpenAI models in Claude Code and Claude models in Codex through the other CLI installed on your PATH and signed in. See the [model guide](docs/models.md) for relay behavior, provider usage, tools, context, and sandbox details.
- **Run approved work in parallel:** The workflow plans multi-step work, runs independent parts at the same time, assigns one owner to each file, and reviews the result. See [workflow and agents](docs/workflow.md).

## Install

On macOS or Linux, install with:

```bash
curl -fsSL https://raw.githubusercontent.com/IbrahimHosseini/agentkit/main/install.sh | bash
```

Requirements, install options, and Codex setup are in the [install guide](docs/install.md).

### Native Windows

Use the [native Windows install steps](docs/install.md#native-windows).

## First use

For example, ask the installed researcher agent to inspect a project:

```bash
claude --agent researcher "Explain this project. Cite files. Do not edit."
```

The CLI must be installed and signed in. See the [model guide](docs/models.md) to set a model and effort for an agent.

## Guides

- [Install and platform setup](docs/install.md)
- [Models and reasoning effort](docs/models.md)
- [Workflow and agent catalog](docs/workflow.md)
- [Updates, health checks, and troubleshooting](docs/maintenance.md)
- [Contributing](CONTRIBUTING.md)
- [Credits](THIRD_PARTY.md)
- [License](LICENSE)
