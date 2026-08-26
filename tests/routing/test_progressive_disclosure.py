import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills" / "mado-loop"
MODULE_PATH = SKILL_ROOT / "scripts" / "classify_task.py"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
ARCHITECTURE_PATH = SKILL_ROOT / "references" / "routing" / "architecture.md"
REGISTRY_PATH = SKILL_ROOT / "references" / "routing" / "capability-registry.md"

SPEC = importlib.util.spec_from_file_location("mado_progressive_classifier", MODULE_PATH)
classifier = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(classifier)


DOMAIN_REFERENCES = {
    "IMAGE": {"references/production/art-direction.md"},
    "SPRITE": {"references/production/sprite-production.md"},
    "PIXEL_ART": {"references/production/pixel-art-profile.md"},
    "UI": {"references/production/game-ui.md"},
    "REFERENCE_TO_UI": {
        "references/production/image-to-game-ui.md",
        "references/production/game-ui.md",
    },
    "ASSET_INTEGRATION": {"references/production/asset-integration.md"},
    "GAMEPLAY": {"references/proof/gameplay-proof.md"},
    "PLAYTEST": {"references/proof/gameplay-proof.md"},
}


def selected_references(task):
    domains = classifier.classify_task(task)["task_domains"]
    selected = set()
    for domain in domains:
        selected.update(DOMAIN_REFERENCES.get(domain, set()))
    return domains, selected


def registry_rows():
    rows = {}
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[0] != "Capability":
            rows[cells[0]] = cells
    return rows


class ProgressiveDisclosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_text = SKILL_PATH.read_text(encoding="utf-8")
        cls.architecture_text = ARCHITECTURE_PATH.read_text(encoding="utf-8")
        cls.registry_text = REGISTRY_PATH.read_text(encoding="utf-8")

    def test_representative_routes_select_only_domain_references(self):
        cases = {
            "Tune player movement and combat": (
                ["GAMEPLAY"],
                {"references/proof/gameplay-proof.md"},
            ),
            "Normalize a pixel art sprite sheet": (
                ["SPRITE", "PIXEL_ART", "MIXED"],
                {
                    "references/production/sprite-production.md",
                    "references/production/pixel-art-profile.md",
                },
            ),
            "Prepare the release build": (["RELEASE"], set()),
        }
        for task, (expected_domains, expected_refs) in cases.items():
            with self.subTest(task=task):
                domains, references = selected_references(task)
                self.assertEqual(domains, expected_domains)
                self.assertEqual(references, expected_refs)
                for reference in references:
                    self.assertTrue((SKILL_ROOT / reference).is_file())

    def test_unrelated_specialists_are_not_disclosed(self):
        _, gameplay_refs = selected_references("Tune player movement and combat")
        self.assertNotIn("references/production/game-ui.md", gameplay_refs)
        self.assertNotIn("references/production/sprite-production.md", gameplay_refs)
        self.assertNotIn("references/production/art-direction.md", gameplay_refs)

    def test_multi_domain_route_composes_in_canonical_order(self):
        domains, references = selected_references(
            "Animate a pixel art sprite sheet and import asset settings"
        )
        self.assertEqual(
            domains,
            ["SPRITE", "ANIMATION", "ASSET_INTEGRATION", "PIXEL_ART", "MIXED"],
        )
        self.assertEqual(domains[-1], "MIXED")
        self.assertEqual(
            references,
            {
                "references/production/sprite-production.md",
                "references/production/pixel-art-profile.md",
                "references/production/asset-integration.md",
            },
        )

    def test_reference_to_ui_composes_ui_and_asset_integration(self):
        domains, references = selected_references(
            "Turn a screenshot to UI and import asset settings"
        )
        self.assertEqual(
            domains, ["UI", "ASSET_INTEGRATION", "REFERENCE_TO_UI", "MIXED"]
        )
        self.assertEqual(
            references,
            {
                "references/production/game-ui.md",
                "references/production/image-to-game-ui.md",
                "references/production/asset-integration.md",
            },
        )
        self.assertIn(
            "`REFERENCE_TO_UI + UI + ASSET_INTEGRATION`",
            self.architecture_text,
        )

    def test_missing_imagegen_is_optional_and_does_not_affect_nonvisual_route(self):
        domains, references = selected_references("Refactor GDScript code")
        self.assertEqual(domains, ["CODE"])
        self.assertEqual(references, set())

        imagegen = registry_rows()["ImageGen"]
        self.assertEqual(imagegen[2], "Optional routed capability")
        self.assertIn("Optional `SKIPPED` plus warning", imagegen[4])
        optional_check = classifier.make_check(
            "capability.imagegen",
            "SKIPPED",
            required=False,
            message="ImageGen is unavailable and was not required by this route.",
        )
        result = classifier.make_result(
            "progressive-disclosure-test",
            proof_level="P0",
            summary="The nonvisual route remains valid.",
            task_domains=domains,
            checks=[optional_check],
        )
        self.assertEqual(result["status"], "WARN")
        self.assertEqual(result["unknowns"], [])

    def test_routing_contract_requires_no_install_or_network(self):
        combined = self.skill_text + self.architecture_text + self.registry_text
        self.assertIn("Do not install or invoke it without availability and authority", combined)
        self.assertIn("Never auto-install a skill, plugin, registry entry", combined)
        self.assertIn("Agent Skills Hub registry", self.registry_text)
        self.assertRegex(
            self.registry_text,
            re.compile(r"Agent Skills Hub registry.*Discovery route only.*never auto-install"),
        )


if __name__ == "__main__":
    unittest.main()
