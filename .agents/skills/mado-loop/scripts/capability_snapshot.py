"""Build an observational MADO Capability Snapshot.

G2 composes declared CapabilityManifest records, sanitized local probe results,
and optional source-bound qualification records. It is intentionally read-only:
a snapshot does not grant authority, select a strategy, lower proof requirements,
or promote PROBED availability to QUALIFIED.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from capability_manifest import DEFAULT_REGISTRY, SKILL_ROOT, load_registry, probe_manifest

SNAPSHOT_SCHEMA_VERSION = "1.0"
QUALIFICATION_SCHEMA_VERSION = "1.0"
DECISIONS = {"QUALIFY", "CANARY", "ADOPT", "HOLD", "DEGRADE", "RETIRE"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SnapshotError(ValueError):
    """Raised when snapshot inputs violate the G2 contract."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    return _digest(dict(manifest))


def _string_list(value: Any, *, label: str, nonempty: bool = False) -> list[str]:
    _expect(isinstance(value, list), f"{label} must be an array")
    items: list[str] = []
    for item in value:
        _expect(isinstance(item, str) and bool(item.strip()), f"{label} values must be non-empty strings")
        items.append(item)
    _expect(len(items) == len(set(items)), f"{label} must not contain duplicates")
    if nonempty:
        _expect(bool(items), f"{label} must not be empty")
    return items


def validate_qualification_source(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "qualification source must be an object")
    _expect(set(value) == {"schema_version", "source_id", "records"}, "qualification source keys are invalid")
    _expect(value.get("schema_version") == QUALIFICATION_SCHEMA_VERSION, "unsupported qualification schema_version")
    source_id = value.get("source_id")
    _expect(isinstance(source_id, str) and ID_RE.fullmatch(source_id) is not None, "qualification source_id is invalid")
    raw_records = value.get("records")
    _expect(isinstance(raw_records, list), "qualification records must be an array")

    records: list[dict[str, Any]] = []
    record_ids: list[str] = []
    for index, raw in enumerate(raw_records):
        label = f"records[{index}]"
        _expect(isinstance(raw, dict), f"{label} must be an object")
        required = {
            "schema_version", "id", "capability_id", "scope", "decision",
            "bound_manifest_digest", "basis", "approved_by",
        }
        _expect(set(raw) == required, f"{label} keys are invalid")
        _expect(raw.get("schema_version") == QUALIFICATION_SCHEMA_VERSION, f"{label}.schema_version is invalid")

        record_id = raw.get("id")
        capability_id = raw.get("capability_id")
        scope = raw.get("scope")
        decision = raw.get("decision")
        bound_digest = raw.get("bound_manifest_digest")
        approved_by = raw.get("approved_by")
        _expect(isinstance(record_id, str) and ID_RE.fullmatch(record_id) is not None, f"{label}.id is invalid")
        _expect(isinstance(capability_id, str) and ID_RE.fullmatch(capability_id) is not None, f"{label}.capability_id is invalid")
        _expect(isinstance(scope, str) and SCOPE_RE.fullmatch(scope) is not None, f"{label}.scope is invalid")
        _expect(isinstance(decision, str) and decision in DECISIONS, f"{label}.decision is invalid")
        _expect(isinstance(bound_digest, str) and DIGEST_RE.fullmatch(bound_digest) is not None, f"{label}.bound_manifest_digest is invalid")
        _expect(isinstance(approved_by, str) and bool(approved_by.strip()), f"{label}.approved_by is invalid")

        basis_raw = raw.get("basis")
        _expect(isinstance(basis_raw, dict), f"{label}.basis must be an object")
        _expect(set(basis_raw).issubset({"experiments", "evidence"}), f"{label}.basis has unknown fields")
        _expect("experiments" in basis_raw, f"{label}.basis.experiments is required")
        basis = {
            "experiments": _string_list(basis_raw.get("experiments"), label=f"{label}.basis.experiments", nonempty=True),
            "evidence": _string_list(basis_raw.get("evidence", []), label=f"{label}.basis.evidence"),
        }

        record_ids.append(record_id)
        records.append({
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "id": record_id,
            "capability_id": capability_id,
            "scope": scope,
            "decision": decision,
            "bound_manifest_digest": bound_digest,
            "basis": basis,
            "approved_by": approved_by,
        })

    _expect(len(record_ids) == len(set(record_ids)), "qualification record ids must be unique within a source")
    records.sort(key=lambda item: item["id"])
    return {"schema_version": QUALIFICATION_SCHEMA_VERSION, "source_id": source_id, "records": records}


def load_qualification_source(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"qualification source is not valid JSON: {source_path}: {exc}") from exc
    normalized = validate_qualification_source(payload)
    return {"path": str(source_path), "digest": _digest(normalized), **normalized}


