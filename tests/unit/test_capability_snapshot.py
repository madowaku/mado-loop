from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from capability_snapshot import (  # noqa: E402
    SnapshotError,
    build_snapshot,
    manifest_digest,
    validate_qualification_source,
)


def manifest(capability_id: str = "tool.alpha", *, probe: dict | None = None) -> dict:
    availability = {"state": "DECLARED"}
    if probe is not None:
        availability["probe"] = probe
    return {
        "schema_version": "2.0",
        "id": capability_id,
        "kind": "tool",
        "domains": ["CODE"],
        "features": ["code.inspect"],
        "provenance": {"source": "first-party", "implementation": "fixture"},
        "requirements": {"network": "none", "credentials": "none", "executables": [], "files": [], "env": []},
        "sensitivity_support": ["public", "private", "secret"],
        "evidence_interfaces": ["report"],
        "availability": availability,
    }


def registry(*items: dict) -> dict:
    return {"schema_version": "2.0", "registry_id": "test.registry", "capabilities": list(items)}


def qualification_source(item: dict, *, source_id: str = "lab.fixture") -> dict:
    return {"schema_version": "1.0", "source_id": source_id, "records": [item]}


def qualification_record(capability_id: str, digest: str, *, record_id: str = "growth.001", decision: str = "QUALIFY") -> dict:
    return {
        "schema_version": "1.0",
        "id": record_id,
        "capability_id": capability_id,
        "scope": "code.inspect",
        "decision": decision,
        "bound_manifest_digest": digest,
        "basis": {"experiments": ["exp-001"], "evidence": ["ev-001"]},
        "approved_by": "explicit-promotion-boundary",
    }


class CapabilitySnapshotTests(unittest.TestCase):
    def test_probe_and_qualification_are_separate_axes(self) -> None:
        item = manifest(probe={"type": "always"})
        digest = manifest_digest(item)
        source = qualification_source(qualification_record(item["id"], digest))
        snapshot = build_snapshot(
            registry(item),
            qualification_sources=[source],
            observed_at="2026-09-17T00:00:00Z",
        )
        capability = snapshot["capabilities"][0]
        self.assertEqual("PROBED", capability["availability"]["effective_state"])
        self.assertEqual("QUALIFY", capability["qualifications"][0]["decision"])
        self.assertEqual("ACTIVE", capability["qualifications"][0]["binding_state"])

    def test_qualification_never_promotes_declared_availability(self) -> None:
        item = manifest()
        digest = manifest_digest(item)
        source = qualification_source(qualification_record(item["id"], digest))
        snapshot = build_snapshot(
            registry(item), qualification_sources=[source], probe=False,
            observed_at="2026-09-17T00:00:00Z",
        )
        capability = snapshot["capabilities"][0]
        self.assertEqual("DECLARED", capability["availability"]["effective_state"])
        self.assertEqual("ACTIVE", capability["qualifications"][0]["binding_state"])

    def test_manifest_change_makes_old_qualification_stale(self) -> None:
        original = manifest()
        old_digest = manifest_digest(original)
        changed = manifest()
        changed["features"].append("code.propose")
        source = qualification_source(qualification_record(changed["id"], old_digest))
        snapshot = build_snapshot(
            registry(changed), qualification_sources=[source], probe=False,
            observed_at="2026-09-17T00:00:00Z",
        )
        qualification = snapshot["capabilities"][0]["qualifications"][0]
        self.assertEqual("STALE", qualification["binding_state"])
        self.assertNotEqual(old_digest, snapshot["capabilities"][0]["manifest_digest"])

    def test_probe_does_not_emit_environment_values(self) -> None:
        item = manifest(probe={"type": "env_requirements", "all": ["SECRET_TOKEN"], "any_groups": []})
        item["requirements"]["env"] = ["SECRET_TOKEN"]
        secret = "super-secret-value-never-emit"
        snapshot = build_snapshot(
            registry(item), env={"SECRET_TOKEN": secret},
            observed_at="2026-09-17T00:00:00Z",
        )
        encoded = json.dumps(snapshot, sort_keys=True)
        self.assertNotIn(secret, encoded)
        self.assertIn("SECRET_TOKEN", encoded)
        self.assertEqual("PROBED", snapshot["capabilities"][0]["availability"]["effective_state"])

    def test_state_digest_ignores_observation_timestamp(self) -> None:
        item = manifest(probe={"type": "always"})
        first = build_snapshot(registry(item), observed_at="2026-09-17T00:00:00Z")
        second = build_snapshot(registry(item), observed_at="2026-09-18T00:00:00Z")
        self.assertNotEqual(first["observed_at"], second["observed_at"])
        self.assertEqual(first["state_digest"], second["state_digest"])

    def test_unknown_capability_in_qualification_is_rejected(self) -> None:
        item = manifest()
        source = qualification_source(
            qualification_record("tool.missing", "sha256:" + "0" * 64)
        )
        with self.assertRaisesRegex(SnapshotError, "unknown capability"):
            build_snapshot(registry(item), qualification_sources=[source], probe=False)

    def test_duplicate_record_id_across_sources_is_rejected(self) -> None:
        item = manifest()
        digest = manifest_digest(item)
        record = qualification_record(item["id"], digest)
        with self.assertRaisesRegex(SnapshotError, "duplicate qualification record id"):
            build_snapshot(
                registry(item),
                qualification_sources=[
                    qualification_source(record, source_id="lab.one"),
                    qualification_source(record, source_id="lab.two"),
                ],
                probe=False,
            )

    def test_qualification_source_requires_experiment_basis(self) -> None:
        item = manifest()
        record = qualification_record(item["id"], manifest_digest(item))
        record["basis"] = {"evidence": ["ev-001"]}
        with self.assertRaisesRegex(SnapshotError, "experiments is required"):
            validate_qualification_source(qualification_source(record))


if __name__ == "__main__":
    unittest.main()
