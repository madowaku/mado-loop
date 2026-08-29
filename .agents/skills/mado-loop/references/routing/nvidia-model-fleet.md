# NVIDIA model fleet

Use this reference when MADO LOOP intentionally routes an adaptive worker swarm through NVIDIA Build hosted NIM endpoints. The fleet is an optional, versioned routing recipe above the provider adapter. It does not change sensitivity, mutation authority, or P0-P5 proof authority.

## Profile

Current profile: `nvidia-balanced-2026-08`

| Adaptive role/tier | Model | Intended use |
| --- | --- | --- |
| `reasoning` | `moonshotai/kimi-k3` | architecture, long-horizon reasoning, complex agentic planning |
| `specialist` | `moonshotai/kimi-k3` | gameplay/UI/asset specialist proposals; multimodal-capable model family |
| `coding` | `deepseek-ai/deepseek-v4-pro-0813` | implementation proposals and code-heavy reasoning |
| `verification` | `nvidia/nemotron-3.5-lightning-30b-a3b` | fast test planning and routine verification |
| `recon` override | `nvidia/nemotron-3.5-lightning-30b-a3b` | fast bounded reconnaissance |
| `reviewer` override | `nvidia/nemotron-3-ultra-550b-a55b` | deep adversarial fan-in review |
| `release_auditor` override | `nvidia/nemotron-3-ultra-550b-a55b` | high-complexity release and proof-gap audit |

The model IDs are deliberately isolated in `scripts/nvidia_fleet.py`. NVIDIA Build catalogs can change faster than MADO LOOP's orchestration contract, so a model replacement should update the profile and tests rather than hard-code a model throughout the router.

## Why these lanes

- Kimi K3 is the broad architect/specialist lane because NVIDIA Build describes it for long-horizon software engineering, agentic knowledge work, multimodal understanding, reasoning, and tool use.
- DeepSeek V4 Pro 0813 is the coding lane because NVIDIA Build describes it for text generation, reasoning, coding, and agentic tool-use workflows with a 1M-token context.
- Nemotron 3.5 Lightning is the fast lane because NVIDIA Build positions it as a fast 30B A3B model for specialized agentic tasks.
- Nemotron 3 Ultra is reserved for reviewer/release-audit work because NVIDIA Build positions it for frontier reasoning, complex agentic workflows, long-context analysis, tool use, and high-accuracy reasoning.

These descriptions are selection rationale, not completion evidence. Worker output remains an untrusted proposal.

## Request Profile Adapter

Fleet execution goes through `scripts/nvidia_request_profiles.py` (`nvidia-request-profiles/v1`). The adapter selects model- and workload-aware request controls without putting model-specific branches into `provider_router.py` or `adaptive_swarm.py`.

| Workload | Request profile | Main controls |
| --- | --- | --- |
| Kimi K3 architect | `kimi-k3-architect-max` | `temperature=1.0`, `reasoning_effort=max` |
| Kimi K3 specialist | `kimi-k3-specialist-high` | `temperature=1.0`, `reasoning_effort=high` |
| DeepSeek V4 Pro implementer | `deepseek-v4-pro-coding-max` | `temperature=1.0`, `reasoning_effort=max` |
| Lightning recon | `nemotron-lightning-recon-fast` | `temperature=1.0`, bounded reasoning budget |
| Lightning verification | `nemotron-lightning-verification` | `temperature=1.0`, larger bounded reasoning budget |
| Ultra reviewer | `nemotron-ultra-review-high` | `temperature=1.0`, `reasoning_effort=high`, bounded reasoning budget |
| Ultra release audit | `nemotron-ultra-release-high` | `temperature=1.0`, `reasoning_effort=high`, bounded reasoning budget |

The fixed API capabilities and limits come from the current NVIDIA NIM API contract. The workload-specific reasoning-budget fractions are MADO LOOP tuning policy, not NVIDIA-published recommendations. Budgets are capped and never consume more than half of the requested completion ceiling, preserving room for the final answer. If the caller explicitly sets `temperature`, that explicit value wins as long as it is valid for the NVIDIA endpoint.

The adapter also clamps `max_tokens` to the current model endpoint maximum to avoid preventable 422 responses. Unknown future NVIDIA models fall back to the generic OpenAI-compatible request without invented reasoning fields.

## Data boundary

The wrapper defaults to `public` sensitivity.

- `public`: hosted NVIDIA fleet is permitted when `NVIDIA_API_KEY` or `MADO_NVIDIA_API_KEY` is configured.
- `private`: requires explicit `--allow-nvidia-private` or the existing `MADO_ALLOW_NVIDIA_PRIVATE=1` opt-in.
- `secret`: hosted NVIDIA is forbidden. Use a configured local provider instead.

Do not pass credentials, private keys, customer-confidential data, or secret-bearing logs through the hosted fleet.

## Commands

Show the profile without a model call:

```powershell
python .agents/skills/mado-loop/scripts/nvidia_fleet.py profile
```

Plan a public adaptive swarm without model calls:

```powershell
$env:NVIDIA_API_KEY = "..."
python .agents/skills/mado-loop/scripts/nvidia_fleet.py plan `
  --sensitivity public `
  --task "HUD UIを改善して実装と検証まで考えて"
```

Run the fleet:

```powershell
python .agents/skills/mado-loop/scripts/nvidia_fleet.py run `
  --sensitivity public `
  --task-file .mado/swarm-task.txt `
  --context-file .mado/swarm-context.txt `
  --output .mado/nvidia-swarm-result.json
```

The fleet runtime defaults to an 8192-token completion ceiling. Per-model endpoint caps and workload reasoning budgets are applied below that ceiling. Override `--max-tokens` or `--temperature` only when the task needs it; explicit values remain bounded by the provider API contract.

For intentionally private unpublished project material, opt in explicitly:

```powershell
python .agents/skills/mado-loop/scripts/nvidia_fleet.py plan `
  --sensitivity private `
  --allow-nvidia-private `
  --task-file .mado/private-worker-task.txt
```

Prefer `--task-file` and `--context-file` for substantial inputs. Never commit the NVIDIA API key.

## Update policy

Before changing the fleet or request profiles:

1. Confirm the replacement model and request parameters are currently available on the NVIDIA hosted endpoint.
2. Preserve the role intent rather than chasing benchmark rank alone.
3. Update `PROFILE_NAME` when the model composition materially changes; update the request-adapter version when its behavior contract changes materially.
4. Update unit tests for deterministic role/model routing and request parameter construction.
5. Keep NVIDIA-published API limits distinct from MADO LOOP tuning choices.
6. Do not weaken public/private/secret boundaries to keep a model available.
7. Treat deprecation, quota failure, or a rejected parameter as availability/configuration evidence, never as permission to silently route secret data externally.
