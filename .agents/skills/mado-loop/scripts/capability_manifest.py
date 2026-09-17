"""Validate, probe, and resolve MADO CapabilityManifest v2 records.

G1 is intentionally advisory. It does not change routing, proof authority, or
permissions. A successful probe may raise availability to PROBED, never to
QUALIFIED, and capability resolution never grants authority.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable, Mapping, Sequence

SCHEMA_VERSION = "2.0"
KINDS = ("agent", "skill", "tool", "engine", "observer", "adapter", "environment")
DOMAINS = (
    "ALL",
    "CODE",
    "GAMEPLAY",
    "UI",
    "SPRITE",
    "IMAGE",
    "ANIMATION",
    "ASSET_INTEGRATION",
    "REFERENCE_TO_UI",
    "PIXEL_ART",
    "PLAYTEST",
    "RELEASE",
)
SENSITIVITIES = ("public", "private", "secret")
AVAILABILITY_STATES = (
    "UNKNOWN",
    "DECLARED",
    "PROBED",
    "QUALIFIED",
    "DEGRADED",
    "UNAVAILABLE",
    "RETIRED",
)
PROBE_TYPES = (
    "always",
    "file_all",
    "executable_any",
    "executables_all",
    "env_requirements",
    "env_path_or_executable",
)
NETWORK_MODES = ("none", "optional", "required")
CREDENTIAL_MODES = ("none", "optional", "required")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")

SCRIPT_PATH = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_REGISTRY = SKILL_ROOT / "capabilities" / "registry-v2.json"


class ManifestError(ValueError):
    """Raised when a capability manifest or registry violates the v2 contract."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _string_list(
    value: Any,
    *,
    label: str,
    allowed: set[str] | None = None,
    pattern: re.Pattern[str] | None = None,
    nonempty: bool = False,
) -> list[str]:
    _expect(isinstance(value, list), f"{label} must be an array")
    items = [str(item) for item in value]
    if nonempty:
        _expect(bool(items), f"{label} must not be empty")
    _expect(len(items) == len(set(items)), f"{label} must not contain duplicates")
    if allowed is not None:
        unknown = sorted(set(items).difference(allowed))
        _expect(not unknown, f"{label} contains unsupported values: {', '.join(unknown)}")
    if pattern is not None:
        _expect(all(pattern.fullmatch(item) for item in items), f"{label} contains invalid identifiers")
    return items


def _relative_paths(value: Any, *, label: str, nonempty: bool = False) -> list[str]:
    items = _string_list(value, label=label, nonempty=nonempty)
    for item in items:
        path = Path(item)
        _expect(not path.is_absolute(), f"{label} must contain relative paths")
        _expect(".." not in path.parts, f"{label} must not escape the capability root")
        _expect(bool(item.strip()), f"{label} contains an empty path")
    return items


def _validate_probe(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "availability.probe must be an object")
    probe_type = str(value.get("type", ""))
    _expect(probe_type in PROBE_TYPES, f"unsupported probe type: {probe_type!r}")

    if probe_type == "always":
        _expect(set(value) == {"type"}, "always probe accepts only type")
        return {"type": probe_type}

    if probe_type == "file_all":
        _expect(set(value) == {"type", "files"}, "file_all probe requires only type and files")
        return {
            "type": probe_type,
            "files": _relative_paths(value.get("files"), label="probe.files", nonempty=True),
        }

    if probe_type in {"executable_any", "executables_all"}:
        _expect(set(value) == {"type", "candidates"}, f"{probe_type} probe requires only type and candidates")
        candidates = _string_list(
            value.get("candidates"),
            label="probe.candidates",
            pattern=TOKEN_RE,
            nonempty=True,
        )
        return {"type": probe_type, "candidates": candidates}

    if probe_type == "env_requirements":
        _expect(
            set(value).issubset({"type", "all", "any_groups"}) and "type" in value,
            "env_requirements probe accepts type, all, and any_groups",
        )
        all_names = _string_list(value.get("all", []), label="probe.all", pattern=ENV_RE)
        raw_groups = value.get("any_groups", [])
        _expect(isinstance(raw_groups, list), "probe.any_groups must be an array")
        groups: list[list[str]] = []
        for index, group in enumerate(raw_groups):
            groups.append(
                _string_list(
                    group,
                    label=f"probe.any_groups[{index}]",
                    pattern=ENV_RE,
                    nonempty=True,
                )
            )
        _expect(bool(all_names or groups), "env_requirements probe needs at least one requirement")
        return {"type": probe_type, "all": all_names, "any_groups": groups}

    _expect(
        set(value) == {"type", "env", "candidates"},
        "env_path_or_executable probe requires type, env, and candidates",
    )
    env_names = _string_list(value.get("env"), label="probe.env", pattern=ENV_RE, nonempty=True)
    candidates = _string_list(
        value.get("candidates"),
        label="probe.candidates",
        pattern=TOKEN_RE,
        nonempty=True,
    )
    return {"type": probe_type, "env": env_names, "candidates": candidates}


