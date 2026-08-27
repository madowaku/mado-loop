# Worker provider router

Read this reference only when MADO LOOP considers delegating a bounded reasoning or coding subtask to another model. Provider routing is an execution choice below domain/capability routing; it does not change the requested artifact, proof target, or acceptance contract. For parallel fan-out/fan-in execution, continue to [parallel worker swarm](worker-swarm.md).

## Purpose

MADO LOOP may use a configured worker model for parallelizable work such as repository reconnaissance, narrow code proposals, test generation, classification support, or bounded review. The orchestrator remains responsible for scope, integration, verification, and the final result.

A worker response is always an **untrusted proposal**, never proof. Validate worker-produced changes through the normal engine/tool and P0-P5 proof path before claiming completion.

## Provider roles

| Provider | Role | Configuration | Data policy |
| --- | --- | --- | --- |
| `openrouter` | Primary external worker hub | `OPENROUTER_API_KEY` plus `MADO_OPENROUTER_MODEL` (or `OPENROUTER_MODEL`) | Requests add `provider.data_collection=deny` and `provider.zdr=true` by default |
| `empero` | Opportunistic free worker for public material | Explicit `--allow-logged-free` or `MADO_ALLOW_LOGGED_FREE=1`; model defaults to the provider's `free` alias | Public-only. The service states that prompts and completions are logged |
| `local` | Non-network worker lane | `MADO_LOCAL_BASE_URL` plus `MADO_LOCAL_MODEL`; optional `MADO_LOCAL_API_KEY` | Required for `secret` sensitivity |
| `off` | Disable worker delegation | none | No model call |

Do not hard-code a specific frontier or open model into MADO LOOP policy. Provider and model are separate. Model IDs are configuration because catalogs and aliases change faster than the orchestration contract.

## Sensitivity contract

Classify the payload before selecting a worker:

- `public`: material already public or intentionally publishable. OpenRouter, local, or explicitly allowed Empero free may be used.
- `private`: ordinary unpublished project material that contains no secrets. OpenRouter is permitted only with MADO LOOP's strict provider privacy request; local is also permitted. Empero free is forbidden.
- `secret`: credentials, tokens, private keys, personal data, customer-confidential material, or other content that must not leave the machine. Only a configured local provider is permitted.

If sensitivity is uncertain, use `private`. If a payload contains credentials or secret-bearing command output, redact it or use `secret`; never encode secrets into AI Creole.

## Auto selection

`auto` never invents credentials and never weakens the sensitivity policy.

1. `secret`: local only.
2. `private`: OpenRouter when configured, otherwise local.
3. `public`: OpenRouter when configured, otherwise local, otherwise explicitly allowed Empero.
4. `public --prefer-free`: explicitly allowed Empero first, then the normal public order.

The free lane is intentionally opt-in because its logging policy differs from the normal worker route.

## Commands

Inspect selection without a network request:

```powershell
python .agents/skills/mado-loop/scripts/provider_router.py plan --sensitivity private
```

Use OpenRouter explicitly:

```powershell
$env:OPENROUTER_API_KEY = "..."
$env:MADO_OPENROUTER_MODEL = "<provider/model>"
python .agents/skills/mado-loop/scripts/provider_router.py call --provider openrouter --sensitivity private --prompt-file .mado/worker-task.txt
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

## Single worker or swarm

Use one worker when one bounded proposal or review is enough. Use [parallel worker swarm](worker-swarm.md) when independent architecture, implementation, verification, and review perspectives are likely to expose different failure modes.

The swarm reuses this provider selection contract. One invocation selects one permitted provider/model configuration and applies the same sensitivity boundary to all scheduled workers. Parallelism must not become a privacy downgrade. Do not route private primary workers to one provider and a logged reviewer to another merely to save cost.

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

A worker provider is optional unless the user explicitly makes it required. Provider outage, quota exhaustion, unsupported parameters, missing credentials, or privacy-policy mismatch produces an optional `SKIPPED`/warning and the orchestrator continues locally when a valid route remains.

Do not silently fall from OpenRouter/private to Empero/public. Do not silently change a requested model. A fallback that changes data handling or cost requires an explicit route decision.
