"""Build advisory strategy candidates from Intent, Authority, and Capability Snapshot.

G3 is a shadow/advisory layer. It does not execute a strategy, grant authority,
select a provider/model, lower proof requirements, or replace MADO LOOP 1.x
routing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from capability_manifest import (  # noqa: E402
    DEFAULT_REGISTRY,
    DOMAINS,
    SENSITIVITIES,
    load_registry,
    validate_registry,
)

SCHEMA_VERSION = "1.0"
INTENT_SCHEMA_VERSION = "1.0"
AUTHORITY_SCHEMA_VERSION = "1.0"
SNAPSHOT_SCHEMA_VERSION = "1.0"
PROOF_LEVELS = ("P0", "P1", "P2", "P3", "P4", "P5")
WORK_MODES = ("observe", "propose", "modify", "release")
COORDINATION_PREFERENCES = ("minimal", "balanced", "parallel_ok")
CANDIDATE_STATES = ("READY", "CONDITIONAL", "BLOCKED")
SENSITIVITY_ORDER = {"public": 0, "private": 1, "secret": 2}

DOMAIN_REQUIRED_FEATURES = {
    "CODE": ("engine.project.inspect",),
    "GAMEPLAY": ("engine.project.inspect", "engine.runtime.execute"),
    "UI": ("engine.project.inspect", "evidence.layout"),
    "SPRITE": ("sprite.normalize",),
    "IMAGE": ("image.generate",),
    "ANIMATION": ("engine.runtime.execute",),
    "ASSET_INTEGRATION": ("engine.project.inspect",),
    "REFERENCE_TO_UI": ("guidance.reference_to_ui", "guidance.ui.design"),
    "PIXEL_ART": ("guidance.pixel_art",),
    "PLAYTEST": ("engine.runtime.execute",),
    "RELEASE": ("artifact.release.audit",),
}

PROOF_REQUIRED_FEATURES = {
    "P0": ("evidence.static",),
    "P1": ("evidence.static", "engine.runtime.execute"),
    "P2": ("evidence.static", "engine.runtime.execute", "evidence.layout"),
    "P3": ("evidence.static", "engine.runtime.execute", "evidence.behavior"),
    "P4": ("evidence.static", "engine.runtime.execute", "screenshot.capture"),
    "P5": ("evidence.static", "engine.runtime.execute", "artifact.export", "artifact.release.audit"),
}

PERMISSION_KEYS = (
    "read_repo",
    "write_isolated_workspace",
    "write_repo",
    "execute_tools",
    "delegate",
    "network",
    "integrate",
    "merge",
    "publish",
)


class StrategyResolverError(ValueError):
    """Raised when G3 inputs violate the advisory contract."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise StrategyResolverError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StrategyResolverError(f"{label} is not valid JSON: {source}: {exc}") from exc
    _expect(isinstance(payload, dict), f"{label} must be an object")
    return payload