def validate_manifest(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "capability manifest must be an object")
    required = {
        "schema_version",
        "id",
        "kind",
        "domains",
        "features",
        "provenance",
        "requirements",
        "sensitivity_support",
        "evidence_interfaces",
        "availability",
    }
    optional = {"policy_requirements", "legacy"}
    unknown = set(value).difference(required | optional)
    missing = required.difference(value)
    _expect(not missing, f"capability manifest missing fields: {', '.join(sorted(missing))}")
    _expect(not unknown, f"capability manifest has unknown fields: {', '.join(sorted(unknown))}")

    _expect(value.get("schema_version") == SCHEMA_VERSION, "unsupported capability schema_version")
    capability_id = str(value.get("id", ""))
    _expect(ID_RE.fullmatch(capability_id) is not None, "capability id is invalid")

    kind = str(value.get("kind", ""))
    _expect(kind in KINDS, f"unsupported capability kind: {kind!r}")

    domains = _string_list(
        value.get("domains"),
        label=f"{capability_id}.domains",
        allowed=set(DOMAINS),
        nonempty=True,
    )
    _expect("ALL" not in domains or domains == ["ALL"], "ALL must be the only domain when present")

    features = _string_list(
        value.get("features"),
        label=f"{capability_id}.features",
        pattern=TOKEN_RE,
        nonempty=True,
    )

    provenance_raw = value.get("provenance")
    _expect(isinstance(provenance_raw, dict), f"{capability_id}.provenance must be an object")
    _expect(
        set(provenance_raw).issubset({"source", "provider", "implementation", "version_policy"}),
        f"{capability_id}.provenance has unknown fields",
    )
    _expect(
        {"source", "implementation"}.issubset(provenance_raw),
        f"{capability_id}.provenance needs source and implementation",
    )
    provenance = {
        "source": str(provenance_raw["source"]),
        "implementation": str(provenance_raw["implementation"]),
    }
    _expect(bool(provenance["source"].strip()), f"{capability_id}.provenance.source must not be empty")
    _expect(bool(provenance["implementation"].strip()), f"{capability_id}.provenance.implementation must not be empty")
    if "provider" in provenance_raw:
        provenance["provider"] = str(provenance_raw["provider"])
    if "version_policy" in provenance_raw:
        provenance["version_policy"] = str(provenance_raw["version_policy"])

    requirements_raw = value.get("requirements")
    _expect(isinstance(requirements_raw, dict), f"{capability_id}.requirements must be an object")
    _expect(
        set(requirements_raw) == {"network", "credentials", "executables", "files", "env"},
        f"{capability_id}.requirements must contain network, credentials, executables, files, and env",
    )
    network = str(requirements_raw.get("network", ""))
    credentials = str(requirements_raw.get("credentials", ""))
    _expect(network in NETWORK_MODES, f"{capability_id}.requirements.network is invalid")
    _expect(credentials in CREDENTIAL_MODES, f"{capability_id}.requirements.credentials is invalid")
    requirements = {
        "network": network,
        "credentials": credentials,
        "executables": _string_list(
            requirements_raw.get("executables"),
            label=f"{capability_id}.requirements.executables",
            pattern=TOKEN_RE,
        ),
        "files": _relative_paths(
            requirements_raw.get("files"),
            label=f"{capability_id}.requirements.files",
        ),
        "env": _string_list(
            requirements_raw.get("env"),
            label=f"{capability_id}.requirements.env",
            pattern=ENV_RE,
        ),
    }

    sensitivity_support = _string_list(
        value.get("sensitivity_support"),
        label=f"{capability_id}.sensitivity_support",
        allowed=set(SENSITIVITIES),
        nonempty=True,
    )
    evidence_interfaces = _string_list(
        value.get("evidence_interfaces"),
        label=f"{capability_id}.evidence_interfaces",
        pattern=TOKEN_RE,
    )

    availability_raw = value.get("availability")
    _expect(isinstance(availability_raw, dict), f"{capability_id}.availability must be an object")
    _expect(set(availability_raw).issubset({"state", "probe"}), f"{capability_id}.availability has unknown fields")
    _expect("state" in availability_raw, f"{capability_id}.availability.state is required")
    state = str(availability_raw["state"]).upper()
    _expect(state in AVAILABILITY_STATES, f"{capability_id}.availability.state is invalid")
    availability: dict[str, Any] = {"state": state}
    if "probe" in availability_raw:
        availability["probe"] = _validate_probe(availability_raw["probe"])

    policy_requirements: dict[str, list[str]] = {}
    raw_policy = value.get("policy_requirements", {})
    _expect(isinstance(raw_policy, dict), f"{capability_id}.policy_requirements must be an object")
    for sensitivity, tokens in raw_policy.items():
        _expect(sensitivity in SENSITIVITIES, f"{capability_id}.policy_requirements has invalid sensitivity")
        _expect(
            sensitivity in sensitivity_support,
            f"{capability_id}.policy_requirements references unsupported sensitivity",
        )
        policy_requirements[sensitivity] = _string_list(
            tokens,
            label=f"{capability_id}.policy_requirements.{sensitivity}",
            pattern=TOKEN_RE,
            nonempty=True,
        )

    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "id": capability_id,
        "kind": kind,
        "domains": domains,
        "features": features,
        "provenance": provenance,
        "requirements": requirements,
        "sensitivity_support": sensitivity_support,
        "evidence_interfaces": evidence_interfaces,
        "availability": availability,
    }
    if policy_requirements:
        normalized["policy_requirements"] = policy_requirements

    if "legacy" in value:
        legacy_raw = value["legacy"]
        _expect(isinstance(legacy_raw, dict), f"{capability_id}.legacy must be an object")
        _expect(
            set(legacy_raw).issubset({"name", "mode", "absence_behavior"}),
            f"{capability_id}.legacy has unknown fields",
        )
        legacy = {key: str(item) for key, item in legacy_raw.items()}
        _expect(all(item.strip() for item in legacy.values()), f"{capability_id}.legacy values must not be empty")
        normalized["legacy"] = legacy
    return normalized


