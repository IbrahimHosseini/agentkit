# Third-party components

## Vendored (copied into this repository)

| Path | Source | License |
|---|---|---|
| `skills/write-swift/` | https://github.com/emilkowalski/skills (`skills/write-swift`) | MIT, Copyright (c) 2026 Emil Kowalski. See `skills/write-swift/LICENSE`. |
| `skills/security-audit/` | https://github.com/cloudflare/security-audit-skill (`skills/security-audit`) | MIT, Copyright (c) 2025-2026 Cloudflare, Inc. See `skills/security-audit/LICENSE`. |

The vendored files are not changed. To refresh them, copy the folder again from the source and record the commit in `CHANGELOG.md`.

## Installed by the installer (not copied)

| Component | Source | License | Used by |
|---|---|---|---|
| gstack (`browse`, `benchmark`, `careful`, `cso`, ...) | https://github.com/garrytan/gstack | MIT | frontend, seo, devops, database, security. On Codex, agentkit runs its `./setup --host codex` (experimental). Codex-only installs clone it to `~/gstack`. |
| andrej-karpathy-skills (`karpathy-guidelines`) | https://github.com/forrestchang/andrej-karpathy-skills | see source | most agents |

## Adapted (rewritten from upstream)

| Path | Source | License |
|---|---|---|
| `codex/karpathy-guidelines.md` | Adapted from https://github.com/forrestchang/andrej-karpathy-skills (`karpathy-guidelines`). Close paraphrase, written for Codex. | See source. I could not read the upstream LICENSE file. |