def validate_intent(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "intent must be an object")
    required = {
        "schema_version",
        "id",
        "goal",
        "domains",
        "work_mode",
        "required_proof",
        "sensitivity",
        "acceptance",
        "preferences",
    }
    _expect(set(value) == required, "intent keys are invalid")
    _expect(value.get("schema_version") == INTENT_SCHEMA_VERSION, "unsupported intent schema_version")

    intent_id = value.get("id")
    goal = value.get("goal")
    domains = value.get("domains")
    work_mode = value.get("work_mode")
    required_proof = value.get("required_proof")
    sensitivity = value.get("sensitivity")
    acceptance = value.get("acceptance")
    preferences = value.get("preferences")

    _expect(isinstance(intent_id, str) and bool(intent_id.strip()), "intent.id is invalid")
    _expect(isinstance(goal, str) and bool(goal.strip()), "intent.goal is invalid")
    _expect(isinstance(domains, list) and bool(domains), "intent.domains must be a non-empty array")
    _expect(all(isinstance(item, str) and item in DOMAINS and item != "ALL" for item in domains), "intent.domains contains invalid domains")
    _expect(len(domains) == len(set(domains)), "intent.domains must not contain duplicates")
    _expect(work_mode in WORK_MODES, "intent.work_mode is invalid")
    _expect(required_proof in PROOF_LEVELS, "intent.required_proof is invalid")
    _expect(sensitivity in SENSITIVITIES, "intent.sensitivity is invalid")

    _expect(isinstance(acceptance, list), "intent.acceptance must be an array")
    normalized_acceptance: list[dict[str, Any]] = []
    acceptance_ids: set[str] = set()
    for index, item in enumerate(acceptance):
        label = f"intent.acceptance[{index}]"
        _expect(isinstance(item, dict), f"{label} must be an object")
        _expect(set(item) == {"id", "required", "claim"}, f"{label} keys are invalid")
        item_id = item.get("id")
        claim = item.get("claim")
        required_flag = item.get("required")
        _expect(isinstance(item_id, str) and bool(item_id.strip()), f"{label}.id is invalid")
        _expect(item_id not in acceptance_ids, "intent.acceptance ids must be unique")
        _expect(isinstance(required_flag, bool), f"{label}.required must be boolean")
        _expect(isinstance(claim, str) and bool(claim.strip()), f"{label}.claim is invalid")
        acceptance_ids.add(item_id)
        normalized_acceptance.append({"id": item_id, "required": required_flag, "claim": claim})

    _expect(isinstance(preferences, dict), "intent.preferences must be an object")
    _expect(set(preferences) == {"coordination"}, "intent.preferences keys are invalid")
    coordination = preferences.get("coordination")
    _expect(coordination in COORDINATION_PREFERENCES, "intent.preferences.coordination is invalid")

    return {
        "schema_version": INTENT_SCHEMA_VERSION,
        "id": intent_id.strip(),
        "goal": goal.strip(),
        "domains": list(domains),
        "work_mode": work_mode,
        "required_proof": required_proof,
        "sensitivity": sensitivity,
        "acceptance": normalized_acceptance,
        "preferences": {"coordination": coordination},
    }


def validate_authority(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "authority must be an object")
    required = {
        "schema_version",
        "subject",
        "permissions",
        "sensitivity_ceiling",
        "policy_tokens",
        "expires_on",
    }
    _expect(set(value) == required, "authority keys are invalid")
    _expect(value.get("schema_version") == AUTHORITY_SCHEMA_VERSION, "unsupported authority schema_version")

    subject = value.get("subject")
    permissions = value.get("permissions")
    sensitivity_ceiling = value.get("sensitivity_ceiling")
    policy_tokens = value.get("policy_tokens")
    expires_on = value.get("expires_on")

    _expect(isinstance(subject, str) and bool(subject.strip()), "authority.subject is invalid")
    _expect(isinstance(permissions, dict), "authority.permissions must be an object")
    _expect(set(permissions) == set(PERMISSION_KEYS), "authority.permissions keys are invalid")
    normalized_permissions: dict[str, bool] = {}
    for key in PERMISSION_KEYS:
        raw = permissions.get(key)
        _expect(isinstance(raw, bool), f"authority.permissions.{key} must be boolean")
        normalized_permissions[key] = raw

    _expect(sensitivity_ceiling in SENSITIVITIES, "authority.sensitivity_ceiling is invalid")
    _expect(isinstance(policy_tokens, list), "authority.policy_tokens must be an array")
    _expect(all(isinstance(item, str) and bool(item.strip()) for item in policy_tokens), "authority.policy_tokens values are invalid")
    _expect(len(policy_tokens) == len(set(policy_tokens)), "authority.policy_tokens must not contain duplicates")
    _expect(isinstance(expires_on, str) and bool(expires_on.strip()), "authority.expires_on is invalid")

    return {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "subject": subject.strip(),
        "permissions": normalized_permissions,
        "sensitivity_ceiling": sensitivity_ceiling,
        "policy_tokens": sorted(policy_tokens),
        "expires_on": expires_on.strip(),
    }