def validate_registry(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "capability registry must be an object")
    _expect(set(value) == {"schema_version", "registry_id", "capabilities"}, "registry keys are invalid")
    _expect(value.get("schema_version") == SCHEMA_VERSION, "unsupported registry schema_version")
    registry_id = str(value.get("registry_id", ""))
    _expect(ID_RE.fullmatch(registry_id) is not None, "registry_id is invalid")
    raw_capabilities = value.get("capabilities")
    _expect(isinstance(raw_capabilities, list), "capabilities must be an array")
    capabilities = [validate_manifest(item) for item in raw_capabilities]
    ids = [item["id"] for item in capabilities]
    _expect(len(ids) == len(set(ids)), "capability ids must be unique")
    capabilities.sort(key=lambda item: str(item["id"]))
    return {"schema_version": SCHEMA_VERSION, "registry_id": registry_id, "capabilities": capabilities}


def load_registry(path: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"registry is not valid JSON: {exc}") from exc
    return validate_registry(payload)


def _env_present(env: Mapping[str, str], name: str) -> bool:
    return bool((env.get(name) or "").strip())


def probe_manifest(
    manifest: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    skill_root: Path = SKILL_ROOT,
) -> dict[str, Any]:
    normalized = validate_manifest(dict(manifest))
    declared = str(normalized["availability"]["state"])
    if declared == "RETIRED":
        return {
            "capability_id": normalized["id"],
            "declared_state": declared,
            "effective_state": "RETIRED",
            "probe_type": None,
            "observed": {},
        }

    probe = normalized["availability"].get("probe")
    if probe is None:
        return {
            "capability_id": normalized["id"],
            "declared_state": declared,
            "effective_state": declared,
            "probe_type": None,
            "observed": {},
        }

    env_map = os.environ if env is None else env
    probe_type = str(probe["type"])
    observed: dict[str, Any] = {}

    try:
        if probe_type == "always":
            state = "PROBED"

        elif probe_type == "file_all":
            files = list(probe["files"])
            missing = [item for item in files if not (skill_root / item).is_file()]
            observed["checked_files"] = files
            observed["missing_files"] = missing
            state = "PROBED" if not missing else "UNAVAILABLE"

        elif probe_type == "executable_any":
            candidates = list(probe["candidates"])
            matched = next((item for item in candidates if which(item)), None)
            observed["candidates"] = candidates
            observed["matched"] = matched
            state = "PROBED" if matched else "UNAVAILABLE"

        elif probe_type == "executables_all":
            candidates = list(probe["candidates"])
            missing = [item for item in candidates if not which(item)]
            observed["candidates"] = candidates
            observed["missing"] = missing
            state = "PROBED" if not missing else "UNAVAILABLE"

        elif probe_type == "env_requirements":
            required_all = list(probe.get("all", []))
            missing_all = [name for name in required_all if not _env_present(env_map, name)]
            missing_groups: list[list[str]] = []
            for group in probe.get("any_groups", []):
                if not any(_env_present(env_map, name) for name in group):
                    missing_groups.append(list(group))
            observed["required_env"] = required_all
            observed["missing_env"] = missing_all
            observed["missing_any_groups"] = missing_groups
            state = "PROBED" if not missing_all and not missing_groups else "UNAVAILABLE"

        elif probe_type == "env_path_or_executable":
            env_names = list(probe["env"])
            configured = False
            for name in env_names:
                raw = (env_map.get(name) or "").strip()
                if raw and Path(raw).is_file():
                    configured = True
                    observed["matched_env"] = name
                    break
            matched_executable = None
            if not configured:
                matched_executable = next((item for item in probe["candidates"] if which(item)), None)
            observed["env"] = env_names
            observed["candidates"] = list(probe["candidates"])
            observed["matched_executable"] = matched_executable
            state = "PROBED" if configured or matched_executable else "UNAVAILABLE"

        else:  # validated above; defensive only
            state = "UNKNOWN"
            observed["error"] = "unsupported probe type"
    except OSError as exc:
        state = "UNKNOWN"
        observed = {"error_type": type(exc).__name__}

    return {
        "capability_id": normalized["id"],
        "declared_state": declared,
        "effective_state": state,
        "probe_type": probe_type,
        "observed": observed,
    }


