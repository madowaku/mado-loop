# Budget Governor 2.0

Read this reference when MADO LOOP should preserve ChatGPT Plus allowance by routing bounded model work across free, hosted, local, and Codex-native lanes.

## Goal

Budget Governor 2.0 is a lane selector above the provider-specific adapters. It does not replace the Provider Router, NVIDIA request profiles, Codex Plus reset controller, or P0-P5 proof. It decides which already-authorized lane should receive each bounded proposal task and executes deterministic fallbacks when a lane fails.

The governor optimizes for **successful bounded work per scarce allowance**, not for raw token price alone.

## Lane classes

| Lane | Model / profile | Cost class | Automatic? | Data boundary |
| --- | --- | --- | --- | --- |
| OpenRouter Hy3 free | `tencent/hy3-preview:free` | zero-priced free endpoint | yes | external; Provider Router applies `data_collection=deny,zdr=true` |
| NVIDIA fleet | role-specific Kimi / DeepSeek / Nemotron | hosted prototype/free quota | yes | public by default; private requires existing explicit NVIDIA opt-in |
| Empero free | configured free model | logged free | only with explicit logged-free opt-in | public only |
| local | configured OpenAI-compatible local model | local compute | yes | required for `secret` |
| Codex Plus Luna | Luna high/xhigh/max selected by reset controller | included ChatGPT-plan usage | yes | current Codex sign-in; not used for `secret` worker payloads |
| WorkBuddy Hy4 | `Hy4 preview` | time-limited product promotion | **manual only** | WorkBuddy product boundary; not API entitlement |

Hy4 OpenRouter API access is not treated as free. Budget Governor 2.0 never silently converts the WorkBuddy promotion into a paid API call.

## Current Hy3 / Hy4 assumptions

As checked on 2026-08-29:

- OpenRouter exposes `tencent/hy3-preview:free` as a free endpoint with a 262K context window. Free endpoints are rate-limited.
- Tencent announced Hy4 preview on 2026-08-28 and said WorkBuddy and CodeBuddy would provide a two-week free product experience from launch.
- Tencent also exposes Hy4 through API channels such as OpenRouter, but API pricing is separate from the WorkBuddy promotion.

The code uses a conservative 2026-09-11 UTC advisory cutoff for the launch promotion and stops suggesting the manual lane after that date unless `MADO_WORKBUDDY_HY4_FREE=1` explicitly says the user still has free access. The WorkBuddy UI remains authoritative for actual entitlement.

## Pressure-aware routing

The governor consumes the existing Codex Plus reset-aware budget state.

### Normal / headroom

- `recon` and `test_writer`: prefer Hy3 free first.
- implementation and specialists: prefer the curated NVIDIA role model, then Luna, then Hy3/local fallbacks.
- release audit: prefer Nemotron Ultra through the NVIDIA fleet.
- when the reset controller reports substantial headroom and Luna is selected, the existing Codex Plus policy may promote xhigh roles to `max`.

### Conserve

- keep NVIDIA specialization first for implementation/specialists;
- move Hy3 and local ahead of Luna;
- cap automatic worker count at 2.

### Critical

- prefer Hy3 free first for ordinary bounded roles;
- then NVIDIA / local / explicit logged-free as permitted;
- use Luna as the last automatic safety valve;
- release audit still prefers the stronger NVIDIA audit model first;
- cap automatic worker count at 2.

The governor never spends a paid Hy4 API call automatically.

## Automatic fallback

Each assignment contains a selected lane plus ordered `fallback_candidates`. `run` tries them in order. A transport/provider failure is isolated to that role, recorded as metadata, and the next permitted lane is attempted.

Automatic fallback does not weaken privacy policy:

- `secret` is local-only;
- private NVIDIA still requires explicit consent;
- logged-free remains public-only and explicit;
- OpenRouter keeps the Provider Router's ZDR/data-collection filters;
- WorkBuddy Hy4 remains manual.

Worker output is still an untrusted proposal. A fallback success does not prove the project.

## Content-free telemetry

The governor writes only execution metadata to:

```text
.mado-loop/budget-governor/usage.jsonl
```

Rows contain timestamp, role, lane, provider, model, cost class, status, duration, and normalized token counts when available. They do **not** contain prompt text, completion text, credentials, or API keys.

The Codex Plus Luna lane continues to write its own content-free token ledger so the reset-aware Plus controller keeps working.

## Commands

Inspect a route without making any model calls:

```powershell
python .\.agents\skills\mado-loop\scripts\budget_governor_v2.py plan `
  --sensitivity public `
  --task "codeを実装してテストも追加して"
```

For private work, NVIDIA remains opt-in while OpenRouter uses the existing ZDR/data-collection policy:

```powershell
python .\.agents\skills\mado-loop\scripts\budget_governor_v2.py plan `
  --sensitivity private `
  --allow-nvidia-private `
  --task-file .mado\swarm-task.txt
```

Run the mixed-lane swarm and automatic fallbacks:

```powershell
python .\.agents\skills\mado-loop\scripts\budget_governor_v2.py run `
  --sensitivity public `
  --task-file .mado\swarm-task.txt `
  --context-file .mado\swarm-context.txt
```

To disable the temporary WorkBuddy Hy4 advisory:

```powershell
$env:MADO_DISABLE_WORKBUDDY_HY4 = "1"
```

If WorkBuddy still shows free Hy4 after the conservative advisory cutoff:

```powershell
$env:MADO_WORKBUDDY_HY4_FREE = "1"
```

This only restores a **manual opportunity** in the plan. It never creates automated WorkBuddy transport.

## Proof and authority

- Sol parent owns orchestration, integration, review, and acceptance.
- Workers are read-only proposal generators.
- No lane gets mutation authority from the governor.
- Model self-evaluation and provider success are not proof.
- Normal P0-P5 proof is still required after integration.