def validate_snapshot(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "snapshot must be an object")
    required = {
        "schema_version",
        "registry_id",
        "registry_digest",
        "observed_at",
        "state_digest",
        "sources",
        "capabilities",
    }
    _expect(set(value) == required, "snapshot keys are invalid")
    _expect(value.get("schema_version") == SNAPSHOT_SCHEMA_VERSION, "unsupported snapshot schema_version")
    _expect(isinstance(value.get("registry_id"), str) and bool(value["registry_id"]), "snapshot.registry_id is invalid")
    _expect(isinstance(value.get("registry_digest"), str) and value["registry_digest"].startswith("sha256:"), "snapshot.registry_digest is invalid")
    _expect(isinstance(value.get("state_digest"), str) and value["state_digest"].startswith("sha256:"), "snapshot.state_digest is invalid")
    _expect(isinstance(value.get("observed_at"), str) and bool(value["observed_at"]), "snapshot.observed_at is invalid")
    _expect(isinstance(value.get("sources"), dict), "snapshot.sources must be an object")
    capabilities = value.get("capabilities")
    _expect(isinstance(capabilities, list), "snapshot.capabilities must be an array")

    ids: set[str] = set()
    normalized_capabilities: list[dict[str, Any]] = []
    for index, item in enumerate(capabilities):
        label = f"snapshot.capabilities[{index}]"
        _expect(isinstance(item, dict), f"{label} must be an object")
        _expect(set(item) == {"id", "kind", "manifest_digest", "availability", "qualifications"}, f"{label} keys are invalid")
        capability_id = item.get("id")
        _expect(isinstance(capability_id, str) and bool(capability_id), f"{label}.id is invalid")
        _expect(capability_id not in ids, "snapshot capability ids must be unique")
        ids.add(capability_id)
        availability = item.get("availability")
        _expect(isinstance(availability, dict), f"{label}.availability must be an object")
        _expect(isinstance(availability.get("effective_state"), str), f"{label}.availability.effective_state is invalid")
        qualifications = item.get("qualifications")
        _expect(isinstance(qualifications, list), f"{label}.qualifications must be an array")
        normalized_capabilities.append(dict(item))

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "registry_id": value["registry_id"],
        "registry_digest": value["registry_digest"],
        "observed_at": value["observed_at"],
        "state_digest": value["state_digest"],
        "sources": value["sources"],
        "capabilities": normalized_capabilities,
    }


def _proof_features(level: str) -> tuple[str, ...]:
    # Higher proof levels include the lower gates relevant to the claim, not
    # every lower proof modality unconditionally. For example, release proof
    # does not inherently require motion capture.
    return PROOF_REQUIRED_FEATURES[level]


def required_features(intent: Mapping[str, Any]) -> tuple[str, ...]:
    ordered = ["strategy.coordinate"]
    for domain in intent["domains"]:
        for feature in DOMAIN_REQUIRED_FEATURES.get(str(domain), ()):
            if feature not in ordered:
                ordered.append(feature)
    for feature in _proof_features(str(intent["required_proof"])):
        if feature not in ordered:
            ordered.append(feature)
    return tuple(ordered)


