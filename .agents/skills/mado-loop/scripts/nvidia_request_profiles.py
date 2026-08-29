"""Apply model-aware request parameters to curated NVIDIA NIM worker calls.

The adapter is deliberately scoped to NVIDIA hosted models. It keeps model-specific
sampling and reasoning controls out of the provider router and adaptive orchestrator.
Explicit caller choices still win where supported; curated defaults only fill in the
model-specific controls the generic OpenAI-compatible request cannot express.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Mapping
from urllib import error, request

import provider_router


@dataclass(frozen=True)
class NvidiaRequestProfile:
    name: str
    model: str
    workload: str
    temperature: float
    max_tokens_cap: int
    reasoning_effort: str | None = None
    reasoning_budget_fraction: float | None = None
    reasoning_budget_cap: int | None = None

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


MODEL_CAPS = {
    "moonshotai/kimi-k3": 65536,
    "deepseek-ai/deepseek-v4-pro-0813": 16384,
    "nvidia/nemotron-3.5-lightning-30b-a3b": 32768,
    "nvidia/nemotron-3-ultra-550b-a55b": 32768,
}


ROLE_MARKERS = (
    ("architecture worker", "architect"),
    ("reconnaissance worker", "recon"),
    ("gameplay specialist", "specialist"),
    ("game ui specialist", "specialist"),
    ("asset specialist", "specialist"),
    ("implementation worker", "implementer"),
    ("verification worker", "test_writer"),
    ("release audit worker", "release_auditor"),
    ("adversarial reviewer", "reviewer"),
)


PROFILES = {
    ("moonshotai/kimi-k3", "architect"): NvidiaRequestProfile(
        name="kimi-k3-architect-max",
        model="moonshotai/kimi-k3",
        workload="architect",
        temperature=1.0,
        max_tokens_cap=65536,
        reasoning_effort="max",
    ),
    ("moonshotai/kimi-k3", "specialist"): NvidiaRequestProfile(
        name="kimi-k3-specialist-high",
        model="moonshotai/kimi-k3",
        workload="specialist",
        temperature=1.0,
        max_tokens_cap=65536,
        reasoning_effort="high",
    ),
    ("deepseek-ai/deepseek-v4-pro-0813", "implementer"): NvidiaRequestProfile(
        name="deepseek-v4-pro-coding-max",
        model="deepseek-ai/deepseek-v4-pro-0813",
        workload="implementer",
        temperature=1.0,
        max_tokens_cap=16384,
        reasoning_effort="max",
    ),
    ("nvidia/nemotron-3.5-lightning-30b-a3b", "recon"): NvidiaRequestProfile(
        name="nemotron-lightning-recon-fast",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        workload="recon",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_budget_fraction=0.25,
        reasoning_budget_cap=4096,
    ),
    ("nvidia/nemotron-3.5-lightning-30b-a3b", "test_writer"): NvidiaRequestProfile(
        name="nemotron-lightning-verification",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        workload="test_writer",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_budget_fraction=0.40,
        reasoning_budget_cap=8192,
    ),
    ("nvidia/nemotron-3-ultra-550b-a55b", "reviewer"): NvidiaRequestProfile(
        name="nemotron-ultra-review-high",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        workload="reviewer",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_effort="high",
        reasoning_budget_fraction=0.50,
        reasoning_budget_cap=16384,
    ),
    ("nvidia/nemotron-3-ultra-550b-a55b", "release_auditor"): NvidiaRequestProfile(
        name="nemotron-ultra-release-high",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        workload="release_auditor",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_effort="high",
        reasoning_budget_fraction=0.60,
        reasoning_budget_cap=16384,
    ),
}


MODEL_DEFAULTS = {
    "moonshotai/kimi-k3": NvidiaRequestProfile(
        name="kimi-k3-default-high",
        model="moonshotai/kimi-k3",
        workload="default",
        temperature=1.0,
        max_tokens_cap=65536,
        reasoning_effort="high",
    ),
    "deepseek-ai/deepseek-v4-pro-0813": NvidiaRequestProfile(
        name="deepseek-v4-pro-default-high",
        model="deepseek-ai/deepseek-v4-pro-0813",
        workload="default",
        temperature=1.0,
        max_tokens_cap=16384,
        reasoning_effort="high",
    ),
    "nvidia/nemotron-3.5-lightning-30b-a3b": NvidiaRequestProfile(
        name="nemotron-lightning-default",
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        workload="default",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_budget_fraction=0.30,
        reasoning_budget_cap=8192,
    ),
    "nvidia/nemotron-3-ultra-550b-a55b": NvidiaRequestProfile(
        name="nemotron-ultra-default-medium",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        workload="default",
        temperature=1.0,
        max_tokens_cap=32768,
        reasoning_effort="medium",
        reasoning_budget_fraction=0.40,
        reasoning_budget_cap=16384,
    ),
}


class NvidiaRequestProfileError(provider_router.ProviderConfigError):
    """Raised when a curated NVIDIA request cannot be constructed safely."""


def infer_workload(system: str | None) -> str:
    normalized = (system or "").casefold()
    for marker, workload in ROLE_MARKERS:
        if marker in normalized:
            return workload
    return "default"


def resolve_profile(model: str, *, system: str | None = None, workload: str | None = None) -> NvidiaRequestProfile | None:
    resolved_workload = workload or infer_workload(system)
    return PROFILES.get((model, resolved_workload)) or MODEL_DEFAULTS.get(model)


def _reasoning_budget(profile: NvidiaRequestProfile, effective_max_tokens: int) -> int | None:
    fraction = profile.reasoning_budget_fraction
    cap = profile.reasoning_budget_cap
    if fraction is None or cap is None:
        return None
    # Keep at least half of the completion ceiling available for the final answer.
    budget = min(cap, max(1, int(effective_max_tokens * fraction)), max(1, effective_max_tokens // 2))
    return budget


def build_profiled_request(
    selected: provider_router.WorkerProvider,
    *,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 8192,
    temperature: float | None = None,
    workload: str | None = None,
) -> tuple[dict[str, object], NvidiaRequestProfile | None]:
    if selected.name != "nvidia":
        raise NvidiaRequestProfileError("NVIDIA request profiles require the nvidia provider")
    if max_tokens <= 0:
        raise NvidiaRequestProfileError("max_tokens must be positive")

    profile = resolve_profile(selected.model, system=system, workload=workload)
    if profile is None:
        fallback_temperature = 0.2 if temperature is None else temperature
        if not 0 <= fallback_temperature <= 1:
            raise NvidiaRequestProfileError("NVIDIA temperature must be between 0 and 1")
        return (
            provider_router.build_chat_request(
                selected,
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=fallback_temperature,
            ),
            None,
        )

    effective_temperature = profile.temperature if temperature is None else temperature
    if not 0 <= effective_temperature <= 1:
        raise NvidiaRequestProfileError("NVIDIA temperature must be between 0 and 1")
    effective_max_tokens = min(max_tokens, profile.max_tokens_cap)
    payload = provider_router.build_chat_request(
        selected,
        prompt=prompt,
        system=system,
        max_tokens=effective_max_tokens,
        temperature=effective_temperature,
    )
    if profile.reasoning_effort is not None:
        payload["reasoning_effort"] = profile.reasoning_effort
    budget = _reasoning_budget(profile, effective_max_tokens)
    if budget is not None:
        payload["reasoning_budget"] = budget
    return payload, profile


def call_profiled(
    selected: provider_router.WorkerProvider,
    *,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 8192,
    temperature: float | None = None,
    timeout: float = 120.0,
    env: Mapping[str, str] | None = None,
    workload: str | None = None,
) -> dict[str, object]:
    """Execute one curated NVIDIA NIM request with model-aware parameters."""
    if not 0 < timeout <= 600:
        raise NvidiaRequestProfileError("timeout must be greater than 0 and at most 600 seconds")
    payload, profile = build_profiled_request(
        selected,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        workload=workload,
    )
    endpoint = selected.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {selected.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "mado-loop/1.0 nvidia-request-profiles",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise provider_router.ProviderCallError(f"nvidia returned HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise provider_router.ProviderCallError(f"nvidia request failed: {exc.reason}") from exc

    try:
        decoded = json.loads(raw)
        content = decoded["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise provider_router.ProviderCallError("nvidia returned an unexpected response shape") from exc
    return {
        "provider": selected.public_dict(),
        "content": content,
        "usage": decoded.get("usage"),
        "request_profile": profile.public_dict() if profile else None,
    }
