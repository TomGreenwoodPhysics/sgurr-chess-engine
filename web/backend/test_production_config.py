from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from web.backend import main
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

    def test_render_hostname_is_added_to_allowed_hosts(self) -> None:
        hosts = allowed_hosts_from_env(
            None,
            platform_host="sgurr-demo.onrender.com",
        )

        self.assertIn("sgurr-demo.onrender.com", hosts)

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

    def test_nnue_asset_uses_canonical_route_and_headers(self) -> None:
        self.assertEqual(
            main.EXPECTED_NET_SHA256,
            "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf",
        )
        self.assertEqual(
            main.NNUE_ASSET_ROUTE,
            f"/api/nnue/gen8/{main.EXPECTED_NET_SHA256}.nnue",
        )

        response = main.nnue_network_asset()

        self.assertEqual(
            Path(response.path),
            (main.REPO_ROOT / "nets" / "gen8.nnue").resolve(),
        )
        self.assertEqual(response.media_type, "application/octet-stream")
        self.assertEqual(response.headers["content-type"], "application/octet-stream")
        self.assertEqual(
            response.headers["cache-control"],
            "public, max-age=31536000, immutable",
        )
        self.assertEqual(
            response.headers["etag"],
            f'"{main.EXPECTED_NET_SHA256}"',
        )

    def test_nnue_asset_returns_generic_503_for_invalid_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.nnue"
            altered = Path(temp_dir) / "altered.nnue"
            altered.write_bytes(b"altered network")

            for net_path in (missing, altered):
                with self.subTest(net_path=net_path):
                    with patch.object(main, "ENGINE_NET_PATH", net_path):
                        with self.assertRaises(HTTPException) as raised:
                            main.nnue_network_asset()

                    self.assertEqual(raised.exception.status_code, 503)
                    self.assertEqual(raised.exception.detail, "NNUE Lab unavailable")


if __name__ == "__main__":
    unittest.main()
