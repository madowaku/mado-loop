# OVP Dispatch Adapter

Use `scripts/ovp_dispatch.py` only after `ovp_runtime.py prepare` has created an isolated mutation task. The adapter is the provider boundary between a prepared OVP worktree and a Codex, Claude, or explicitly configured local mutation worker.

The adapter does **not** give the provider acceptance authority. It reads the runtime-owned manifest and `AI_CREOLE.txt`, runs one worker inside the recorded worktree, parses a bounded mutation handoff, and then calls the authoritative OVP receipt gate from the orchestrator-side process. The worker never needs write access to OVP state under the Git common directory.

## Authority split

```text
OVP prepare
  -> READY
  -> Dispatch Adapter
       -> provider process in isolated worktree
       -> edit / test / commit
       -> mado-mutation-handoff/v1
  -> orchestrator-side receipt validation
  -> REVIEW_READY
  -> OVP review / integrate
  -> P0-P5 proof
```

The provider may mutate only the assigned worktree. It must not review, merge, integrate, bind proof, alter acceptance criteria, or claim `DONE` / `PROVEN`.

## Dry-run first

Validate the prepared task and provider executable without starting a worker:

```powershell
python .agents/skills/mado-loop/scripts/ovp_dispatch.py `
  --repo . `
  --task-id KAN-024 `
  --provider codex `
  --dry-run `
  --pretty
```

A dry-run does not advance the task from `READY` or `REWORK`.

## Codex mutation worker

The first-party Codex profile uses `codex exec` with an ephemeral `workspace-write` sandbox rooted at the recorded OVP worktree. Existing user configuration is ignored by default while normal home-directory authentication remains available.

```powershell
python .agents/skills/mado-loop/scripts/ovp_dispatch.py `
  --repo . `
  --task-id KAN-024 `
  --provider codex `
  --model gpt-5.6-luna `
  --reasoning-effort xhigh `
  --pretty
```

Use `--keep-user-config` only when the task explicitly depends on the user's Codex configuration. Model choice remains an orchestrator routing decision.

## Claude mutation worker

The first-party Claude profile uses non-interactive JSON output and edit acceptance inside the recorded worktree:

```powershell
python .agents/skills/mado-loop/scripts/ovp_dispatch.py `
  --repo . `
  --task-id KAN-024 `
  --provider claude `
  --model sonnet `
  --pretty
```

Provider CLI surfaces can change independently of MADO LOOP. If an installed Codex or Claude version needs different invocation flags, use an explicit `--command-json` override. A command override is executed directly without a shell and must return the MADO mutation handoff on stdout.

## Local mutation worker

MADO LOOP does not assume that a local model runtime is an agent capable of editing and committing a repository. Therefore `local` requires an explicit argv contract:

```powershell
python .agents/skills/mado-loop/scripts/ovp_dispatch.py `
  --repo . `
  --task-id KAN-024 `
  --provider local `
  --command-json '["my-local-agent", "--headless"]' `
  --pretty
```

The command receives the mutation prompt on stdin and runs with the OVP worktree as its current directory. It must edit and commit through its own agent/tool runtime, then write a valid handoff object to stdout.

Do not wrap the command in `cmd /c`, `powershell -Command`, `sh -c`, or another shell merely to gain quoting convenience. Keep argv explicit and bounded.

## Mutation handoff

Every successful worker run must end with one JSON object using this schema:

```json
{
  "schema_version": "mado-mutation-handoff/v1",
  "summary": "Implemented dash and regression coverage",
  "checks": {
    "unit": "PASS",
    "visual": "PASS"
  },
  "evidence": {
    "unit": "python -m unittest tests.test_dash",
    "visual": "artifacts/dash.png"
  },
  "artifacts": ["artifacts/dash.png"],
  "risks": [],
  "assumptions": []
}
```

The `checks` keys must match the prepared OVP acceptance IDs exactly. Allowed statuses are `PASS`, `FAIL`, `WARN`, `UNKNOWN`, and `SKIPPED`. A worker must report uncertainty rather than invent a pass.

A valid JSON handoff is still not trusted evidence by itself. The adapter calls `ovp_runtime.submit_receipt`, which independently requires the recorded branch, a changed committed HEAD, a clean worktree, include/exclude scope compliance, and exact check identity before the task may enter `REVIEW_READY`.

## Environment boundary

The adapter does not copy the parent process environment wholesale. By default it passes only a small operating-system/runtime allowlist such as `PATH`, home-directory variables, temp-directory variables, locale, and certificate paths.

Secret-looking variables such as API keys, auth tokens, passwords, private keys, and credentials are not inherited automatically. Explicit non-secret pass-through uses:

```powershell
--pass-env MY_NON_SECRET_SETTING
```

Passing a secret-looking variable also requires explicit authority:

```powershell
--pass-env REQUIRED_PROVIDER_TOKEN --allow-secret-env
```

Do this only when the selected worker lane is permitted to receive that secret. Prefer existing provider sign-in stored outside environment variables when possible.

## Failure and resume

The adapter advances a fresh task through `READY/REWORK -> DISPATCHED -> WORKING` before the provider result is accepted. A provider crash, timeout, invalid handoff, missing commit, dirty worktree, or rejected receipt gate leaves the task at `WORKING` so the failure is visible rather than silently reset.

After inspecting the worktree and failure artifacts, explicitly resume the same assignment with:

```powershell
python .agents/skills/mado-loop/scripts/ovp_dispatch.py `
  --repo . `
  --task-id KAN-024 `
  --provider codex `
  --resume `
  --pretty
```

`--resume` is valid only from `WORKING`. It does not replay the `DISPATCHED` transition. If the task needs a changed contract or scope, do not blindly resume; recover or replace the assignment under orchestrator control.

## Dispatch artifacts

Provider stdout, stderr, and the latest bounded dispatch record are stored under the OVP task state directory in the Git common directory, outside the tracked project worktree. This keeps transient model logs out of normal source changes while preserving failure evidence for the orchestrator.

Do not treat provider stdout as final proof. Once the adapter reaches `REVIEW_READY`, continue with normal OVP `review`, `integrate`, and schema-v1.1 P0-P5 proof binding.
