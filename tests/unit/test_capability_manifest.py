from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills" / "mado-loop"
MODULE_PATH = SKILL_ROOT / "scripts" / "capability_manifest.py"
REGISTRY_PATH = SKILL_ROOT / "capabilities" / "registry-v2.json"
SCHEMA_PATH = SKILL_ROOT / "capabilities" / "capability-manifest-v2.schema.json"

SPEC = importlib.util.spec_from_file_location("capability_manifest", MODULE_PATH)
capability = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(capability)


LEGACY_NAMES = {
    "MADO LOOP orchestrator",
    "Godot skill snapshot and first-party adapter",
    "Sprite production guidance",
    "Agent Sprite Forge processor and first-party adapter",
    "Game UI guidance",
    "Game playtest guidance",
    "Product Design image-to-code concepts",
    "Generic pixel-art rules",
    "ImageGen",
    "External image editor",
    "OpenRouter worker",
    "NVIDIA NIM hosted worker",
    "Empero logged free worker",
    "Local OpenAI-compatible worker",
    "Parallel worker swarm",
    "Adaptive worker swarm",
    "Installed specialist skill",
    "Agent Skills Hub registry",
}


class CapabilityManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = capability.load_registry(REGISTRY_PATH)
        self.by_id = {item["id"]: item for item in self.registry["capabilities"]}

    def test_builtin_registry_covers_legacy_registry_and_growth_capabilities(self) -> None:
        self.assertEqual("2.0", self.registry["schema_version"])
        self.assertEqual("mado-loop.default", self.registry["registry_id"])
        self.assertEqual(21, len(self.registry["capabilities"]))
        self.assertEqual(
            LEGACY_NAMES,
            {item["legacy"]["name"] for item in self.registry["capabilities"] if "legacy" in item},
        )
        self.assertIn("runtime.ovp-mutation", self.by_id)
        self.assertIn("observer.visual-broker", self.by_id)
        self.assertIn("observer.release-audit", self.by_id)

    def test_schema_is_json_and_tracks_v2(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("2.0", schema["properties"]["schema_version"]["const"])

    def test_first_party_file_probes_bind_to_real_installed_skill_files(self) -> None:
        probed = []
        for manifest in self.registry["capabilities"]:
            probe = manifest["availability"].get("probe")
            if probe and probe["type"] == "file_all":
                result = capability.probe_manifest(manifest, skill_root=SKILL_ROOT)
                self.assertEqual("PROBED", result["effective_state"], manifest["id"])
                probed.append(manifest["id"])
        self.assertIn("adapter.sprite-forge", probed)
        self.assertIn("runtime.ovp-mutation", probed)

    def test_probe_success_never_self_promotes_to_qualified(self) -> None:
        result = capability.probe_manifest(self.by_id["runtime.orchestrator"])
        self.assertEqual("DECLARED", result["declared_state"])
        self.assertEqual("PROBED", result["effective_state"])
        self.assertNotEqual("QUALIFIED", result["effective_state"])

    def test_provider_probe_never_exposes_environment_values(self) -> None:
        secret = "sk-example-do-not-leak"
        model = "provider/model-private"
        result = capability.probe_manifest(
            self.by_id["worker.openrouter"],
            env={"OPENROUTER_API_KEY": secret, "MADO_OPENROUTER_MODEL": model},
        )
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertEqual("PROBED", result["effective_state"])
        self.assertNotIn(secret, encoded)
        self.assertNotIn(model, encoded)
        self.assertIn("OPENROUTER_API_KEY", encoded)

    def test_secret_delegation_resolves_only_configured_local_worker(self) -> None:
        result = capability.resolve_capabilities(
            self.registry,
            features=["agent.delegate.proposal"],
            sensitivity="secret",
            probe=True,
            require_probed=True,
            env={
                "MADO_LOCAL_BASE_URL": "http://127.0.0.1:1234/v1",
                "MADO_LOCAL_MODEL": "local-model",
                "OPENROUTER_API_KEY": "external",
                "MADO_OPENROUTER_MODEL": "external/model",
            },
            which=lambda _name: None,
            skill_root=SKILL_ROOT,
        )
        self.assertEqual(["worker.local-openai"], [item["id"] for item in result["selected"]])

    def test_private_nvidia_requires_explicit_policy_token(self) -> None:
        env = {"NVIDIA_API_KEY": "secret", "MADO_NVIDIA_MODEL": "configured-model"}
        blocked = capability.resolve_capabilities(
            self.registry,
            features=["code.proposal"],
            sensitivity="private",
            probe=True,
            env=env,
            which=lambda _name: None,
            skill_root=SKILL_ROOT,
        )
        self.assertNotIn("worker.nvidia-nim", [item["id"] for item in blocked["selected"]])
        excluded = {item["id"]: item["reasons"] for item in blocked["excluded"]}
        self.assertIn("policy", excluded["worker.nvidia-nim"])

        allowed = capability.resolve_capabilities(
            self.registry,
            features=["code.proposal"],
            sensitivity="private",
            policies=["explicit.nvidia_private"],
            probe=True,
            require_probed=True,
            env=env,
            which=lambda _name: None,
            skill_root=SKILL_ROOT,
        )
        self.assertIn("worker.nvidia-nim", [item["id"] for item in allowed["selected"]])

    def test_declared_host_capability_is_not_treated_as_probed(self) -> None:
        result = capability.resolve_capabilities(
            self.registry,
            features=["image.generate"],
            sensitivity="public",
            probe=True,
            require_probed=True,
            env={},
            which=lambda _name: None,
            skill_root=SKILL_ROOT,
        )
        self.assertEqual([], result["selected"])
        excluded = {item["id"]: item["reasons"] for item in result["excluded"]}
        self.assertIn("not_probed", excluded["host.image-generation"])

    def test_provider_identity_is_provenance_not_semantic_feature(self) -> None:
        result = capability.resolve_capabilities(
            self.registry,
            features=["reasoning.text"],
            sensitivity="public",
        )
        ids = {item["id"] for item in result["selected"]}
        self.assertIn("worker.openrouter", ids)
        self.assertIn("worker.nvidia-nim", ids)
        self.assertNotIn("worker.empero", ids)  # explicit logged-free policy is still required

    def test_path_traversal_and_duplicate_ids_are_rejected(self) -> None:
        bad = dict(self.by_id["runtime.ovp-mutation"])
        bad["availability"] = {"state": "DECLARED", "probe": {"type": "file_all", "files": ["../escape"]}}
        with self.assertRaises(capability.ManifestError):
            capability.validate_manifest(bad)

        duplicated = {
            "schema_version": "2.0",
            "registry_id": "test.registry",
            "capabilities": [self.by_id["runtime.orchestrator"], self.by_id["runtime.orchestrator"]],
        }
        with self.assertRaises(capability.ManifestError):
            capability.validate_registry(duplicated)

    def test_cli_validate_emits_normalized_registry(self) -> None:
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout):
            code = capability.main(["--registry", str(REGISTRY_PATH), "validate"])
        self.assertEqual(0, code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual("PASS", payload["status"])
        self.assertEqual("2.0", payload["schema_version"])


if __name__ == "__main__":
    unittest.main()
