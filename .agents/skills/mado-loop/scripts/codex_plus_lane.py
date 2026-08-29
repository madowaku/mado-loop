"""Run bounded MADO LOOP workers through the local Codex CLI using ChatGPT-plan auth.

The lane is intentionally separate from API provider routing. It shells out to
`codex exec`, which reuses the user's existing Codex authentication, and records
only non-secret execution metadata plus token usage. The actual ChatGPT plan
remaining allowance is not inferred from this ledger; `/status` or the ChatGPT
usage dashboard remains authoritative.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mado-codex-plus-lane/v1"
LEDGER_VERSION = "mado-codex-plus-usage/v1"
TARGET_DAYS = 7
SOL_MODEL = "gpt-5.6-sol"
LUNA_MODEL = "gpt-5.6-luna"
SENSITIVITIES = ("public", "private", "secret")
BUDGET_MODES = ("normal", "conserve", "critical")
DEFAULT_LEDGER = Path(".mado-loop/codex-plus/usage.jsonl")
MAX_PROMPT_CHARS = 120_000
TRUE_VALUES = {"1", "true", "yes", "on"}

# ChatGPT/Codex credit-equivalent rate card published for GPT-5.6. The ledger
# uses this only for pacing comparisons; included Plus allowance remains dynamic.
CREDIT_RATES_PER_MILLION = {
    SOL_MODEL: {"input": 125.0, "cached_input": 12.5, "output": 750.0},
    LUNA_MODEL: {"input": 5.0, "cached_input": 0.5, "output": 30.0},
}


class CodexPlusConfigError(ValueError):
    """Raised when the native lane cannot be planned safely."""


class CodexPlusCallError(RuntimeError):
    """Raised when a Codex CLI worker call fails."""


@dataclass(frozen=True)
class NativeProfile:
    role: str
    model: str
    effort: str
    owner: str
    rationale: str

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    @classmethod
    def from_object(cls, value: object) -> "Usage":
        data = value if isinstance(value, dict) else {}
        return cls(
            input_tokens=_nonnegative_int(data.get("input_tokens")),
            cached_input_tokens=_nonnegative_int(data.get("cached_input_tokens")),
            output_tokens=_nonnegative_int(data.get("output_tokens")),
            reasoning_output_tokens=_nonnegative_int(data.get("reasoning_output_tokens")),
        )

    def public_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class CodexCallResult:
    status: str
    role: str
    model: str
    effort: str
    duration_ms: int
    content: str | None
    usage: Usage
    estimated_credits: float
    error: str | None

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["usage"] = self.usage.public_dict()
        return data


BASE_PROFILES = {
    "orchestrator": NativeProfile(
        "orchestrator", SOL_MODEL, "medium", "parent", "quality-first parent session"
    ),
    "architect": NativeProfile(
        "architect", SOL_MODEL, "medium", "parent", "architecture stays with the Sol parent"
    ),
    "recon": NativeProfile(
        "recon", LUNA_MODEL, "high", "spawn", "cheap bounded reconnaissance"
    ),
    "gameplay_specialist": NativeProfile(
        "gameplay_specialist", LUNA_MODEL, "xhigh", "spawn", "focused specialist proposal"
    ),
    "ui_specialist": NativeProfile(
        "ui_specialist", LUNA_MODEL, "xhigh", "spawn", "focused specialist proposal"
    ),
    "asset_specialist": NativeProfile(
        "asset_specialist", LUNA_MODEL, "xhigh", "spawn", "focused specialist proposal"
    ),
    "implementer": NativeProfile(
        "implementer", LUNA_MODEL, "xhigh", "spawn", "bounded implementation proposal"
    ),
    "test_writer": NativeProfile(
        "test_writer", LUNA_MODEL, "high", "spawn", "verification proposal does not need max reasoning"
    ),
    "release_auditor": NativeProfile(
        "release_auditor", LUNA_MODEL, "xhigh", "spawn", "bounded release audit before parent acceptance"
    ),
    "reviewer": NativeProfile(
        "reviewer", SOL_MODEL, "medium", "parent", "fan-in acceptance stays with the Sol parent"
    ),
    "bounded_retry": NativeProfile(
        "bounded_retry", LUNA_MODEL, "max", "spawn", "explicit last-mile retry only"
    ),
}


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in TRUE_VALUES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weekly_budget(env: Mapping[str, str], explicit: float | None) -> float | None:
    if explicit is not None:
        if explicit <= 0:
            raise CodexPlusConfigError("weekly budget credits must be greater than zero")
        return float(explicit)
    raw = (env.get("MADO_CODEX_PLUS_WEEKLY_CREDITS") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise CodexPlusConfigError("MADO_CODEX_PLUS_WEEKLY_CREDITS must be numeric") from exc
    if value <= 0:
        raise CodexPlusConfigError("MADO_CODEX_PLUS_WEEKLY_CREDITS must be greater than zero")
    return value


def estimate_credits(model: str, usage: Usage) -> float:
    rates = CREDIT_RATES_PER_MILLION.get(model)
    if rates is None:
        return 0.0
    cached = min(usage.input_tokens, usage.cached_input_tokens)
    uncached = max(0, usage.input_tokens - cached)
    credits = (
        uncached * rates["input"]
        + cached * rates["cached_input"]
        + usage.output_tokens * rates["output"]
    ) / 1_000_000.0
    return round(credits, 6)


def load_ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CodexPlusConfigError(f"could not read Codex Plus ledger: {exc}") from exc
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == LEDGER_VERSION:
            rows.append(value)
    return rows


def append_ledger(path: Path, result: CodexCallResult, *, now: datetime | None = None) -> None:
    timestamp = (now or _utcnow()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "schema_version": LEDGER_VERSION,
        "timestamp": timestamp,
        "status": result.status,
        "role": result.role,
        "model": result.model,
        "effort": result.effort,
        "duration_ms": result.duration_ms,
        "usage": result.usage.public_dict(),
        "estimated_credits": result.estimated_credits,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def budget_summary(
    *,
    ledger: Iterable[dict[str, object]],
    weekly_budget_credits: float | None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or _utcnow()
    week_start = current - timedelta(days=TARGET_DAYS)
    day_start = current - timedelta(days=1)
    week_credits = 0.0
    day_credits = 0.0
    calls_7d = 0
    calls_24h = 0
    by_model: dict[str, float] = {}

    for row in ledger:
        timestamp = _parse_time(row.get("timestamp"))
        if timestamp is None or timestamp < week_start:
            continue
        credits_raw = row.get("estimated_credits", 0.0)
        credits = float(credits_raw) if isinstance(credits_raw, (int, float)) else 0.0
        week_credits += credits
        calls_7d += 1
        model = row.get("model")
        if isinstance(model, str):
            by_model[model] = by_model.get(model, 0.0) + credits
        if timestamp >= day_start:
            day_credits += credits
            calls_24h += 1

    projected_week = day_credits * TARGET_DAYS
    mode = "normal"
    budget_fraction = None
    daily_budget = None
    if weekly_budget_credits is not None:
        daily_budget = weekly_budget_credits / TARGET_DAYS
        budget_fraction = week_credits / weekly_budget_credits
        daily_pressure = day_credits / daily_budget if daily_budget > 0 else 0.0
        projected_pressure = projected_week / weekly_budget_credits
        if budget_fraction >= 0.95 or daily_pressure >= 1.5 or projected_pressure >= 1.35:
            mode = "critical"
        elif budget_fraction >= 0.80 or daily_pressure >= 1.0 or projected_pressure >= 1.05:
            mode = "conserve"

    return {
        "target_days": TARGET_DAYS,
        "mode": mode,
        "weekly_budget_credits": weekly_budget_credits,
        "estimated_credits_7d": round(week_credits, 6),
        "estimated_credits_24h": round(day_credits, 6),
        "projected_credits_7d_from_24h": round(projected_week, 6),
        "daily_budget_credits": round(daily_budget, 6) if daily_budget is not None else None,
        "budget_fraction": round(budget_fraction, 6) if budget_fraction is not None else None,
        "calls_7d": calls_7d,
        "calls_24h": calls_24h,
        "credits_by_model_7d": {key: round(value, 6) for key, value in sorted(by_model.items())},
        "authoritative_remaining_source": "Codex /status or ChatGPT usage dashboard",
    }


def choose_profile(
    role: str,
    *,
    budget_mode: str = "normal",
    allow_max: bool = False,
    spawn_parent_role: bool = False,
) -> NativeProfile:
    if role not in BASE_PROFILES:
        raise CodexPlusConfigError(f"unknown Codex Plus role: {role}")
    if budget_mode not in BUDGET_MODES:
        raise CodexPlusConfigError(f"unknown budget mode: {budget_mode}")

    base = BASE_PROFILES[role]
    if role == "bounded_retry" and not allow_max:
        return NativeProfile(role, LUNA_MODEL, "xhigh", "spawn", "max retry disabled; use xhigh")

    model = base.model
    effort = base.effort
    owner = base.owner
    rationale = base.rationale

    if owner == "parent" and spawn_parent_role:
        owner = "spawn"
        rationale += "; explicit standalone Sol spawn"

    if model == LUNA_MODEL:
        if budget_mode == "conserve":
            if effort in {"xhigh", "max"}:
                effort = "high"
            rationale += "; 7-day budget conservation"
        elif budget_mode == "critical":
            if role in {"implementer", "release_auditor", "gameplay_specialist", "ui_specialist", "asset_specialist"}:
                effort = "high"
            else:
                effort = "medium"
            rationale += "; critical budget pressure"

    if model == SOL_MODEL and owner == "spawn" and budget_mode == "critical":
        raise CodexPlusConfigError("critical budget mode forbids spawned Sol; keep Sol work in the parent session")

    return NativeProfile(role, model, effort, owner, rationale)


def _validate_prompt(prompt: str) -> str:
    text = prompt.strip()
    if not text:
        raise CodexPlusConfigError("prompt must not be empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise CodexPlusConfigError(f"prompt exceeds the {MAX_PROMPT_CHARS}-character bound")
    return text


def build_codex_command(
    profile: NativeProfile,
    *,
    cwd: Path,
    codex_bin: str = "codex",
    keep_user_config: bool = False,
) -> list[str]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "--model",
        profile.model,
        "-c",
        f'model_reasoning_effort="{profile.effort}"',
        "--cd",
        str(cwd),
    ]
    if not keep_user_config:
        command.append("--ignore-user-config")
    command.append("-")
    return command


def parse_codex_jsonl(stdout: str) -> tuple[str | None, Usage]:
    final_message: str | None = None
    usage = Usage()
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    final_message = text
        elif event_type == "turn.completed":
            usage = Usage.from_object(event.get("usage"))
    return final_message, usage


def _worker_prompt(role: str, prompt: str) -> str:
    return (
        f"MADO LOOP ROLE: {role}\n"
        "AUTHORITY: read-only proposal worker. Do not modify files, run proof, or claim completion.\n"
        "OUTPUT: separate facts, assumptions, proposal, risks, and checks. Keep scope bounded.\n\n"
        f"TASK:\n{prompt}\n"
    )


def run_codex_worker(
    profile: NativeProfile,
    *,
    prompt: str,
    cwd: Path,
    timeout: float = 300.0,
    codex_bin: str = "codex",
    keep_user_config: bool = False,
    runner=subprocess.run,
) -> CodexCallResult:
    if profile.owner != "spawn":
        raise CodexPlusConfigError(
            f"role {profile.role} belongs to the Sol parent session; use --spawn-parent-role only for standalone testing"
        )
    text = _validate_prompt(prompt)
    binary = shutil.which(codex_bin) if runner is subprocess.run else codex_bin
    if not binary:
        raise CodexPlusConfigError("Codex CLI was not found on PATH")
    command = build_codex_command(
        profile,
        cwd=cwd,
        codex_bin=binary,
        keep_user_config=keep_user_config,
    )
    started = monotonic()
    try:
        completed = runner(
            command,
            input=_worker_prompt(profile.role, text),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = max(0, int((monotonic() - started) * 1000))
        return CodexCallResult(
            "ERROR", profile.role, profile.model, profile.effort, duration_ms, None, Usage(), 0.0,
            f"TimeoutExpired: {exc}",
        )
    duration_ms = max(0, int((monotonic() - started) * 1000))
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    content, usage = parse_codex_jsonl(stdout)
    credits = estimate_credits(profile.model, usage)
    if completed.returncode != 0:
        detail = stderr.strip() or "Codex exec returned a non-zero exit code"
        return CodexCallResult(
            "ERROR", profile.role, profile.model, profile.effort, duration_ms, content, usage, credits,
            f"exit {completed.returncode}: {detail[:1200]}",
        )
    if not content:
        return CodexCallResult(
            "ERROR", profile.role, profile.model, profile.effort, duration_ms, None, usage, credits,
            "Codex exec completed without an agent message",
        )
    return CodexCallResult(
        "PASS", profile.role, profile.model, profile.effort, duration_ms, content, usage, credits, None
    )


def _ledger_path(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_LEDGER


def _plan(
    *,
    role: str,
    sensitivity: str,
    ledger_path: Path,
    weekly_budget_credits: float | None,
    allow_max: bool,
    spawn_parent_role: bool,
    env: Mapping[str, str],
) -> dict[str, object]:
    if sensitivity not in SENSITIVITIES:
        raise CodexPlusConfigError(f"unknown sensitivity: {sensitivity}")
    if sensitivity == "secret":
        raise CodexPlusConfigError("secret tasks are not routed to ChatGPT-plan Codex workers")
    budget = budget_summary(
        ledger=load_ledger(ledger_path),
        weekly_budget_credits=_weekly_budget(env, weekly_budget_credits),
    )
    profile = choose_profile(
        role,
        budget_mode=str(budget["mode"]),
        allow_max=allow_max,
        spawn_parent_role=spawn_parent_role,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "sensitivity": sensitivity,
        "profile": profile.public_dict(),
        "budget": budget,
        "ledger": str(ledger_path),
        "subscription_auth": "Codex CLI existing ChatGPT sign-in",
        "api_key_required": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(target: argparse.ArgumentParser) -> None:
        target.add_argument("--role", default="implementer", choices=tuple(BASE_PROFILES))
        target.add_argument("--sensitivity", default="private", choices=SENSITIVITIES)
        target.add_argument("--ledger")
        target.add_argument("--weekly-budget-credits", type=float)
        target.add_argument("--allow-max", action="store_true")
        target.add_argument("--spawn-parent-role", action="store_true")

    plan = sub.add_parser("plan", help="Show the native profile and current pacing without a model call")
    shared(plan)

    status = sub.add_parser("status", help="Show the local 7-day token/credit-equivalent ledger")
    status.add_argument("--ledger")
    status.add_argument("--weekly-budget-credits", type=float)

    run = sub.add_parser("run", help="Run one bounded Codex worker using existing ChatGPT-plan auth")
    shared(run)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt")
    source.add_argument("--prompt-file")
    run.add_argument("--cwd", default=".")
    run.add_argument("--timeout", type=float, default=300.0)
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--keep-user-config", action="store_true")
    run.add_argument("--no-record", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    env = os.environ
    ledger_path = _ledger_path(getattr(args, "ledger", None))
    try:
        if args.command == "status":
            payload = {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS",
                "budget": budget_summary(
                    ledger=load_ledger(ledger_path),
                    weekly_budget_credits=_weekly_budget(env, args.weekly_budget_credits),
                ),
                "ledger": str(ledger_path),
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        plan = _plan(
            role=args.role,
            sensitivity=args.sensitivity,
            ledger_path=ledger_path,
            weekly_budget_credits=args.weekly_budget_credits,
            allow_max=args.allow_max,
            spawn_parent_role=args.spawn_parent_role,
            env=env,
        )
        if args.command == "plan":
            print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
            return 0

        profile = choose_profile(
            args.role,
            budget_mode=str(plan["budget"]["mode"]),
            allow_max=args.allow_max,
            spawn_parent_role=args.spawn_parent_role,
        )
        prompt = args.prompt
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        result = run_codex_worker(
            profile,
            prompt=prompt or "",
            cwd=Path(args.cwd).resolve(),
            timeout=args.timeout,
            codex_bin=args.codex_bin,
            keep_user_config=args.keep_user_config,
        )
        if not args.no_record:
            append_ledger(ledger_path, result)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": result.status,
            "result": result.public_dict(),
            "budget_before": plan["budget"],
            "ledger": str(ledger_path),
            "proof_status": "UNPROVEN",
            "integration_required": True,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if result.status == "PASS" else 2
    except (CodexPlusConfigError, OSError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
