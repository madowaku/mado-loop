from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import provider_router as router  # noqa: E402


class ProviderRouterTests(unittest.TestCase):
    def test_private_auto_prefers_openrouter(self) -> None:
        selected = router.select_provider(
            sensitivity="private",
            env={
                "OPENROUTER_API_KEY": "secret-key",
                "MADO_OPENROUTER_MODEL": "example/model",
                "MADO_LOCAL_BASE_URL": "http://127.0.0.1:1234/v1",
                "MADO_LOCAL_MODEL": "local-model",
            },
        )
        self.assertEqual(selected.name, "openrouter")
        self.assertEqual(selected.model, "example/model")
        self.assertNotIn("api_key", selected.public_dict())

    def test_openrouter_payload_enforces_privacy_controls(self) -> None:
        selected = router.select_provider(
            provider="openrouter",
            sensitivity="private",
            env={"OPENROUTER_API_KEY": "k", "MADO_OPENROUTER_MODEL": "example/model"},
        )
        payload = router.build_chat_request(selected, prompt="Review this bounded patch")
        self.assertEqual(payload["provider"], {"data_collection": "deny", "zdr": True})

    def test_empero_requires_public_sensitivity(self) -> None:
        with self.assertRaisesRegex(router.ProviderConfigError, "restricted to public"):
            router.select_provider(
                provider="empero",
                sensitivity="private",
                allow_logged_free=True,
                env={},
            )

    def test_empero_requires_logging_consent(self) -> None:
        with self.assertRaisesRegex(router.ProviderConfigError, "allow-logged-free"):
            router.select_provider(provider="empero", sensitivity="public", env={})

    def test_public_prefer_free_uses_empero_only_after_consent(self) -> None:
        selected = router.select_provider(
            sensitivity="public",
            prefer_free=True,
            allow_logged_free=True,
            env={
                "OPENROUTER_API_KEY": "k",
                "MADO_OPENROUTER_MODEL": "example/model",
            },
        )
        self.assertEqual(selected.name, "empero")
        self.assertTrue(selected.logs_content)
        self.assertEqual(selected.model, "free")

    def test_secret_auto_requires_local(self) -> None:
        with self.assertRaisesRegex(router.ProviderConfigError, "requires a configured local provider"):
            router.select_provider(
                sensitivity="secret",
                env={"OPENROUTER_API_KEY": "k", "MADO_OPENROUTER_MODEL": "example/model"},
            )

    def test_secret_auto_selects_local(self) -> None:
        selected = router.select_provider(
            sensitivity="secret",
            env={
                "MADO_LOCAL_BASE_URL": "http://127.0.0.1:1234/v1",
                "MADO_LOCAL_MODEL": "local-model",
            },
        )
        self.assertEqual(selected.name, "local")
        self.assertFalse(selected.external)

    def test_explicit_openrouter_rejects_secret(self) -> None:
        with self.assertRaisesRegex(router.ProviderConfigError, "may not use external"):
            router.select_provider(
                provider="openrouter",
                sensitivity="secret",
                env={"OPENROUTER_API_KEY": "k", "MADO_OPENROUTER_MODEL": "example/model"},
            )

    def test_model_override_is_scoped_to_explicit_provider(self) -> None:
        selected = router.select_provider(
            provider="openrouter",
            sensitivity="public",
            model_override="override/model",
            env={"OPENROUTER_API_KEY": "k", "MADO_OPENROUTER_MODEL": "default/model"},
        )
        self.assertEqual(selected.model, "override/model")

    def test_auto_rejects_model_override(self) -> None:
        with self.assertRaisesRegex(router.ProviderConfigError, "requires an explicit provider"):
            router.select_provider(
                provider="auto",
                sensitivity="public",
                model_override="ambiguous/model",
                env={"OPENROUTER_API_KEY": "k", "MADO_OPENROUTER_MODEL": "default/model"},
            )

    def test_empty_prompt_is_rejected(self) -> None:
        selected = router.WorkerProvider(
            name="local",
            base_url="http://127.0.0.1:1234/v1",
            model="local",
            api_key="local",
            external=False,
            logs_content=False,
            privacy_mode="local-only",
        )
        with self.assertRaisesRegex(router.ProviderConfigError, "must not be empty"):
            router.build_chat_request(selected, prompt="  ")


if __name__ == "__main__":
    unittest.main()