def _normalize_observed_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError("observed_at must be an ISO-8601 date-time") from exc
    _expect(parsed.tzinfo is not None, "observed_at must include a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def build_snapshot(
    registry: Mapping[str, Any],
    *,
    qualification_sources: Sequence[Mapping[str, Any]] = (),
    probe: bool = True,
    observed_at: str | None = None,
    env: Mapping[str, str] | None = None,
    which=None,
    skill_root: Path = SKILL_ROOT,
) -> dict[str, Any]:
    # load_registry already provides normalized registries in the CLI path. Reuse
    # the public G1 validator without creating a second manifest dialect.
    from capability_manifest import validate_registry

    normalized_registry = validate_registry(dict(registry))
    registry_digest = _digest(normalized_registry)
    manifests = {item["id"]: item for item in normalized_registry["capabilities"]}
    manifest_digests = {capability_id: manifest_digest(item) for capability_id, item in manifests.items()}

    normalized_sources: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_records: set[str] = set()
    records_by_capability: dict[str, list[dict[str, Any]]] = {item: [] for item in manifests}

    for raw_source in qualification_sources:
        # Accept either a normalized in-memory source or the object returned by
        # load_qualification_source(). Local paths never enter the snapshot.
        source_payload = {
            "schema_version": raw_source.get("schema_version"),
            "source_id": raw_source.get("source_id"),
            "records": raw_source.get("records"),
        }
        source = validate_qualification_source(source_payload)
        source_id = source["source_id"]
        _expect(source_id not in seen_sources, f"duplicate qualification source_id: {source_id}")
        seen_sources.add(source_id)
        source_digest = str(raw_source.get("digest") or _digest(source))
        _expect(DIGEST_RE.fullmatch(source_digest) is not None, f"qualification source digest is invalid: {source_id}")
        normalized_sources.append({"source_id": source_id, "digest": source_digest, "records": len(source["records"])})

        for record in source["records"]:
            record_id = record["id"]
            _expect(record_id not in seen_records, f"duplicate qualification record id across sources: {record_id}")
            seen_records.add(record_id)
            capability_id = record["capability_id"]
            _expect(capability_id in manifests, f"qualification references unknown capability: {capability_id}")
            current_digest = manifest_digests[capability_id]
            records_by_capability[capability_id].append({
                "record_id": record_id,
                "source_id": source_id,
                "source_digest": source_digest,
                "scope": record["scope"],
                "decision": record["decision"],
                "binding_state": "ACTIVE" if record["bound_manifest_digest"] == current_digest else "STALE",
                "bound_manifest_digest": record["bound_manifest_digest"],
                "basis": record["basis"],
                "approved_by": record["approved_by"],
            })

    normalized_sources.sort(key=lambda item: item["source_id"])
    capabilities: list[dict[str, Any]] = []
    for capability_id in sorted(manifests):
        manifest = manifests[capability_id]
        if probe:
            kwargs: dict[str, Any] = {"env": env, "skill_root": skill_root}
            if which is not None:
                kwargs["which"] = which
            availability = probe_manifest(manifest, **kwargs)
        else:
            availability = {
                "capability_id": capability_id,
                "declared_state": manifest["availability"]["state"],
                "effective_state": manifest["availability"]["state"],
                "probe_type": None,
                "observed": {},
            }
        qualifications = sorted(records_by_capability[capability_id], key=lambda item: (item["scope"], item["record_id"]))
        capabilities.append({
            "id": capability_id,
            "kind": manifest["kind"],
            "manifest_digest": manifest_digests[capability_id],
            "availability": availability,
            "qualifications": qualifications,
        })

    semantic_state = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "registry_id": normalized_registry["registry_id"],
        "registry_digest": registry_digest,
        "sources": {
            "registry": {"digest": registry_digest},
            "qualifications": normalized_sources,
        },
        "capabilities": capabilities,
    }
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "registry_id": normalized_registry["registry_id"],
        "registry_digest": registry_digest,
        "observed_at": _normalize_observed_at(observed_at),
        "state_digest": _digest(semantic_state),
        "sources": semantic_state["sources"],
        "capabilities": capabilities,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--qualification", action="append", default=[], help="source-bound qualification JSON; repeatable")
    parser.add_argument("--no-probe", action="store_true", help="snapshot declarations without local availability probes")
    parser.add_argument("--observed-at", help="explicit ISO-8601 timestamp for reproducible fixtures")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        registry = load_registry(args.registry)
        sources = [load_qualification_source(path) for path in args.qualification]
        payload = build_snapshot(
            registry,
            qualification_sources=sources,
            probe=not args.no_probe,
            observed_at=args.observed_at,
        )
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except (SnapshotError, OSError, ValueError) as exc:
        sys.stderr.write(f"capability_snapshot configuration error: {exc}\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
