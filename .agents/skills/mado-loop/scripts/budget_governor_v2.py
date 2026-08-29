"""Route bounded MADO LOOP workers across free, hosted, local, and Codex Plus lanes.

Budget Governor 2.0 sits above provider-specific routers. It keeps Sol in the
current parent session, uses genuinely free/hosted lanes before consuming Plus
when quality and privacy policy permit, and falls back deterministically when a
lane is unavailable or fails. WorkBuddy Hy4 promotional access is advisory and
manual because product access is not the same thing as API entitlement.

No prompt, completion, credential, or API key is persisted by this module.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from time import monotonic
from typing import Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import codex_plus_budget  # noqa: E402
import codex_plus_lane  # noqa: E402
import codex_plus_swarm  # noqa: E402
import nvidia_fleet  # noqa: E402
import nvidia_request_profiles  # noqa: E402
import provider_router  # noqa: E402


SCHEMA_VERSION = "mado-budget-governor/v2"
LEDGER_VERSION = "mado-budget-governor-usage/v1"
HY3_FREE_MODEL = "tencent/hy3-preview:free"
HY4_PREVIEW_MODEL = "tencent/hy4-preview"
WORKBUDDY_HY4_PROMO_NOT_AFTER = datetime(2026, 9, 11, tzinfo=timezone.utc)
DEFAULT_LEDGER = Path(".mado-loop/budget-governor/usage.jsonl")
MAX_TASK_CHARS = 20_000
MAX_CONTEXT_CHARS = 120_000
MAX_AUTOMATIC_WORKERS = {"normal": 3, "conserve": 2, "critical": 2}
TRUE_VALUES = {"1", "true", "yes", "on"}

ROLE_WORKLOADS = {
    "recon": "recon",
    "gameplay_specialist": "specialist",
    "ui_specialist": "specialist",
    "asset_specialist": "specialist",
    "implementer": "implementer",
    "test_writer": "test_writer",
    "release_auditor": "release_auditor",
}

ROLE_FOCUS = {
    "recon": "Identify responsibility boundaries, missing facts, and the smallest next inspectable action.",
    "gameplay_specialist": "Focus on mechanics, state, input, failure modes, and observable gameplay behavior.",
    "ui_specialist": "Focus on UI hierarchy, interaction, responsiveness, accessibility, and Godot integration risk.",
    "asset_specialist": "Focus on asset constraints, imports, animation, resources, and deterministic integration.",
    "implementer": "Propose concrete bounded code/project changes, likely files, assumptions, and checks.",
    "test_writer": "Propose tests, P0-P5 proof gates, edge cases, and explicit failure conditions.",
    "release_auditor": "Audit release readiness, evidence, packaging, export, configuration, and missing proof.",
}

LANE_COST = {
    "openrouter-hy3-free": "free-endpoint",
    "nvidia-fleet": "hosted-free-prototype-quota",
    "empero-free": "logged-free",
    "local": "local-compute",
    "codex-plus-luna": "chatgpt-plus-included-usage",
    "workbuddy-hy4-manual": "time-limited-product-promo",
}


class BudgetGovernorConfigError(ValueError):
    """Raised when Budget Governor 2.0 cannot plan a safe route."""


@dataclass(frozen=True)
class LaneCandidate:
    lane: str
    provider: str
    model: str
    cost_class: str
    automatic: bool
    rationale: str

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LaneAvailability:
    openrouter_hy3: bool
    nvidia: bool
    empero: bool
    local: bool
    codex_plus: bool
    workbuddy_hy4_manual: bool

    def public_dict(self) -> dict[str, bool]:
        return asdict(self)


LaneCaller = Callable[..., dict[str, object]]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in TRUE_VALUES


def _validate_text(name: str, value: str, limit: int, *, allow_empty: bool = False) -> str:
    text = value.strip()
    if not text and not allow_empty:
        raise BudgetGovernorConfigError(f"{name} must not be empty")
    if len(text) > limit:
        raise BudgetGovernorConfigError(f"{name} exceeds the {limit}-character bound")
    return text


def _private_nvidia_allowed(env: Mapping[str, str], explicit: bool) -> bool:
    return explicit or _truthy(env.get("MADO_ALLOW_NVIDIA_PRIVATE"))


def _workbuddy_campaign_available(env: Mapping[str, str], *, now: datetime | None = None) -> bool:
    if _truthy(env.get("MADO_DISABLE_WORKBUDDY_HY4")):
        return False
    if _truthy(env.get("MADO_WORKBUDDY_HY4_FREE")):
        return True
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current < WORKBUDDY_HY4_PROMO_NOT_AFTER


def detect_availability(
    *,
    sensitivity: str,
    allow_logged_free: bool = False,
    allow_nvidia_private: bool = False,
    env: Mapping[str, str] | None = None,
    codex_available: bool | None = None,
    now: datetime | None = None,
) -> LaneAvailability:
    env_map = os.environ if env is None else env
    if sensitivity not in provider_router.SENSITIVITIES:
        raise BudgetGovernorConfigError(f"unknown sensitivity: {sensitivity}")

    openrouter = bool((env_map.get("OPENROUTER_API_KEY") or "").strip())
    nvidia_key = bool((env_map.get("NVIDIA_API_KEY") or env_map.get("MADO_NVIDIA_API_KEY") or "").strip())
    nvidia = nvidia_key and (
        sensitivity == "public"
        or (sensitivity == "private" and _private_nvidia_allowed(env_map, allow_nvidia_private))
    )
    empero = sensitivity == "public" and (
        allow_logged_free or _truthy(env_map.get("MADO_ALLOW_LOGGED_FREE"))
    )
    local = bool(
        (env_map.get("MADO_LOCAL_BASE_URL") or "").strip()
        and (env_map.get("MADO_LOCAL_MODEL") or "").strip()
    )
    if codex_available is None:
        codex = shutil.which("codex") is not None and not _truthy(env_map.get("MADO_DISABLE_CODEX_PLUS"))
    else:
        codex = bool(codex_available)
    workbuddy = _workbuddy_campaign_available(env_map, now=now)

    if sensitivity == "secret":
        return LaneAvailability(False, False, False, local, False, False)
    return LaneAvailability(openrouter, nvidia, empero, local, codex, workbuddy)


def _budget(
    *,
    ledger_path: Path,
    status_path: Path,
    weekly_budget_credits: float | None,
    env: Mapping[str, str],
) -> dict[str, object]:
    configured = codex_plus_lane._weekly_budget(env, weekly_budget_credits)
    ledger = codex_plus_lane.budget_summary(
        ledger=codex_plus_lane.load_ledger(ledger_path),
        weekly_budget_credits=configured,
    )
    account = codex_plus_budget.calibrated_pressure(
        codex_plus_budget.load_observation(status_path)
    )
    if bool(account.get("calibrated")):
        mode = str(account.get("mode", "normal"))
        source = "account-status-reset-controller"
        burn_state = str(account.get("burn_state", mode))
    else:
        mode = str(ledger.get("mode", "normal"))
        source = "local-ledger-fallback"
        burn_state = mode
    return {
        **ledger,
        "mode": mode,
        "mode_source": source,
        "burn_state": burn_state,
        "account_status": account,
        "max_recommended": bool(account.get("max_recommended", False)) and mode == "normal",
        "status_file": str(status_path),
    }


def _candidate(lane: str, role: str, rationale: str, *, env: Mapping[str, str]) -> LaneCandidate:
    if lane == "openrouter-hy3-free":
        return LaneCandidate(lane, "openrouter", HY3_FREE_MODEL, LANE_COST[lane], True, rationale)
    if lane == "nvidia-fleet":
        model = nvidia_fleet.ROLE_MODELS.get(role)
        if model is None:
            tier = adaptive_swarm.ROLE_TIERS.get(role, "specialist")
            model = nvidia_fleet.TIER_MODELS.get(tier, nvidia_fleet.TIER_MODELS["specialist"])
        return LaneCandidate(lane, "nvidia", model, LANE_COST[lane], True, rationale)
    if lane == "empero-free":
        model = (env.get("MADO_EMPERO_MODEL") or provider_router.EMPERO_DEFAULT_MODEL).strip()
        return LaneCandidate(lane, "empero", model, LANE_COST[lane], True, rationale)
    if lane == "local":
        model = (env.get("MADO_LOCAL_MODEL") or "").strip()
        return LaneCandidate(lane, "local", model, LANE_COST[lane], True, rationale)
    if lane == "codex-plus-luna":
        return LaneCandidate(lane, "codex-native", codex_plus_lane.LUNA_MODEL, LANE_COST[lane], True, rationale)
    if lane == "workbuddy-hy4-manual":
        return LaneCandidate(lane, "workbuddy", HY4_PREVIEW_MODEL, LANE_COST[lane], False, rationale)
    raise BudgetGovernorConfigError(f"unknown lane: {lane}")


def _ordered_lane_names(
    role: str,
    *,
    mode: str,
    burn_state: str,
    availability: LaneAvailability,
) -> tuple[str, ...]:
    if role not in ROLE_FOCUS:
        raise BudgetGovernorConfigError(f"unsupported automatic worker role: {role}")
    if mode not in MAX_AUTOMATIC_WORKERS:
        raise BudgetGovernorConfigError(f"unknown budget mode: {mode}")

    cheapest = ["openrouter-hy3-free", "nvidia-fleet", "empero-free", "local", "codex-plus-luna"]
    verification = ["openrouter-hy3-free", "nvidia-fleet", "empero-free", "codex-plus-luna", "local"]
    release = ["nvidia-fleet", "openrouter-hy3-free", "empero-free", "codex-plus-luna", "local"]
    quality = ["nvidia-fleet", "codex-plus-luna", "openrouter-hy3-free", "local", "empero-free"]
    conserve = ["nvidia-fleet", "openrouter-hy3-free", "local", "empero-free", "codex-plus-luna"]

    if role in {"recon", "test_writer"}:
        order = verification
    elif role == "release_auditor":
        order = release
    elif mode == "critical":
        order = cheapest
    elif mode == "conserve":
        order = conserve
    elif burn_state == "aggressive":
        order = quality
    else:
        order = quality

    enabled = {
        "openrouter-hy3-free": availability.openrouter_hy3,
        "nvidia-fleet": availability.nvidia,
        "empero-free": availability.empero,
        "local": availability.local,
        "codex-plus-luna": availability.codex_plus,
    }
    return tuple(name for name in order if enabled[name])


def _select_roles(roles: Sequence[str], *, domains: Sequence[str], mode: str) -> tuple[str, ...]:
    cap = MAX_AUTOMATIC_WORKERS[mode]
    candidates = {role for role in roles if role in ROLE_FOCUS}
    priority = codex_plus_swarm._priority_for_domains(domains)
    return tuple(role for role in priority if role in candidates)[:cap]


def _manual_opportunities(
    availability: LaneAvailability,
    *,
    roles: Sequence[str],
    env: Mapping[str, str],
) -> list[dict[str, object]]:
    if not availability.workbuddy_hy4_manual:
        return []
    role_text = ", ".join(roles) if roles else "bounded worker"
    candidate = _candidate(
        "workbuddy-hy4-manual",
        roles[0] if roles else "implementer",
        f"manual promotional experiment for {role_text}; product promo is not API entitlement and is never auto-executed",
        env=env,
    )
    data = candidate.public_dict()
    data["campaign_policy"] = "Tencent announced two weeks free from the 2026-08-28 launch; WorkBuddy UI is authoritative"
    data["automatic"] = False
    return [data]


def _rationale_for_lane(lane: str, *, role: str, mode: str) -> str:
    if lane == "openrouter-hy3-free":
        return f"zero-priced OpenRouter Hy3 endpoint reduces Plus burn for bounded {role}"
    if lane == "nvidia-fleet":
        return f"curated NVIDIA role model preserves Plus allowance while retaining role specialization for {role}"
    if lane == "empero-free":
        return f"explicit logged-free public fallback for {role}"
    if lane == "local":
        return f"configured local compute avoids hosted subscription usage for {role}"
    if lane == "codex-plus-luna":
        return f"Codex-native Luna is the subscription fallback after cheaper permitted lanes in {mode} mode"
    return lane


def plan_governor(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "private",
    allow_logged_free: bool = False,
    allow_nvidia_private: bool = False,
    ledger_path: Path = codex_plus_lane.DEFAULT_LEDGER,
    status_path: Path = codex_plus_budget.DEFAULT_STATUS_PATH,
    weekly_budget_credits: float | None = None,
    env: Mapping[str, str] | None = None,
    codex_available: bool | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    _validate_text("context", context, MAX_CONTEXT_CHARS, allow_empty=True)
    if sensitivity not in provider_router.SENSITIVITIES:
        raise BudgetGovernorConfigError(f"unknown sensitivity: {sensitivity}")

    env_map = os.environ if env is None else env
    availability = detect_availability(
        sensitivity=sensitivity,
        allow_logged_free=allow_logged_free,
        allow_nvidia_private=allow_nvidia_private,
        env=env_map,
        codex_available=codex_available,
        now=now,
    )
    domains = adaptive_swarm.classify_domains(task_text)
    roles, review, complexity_score, reasons = adaptive_swarm.choose_roles(task_text, domains)

    if sensitivity == "secret":
        if not availability.local:
            raise BudgetGovernorConfigError("secret tasks require a configured local provider")
        selected_roles = _select_roles(roles, domains=domains, mode="normal")
        assignments = []
        for role in selected_roles:
            selected = _candidate("local", role, "secret payloads are local-only", env=env_map)
            assignments.append({"role": role, "selected": selected.public_dict(), "fallback_candidates": []})
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "sensitivity": sensitivity,
            "domains": list(domains),
            "complexity_score": complexity_score,
            "complexity_reasons": reasons,
            "budget": {"mode": "normal", "burn_state": "normal", "mode_source": "secret-local-only"},
            "availability": availability.public_dict(),
            "assignments": assignments,
            "parent": {
                "model": None,
                "responsibilities": ["orchestrator", "integration", "acceptance", "P0-P5 proof"],
                "hosted_payload_allowed": False,
            },
            "manual_opportunities": [],
            "review_required": review,
            "proof_status": "UNPROVEN",
            "integration_required": True,
        }

    budget = _budget(
        ledger_path=ledger_path,
        status_path=status_path,
        weekly_budget_credits=weekly_budget_credits,
        env=env_map,
    )
    mode = str(budget["mode"])
    selected_roles = _select_roles(roles, domains=domains, mode=mode)
    assignments: list[dict[str, object]] = []
    for role in selected_roles:
        names = _ordered_lane_names(
            role,
            mode=mode,
            burn_state=str(budget.get("burn_state", mode)),
            availability=availability,
        )
        if not names:
            raise BudgetGovernorConfigError(
                f"no permitted automatic lane is available for role {role}; configure OpenRouter, NVIDIA, local, or Codex"
            )
        candidates = [
            _candidate(name, role, _rationale_for_lane(name, role=role, mode=mode), env=env_map)
            for name in names
        ]
        assignments.append({
            "role": role,
            "selected": candidates[0].public_dict(),
            "fallback_candidates": [item.public_dict() for item in candidates[1:]],
        })

    parent_responsibilities = ["orchestrator", "integration", "acceptance", "P0-P5 proof"]
    if "architect" in roles:
        parent_responsibilities.append("architect")
    if review:
        parent_responsibilities.append("reviewer")
    omitted = [role for role in roles if role not in selected_roles and role != "architect"]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "sensitivity": sensitivity,
        "domains": list(domains),
        "complexity_score": complexity_score,
        "complexity_reasons": reasons,
        "budget": budget,
        "availability": availability.public_dict(),
        "max_automatic_workers": MAX_AUTOMATIC_WORKERS[mode],
        "assignments": assignments,
        "omitted_worker_roles": omitted,
        "parent": {
            "model": codex_plus_lane.SOL_MODEL,
            "effort": "medium",
            "responsibilities": parent_responsibilities,
        },
        "manual_opportunities": _manual_opportunities(availability, roles=selected_roles, env=env_map),
        "review_required": review,
        "routing_policy": "free-and-hosted-first under pressure; quality-balanced when Plus has headroom",
        "paid_api_fallback_enabled": False,
        "proof_status": "UNPROVEN",
        "integration_required": True,
    }


def _role_system(role: str) -> str:
    markers = {
        "recon": "You are the reconnaissance worker.",
        "gameplay_specialist": "You are the gameplay specialist.",
        "ui_specialist": "You are the game UI specialist.",
        "asset_specialist": "You are the asset specialist.",
        "implementer": "You are the implementation worker.",
        "test_writer": "You are the verification worker.",
        "release_auditor": "You are the release audit worker.",
    }
    return markers[role] + " Produce read-only proposals; mutation and proof authority remain with the orchestrator."


def _worker_prompt(*, role: str, task: str, context: str) -> str:
    context_text = context or "(No additional bounded repository context supplied.)"
    return (
        f"ROLE-SPECIFIC FOCUS:\n{ROLE_FOCUS[role]}\n\n"
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_text}\n\n"
        "Return a compact proposal. Separate facts, assumptions, proposal, risks, and checks. "
        "Do not modify files or claim runtime proof."
    )


def _normalise_usage(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    allowed: dict[str, object] = {}
    for key in (
        "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens",
        "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
    ):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            allowed[key] = int(raw)
    return allowed or None


def append_governor_ledger(
    path: Path,
    *,
    role: str,
    candidate: Mapping[str, object],
    status: str,
    duration_ms: int,
    usage: object,
    now: datetime | None = None,
) -> None:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "schema_version": LEDGER_VERSION,
        "timestamp": stamp,
        "role": role,
        "lane": candidate.get("lane"),
        "provider": candidate.get("provider"),
        "model": candidate.get("model"),
        "cost_class": candidate.get("cost_class"),
        "status": status,
        "duration_ms": max(0, int(duration_ms)),
        "usage": _normalise_usage(usage),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _call_lane(
    candidate: Mapping[str, object],
    *,
    role: str,
    prompt: str,
    sensitivity: str,
    cwd: Path,
    timeout: float,
    budget: Mapping[str, object],
    allow_logged_free: bool,
    allow_nvidia_private: bool,
    codex_ledger_path: Path,
    env: Mapping[str, str],
) -> dict[str, object]:
    lane = str(candidate["lane"])
    model = str(candidate["model"])
    if lane == "openrouter-hy3-free":
        selected = provider_router.select_provider(
            provider="openrouter", sensitivity=sensitivity, model_override=model, env=env,
        )
        result = provider_router.call_provider(
            selected, prompt=prompt, system=_role_system(role), max_tokens=4096,
            temperature=0.2, timeout=timeout, env=env,
        )
        return {
            "content": result.get("content"), "usage": result.get("usage"),
            "provider": result.get("provider"),
            "request_profile": {"name": "hy3-free-balanced", "reasoning": "provider-default"},
        }

    if lane == "nvidia-fleet":
        selected = provider_router.select_provider(
            provider="nvidia", sensitivity=sensitivity,
            allow_nvidia_private=allow_nvidia_private, model_override=model, env=env,
        )
        return nvidia_request_profiles.call_profiled(
            selected, prompt=prompt, system=_role_system(role), max_tokens=8192,
            temperature=None, timeout=timeout, env=env, workload=ROLE_WORKLOADS[role],
        )

    if lane == "empero-free":
        selected = provider_router.select_provider(
            provider="empero", sensitivity=sensitivity, allow_logged_free=allow_logged_free,
            model_override=model, env=env,
        )
        result = provider_router.call_provider(
            selected, prompt=prompt, system=_role_system(role), max_tokens=4096,
            temperature=0.2, timeout=timeout, env=env,
        )
        return {"content": result.get("content"), "usage": result.get("usage"), "provider": result.get("provider"), "request_profile": None}

    if lane == "local":
        selected = provider_router.select_provider(
            provider="local", sensitivity=sensitivity, model_override=model or None, env=env,
        )
        result = provider_router.call_provider(
            selected, prompt=prompt, system=_role_system(role), max_tokens=4096,
            temperature=0.2, timeout=timeout, env=env,
        )
        return {"content": result.get("content"), "usage": result.get("usage"), "provider": result.get("provider"), "request_profile": None}

    if lane == "codex-plus-luna":
        profile = codex_plus_swarm._profile_for_role(role, budget=budget)
        result = codex_plus_lane.run_codex_worker(profile, prompt=prompt, cwd=cwd, timeout=timeout)
        codex_plus_lane.append_ledger(codex_ledger_path, result)
        if result.status != "PASS":
            raise RuntimeError(result.error or "Codex Plus Luna worker failed")
        return {
            "content": result.content,
            "usage": result.usage.public_dict(),
            "provider": {"name": "codex-native", "model": result.model, "effort": result.effort},
            "request_profile": profile.public_dict(),
        }

    raise BudgetGovernorConfigError(f"lane {lane} is not executable")


def _attempt_candidates(assignment: Mapping[str, object]) -> list[dict[str, object]]:
    candidates = [assignment["selected"]]
    fallbacks = assignment.get("fallback_candidates")
    if isinstance(fallbacks, list):
        candidates.extend(fallbacks)
    return [item for item in candidates if isinstance(item, dict) and bool(item.get("automatic", False))]


def run_governor(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "private",
    cwd: Path = Path("."),
    allow_logged_free: bool = False,
    allow_nvidia_private: bool = False,
    ledger_path: Path = codex_plus_lane.DEFAULT_LEDGER,
    status_path: Path = codex_plus_budget.DEFAULT_STATUS_PATH,
    governor_ledger_path: Path = DEFAULT_LEDGER,
    weekly_budget_credits: float | None = None,
    timeout: float = 180.0,
    env: Mapping[str, str] | None = None,
    codex_available: bool | None = None,
    lane_caller: LaneCaller = _call_lane,
) -> dict[str, object]:
    if not 0 < timeout <= 600:
        raise BudgetGovernorConfigError("timeout must be greater than zero and at most 600 seconds")
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    context_text = _validate_text("context", context, MAX_CONTEXT_CHARS, allow_empty=True)
    env_map = dict(os.environ if env is None else env)
    plan = plan_governor(
        task=task_text, context=context_text, sensitivity=sensitivity,
        allow_logged_free=allow_logged_free, allow_nvidia_private=allow_nvidia_private,
        ledger_path=ledger_path, status_path=status_path,
        weekly_budget_credits=weekly_budget_credits, env=env_map,
        codex_available=codex_available,
    )
    budget = plan["budget"]
    results_by_role: dict[str, dict[str, object]] = {}

    def run_assignment(assignment: Mapping[str, object]) -> dict[str, object]:
        role = str(assignment["role"])
        prompt = _worker_prompt(role=role, task=task_text, context=context_text)
        attempts: list[dict[str, object]] = []
        for candidate in _attempt_candidates(assignment):
            started = monotonic()
            try:
                raw = lane_caller(
                    candidate, role=role, prompt=prompt, sensitivity=sensitivity,
                    cwd=cwd.resolve(), timeout=timeout, budget=budget,
                    allow_logged_free=allow_logged_free,
                    allow_nvidia_private=allow_nvidia_private,
                    codex_ledger_path=ledger_path, env=env_map,
                )
                duration_ms = max(0, int((monotonic() - started) * 1000))
                content = raw.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise RuntimeError("lane completed without proposal content")
                attempt = {
                    "lane": candidate["lane"], "provider": candidate["provider"],
                    "model": candidate["model"], "status": "PASS",
                    "duration_ms": duration_ms, "usage": _normalise_usage(raw.get("usage")), "error": None,
                }
                attempts.append(attempt)
                append_governor_ledger(
                    governor_ledger_path, role=role, candidate=candidate,
                    status="PASS", duration_ms=duration_ms, usage=raw.get("usage"),
                )
                return {
                    "status": "PASS", "role": role, "lane": candidate["lane"],
                    "provider": raw.get("provider") or {"name": candidate["provider"], "model": candidate["model"]},
                    "model": candidate["model"], "content": content,
                    "usage": _normalise_usage(raw.get("usage")),
                    "request_profile": raw.get("request_profile"), "attempts": attempts,
                }
            except Exception as exc:
                duration_ms = max(0, int((monotonic() - started) * 1000))
                attempt = {
                    "lane": candidate.get("lane"), "provider": candidate.get("provider"),
                    "model": candidate.get("model"), "status": "ERROR",
                    "duration_ms": duration_ms, "usage": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                attempts.append(attempt)
                append_governor_ledger(
                    governor_ledger_path, role=role, candidate=candidate,
                    status="ERROR", duration_ms=duration_ms, usage=None,
                )
        return {"status": "ERROR", "role": role, "content": None, "attempts": attempts, "error": "all permitted automatic lanes failed"}

    assignments = [item for item in plan["assignments"] if isinstance(item, dict)]
    if assignments:
        with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            futures = {pool.submit(run_assignment, item): str(item["role"]) for item in assignments}
            for future in as_completed(futures):
                role = futures[future]
                try:
                    results_by_role[role] = future.result()
                except Exception as exc:
                    results_by_role[role] = {
                        "status": "ERROR", "role": role, "content": None,
                        "attempts": [], "error": f"{type(exc).__name__}: {exc}",
                    }

    ordered = [results_by_role[str(item["role"])] for item in assignments]
    passed = sum(1 for item in ordered if item.get("status") == "PASS")
    if not ordered or passed == len(ordered):
        status = "PASS"
    elif passed:
        status = "WARN"
    else:
        status = "FAIL"

    return {
        **plan,
        "status": status,
        "results": ordered,
        "governor_ledger": str(governor_ledger_path),
        "parent_handoff": {
            "instruction": "Sol parent inspects proposals, fills omitted perspectives, integrates deliberately, then runs normal P0-P5 proof.",
            "worker_mutation_authority": False,
            "automatic_paid_hy4": False,
            "manual_workbuddy_only": True,
        },
        "proof_status": "UNPROVEN",
        "integration_required": True,
    }


def _read_optional(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--task")
        source.add_argument("--task-file")
        command.add_argument("--context-file")
        command.add_argument("--sensitivity", choices=provider_router.SENSITIVITIES, default="private")
        command.add_argument("--allow-logged-free", action="store_true")
        command.add_argument("--allow-nvidia-private", action="store_true")
        command.add_argument("--ledger")
        command.add_argument("--status-file")
        command.add_argument("--weekly-budget-credits", type=float)
        if name == "run":
            command.add_argument("--cwd", default=".")
            command.add_argument("--governor-ledger")
            command.add_argument("--timeout", type=float, default=180.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        task = args.task if args.task is not None else _read_optional(args.task_file)
        context = _read_optional(args.context_file)
        common = dict(
            task=task, context=context, sensitivity=args.sensitivity,
            allow_logged_free=args.allow_logged_free,
            allow_nvidia_private=args.allow_nvidia_private,
            ledger_path=Path(args.ledger) if args.ledger else codex_plus_lane.DEFAULT_LEDGER,
            status_path=Path(args.status_file) if args.status_file else codex_plus_budget.DEFAULT_STATUS_PATH,
            weekly_budget_credits=args.weekly_budget_credits,
        )
        if args.command == "plan":
            payload = plan_governor(**common)
        else:
            payload = run_governor(
                **common, cwd=Path(args.cwd),
                governor_ledger_path=Path(args.governor_ledger) if args.governor_ledger else DEFAULT_LEDGER,
                timeout=args.timeout,
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["status"] in {"PASS", "WARN"} else 2
    except (BudgetGovernorConfigError, provider_router.ProviderConfigError, OSError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
