# Codex Plus native lane

Read this reference when MADO LOOP is running inside Codex with **Sign in with ChatGPT** and bounded worker delegation should consume the user's included ChatGPT-plan Codex allowance instead of an API key.

## Boundary

The native lane is not an OpenAI API provider. It invokes the installed `codex` CLI and reuses the user's existing ChatGPT-plan authentication. Keep it separate from `provider_router.py`, whose job is API/local provider policy.

The Codex CLI's actual account limit and reset information remains authoritative. Check `/status` in an interactive Codex session or the ChatGPT usage dashboard. MADO LOOP's local ledger records token usage and a credit-equivalent pacing estimate, but it must never claim that estimate is the account's true remaining Plus quota.

## Reset-aware operating policy

Do not assume the allowance must last seven days. The reset horizon can be shorter than a week, and temporary model promotions can change effective burn. The controller therefore targets the **next observed reset** and adapts from actual remaining-percentage movement.

- keep the current **Sol Medium parent session** as orchestrator, architecture owner, integrator, reviewer, and acceptance authority;
- do not spawn Sol for work the parent can do in the current context;
- use **Luna xhigh** for bounded implementation and focused specialist proposals by default;
- use **Luna high** for reconnaissance and routine test/proof proposals;
- spawn at most **two Luna workers** in `normal` or `aggressive` burn state;
- reduce to **one Luna worker** when the controller enters `conserve` or `critical` mode;
- allow xhigh roles such as `implementer`, focused specialists, and `release_auditor` to auto-promote to **Luna max** only when observed burn leaves substantial headroom at the next reset;
- do not promote routine `recon` or `test_writer` work to max merely because headroom exists;
- if observed burn accelerates, remove the automatic max recommendation and downshift through xhigh/high/medium as appropriate;
- never hard-code a temporary Luna Max discount or promotion multiplier; infer the practical effect from account-status burn instead;
- prefer deterministic tools or the existing Sol parent over an unnecessary worker call;
- use the NVIDIA fleet as an external second opinion or overflow lane when independent model diversity is useful.

This is a feedback controller, not a guarantee that a plan will last to a specific clock time. ChatGPT-plan allowance is dynamic and actual consumption depends on context size, reasoning, tool calls, caching, model behavior, and account-side promotions.

## Local usage ledger

`scripts/codex_plus_lane.py` consumes `codex exec --json` events and stores only non-secret metadata:

- timestamp;
- role;
- model and reasoning effort;
- duration;
- input, cached input, output, and reasoning-output token counts;
- a credit-equivalent estimate based on the configured GPT-5.6 reference rate card.

It never stores the prompt, model response, ChatGPT credentials, or API keys in the usage ledger.

Default ledger:

```text
.mado-loop/codex-plus/usage.jsonl
```

Inspect the local telemetry without a model call:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_lane.py status
```

An optional user-defined weekly guardrail can still be supplied with `--weekly-budget-credits` or `MADO_CODEX_PLUS_WEEKLY_CREDITS`. It is a legacy/fallback pacing target only. When a fresh account-status observation exists, the reset-aware account controller is authoritative for the swarm mode.

## Calibrate from actual account status

Read the remaining percentage and reset horizon from Codex `/status` or the ChatGPT usage dashboard, then append a local observation:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_budget.py sync `
  --remaining-percent 72 `
  --hours-until-reset 36
```

Run the same command again later with the new values. The controller compares observations from the **same absolute reset window**, learns the recent percentage burn per hour, and projects how much allowance would remain at reset if that rate continued.

The observation history is stored at:

```text
.mado-loop/codex-plus/status.json
```

Only remaining percentage, observation time, and reset time are stored. The file contains no prompt, response, credential, account identifier, or API key. The last 32 coarse observations are retained; burn-rate estimation uses the recent 24-hour portion of the current reset window.

Inspect the controller:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_budget.py status
```

The controller returns two related fields:

- `burn_state`: `aggressive`, `normal`, `conserve`, or `critical`;
- `mode`: the execution safety mode consumed by the swarm, where `aggressive` maps to normal concurrency but can permit automatic Luna Max for xhigh roles.

The main signals are observed burn rate, sustainable burn rate to the next reset while keeping a small reserve, and projected remaining percentage at reset. A large projected surplus enters `aggressive`; a rate that would consume the reserve enters `conserve`; likely pre-reset exhaustion enters `critical`.

When the displayed reset time changes materially, observations from the old reset window are not used to calculate the new burn rate. This naturally handles early/manual reset events without assuming a seven-day cycle.

## Role profile

| Role | Native model | Default effort | Aggressive/headroom behavior | Execution owner |
| --- | --- | --- | --- | --- |
| `orchestrator` | Sol | `medium` | unchanged | current parent |
| `architect` | Sol | `medium` | unchanged | current parent |
| `reviewer` | Sol | `medium` | unchanged | current parent |
| `recon` | Luna | `high` | stays `high` | spawned worker |
| gameplay/UI/asset specialist | Luna | `xhigh` | may promote to `max` | spawned worker |
| `implementer` | Luna | `xhigh` | may promote to `max` | spawned worker |
| `test_writer` | Luna | `high` | stays `high` | spawned worker |
| `release_auditor` | Luna | `xhigh` | may promote to `max` | spawned worker |
| `bounded_retry` | Luna | explicit lane profile | not automatically spawned by swarm | spawned worker |

Under conserve/critical pressure Luna downshifts before another expensive reasoning call. Parent-owned Sol work stays in the parent instead of creating duplicate Sol sessions.

## Planning and execution

Inspect one standalone role without calling a model:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_lane.py plan `
  --role implementer `
  --sensitivity private
```

Run one bounded worker through the existing ChatGPT sign-in:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_lane.py run `
  --role implementer `
  --sensitivity private `
  --prompt "Inspect the supplied task and propose the smallest coherent implementation."
```

The lane uses `codex exec --json --ephemeral --sandbox read-only` and passes the selected model and `model_reasoning_effort`. Workers are proposal-only and do not receive mutation or proof authority.

## Reset-aware adaptive swarm

`scripts/codex_plus_swarm.py` reuses the existing deterministic adaptive role classifier, but only spawns the highest-leverage Luna roles that fit the current account mode. Architect and reviewer responsibilities remain with the Sol parent. The swarm reads both the content-free usage ledger and the optional account-status history automatically.

Plan without calls:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_swarm.py plan `
  --sensitivity private `
  --task "HUD UI architectureを整理して実装と検証まで設計して"
```

The plan exposes `burn_state`, `max_recommended`, and the chosen effort for each worker. Automatic max is never inferred from API price alone; it requires reset-aware headroom.

Run the selected Luna workers:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_swarm.py run `
  --sensitivity private `
  --task-file .mado/swarm-task.txt `
  --context-file .mado/swarm-context.txt
```

The result always returns `proof_status: UNPROVEN` and `integration_required: true`. The Sol parent must inspect the worker proposals, fill omitted perspectives, integrate deliberately, and run normal P0-P5 proof.

## Safety

- `secret` work remains local-only and is rejected by this hosted subscription lane.
- Do not pass credentials or secret-bearing output into spawned workers.
- Do not persist prompt or completion content in the usage ledger or status history.
- Do not bypass the Codex sandbox or approval system from this lane.
- Do not interpret model self-evaluation or worker majority as acceptance.
- Do not auto-retry failed workers just because max is currently recommended; failure handling remains an explicit orchestration decision.
