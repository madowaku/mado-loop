"""Deterministic Loop Budget ledger for MADO LOOP orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .result import make_check


_BUDGET_FIELDS = {
    "repair_cycles": "max_repair_cycles",
    "same_failure_repairs": "max_same_failure_repairs",
    "file_reversals": "max_file_reversals",
    "asset_regenerations": "max_asset_regenerations",
    "full_video_inspections": "max_full_video_inspections",
}


@dataclass(frozen=True)
class BudgetPolicy:
    """Per-invocation hard ceilings for repair and expensive evidence work."""

    max_repair_cycles: int = 5
    max_same_failure_repairs: int = 2
    max_file_reversals: int = 2
    max_asset_regenerations: int = 3
    max_full_video_inspections: int = 1

    def __post_init__(self) -> None:
        for name, value in self.as_dict().items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def as_dict(self) -> dict[str, int]:
        return {
            "asset_regenerations": self.max_asset_regenerations,
            "file_reversals": self.max_file_reversals,
            "full_video_inspections": self.max_full_video_inspections,
            "repair_cycles": self.max_repair_cycles,
            "same_failure_repairs": self.max_same_failure_repairs,
        }

    def with_override(self, name: str, value: int) -> "BudgetPolicy":
        """Return a policy with one explicitly raised per-invocation limit."""
        if name not in _BUDGET_FIELDS:
            raise ValueError(f"unknown budget: {name!r}")
        current = self.as_dict()[name]
        if not isinstance(value, int) or isinstance(value, bool) or value <= current:
            raise ValueError("a budget override must explicitly raise the current positive limit")
        return replace(self, **{_BUDGET_FIELDS[name]: value})


DEFAULT_BUDGET_POLICY = BudgetPolicy()


def _key(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


@dataclass
class BudgetLedger:
    """Track one MADO LOOP invocation without estimating unavailable token counts."""

    policy: BudgetPolicy = field(default_factory=BudgetPolicy)
    repair_cycles: int = 0
    same_failure_repairs: dict[str, int] = field(default_factory=dict)
    file_reversals: dict[str, int] = field(default_factory=dict)
    asset_regenerations: dict[str, int] = field(default_factory=dict)
    full_video_inspections: int = 0
    context_checkpoints: int = 0
    blocked_reasons: list[str] = field(default_factory=list)

    def _block(self, reason: str) -> bool:
        if reason not in self.blocked_reasons:
            self.blocked_reasons.append(reason)
            self.blocked_reasons.sort()
        return False

    def try_repair(self, failure_signature: str) -> bool:
        """Consume one repair cycle if both total and same-failure budgets allow it."""
        signature = _key(failure_signature, "failure_signature")
        if self.repair_cycles >= self.policy.max_repair_cycles:
            return self._block(
                f"repair_cycles limit {self.policy.max_repair_cycles} would be exceeded"
            )
        same_count = self.same_failure_repairs.get(signature, 0)
        if same_count >= self.policy.max_same_failure_repairs:
            return self._block(
                "same_failure_repairs limit "
                f"{self.policy.max_same_failure_repairs} would be exceeded for {signature}"
            )
        self.repair_cycles += 1
        self.same_failure_repairs[signature] = same_count + 1
        return True

    def try_file_reversal(self, path: str) -> bool:
        """Consume one reversal allowance for a file before applying the reversal."""
        key = _key(path, "path")
        count = self.file_reversals.get(key, 0)
        if count >= self.policy.max_file_reversals:
            return self._block(
                f"file_reversals limit {self.policy.max_file_reversals} would be exceeded for {key}"
            )
        self.file_reversals[key] = count + 1
        return True

    def try_asset_regeneration(self, asset_id: str) -> bool:
        """Consume one generation allowance for the same logical visual asset."""
        key = _key(asset_id, "asset_id")
        count = self.asset_regenerations.get(key, 0)
        if count >= self.policy.max_asset_regenerations:
            return self._block(
                "asset_regenerations limit "
                f"{self.policy.max_asset_regenerations} would be exceeded for {key}"
            )
        self.asset_regenerations[key] = count + 1
        return True

    def try_full_video_inspection(self) -> bool:
        """Consume the last-resort full-video inspection allowance."""
        if self.full_video_inspections >= self.policy.max_full_video_inspections:
            return self._block(
                "full_video_inspections limit "
                f"{self.policy.max_full_video_inspections} would be exceeded"
            )
        self.full_video_inspections += 1
        return True

    def reject_nested_invocation(self) -> bool:
        """Record the non-overridable re-entry guard and reject recursion."""
        return self._block("nested MADO LOOP invocation is forbidden while a run is active")

    def record_context_checkpoint(self) -> None:
        """Record a meaningful compaction boundary; checkpoints have no retry budget."""
        self.context_checkpoints += 1

    def overrides(self) -> dict[str, int]:
        defaults = DEFAULT_BUDGET_POLICY.as_dict()
        return {
            name: value
            for name, value in self.policy.as_dict().items()
            if value != defaults[name]
        }

    def state(self) -> dict[str, Any]:
        """Return a deterministic, compact handoff-friendly snapshot."""
        return {
            "status": "UNKNOWN" if self.blocked_reasons else "PASS",
            "limits": self.policy.as_dict(),
            "usage": {
                "asset_regenerations": dict(sorted(self.asset_regenerations.items())),
                "context_checkpoints": self.context_checkpoints,
                "file_reversals": dict(sorted(self.file_reversals.items())),
                "full_video_inspections": self.full_video_inspections,
                "repair_cycles": self.repair_cycles,
                "same_failure_repairs": dict(sorted(self.same_failure_repairs.items())),
            },
            "overrides": self.overrides(),
            "blocked_reasons": list(self.blocked_reasons),
        }

    def to_check(self) -> dict[str, Any]:
        """Build the required schema-v1.1-compatible loop-budget check."""
        snapshot = self.state()
        blocked = snapshot["blocked_reasons"]
        return make_check(
            "orchestrator.loop_budget",
            snapshot["status"],
            required=True,
            message=(
                "Loop Budget is within the authorized envelope."
                if not blocked
                else "Loop Budget stopped further automatic work."
            ),
            evidence=blocked,
            details={
                "limits": snapshot["limits"],
                "overrides": snapshot["overrides"],
                "usage": snapshot["usage"],
            },
        )
