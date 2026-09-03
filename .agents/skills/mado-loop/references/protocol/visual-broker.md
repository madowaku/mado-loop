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
- screenshot artifacts must be `.png` files inside that worktree;
- broker state lives under the Git common directory, outside tracked source;
- launch records process identity, not only PID;
- capture and stop refuse a process whose identity no longer matches;
- stop may terminate only the recorded broker-owned process;
- there is no recursive worker or AI call inside the broker.

## Platform scope

Windows 11 is first-class. `capture` uses Pillow `ImageGrab` with the HWND owned by the launched Godot PID, so it captures the game window rather than the full desktop.

Launch and stop also work on Linux where process identity is available through `/proc`. Window-only Linux capture is intentionally not implemented yet; it returns `UNKNOWN` instead of widening the broker into general desktop capture or adding another dependency.

## Usage

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

Use the screenshot path as worker evidence in `mado-mutation-handoff/v1`. A successful capture is P3 visual evidence only; it does not mark the OVP task accepted, integrated, or proven.

## Provider policy

The broker is provider-neutral and consumes no model quota itself. Current MADO LOOP mutation work should prefer Codex because that is the configured operational provider. Claude remains an optional adapter for a future subscription and should not be auto-selected. Free or free-tier Gemini, NVIDIA, AMD, OpenRouter, or local lanes may be used for bounded proposal/recon/test work when their data-handling policy permits it, without changing the broker contract.
