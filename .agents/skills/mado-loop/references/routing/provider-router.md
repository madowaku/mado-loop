# Worker provider router

Read this reference only when MADO LOOP considers delegating a bounded reasoning or coding subtask to another model. Provider routing is an execution choice below domain/capability routing; it does not change the requested artifact, proof target, or acceptance contract. For parallel fan-out/fan-in execution, continue to [parallel worker swarm](worker-swarm.md).

## Purpose

MADO LOOP may use a configured worker model for parallelizable work such as repository reconnaissance, narrow code proposals, test generation, classification support, or bounded review. The orchestrator remains responsible for scope, integration, verification, and the final result.

A worker response is always an **untrusted proposal**, never proof. Validate worker-produced changes through the normal engine/tool and P0-P5 proof path before claiming completion.

## Provider roles

| Provider | Role | Configuration | Data policy |
| --- | --- | --- | --- |
| `openrouter` | Primary external worker hub | `OPENROUTER_API_KEY` plus `MADO_OPENROUTER_MODEL` (or `OPENROUTER_MODEL`) | Requests add `provider.data_collection=deny` and `provider.zdr=true` by default |
| `nvidia` | NVIDIA NIM hosted OpenAI-compatible worker lane | `NVIDIA_API_KEY` plus `MADO_NVIDIA_MODEL`; optional `MADO_NVIDIA_BASE_URL` | Public by default. Private requires `--allow-nvidia-private` or `MADO_ALLOW_NVIDIA_PRIVATE=1`. Secret is forbidden |
| `empero` | Opportunistic free worker for public material | Explicit `--allow-logged-free` or `MADO_ALLOW_LOGGED_FREE=1`; model defaults to the provider's `free` alias | Public-only. The service states that prompts and completions are logged |
| `local` | Non-network worker lane | `MADO_LOCAL_BASE_URL` plus `MADO_LOCAL_MODEL`; optional `MADO_LOCAL_API_KEY` | Required for `secret` sensitivity |
| `off` | Disable worker delegation | none | No model call |

Do not hard-code a specific frontier or open model into MADO LOOP policy. Provider and model are separate. Model IDs are configuration because hosted catalogs and aliases change faster than the orchestration contract. NVIDIA NIM is therefore represented as a provider capability, not as a frozen list of Kimi, DeepSeek, Nemotron, or other model IDs.

## Sensitivity contract

Classify the payload before selecting a worker:

- `public`: material already public or intentionally publishable. OpenRouter, configured NVIDIA NIM, local, or explicitly allowed Empero free may be used.
- `private`: ordinary unpublished project material that contains no secrets. OpenRouter is permitted with MADO LOOP's strict provider privacy request; local is permitted. NVIDIA NIM is permitted only after an explicit private-data opt-in. Empero free is forbidden.
- `secret`: credentials, tokens, private keys, personal data, customer-confidential material, or other content that must not leave the machine. Only a configured local provider is permitted.

If sensitivity is uncertain, use `private`. If a payload contains credentials or secret-bearing command output, redact it or use `secret`; never encode secrets into AI Creole.

The NVIDIA private opt-in exists because an API being convenient, free-to-prototype, or OpenAI-compatible is not itself a zero-retention guarantee. MADO LOOP does not infer a stronger privacy contract than the configured route explicitly provides.

## Auto selection and fallback candidates

`auto` never invents credentials and never weakens the sensitivity policy. `provider_router.py plan` reports the selected provider plus `fallback_candidates`, a deterministic list of already-permitted routes. The list is advisory routing state; `call` still performs one provider call and never silently retries a route with different privacy or cost semantics.

Default candidate order:

1. `secret`: local only.
2. `private`: OpenRouter, then explicitly allowed NVIDIA NIM, then local.
3. `public`: OpenRouter, then local, then NVIDIA NIM, then explicitly allowed Empero.
4. `public --prefer-free`: configured NVIDIA NIM, then explicitly allowed Empero, then the normal public order with duplicates removed.

This separation lets higher-level orchestration implement bounded fallback without baking provider-specific model catalogs into the core. A future Cerebras, Groq, or other OpenAI-compatible adapter can join the same contract instead of creating a parallel routing system.

## Commands

Inspect selection and permitted fallback order without a network request:

