# Visual Broker

`visual_broker.py` is the narrow visual I/O boundary for delegated Godot work. It is deliberately not an AI agent, desktop automation framework, retry loop, or scheduler.

The supported action surface is exactly:

```text
launch(target)
capture(target, artifact_path)
stop(target)
```

In the first-party CLI those actions are `launch`, `capture`, and `stop`.

## Why it exists

A mutation worker can prove that code changed and tests ran, but UI/gameplay work often needs visual evidence. The broker gives the worker one bounded Godot process and, on native Windows, a screenshot of only the visible window owned by that process. It does not grant arbitrary mouse/keyboard control or full-desktop capture.

Visual evidence is still evidence, not acceptance. The orchestrator must inspect it and normal P0-P5 proof remains authoritative.

## Safety boundary

- sessions are scoped to one Git worktree root;
- project and scene paths must stay inside that worktree;
- screenshot artifacts must be `.png` files inside that worktree while the broker is capturing them;
- broker state lives under the Git common directory, outside tracked source;
- launch records process identity, not only PID;
- capture and stop refuse a process whose identity no longer matches;
- stop may terminate only the recorded broker-owned process;
- there is no recursive worker or AI call inside the broker.

## Platform scope

Windows 11 is first-class. `capture` uses Pillow `ImageGrab` with the HWND owned by the launched Godot PID, so it captures the game window rather than the full desktop.

Launch and stop also work on Linux where process identity is available through `/proc`. Window-only Linux capture is intentionally not implemented yet; it returns `UNKNOWN` instead of widening the broker into general desktop capture or adding another dependency.

## Direct broker usage

Launch the project or one scene:

```powershell
python .agents/skills/mado-loop/scripts/visual_broker.py launch `
  --repo . `
  --session KAN-024 `
  --godot-bin C:\tools\Godot_v4.7.2-stable_win64.exe `
  --scene scenes/player_test.tscn `
  --pretty
```

Capture the owned window:

```powershell
python .agents/skills/mado-loop/scripts/visual_broker.py capture `
  --repo . `
  --session KAN-024 `
  --output artifacts/KAN-024/player-test.png `
  --pretty
```

Stop the owned process:

```powershell
python .agents/skills/mado-loop/scripts/visual_broker.py stop `
  --repo . `
  --session KAN-024 `
  --pretty
```

A successful capture is P3 visual evidence only; it does not mark the OVP task accepted, integrated, or proven.

## OVP visual review bridge

For an OVP mutation task, prefer `ovp_visual_review.py` after `ovp_dispatch.py` has reached `REVIEW_READY`. The bridge adds no model call. It separates evidence capture from the acceptance decision so a screenshot cannot self-certify its own correctness.

Capture evidence against the exact worker HEAD:

```powershell
python .agents/skills/mado-loop/scripts/ovp_visual_review.py capture `
  --repo . `
  --task-id KAN-024 `
  --godot-bin C:\tools\Godot_v4.7.2-stable_win64.exe `
  --scene scenes/player_test.tscn `
  --pretty
```

The bridge launches through the Visual Broker, captures the owned Godot window, stops that process, copies the PNG into OVP state outside tracked source, hashes it, removes the temporary worktree copy, and verifies that the worker HEAD and clean-worktree invariant stayed unchanged.

Inspect the reported PNG. Then carry that evidence into the normal OVP review gate:

```powershell
python .agents/skills/mado-loop/scripts/ovp_visual_review.py review `
  --repo . `
  --task-id KAN-024 `
  --decision accept `
  --reason "visual result matches the requested UI/gameplay intent" `
  --inspected-diff `
  --inspected-visual `
  --pretty
```

`accept` is blocked unless the recorded capture passed, its durable PNG hash still matches, the visual artifact was explicitly inspected, and the normal OVP review gate also passes. `rework` or `reject` may still be recorded when visual capture is unavailable. This keeps unavailable capture from trapping a bad task in `REVIEW_READY` while preventing unavailable or uninspected evidence from becoming an acceptance shortcut.

The visual-review record stores the worker HEAD and artifact SHA-256, and the OVP review reason includes that evidence reference. Final P0-P5 proof still runs after integration.

## Provider policy

The broker and visual-review bridge are provider-neutral and consume no model quota themselves. Current MADO LOOP mutation work should prefer Codex because that is the configured operational provider. Claude remains an optional adapter for a future subscription and should not be auto-selected. Free or free-tier Gemini, NVIDIA, AMD, OpenRouter, or local lanes may be used for bounded proposal/recon/test work when their data-handling policy permits it, without changing the broker contract.
