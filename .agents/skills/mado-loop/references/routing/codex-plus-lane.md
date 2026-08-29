# Codex Plus native lane

Read this reference when MADO LOOP is running inside Codex with **Sign in with ChatGPT** and bounded worker delegation should consume the user's included ChatGPT-plan Codex allowance instead of an API key.

## Boundary

The native lane is not an OpenAI API provider. It invokes the installed `codex` CLI and reuses the user's existing ChatGPT-plan authentication. Keep it separate from `provider_router.py`, whose job is API/local provider policy.

The Codex CLI's actual account limit and reset information remains authoritative. Check `/status` in an interactive Codex session or the ChatGPT usage dashboard. MADO LOOP's local ledger records token usage and a credit-equivalent pacing estimate, but it must never claim that estimate is the account's true remaining Plus quota.

## Seven-day operating policy

The default policy is designed to stretch the included allowance across a full week:

- keep the current **Sol Medium parent session** as orchestrator, architecture owner, integrator, reviewer, and acceptance authority;
- do not spawn Sol for work the parent can do in the current context;
- use **Luna xhigh** for bounded implementation and focused specialist proposals;
- use **Luna high** for reconnaissance and routine test/proof proposals;
- spawn at most **two Luna workers** for one task in normal mode;
- reduce to **one Luna worker** when the guardrail enters `conserve` or `critical` mode;
- never auto-upgrade to Luna `max`;
- allow Luna `max` only as an explicit `bounded_retry` after xhigh failed while scope and acceptance criteria remain clear;
- prefer deterministic tools or the existing Sol parent over an unnecessary worker call;
- use the NVIDIA fleet as an external second opinion or overflow lane when appropriate rather than spending Plus allowance on redundant model calls.

This is a pacing policy, not a guarantee that a plan will last exactly seven days. ChatGPT-plan allowance is dynamic and actual consumption depends on context size, reasoning, tool calls, caching, and model behavior.

## Local pacing ledger

`scripts/codex_plus_lane.py` consumes `codex exec --json` events and stores only non-secret metadata:

- timestamp;
- role;
- model and reasoning effort;
- duration;
- input, cached input, output, and reasoning-output token counts;
- a credit-equivalent estimate based on the current GPT-5.6 Codex rate card.

It never stores the prompt, model response, ChatGPT credentials, or API keys in the usage ledger.

Default ledger:

```text
.mado-loop/codex-plus/usage.jsonl
```

Inspect the local pace without a model call:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_lane.py status
```

An optional user-defined weekly guardrail can be supplied with `--weekly-budget-credits` or `MADO_CODEX_PLUS_WEEKLY_CREDITS`. This value is a pacing target only and must not be described as the Plus plan's official quota.

## Calibrate from actual account status

Because the included allowance is dynamic, prefer a coarse manual calibration from the account's real weekly status instead of inventing a fixed Plus quota. Read the weekly remaining percentage and reset time from Codex `/status` or the ChatGPT usage dashboard, then sync them locally:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_budget.py sync `
  --remaining-percent 72 `
  --hours-until-reset 120
```

The observation is stored at:

```text
.mado-loop/codex-plus/status.json
```

Only remaining percentage, observation time, and reset time are stored. The file contains no prompt, response, credential, or account identifier.

Inspect the calibration:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_budget.py status
```

The governor compares actual remaining weekly percentage with the fraction of the seven-day window still remaining. Roughly on pace stays `normal`; materially below even pace enters `conserve`; far below pace enters `critical`. An expired observation is ignored until refreshed. When the local credit-equivalent ledger and account-status calibration disagree, the **stricter** mode wins.

## Role profile

| Role | Native model | Effort | Execution owner |
| --- | --- | --- | --- |
| `orchestrator` | Sol | `medium` | current parent |
| `architect` | Sol | `medium` | current parent |
| `reviewer` | Sol | `medium` | current parent |
| `recon` | Luna | `high` | spawned worker |
| gameplay/UI/asset specialist | Luna | `xhigh` | spawned worker |
| `implementer` | Luna | `xhigh` | spawned worker |
| `test_writer` | Luna | `high` | spawned worker |
| `release_auditor` | Luna | `xhigh` | spawned worker |
| `bounded_retry` | Luna | `max` only when explicit | spawned worker |

Budget pressure downshifts Luna before it spends another high-reasoning call. Parent-owned Sol work stays in the parent instead of creating duplicate Sol sessions.

## Planning and execution

Inspect one role without calling a model:

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

## Subscription-efficient adaptive swarm

`scripts/codex_plus_swarm.py` reuses the existing deterministic adaptive role classifier, but only spawns the highest-leverage Luna roles that fit the current budget mode. Architect and reviewer responsibilities remain with the Sol parent. The swarm reads both the content-free usage ledger and the optional account-status calibration automatically.

Plan without calls:

```powershell
python .agents/skills/mado-loop/scripts/codex_plus_swarm.py plan `
  --sensitivity private `
  --task "HUD UI architectureを整理して実装と検証まで設計して"
```

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
- Do not persist prompt or completion content in the usage ledger.
- Do not bypass the Codex sandbox or approval system from this lane.
- Do not interpret model self-evaluation or worker majority as acceptance.
- Do not auto-retry failed workers with a more expensive effort level.