```powershell
python .agents/skills/mado-loop/scripts/provider_router.py plan --sensitivity private
```

Use OpenRouter explicitly:

```powershell
$env:OPENROUTER_API_KEY = "..."
$env:MADO_OPENROUTER_MODEL = "<provider/model>"
python .agents/skills/mado-loop/scripts/provider_router.py call --provider openrouter --sensitivity private --prompt-file .mado/worker-task.txt
```

Use NVIDIA NIM for public work:

```powershell
$env:NVIDIA_API_KEY = "nvapi-..."
$env:MADO_NVIDIA_MODEL = "<provider/model>"
python .agents/skills/mado-loop/scripts/provider_router.py call --provider nvidia --sensitivity public --prompt-file .mado/public-worker-task.txt
```

Explicitly permit a private NVIDIA NIM task:

```powershell
$env:NVIDIA_API_KEY = "nvapi-..."
$env:MADO_NVIDIA_MODEL = "<provider/model>"
python .agents/skills/mado-loop/scripts/provider_router.py call --provider nvidia --sensitivity private --allow-nvidia-private --prompt-file .mado/private-worker-task.txt
```

Use the logged free lane for intentionally public work:

```powershell
python .agents/skills/mado-loop/scripts/provider_router.py call --provider empero --sensitivity public --allow-logged-free --prompt-file .mado/public-worker-task.txt
```

Use a local OpenAI-compatible server for secret work:

```powershell
$env:MADO_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"
$env:MADO_LOCAL_MODEL = "<local-model>"
python .agents/skills/mado-loop/scripts/provider_router.py call --provider local --sensitivity secret --prompt-file .mado/secret-worker-task.txt
```

Prefer `--prompt-file` or `--stdin` over shell arguments for substantial prompts. Never commit API keys or secret-bearing worker payloads.

## OpenAI-compatible adapter boundary

The first-party router intentionally uses the common `/chat/completions` transport with stdlib HTTP. It does not install provider SDKs. Provider adapters own only configuration, headers, provider-specific request fields, and data-policy gates.

NVIDIA's hosted NIM endpoint defaults to `https://integrate.api.nvidia.com/v1`, so the router targets the same `.../chat/completions` shape already used by the generic transport. `MADO_NVIDIA_BASE_URL` exists for controlled endpoint substitution, including compatible enterprise/self-hosted arrangements, without changing the provider contract.

Provider-specific parameters that are not portable across models, such as reasoning budgets or proprietary sampling controls, must not be injected globally. Add them only behind a bounded capability/model-aware extension with tests.

## Single worker or swarm

Use one worker when one bounded proposal or review is enough. Use [parallel worker swarm](worker-swarm.md) when independent architecture, implementation, verification, and review perspectives are likely to expose different failure modes.

The swarm reuses this provider selection contract. One invocation selects one permitted provider/model configuration and applies the same sensitivity boundary to all scheduled workers. Parallelism must not become a privacy downgrade. Do not route private primary workers to one provider and a public/logged reviewer merely to save cost.

## Delegation contract

Delegate only a bounded subtask with explicit inputs and expected output. Good worker tasks have a small blast radius and an independently checkable result. Examples include:

- summarize the responsibility of a known file set;
- propose a patch for one named defect;
- generate tests for an already specified behavior;
- review a diff for a named invariant;
- turn an AI Creole handoff into a bounded next action.

Do not delegate final acceptance, release readiness, project-wide destructive edits, or authority decisions. The orchestrator must inspect the returned proposal, apply only the useful portion, and run the normal proof ladder.

For parallel work, keep primary workers read-only proposal generators and perform cross-worker comparison in the reviewer/orchestrator fan-in. Do not allow multiple model workers to mutate the same files concurrently.

## Failure and fallback

A worker provider is optional unless the user explicitly makes it required. Provider outage, quota exhaustion, unsupported parameters, missing credentials, catalog removal, or privacy-policy mismatch produces an optional `SKIPPED`/warning and the orchestrator continues locally when a valid route remains.

A fallback candidate is eligible only if it was already legal for the same sensitivity. Do not silently fall from OpenRouter/private to NVIDIA/private unless the NVIDIA private opt-in is active. Do not silently fall from any private route to Empero/public. Do not silently change a requested model. A fallback that changes data handling, cost, model identity, or acceptance semantics requires an explicit route decision.
