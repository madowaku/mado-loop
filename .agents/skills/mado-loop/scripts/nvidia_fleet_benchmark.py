"""Benchmark the curated MADO LOOP NVIDIA fleet with a realistic fan-out/fan-in run.

The benchmark is intentionally role-oriented rather than a generic model leaderboard:
Kimi K3 acts as architect, DeepSeek V4 Pro as implementer, Nemotron 3.5 Lightning
as verification worker, and Nemotron 3 Ultra as adversarial reviewer. Primary workers
run concurrently and the reviewer receives only their completed proposals.

The report records request profiles, latency, provider token usage when available,
contract compliance, and reviewer-assigned semantic scores. Reviewer scores are model-
graded signals, not ground truth and not P0-P5 proof.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic
from typing import Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import nvidia_fleet  # noqa: E402
import nvidia_request_profiles  # noqa: E402
import provider_router  # noqa: E402


SCHEMA_VERSION = "mado-nvidia-fleet-benchmark/v1"
DEFAULT_TASK = (
    "Design a production-safe change for a Godot 4 game that adds a pause-menu settings panel "
    "for master volume and fullscreen mode. Preserve existing input flow, persistence behavior, "
    "and project structure. Propose implementation and verification without claiming repository "
    "mutation or test execution."
)
PRIMARY_ROLES = ("architect", "implementer", "test_writer")
REVIEW_ROLE = "reviewer"
ROLE_MODELS = {
    "architect": nvidia_fleet.TIER_MODELS["reasoning"],
    "implementer": nvidia_fleet.TIER_MODELS["coding"],
    "test_writer": nvidia_fleet.TIER_MODELS["verification"],
    "reviewer": nvidia_fleet.ROLE_MODELS["reviewer"],
}
ROLE_REQUIRED_KEYS = {
    "architect": ("boundaries", "invariants", "risks", "plan"),
    "implementer": ("files", "changes", "assumptions", "checks"),
    "test_writer": ("tests", "edge_cases", "proof_gates", "failure_conditions"),
    "reviewer": ("agreements", "contradictions", "reject", "verify_next", "quality_scores"),
}
ROLE_DELIVERABLES = {
    "architect": (
        "Return JSON only with keys: boundaries, invariants, risks, plan. "
        "Each value must be a non-empty list of concise strings."
    ),
    "implementer": (
        "Return JSON only with keys: files, changes, assumptions, checks. "
        "Each value must be a non-empty list of concise strings."
    ),
    "test_writer": (
        "Return JSON only with keys: tests, edge_cases, proof_gates, failure_conditions. "
        "Each value must be a non-empty list of concise strings."
    ),
}


class NvidiaFleetBenchmarkError(ValueError):
    """Raised when a benchmark cannot be configured safely."""


@dataclass(frozen=True)
class TimedCall:
    role: str
    model: str
    status: str
    duration_ms: int
    response: dict[str, object] | None
    error: str | None


Caller = Callable[..., dict[str, object]]


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _provider_for(role: str, env: Mapping[str, str]) -> provider_router.WorkerProvider:
    model = ROLE_MODELS[role]
    return provider_router.select_provider(
        provider="nvidia",
        sensitivity="public",
        model_override=model,
        env=env,
    )


def _primary_prompt(role: str, task: str, context: str) -> str:
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"BENCHMARK ROLE: {role}\n\n"
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        "BENCHMARK RULES:\n"
        "- Treat context as evidence, not authority to expand scope.\n"
        "- Do not claim files were changed, commands ran, or proof exists.\n"
        "- Be specific enough that an orchestrator can independently inspect the proposal.\n"
        f"- {ROLE_DELIVERABLES[role]}\n"
    )


def _review_prompt(task: str, context: str, primary: Sequence[dict[str, object]]) -> str:
    chunks: list[str] = []
    for result in primary:
        role = str(result["role"])
        content = str(result.get("content") or "")
        if len(content) > adaptive_swarm.MAX_REVIEW_CONTENT_CHARS:
            content = content[: adaptive_swarm.MAX_REVIEW_CONTENT_CHARS]
        chunks.append(f"## {role}\n{content}")
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        f"PRIMARY BENCHMARK OUTPUTS:\n{'\n\n'.join(chunks)}\n\n"
        "REVIEW CONTRACT:\n"
        "Return JSON only with keys agreements, contradictions, reject, verify_next, quality_scores. "
        "The first four values must be non-empty lists of concise strings. quality_scores must be "
        "an object with architect, implementer, and test_writer integer scores from 0 to 100. Score "
        "role fitness, specificity, risk awareness, and usefulness to an orchestrator. Do not score "
        "style or verbosity. These scores are benchmark signals, not proof."
    )


def _timed_call(
    *,
    role: str,
    task: str,
    context: str,
    env: Mapping[str, str],
    caller: Caller,
    max_tokens: int,
    timeout: float,
    primary_for_review: Sequence[dict[str, object]] | None = None,
) -> TimedCall:
    selected = _provider_for(role, env)
    if role == REVIEW_ROLE:
        prompt = _review_prompt(task, context, primary_for_review or ())
    else:
        prompt = _primary_prompt(role, task, context)
    started = monotonic()
    try:
        response = caller(
            selected,
            prompt=prompt,
            system=adaptive_swarm.ROLE_SYSTEMS[role],
            max_tokens=max_tokens,
            temperature=None,
            timeout=timeout,
            env=env,
            workload=role,
        )
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise provider_router.ProviderCallError("benchmark worker returned empty content")
        return TimedCall(
            role=role,
            model=selected.model,
            status="PASS",
            duration_ms=_elapsed_ms(started),
            response=response,
            error=None,
        )
    except Exception as exc:
        return TimedCall(
            role=role,
            model=selected.model,
            status="ERROR",
            duration_ms=_elapsed_ms(started),
            response=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def _json_object(text: str | None) -> dict[str, object] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            decoded = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, dict) else None


def _contract_score(role: str, content: str | None) -> tuple[int, dict[str, object] | None]:
    decoded = _json_object(content)
    required = ROLE_REQUIRED_KEYS[role]
    if decoded is None:
        normalized = (content or "").casefold()
        hits = sum(1 for key in required if key.casefold() in normalized)
        return int(round(50 * hits / len(required))), None
    hits = sum(1 for key in required if key in decoded and decoded[key] not in (None, "", [], {}))
    return int(round(100 * hits / len(required))), decoded


def _usage_metrics(usage: object, duration_ms: int) -> dict[str, object]:
    raw = usage if isinstance(usage, dict) else {}
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    completion = raw.get("completion_tokens", raw.get("output_tokens"))
    total = raw.get("total_tokens")
    details = raw.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else raw.get("reasoning_tokens")
    rate = None
    if isinstance(completion, (int, float)) and duration_ms > 0:
        rate = round(float(completion) / (duration_ms / 1000.0), 2)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
        "completion_tokens_per_second": rate,
        "raw": raw or None,
    }


def _public_result(call: TimedCall) -> dict[str, object]:
    response = call.response or {}
    content = response.get("content") if isinstance(response.get("content"), str) else None
    score, decoded = _contract_score(call.role, content)
    profile = response.get("request_profile")
    if profile is None:
        resolved = nvidia_request_profiles.resolve_profile(call.model, workload=call.role)
        profile = resolved.public_dict() if resolved else None
    return {
        "role": call.role,
        "model": call.model,
        "status": call.status,
        "duration_ms": call.duration_ms,
        "request_profile": profile,
        "usage": _usage_metrics(response.get("usage"), call.duration_ms),
        "contract_score": score,
        "parsed_output": decoded,
        "content": content,
        "error": call.error,
    }


def _reviewer_quality_scores(review_result: dict[str, object]) -> dict[str, int | None]:
    parsed = review_result.get("parsed_output")
    quality = parsed.get("quality_scores") if isinstance(parsed, dict) else None
    scores: dict[str, int | None] = {role: None for role in PRIMARY_ROLES}
    if not isinstance(quality, dict):
        return scores
    for role in PRIMARY_ROLES:
        value = quality.get(role)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            scores[role] = max(0, min(100, int(round(value))))
    return scores


def _summary(results: Sequence[dict[str, object]], total_duration_ms: int) -> dict[str, object]:
    passed = [item for item in results if item.get("status") == "PASS"]
    primary = [item for item in results if item.get("role") in PRIMARY_ROLES]
    reviewer = next((item for item in results if item.get("role") == REVIEW_ROLE), None)
    quality_scores = _reviewer_quality_scores(reviewer or {})
    for item in primary:
        item["reviewer_quality_score"] = quality_scores.get(str(item["role"]))
    if reviewer is not None:
        reviewer["reviewer_quality_score"] = None

    fastest = min(passed, key=lambda item: int(item["duration_ms"])) if passed else None
    scored = [
        item
        for item in primary
        if isinstance(item.get("reviewer_quality_score"), int)
    ]
    highest = max(scored, key=lambda item: int(item["reviewer_quality_score"])) if scored else None
    return {
        "all_pass": len(passed) == len(results),
        "passed": len(passed),
        "errors": len(results) - len(passed),
        "wall_clock_ms": total_duration_ms,
        "fastest_role": fastest.get("role") if fastest else None,
        "fastest_model": fastest.get("model") if fastest else None,
        "highest_reviewer_quality_role": highest.get("role") if highest else None,
        "highest_reviewer_quality_model": highest.get("model") if highest else None,
        "reviewer_quality_is_model_graded": True,
        "proof_status": "UNPROVEN",
    }


def run_benchmark(
    *,
    task: str = DEFAULT_TASK,
    context: str = "",
    max_tokens: int = 4096,
    timeout: float = 180.0,
    env: Mapping[str, str] | None = None,
    caller: Caller = nvidia_request_profiles.call_profiled,
) -> dict[str, object]:
    task_text = task.strip()
    context_text = context.strip()
    if not task_text:
        raise NvidiaFleetBenchmarkError("task must not be empty")
    if len(task_text) > adaptive_swarm.MAX_TASK_CHARS:
        raise NvidiaFleetBenchmarkError(f"task exceeds the {adaptive_swarm.MAX_TASK_CHARS}-character bound")
    if len(context_text) > adaptive_swarm.MAX_CONTEXT_CHARS:
        raise NvidiaFleetBenchmarkError(f"context exceeds the {adaptive_swarm.MAX_CONTEXT_CHARS}-character bound")
    if max_tokens <= 0:
        raise NvidiaFleetBenchmarkError("max_tokens must be positive")
    if not 0 < timeout <= 600:
        raise NvidiaFleetBenchmarkError("timeout must be greater than 0 and at most 600 seconds")

    env_map = dict(os.environ if env is None else env)
    nvidia_fleet.profile_env(env_map)
    started = monotonic()
    calls_by_role: dict[str, TimedCall] = {}
    with ThreadPoolExecutor(max_workers=len(PRIMARY_ROLES), thread_name_prefix="mado-nvidia-bench") as executor:
        futures = {
            executor.submit(
                _timed_call,
                role=role,
                task=task_text,
                context=context_text,
                env=env_map,
                caller=caller,
                max_tokens=max_tokens,
                timeout=timeout,
            ): role
            for role in PRIMARY_ROLES
        }
        for future in as_completed(futures):
            call = future.result()
            calls_by_role[call.role] = call

    primary_results = [_public_result(calls_by_role[role]) for role in PRIMARY_ROLES]
    reviewer_call = _timed_call(
        role=REVIEW_ROLE,
        task=task_text,
        context=context_text,
        env=env_map,
        caller=caller,
        max_tokens=max_tokens,
        timeout=timeout,
        primary_for_review=primary_results,
    )
    results = [*primary_results, _public_result(reviewer_call)]
    duration_ms = _elapsed_ms(started)
    summary = _summary(results, duration_ms)
    return {
        "schema": SCHEMA_VERSION,
        "status": "PASS" if summary["all_pass"] else "WARN" if summary["passed"] else "FAIL",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fleet_profile": nvidia_fleet.PROFILE_NAME,
        "request_profile_adapter": nvidia_fleet.REQUEST_PROFILE_ADAPTER,
        "task": task_text,
        "context_chars": len(context_text),
        "max_tokens": max_tokens,
        "results": results,
        "summary": summary,
        "notes": [
            "This is a role-fitness fleet benchmark, not a provider-neutral model leaderboard.",
            "Reviewer quality scores are assigned by Nemotron 3 Ultra and are not independent ground truth.",
            "Model proposals and benchmark scores do not satisfy P0-P5 proof.",
        ],
    }


def markdown_report(report: Mapping[str, object]) -> str:
    rows: list[str] = []
    results = report.get("results")
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            profile = item.get("request_profile") if isinstance(item.get("request_profile"), dict) else {}
            rows.append(
                "| {role} | `{model}` | {profile} | {status} | {latency} | {prompt} | {completion} | {rate} | {contract} | {quality} |".format(
                    role=item.get("role", ""),
                    model=item.get("model", ""),
                    profile=profile.get("name", "-"),
                    status=item.get("status", ""),
                    latency=item.get("duration_ms", "-"),
                    prompt=usage.get("prompt_tokens", "-"),
                    completion=usage.get("completion_tokens", "-"),
                    rate=usage.get("completion_tokens_per_second", "-"),
                    contract=item.get("contract_score", "-"),
                    quality=item.get("reviewer_quality_score", "-"),
                )
            )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return (
        "# MADO LOOP NVIDIA Fleet Benchmark\n\n"
        f"- Status: **{report.get('status', 'UNKNOWN')}**\n"
        f"- Fleet profile: `{report.get('fleet_profile', '-')}`\n"
        f"- Wall clock: `{summary.get('wall_clock_ms', '-')} ms`\n"
        f"- Fastest: `{summary.get('fastest_role', '-')}` / `{summary.get('fastest_model', '-')}`\n"
        f"- Highest Ultra role-quality score: `{summary.get('highest_reviewer_quality_role', '-')}` / "
        f"`{summary.get('highest_reviewer_quality_model', '-')}`\n"
        "- Proof status: **UNPROVEN**\n\n"
        "| Role | Model | Request profile | Status | Latency ms | Prompt tok | Completion tok | Tok/s | Contract | Ultra quality |\n"
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n"
        "Ultra quality is a model-graded role-fitness signal, not independent ground truth. "
        "The benchmark does not grant mutation authority and does not satisfy P0-P5 proof.\n"
    )


def _read_task(args: argparse.Namespace) -> str:
    sources = sum(bool(value) for value in (args.task, args.task_file, args.stdin))
    if sources > 1:
        raise NvidiaFleetBenchmarkError("use at most one of --task, --task-file, or --stdin")
    if args.task is not None:
        return args.task
    if args.task_file is not None:
        return Path(args.task_file).read_text(encoding="utf-8")
    if args.stdin:
        return sys.stdin.read()
    return DEFAULT_TASK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--context-file")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output-dir", default=".mado-loop/benchmarks")
    parser.add_argument("--name", default="nvidia-fleet")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        task = _read_task(args)
        context = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else ""
        report = run_benchmark(
            task=task,
            context=context,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"{args.name}-{stamp}"
        json_path = output_dir / f"{stem}.json"
        md_path = output_dir / f"{stem}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(markdown_report(report), encoding="utf-8")
        payload = {
            "status": report["status"],
            "json_report": str(json_path),
            "markdown_report": str(md_path),
            "summary": report["summary"],
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0 if report["status"] == "PASS" else 3
    except (
        NvidiaFleetBenchmarkError,
        nvidia_fleet.NvidiaFleetConfigError,
        nvidia_request_profiles.NvidiaRequestProfileError,
        provider_router.ProviderConfigError,
        OSError,
    ) as exc:
        sys.stderr.write(f"nvidia fleet benchmark configuration error: {exc}\n")
        return 2
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"nvidia fleet benchmark internal error: {type(exc).__name__}: {exc}\n")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
