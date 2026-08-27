# Adaptive worker swarm

Read this reference when MADO LOOP can gain leverage by composing a worker team from the classified task instead of using the fixed default swarm. Adaptive composition is deterministic orchestration. Models do not choose their own roles, spawn siblings, relax sensitivity, mutate the project, or establish proof.

## Purpose

The fixed [parallel worker swarm](worker-swarm.md) is useful when the orchestrator already knows the desired roles. The adaptive swarm is useful when task domains should determine the smallest useful team automatically.

```text
TASK
  |
  v
DETERMINISTIC DOMAIN CLASSIFIER
  |
  v
ADAPTIVE TEAM POLICY
  |  role + tier + routing rationale
  +--> ARCHITECT / RECON / SPECIALISTS / IMPLEMENTER / TEST WRITER / RELEASE AUDITOR
  |                         parallel fan-out
  +--------------------------------------------------------------+
                                                                 v
                                                            REVIEWER
                                                                 |
                                                                 v
                                                          ORCHESTRATOR
                                                                 |
                                                    INTEGRATE / RUN / P0-P5
```

The team planner is first-party deterministic code. It uses the existing task-domain classifier plus bounded complexity signals. A model response never changes the team during the same invocation.

## Role catalog

| Role | Tier | Selected when | Non-authority |
| --- | --- | --- | --- |
| `architect` | `reasoning` | mixed/cross-domain or complexity threshold | no mutation or proof |
| `recon` | `reasoning` | no concrete domain can be classified | no invented repository state |
| `gameplay_specialist` | `specialist` | `GAMEPLAY` or `PLAYTEST` | proposal only |
| `ui_specialist` | `specialist` | `UI` or `REFERENCE_TO_UI` | proposal only |
| `asset_specialist` | `specialist` | sprite/image/animation/integration/pixel-art work | proposal only |
| `implementer` | `coding` | implementation-bearing domains | does not apply patches |
| `test_writer` | `verification` | implementation or proof-bearing domains | does not claim tests ran |
| `release_auditor` | `verification` | `RELEASE` | audit only, no implicit feature implementation |
| `reviewer` | `verification` | adaptive fan-in when several perspectives need comparison | no acceptance authority |

The canonical role order is stable so network completion order cannot change orchestration semantics.

## Domain composition

The first-party policy currently composes roles as follows:

- `CODE` -> `implementer`, `test_writer`
- `GAMEPLAY` -> `gameplay_specialist`, `implementer`, `test_writer`
- `UI` -> `ui_specialist`, `implementer`, `test_writer`
- `SPRITE`, `ANIMATION`, `ASSET_INTEGRATION` -> `asset_specialist`, `implementer`, `test_writer`
- `IMAGE`, `PIXEL_ART` -> `asset_specialist`, `test_writer`
- `REFERENCE_TO_UI` -> `ui_specialist`, `asset_specialist`, `implementer`, `test_writer`
- `PLAYTEST` -> `gameplay_specialist`, `test_writer`
- `RELEASE` -> `release_auditor`, `test_writer`; release mode removes implicit `implementer`
- no domain match -> `recon`

`architect` is added when the complexity score reaches the threshold or two or more concrete domains are active. `RELEASE` adds extra complexity because it crosses proof and packaging surfaces. Asset integration and reference-to-UI add complexity because they cross integration boundaries.

This policy is intentionally small and inspectable. Do not replace it with an unconstrained LLM planner.

## Per-role provider and model routing

Adaptive composition separates **role**, **model tier**, **provider**, and **model**. MADO LOOP does not hard-code vendor model IDs. The existing [provider router](provider-router.md) remains the sensitivity authority for every assignment.

Default tier mapping:

- `reasoning`: architect and recon
- `specialist`: gameplay/UI/asset specialists
- `coding`: implementer
- `verification`: test writer, release auditor, reviewer

Optional environment configuration may assign a model/provider by role or tier. Role-specific settings take precedence over tier settings.

```text
MADO_ADAPTIVE_PROVIDER_<ROLE>
MADO_ADAPTIVE_MODEL_<ROLE>
MADO_ADAPTIVE_PROVIDER_<TIER>
MADO_ADAPTIVE_MODEL_<TIER>
MADO_ADAPTIVE_DEFAULT_PROVIDER
```

Examples:

```powershell
$env:MADO_ADAPTIVE_MODEL_REASONING = "<reasoning-model>"
$env:MADO_ADAPTIVE_MODEL_SPECIALIST = "<specialist-model>"
$env:MADO_ADAPTIVE_MODEL_CODING = "<coding-model>"
$env:MADO_ADAPTIVE_MODEL_VERIFICATION = "<verification-model>"
```

A role-specific override such as `MADO_ADAPTIVE_MODEL_IMPLEMENTER` beats `MADO_ADAPTIVE_MODEL_CODING`.

A model override cannot silently weaken provider policy. If the provider cannot be resolved safely, planning fails. `secret` assignments remain local-only. A private assignment never falls to the logged public lane. Empero remains public-only and explicit opt-in. Credentials never appear in assignment or result metadata.

If no adaptive model profile is configured, roles use the normal provider-router model. Adaptive composition still changes the team even when all roles happen to share one model.

## Review policy

Review is adaptive by default:

- one `recon` role with no concrete domain does not automatically require a reviewer;
- teams with two or more primary roles use reviewer fan-in;
- mixed-domain and release tasks use reviewer fan-in;
- the orchestrator may explicitly force or disable review when the acceptance contract justifies it.

The reviewer may use a different verification-tier model from primary workers. It receives collected primary outputs only after fan-out completes.

## Safety and bounds

Current first-party bounds:

- task: at most 20,000 characters;
- shared context: at most 120,000 characters;
- parallel threads: 1 through 8, default 4;
- no recursive spawning;
- no dynamic role creation from model output;
- no worker repository mutation authority;
- no majority-vote acceptance;
- all results set `proof_status: UNPROVEN` and `integration_required: true`.

A worker failure is isolated. Partial success produces transport `WARN`; all scheduled calls failing produces transport `FAIL`. These statuses never establish the requested game outcome.

## CLI

Inspect adaptive composition without model calls:

```powershell
python .agents/skills/mado-loop/scripts/adaptive_swarm.py plan `
  --sensitivity private `
  --task-file .mado/swarm-task.txt
```

Run the composed team:

```powershell
python .agents/skills/mado-loop/scripts/adaptive_swarm.py run `
  --sensitivity private `
  --task-file .mado/swarm-task.txt `
  --context-file .mado/swarm-context.txt `
  --output .mado/adaptive-swarm-result.json
```

Use `--review` or `--no-review` only to override the deterministic review decision. `--provider` and `--model` are whole-invocation defaults; role/tier environment profiles can refine them.

## Choosing fixed vs adaptive swarm

Use the fixed swarm when the orchestrator or user explicitly specifies the desired role set. Use adaptive swarm when the task domains should choose the smallest useful team and role-specific model tiers may reduce cost or improve quality.

Do not use either swarm when deterministic tooling already answers the question or the task is too small to justify multiple proposal calls.

After any swarm, the orchestrator still owns the final sequence:

`inspect proposals -> choose -> integrate -> run -> inspect -> verify -> fix -> P0-P5 prove`.
