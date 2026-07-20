from __future__ import annotations

import unittest

from fastapi import HTTPException

from web.backend.main import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_ALLOWED_ORIGINS,
    allowed_hosts_from_env,
    allowed_origins_from_env,
    health,
    web_asset_path,
)


class ProductionConfigTest(unittest.TestCase):
    def test_local_development_origins_are_explicit(self) -> None:
        origins = allowed_origins_from_env(None)

        self.assertEqual(origins, list(DEFAULT_ALLOWED_ORIGINS))
        self.assertIn("http://127.0.0.1:5500", origins)
        self.assertNotIn("*", origins)

    def test_same_origin_mode_disables_cors(self) -> None:
        self.assertEqual(allowed_origins_from_env("none"), [])
        self.assertEqual(allowed_origins_from_env("  "), [])

    def test_production_origins_are_normalized_and_deduplicated(self) -> None:
        origins = allowed_origins_from_env(
            "https://play.example.com/, https://play.example.com"
        )

        self.assertEqual(origins, ["https://play.example.com"])

    def test_wildcard_and_origin_paths_are_rejected(self) -> None:
        for value in (
            "*",
            "https://play.example.com/api",
            "https://user:secret@play.example.com",
            "https://play.example.com:not-a-port",
        ):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                allowed_origins_from_env(value)

    def test_allowed_hosts_are_explicit_and_normalized(self) -> None:
        self.assertEqual(allowed_hosts_from_env(None), list(DEFAULT_ALLOWED_HOSTS))
        self.assertEqual(
            allowed_hosts_from_env("PLAY.EXAMPLE.COM.,api.example.com"),
            ["play.example.com", "api.example.com"],
        )

    def test_invalid_or_wildcard_hosts_are_rejected(self) -> None:
        for value in ("*", "", "https://play.example.com", "play.example.com:443"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                allowed_hosts_from_env(value)

    def test_health_does_not_leak_engine_path_by_default(self) -> None:
        self.assertNotIn("engine_path", health())

    def test_web_audio_allowlist_serves_known_file(self) -> None:
        path = web_asset_path("sounds", "clock-warning.ogg")

        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "clock-warning.ogg")

    def test_web_audio_allowlist_blocks_unverified_legacy_file(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            web_asset_path("sounds", "button.mp3")

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