def resolve_capabilities(
    registry: Mapping[str, Any],
    *,
    features: Sequence[str] = (),
    domain: str | None = None,
    sensitivity: str | None = None,
    policies: Sequence[str] = (),
    probe: bool = False,
    require_probed: bool = False,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    skill_root: Path = SKILL_ROOT,
) -> dict[str, Any]:
    normalized = validate_registry(dict(registry))
    required_features = set(_string_list(list(features), label="resolve.features", pattern=TOKEN_RE))
    policy_tokens = set(_string_list(list(policies), label="resolve.policies", pattern=TOKEN_RE))
    if domain is not None:
        _expect(domain in DOMAINS and domain != "ALL", "resolve.domain is invalid")
    if sensitivity is not None:
        _expect(sensitivity in SENSITIVITIES, "resolve.sensitivity is invalid")
    _expect(not require_probed or probe, "require_probed requires probe=True")

    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for manifest in normalized["capabilities"]:
        reasons: list[str] = []
        if not required_features.issubset(set(manifest["features"])):
            reasons.append("missing_feature")
        if domain is not None and "ALL" not in manifest["domains"] and domain not in manifest["domains"]:
            reasons.append("domain")
        if sensitivity is not None:
            if sensitivity not in manifest["sensitivity_support"]:
                reasons.append("sensitivity")
            else:
                required_policy = set(manifest.get("policy_requirements", {}).get(sensitivity, []))
                if not required_policy.issubset(policy_tokens):
                    reasons.append("policy")
        if manifest["availability"]["state"] == "RETIRED":
            reasons.append("retired")

        probe_result = None
        if probe and not reasons:
            probe_result = probe_manifest(manifest, env=env, which=which, skill_root=skill_root)
            effective = probe_result["effective_state"]
            if effective in {"UNAVAILABLE", "RETIRED"}:
                reasons.append("availability")
            if require_probed and effective not in {"PROBED", "QUALIFIED"}:
                reasons.append("not_probed")

        if reasons:
            excluded.append({"id": manifest["id"], "reasons": sorted(set(reasons))})
            continue

        selected.append(
            {
                "id": manifest["id"],
                "kind": manifest["kind"],
                "provenance": manifest["provenance"],
                "availability": (
                    probe_result
                    if probe_result is not None
                    else {
                        "capability_id": manifest["id"],
                        "declared_state": manifest["availability"]["state"],
                        "effective_state": manifest["availability"]["state"],
                        "probe_type": None,
                        "observed": {},
                    }
                ),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "registry_id": normalized["registry_id"],
        "criteria": {
            "features": sorted(required_features),
            "domain": domain,
            "sensitivity": sensitivity,
            "policies": sorted(policy_tokens),
            "probe": probe,
            "require_probed": require_probed,
        },
        "selected": selected,
        "excluded": excluded,
    }


def _print(payload: Mapping[str, Any], *, pretty: bool) -> None:
    if pretty:
        sys.stdout.write(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate and normalize the registry")
    sub.add_parser("list", help="list normalized capability manifests")

    probe_cmd = sub.add_parser("probe", help="probe availability without granting qualification")
    probe_cmd.add_argument("--id", action="append", dest="ids")

    resolve_cmd = sub.add_parser("resolve", help="advisory capability filtering only")
    resolve_cmd.add_argument("--feature", action="append", default=[])
    resolve_cmd.add_argument("--domain", choices=[item for item in DOMAINS if item != "ALL"])
    resolve_cmd.add_argument("--sensitivity", choices=SENSITIVITIES)
    resolve_cmd.add_argument("--policy", action="append", default=[])
    resolve_cmd.add_argument("--probe", action="store_true")
    resolve_cmd.add_argument("--require-probed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        registry = load_registry(args.registry)
        if args.command == "validate":
            _print({"status": "PASS", **registry}, pretty=args.pretty)
            return 0
        if args.command == "list":
            _print(
                {
                    "status": "PASS",
                    "schema_version": SCHEMA_VERSION,
                    "registry_id": registry["registry_id"],
                    "capabilities": registry["capabilities"],
                },
                pretty=args.pretty,
            )
            return 0
        if args.command == "probe":
            requested = set(args.ids or [])
            known = {item["id"] for item in registry["capabilities"]}
            unknown = sorted(requested.difference(known))
            _expect(not unknown, f"unknown capability ids: {', '.join(unknown)}")
            manifests = [
                item
                for item in registry["capabilities"]
                if not requested or item["id"] in requested
            ]
            payload = {
                "status": "PASS",
                "schema_version": SCHEMA_VERSION,
                "registry_id": registry["registry_id"],
                "probes": [probe_manifest(item) for item in manifests],
            }
            _print(payload, pretty=args.pretty)
            return 0

        payload = resolve_capabilities(
            registry,
            features=args.feature,
            domain=args.domain,
            sensitivity=args.sensitivity,
            policies=args.policy,
            probe=args.probe,
            require_probed=args.require_probed,
        )
        _print({"status": "PASS", **payload}, pretty=args.pretty)
        return 0
    except (ManifestError, OSError) as exc:
        sys.stderr.write(f"capability_manifest configuration error: {exc}\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
