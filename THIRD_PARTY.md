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
| Claude Agent SDK (`@anthropic-ai/claude-agent-sdk` 0.3.327) | https://github.com/anthropics/claude-agent-sdk-typescript | See the SDK package's `README.md` and Anthropic Commercial Terms. | Optional live Claude model discovery; locked dependencies are installed in the selected target's `agentkit/runtime/claude-catalog`. SDK code and bundled CLI binaries are not copied into this repository. |

## Adapted (rewritten from upstream)

| Path | Source | License |
|---|---|---|
| `codex/karpathy-guidelines.md` | Adapted from https://github.com/forrestchang/andrej-karpathy-skills (`karpathy-guidelines`). Close paraphrase, written for Codex. | See source. I could not read the upstream LICENSE file. |

### Agency Agents role sources

The roles below draw on [Agency Agents](https://github.com/msitarzewski/agency-agents) and were rewritten for agentkit's role scopes, verification, and host workflow. Copyright (c) 2025 AgentLand Contributors. [Upstream MIT license](https://github.com/msitarzewski/agency-agents/blob/main/LICENSE).

| Upstream source | Agentkit role |
|---|---|
| [Software Architect](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-software-architect.md) | `architect` |
| [Payments & Billing Engineer](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-payments-billing-engineer.md) | `payments` |
| [Workflow Optimizer](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-workflow-optimizer.md) | `workflow-optimizer` |
| [Product Manager](https://github.com/msitarzewski/agency-agents/blob/main/product/product-manager.md) | `product` |
| [UX Researcher](https://github.com/msitarzewski/agency-agents/blob/main/design/design-ux-researcher.md) | `design-ux-research` |
| [UX Architect](https://github.com/msitarzewski/agency-agents/blob/main/design/design-ux-architect.md) | `design-ux-architecture` |
| [AEO Foundations Architect](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-aeo-foundations.md) | `seo-aeo-foundations` |
| [Agentic Search Optimizer](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-agentic-search-optimizer.md) | `seo-agentic-search` |
| [AI Citation Strategist](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-ai-citation-strategist.md) | `seo-ai-citations` |
| [App Store Optimizer](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-app-store-optimizer.md) | `marketing-aso` |
| [Developer Community Builder](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-developer-community-builder.md) | `marketing-dev-community` |
| [Email Marketing Strategist](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-email-strategist.md) | `marketing-email` |
| [Instagram Curator](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-instagram-curator.md) | `marketing-instagram` |
| [LinkedIn Content Creator](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-linkedin-content-creator.md) | `marketing-linkedin` |
| [Multi-Platform Publisher](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-multi-platform-publisher.md) | `marketing-publishing` |
| [Reddit Community Builder](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-reddit-community-builder.md) | `marketing-reddit` |
| [TikTok Strategist](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-tiktok-strategist.md) | `marketing-tiktok` |
| [Twitter Engager](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-twitter-engager.md) | `marketing-x-engagement` |
| [X/Twitter Intelligence Analyst](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-x-twitter-intelligence-analyst.md) | `marketing-x-research` |
| [Trend Researcher](https://github.com/msitarzewski/agency-agents/blob/main/product/product-trend-researcher.md) | `product-trends` |
| [Behavioral Nudge Engine](https://github.com/msitarzewski/agency-agents/blob/main/product/product-behavioral-nudge-engine.md) | `product-behavior` |
| [Experiment Tracker](https://github.com/msitarzewski/agency-agents/blob/main/project-management/project-management-experiment-tracker.md) | `product-experiments` |
| [AI-Generated Code Security Auditor](https://github.com/msitarzewski/agency-agents/blob/main/security/security-ai-generated-code-auditor.md) | `security-ai-code` |
| [Security Architect](https://github.com/msitarzewski/agency-agents/blob/main/security/security-architect.md) | `security-architecture` |
| [Compliance Auditor](https://github.com/msitarzewski/agency-agents/blob/main/security/security-compliance-auditor.md) | `security-compliance` |
| [Senior SecOps Engineer](https://github.com/msitarzewski/agency-agents/blob/main/security/security-senior-secops.md) | `security-appsec` |
| [Secrets & Credential Hygiene Engineer](https://github.com/msitarzewski/agency-agents/blob/main/security/security-secrets-credential-engineer.md) | `security-credentials` |
| [Threat Intelligence Analyst](https://github.com/msitarzewski/agency-agents/blob/main/security/security-threat-intelligence-analyst.md) | `security-threat-intel` |
| [Threat Detection Engineer](https://github.com/msitarzewski/agency-agents/blob/main/security/security-threat-detection-engineer.md) | `security-detection` |
| [Accessibility Auditor](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-accessibility-auditor.md) | `test-accessibility` |
| [API Tester](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-api-tester.md) | `test-api` |
| [Performance Benchmarker](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-performance-benchmarker.md) | `test-performance` |
| [Test Automation Engineer](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-test-automation-engineer.md) | `test-e2e` |
| [Technical Writer](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-technical-writer.md) | `docs` |
| [Senior Developer](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-senior-developer.md) | `backend`, `frontend` |
| [Content Creator](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-content-creator.md) | `writing`, `marketing` |
| [SEO Specialist](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-seo-specialist.md) | `seo` |
| [Social Media Strategist](https://github.com/msitarzewski/agency-agents/blob/main/marketing/marketing-social-media-strategist.md) | `marketing` |
| [Senior Project Manager](https://github.com/msitarzewski/agency-agents/blob/main/project-management/project-manager-senior.md) | `planner` |
| [Research Synthesist](https://github.com/msitarzewski/agency-agents/blob/main/research/research-synthesist.md) | `researcher` |