def _authority_common_checks(intent: Mapping[str, Any], authority: Mapping[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    permitted = SENSITIVITY_ORDER[str(intent["sensitivity"])] <= SENSITIVITY_ORDER[str(authority["sensitivity_ceiling"])]
    checks.append({
        "id": "authority.sensitivity_ceiling",
        "status": "PASS" if permitted else "BLOCKED",
        "message": "intent sensitivity is within authority ceiling" if permitted else "intent sensitivity exceeds authority ceiling",
    })
    return checks


def _manifest_compatible(
    manifest: Mapping[str, Any],
    *,
    feature: str,
    intent: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> bool:
    if feature not in manifest["features"]:
        return False
    domains = set(manifest["domains"])
    if "ALL" not in domains and not domains.intersection(intent["domains"]):
        return False
    sensitivity = str(intent["sensitivity"])
    if sensitivity not in manifest["sensitivity_support"]:
        return False
    if manifest["requirements"]["network"] == "required" and not authority["permissions"]["network"]:
        return False
    required_policy = set(manifest.get("policy_requirements", {}).get(sensitivity, []))
    if not required_policy.issubset(set(authority["policy_tokens"])):
        return False
    return True


def _binding_for_feature(
    feature: str,
    *,
    manifests: Mapping[str, Mapping[str, Any]],
    snapshot_entries: Mapping[str, Mapping[str, Any]],
    intent: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for capability_id in sorted(manifests):
        manifest = manifests[capability_id]
        entry = snapshot_entries.get(capability_id)
        if entry is None or not _manifest_compatible(manifest, feature=feature, intent=intent, authority=authority):
            continue
        effective_state = str(entry["availability"]["effective_state"])
        if effective_state in {"UNAVAILABLE", "RETIRED"}:
            continue
        active_scopes = sorted({
            str(item.get("scope"))
            for item in entry.get("qualifications", [])
            if item.get("binding_state") == "ACTIVE"
        })
        matches.append({
            "capability_id": capability_id,
            "kind": manifest["kind"],
            "availability": effective_state,
            "active_qualification_scopes": active_scopes,
        })
    return {"feature": feature, "matches": matches}


def _candidate_state(
    bindings: Sequence[Mapping[str, Any]],
    authority_checks: Sequence[Mapping[str, str]],
    *,
    forced_conditional: bool = False,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if any(item["status"] == "BLOCKED" for item in authority_checks):
        reasons.append("authority_boundary")
    missing = [item["feature"] for item in bindings if not item["matches"]]
    if missing:
        reasons.append("missing_capability:" + ",".join(missing))
    if reasons:
        return "BLOCKED", reasons

    declared_only: list[str] = []
    degraded: list[str] = []
    for binding in bindings:
        states = {match["availability"] for match in binding["matches"]}
        if "PROBED" not in states:
            if states.intersection({"UNKNOWN", "DEGRADED"}):
                degraded.append(str(binding["feature"]))
            else:
                declared_only.append(str(binding["feature"]))
    if declared_only:
        reasons.append("unprobed_capability:" + ",".join(declared_only))
    if degraded:
        reasons.append("degraded_capability:" + ",".join(degraded))
    if forced_conditional:
        reasons.append("coordination_not_preferred")
    return ("CONDITIONAL" if reasons else "READY"), reasons


def _permission_checks(authority: Mapping[str, Any], required: Sequence[str]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    for permission in required:
        granted = bool(authority["permissions"][permission])
        checks.append({
            "id": f"authority.permission.{permission}",
            "status": "PASS" if granted else "BLOCKED",
            "message": "permission granted" if granted else "permission denied",
        })
    return checks


def _build_candidate(
    strategy: str,
    *,
    intent: Mapping[str, Any],
    authority: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]],
    snapshot_entries: Mapping[str, Mapping[str, Any]],
    extra_features: Sequence[str] = (),
    permissions: Sequence[str] = (),
    coordination: str,
    forced_block_reason: str | None = None,
    forced_conditional: bool = False,
) -> dict[str, Any]:
    features = list(required_features(intent))
    for feature in extra_features:
        if feature not in features:
            features.append(feature)
    bindings = [
        _binding_for_feature(
            feature,
            manifests=manifests,
            snapshot_entries=snapshot_entries,
            intent=intent,
            authority=authority,
        )
        for feature in features
    ]
    authority_checks = _authority_common_checks(intent, authority) + _permission_checks(authority, permissions)
    state, reasons = _candidate_state(bindings, authority_checks, forced_conditional=forced_conditional)
    if forced_block_reason is not None:
        state = "BLOCKED"
        reasons = [forced_block_reason, *reasons]
    _expect(state in CANDIDATE_STATES, "internal candidate state error")
    return {
        "id": f"strategy.{strategy}",
        "strategy": strategy,
        "state": state,
        "coordination": coordination,
        "required_features": features,
        "bindings": bindings,
        "authority_checks": authority_checks,
        "proof_target": intent["required_proof"],
        "reasons": reasons,
    }


def build_strategy_candidates(
    intent: Mapping[str, Any],
    authority: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_intent = validate_intent(dict(intent))
    normalized_authority = validate_authority(dict(authority))
    normalized_snapshot = validate_snapshot(dict(snapshot))
    normalized_registry = validate_registry(dict(registry))

    registry_digest = _digest(normalized_registry)
    _expect(normalized_snapshot["registry_id"] == normalized_registry["registry_id"], "snapshot registry_id does not match registry")
    _expect(normalized_snapshot["registry_digest"] == registry_digest, "snapshot registry_digest does not match registry")

    manifests = {item["id"]: item for item in normalized_registry["capabilities"]}
    snapshot_entries = {item["id"]: item for item in normalized_snapshot["capabilities"]}
    _expect(set(snapshot_entries).issubset(set(manifests)), "snapshot contains capabilities absent from registry")

    work_mode = normalized_intent["work_mode"]
    coordination_pref = normalized_intent["preferences"]["coordination"]
    candidates: list[dict[str, Any]] = []

    direct_block = "modify_requires_isolated_mutation_candidate" if work_mode == "modify" else None
    candidates.append(_build_candidate(
        "direct-agent-with-tools",
        intent=normalized_intent,
        authority=normalized_authority,
        manifests=manifests,
        snapshot_entries=snapshot_entries,
        permissions=("read_repo", "execute_tools"),
        coordination="single",
        forced_block_reason=direct_block,
    ))

    if work_mode == "modify":
        candidates.insert(0, _build_candidate(
            "isolated-mutation-agent",
            intent=normalized_intent,
            authority=normalized_authority,
            manifests=manifests,
            snapshot_entries=snapshot_entries,
            extra_features=("workspace.isolated.mutation", "repo.worktree", "review.boundary"),
            permissions=("read_repo", "write_isolated_workspace", "execute_tools"),
            coordination="single",
        ))

    candidates.append(_build_candidate(
        "single-delegate-proposal",
        intent=normalized_intent,
        authority=normalized_authority,
        manifests=manifests,
        snapshot_entries=snapshot_entries,
        extra_features=("agent.delegate.proposal",),
        permissions=("read_repo", "delegate"),
        coordination="single+delegate",
    ))

    candidates.append(_build_candidate(
        "adaptive-swarm",
        intent=normalized_intent,
        authority=normalized_authority,
        manifests=manifests,
        snapshot_entries=snapshot_entries,
        extra_features=("agent.delegate.proposal", "strategy.multi_agent.adaptive"),
        permissions=("read_repo", "delegate"),
        coordination="multi",
        forced_conditional=coordination_pref != "parallel_ok",
    ))

    return {
        "schema_version": SCHEMA_VERSION,
        "advisory_only": True,
        "intent_id": normalized_intent["id"],
        "intent_digest": _digest(normalized_intent),
        "authority_digest": _digest(normalized_authority),
        "snapshot_state_digest": normalized_snapshot["state_digest"],
        "registry_digest": registry_digest,
        "candidates": candidates,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True, help="Intent Contract v1 JSON")
    parser.add_argument("--authority", required=True, help="Authority Contract v1 JSON")
    parser.add_argument("--snapshot", required=True, help="Capability Snapshot v1 JSON")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="CapabilityManifest v2 registry")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        intent = _read_json(args.intent, label="intent")
        authority = _read_json(args.authority, label="authority")
        snapshot = _read_json(args.snapshot, label="snapshot")
        registry = load_registry(args.registry)
        payload = build_strategy_candidates(intent, authority, snapshot, registry)
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except (StrategyResolverError, OSError, ValueError) as exc:
        sys.stderr.write(f"strategy_resolver configuration error: {exc}\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
