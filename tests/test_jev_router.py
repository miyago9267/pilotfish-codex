"""Local HTTP contract tests for the optional Jev classifier."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "plugin/plugins/pilotfish-jev-router/jev_router.py"
spec = importlib.util.spec_from_file_location("jev_router", MODULE)
assert spec is not None and spec.loader is not None
router = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = router
spec.loader.exec_module(router)


def answer(**values: object) -> dict[str, object]:
    scores = {
        "parent_local": 0.05,
        "mechanical": 0.05,
        "exploration": 0.05,
        "judgment": 0.8,
        "deep_judgment": 0.05,
    }
    scores.update(values)
    return {
        "model": router.MODEL,
        "answers": {
            name: {"type": "noul", "noul": score} for name, score in scores.items()
        },
    }


class JevConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_config(self, value: object) -> None:
        path = self.home / router.CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def install_cache(self, version: str) -> Path:
        root = self.home / router.CACHE_DIR / version
        root.mkdir(parents=True)
        (root / "jev_router.py").write_text("# test package\n", encoding="utf-8")
        manifest = root / ".codex-plugin/plugin.json"
        manifest.parent.mkdir()
        manifest.write_text(json.dumps({"name": "pilotfish-jev-router", "version": version}), encoding="utf-8")
        (self.home / "config.toml").write_text(
            '[plugins."pilotfish-jev-router@pilotfish-codex"]\nenabled = true\n',
            encoding="utf-8",
        )
        return root

    def test_missing_config_and_missing_plugin_default_off(self) -> None:
        root = self.install_cache("0.1.0")
        self.assertTrue(root.is_dir())
        self.assertEqual(router.load_config(self.home), ("off", None))
        self.write_config({"mode": "shadow"})
        (root / "jev_router.py").unlink()
        self.assertEqual(router.load_config(self.home), ("off", None))

    def test_shadow_and_active_select_installed_cache(self) -> None:
        versioned = self.install_cache("0.1.0")
        self.write_config({"mode": "shadow"})
        self.assertEqual(router.load_config(self.home), ("shadow", versioned))
        self.write_config({"mode": "active"})
        self.assertEqual(router.load_config(self.home), ("active", versioned))
        (self.home / "config.toml").write_text(
            '[plugins."pilotfish-jev-router@pilotfish-codex"]\nenabled = false\n',
            encoding="utf-8",
        )
        self.assertEqual(router.load_config(self.home), ("off", None))

    def test_cache_manifest_and_plugin_identity_must_match(self) -> None:
        root = self.install_cache("0.1.0")
        self.write_config({"mode": "shadow"})
        (self.home / "config.toml").write_text(
            '[plugins."another-plugin@pilotfish-codex"]\nenabled = true\n',
            encoding="utf-8",
        )
        self.assertEqual(router.load_config(self.home), ("off", None))
        (self.home / "config.toml").write_text(
            '[plugins."pilotfish-jev-router@pilotfish-codex"]\nenabled = true\n',
            encoding="utf-8",
        )
        (root / ".codex-plugin/plugin.json").write_text(
            json.dumps({"name": "another-plugin", "version": "0.1.0"}),
            encoding="utf-8",
        )
        self.assertEqual(router.load_config(self.home), ("off", None))

    def test_invalid_config_and_ambiguous_cache_fail_closed(self) -> None:
        self.install_cache("0.1.0")
        for value in ({"mode": "off"}, {"mode": "shadow", "root": "/tmp"},
                      {"mode": ["active"]}, [], None):
            with self.subTest(value=value):
                self.write_config(value)
                self.assertEqual(router.load_config(self.home), ("off", None))
        self.write_config({"mode": "shadow"})
        self.install_cache("0.2.0")
        self.assertEqual(router.load_config(self.home), ("off", None))
        (self.home / router.CONFIG_FILE).write_text("{invalid", encoding="utf-8")
        self.assertEqual(router.load_config(self.home), ("off", None))

    def test_symlinked_config_and_cache_are_rejected(self) -> None:
        local = self.install_cache("0.1.0")
        self.write_config({"mode": "shadow"})
        config = self.home / router.CONFIG_FILE
        config.rename(config.with_suffix(".saved"))
        config.symlink_to(config.with_suffix(".saved"))
        self.assertEqual(router.load_config(self.home), ("off", None))
        config.unlink()
        config.with_suffix(".saved").rename(config)
        (local / "jev_router.py").unlink()
        (local / "jev_router.py").symlink_to(MODULE)
        self.assertEqual(router.load_config(self.home), ("off", None))

    def test_environment_overrides_config_without_implicit_activation(self) -> None:
        local = self.install_cache("0.1.0")
        self.write_config({"mode": "active"})
        with mock.patch.dict(os.environ, {"PILOTFISH_JEV_MODE": "off"}):
            self.assertEqual(router.load_config(self.home), ("off", None))
        with mock.patch.dict(os.environ, {"PILOTFISH_JEV_MODE": "shadow"}):
            self.assertEqual(router.load_config(self.home), ("shadow", local))
        with mock.patch.dict(os.environ, {"PILOTFISH_JEV_PLUGIN_ROOT": str(MODULE.parent)}):
            self.assertEqual(router.load_config(self.home), ("active", MODULE.parent))
        with mock.patch.dict(os.environ, {"PILOTFISH_JEV_PLUGIN_ROOT": "relative/path"}):
            self.assertEqual(router.load_config(self.home), ("off", None))
        (self.home / router.CONFIG_FILE).unlink()
        with mock.patch.dict(os.environ, {"PILOTFISH_JEV_PLUGIN_ROOT": str(MODULE.parent)}):
            self.assertEqual(router.load_config(self.home), ("off", None))
        with mock.patch.dict(os.environ, {
            "PILOTFISH_JEV_MODE": "active",
            "PILOTFISH_JEV_PLUGIN_ROOT": str(MODULE.parent),
        }):
            self.assertEqual(router.load_config(self.home), ("active", MODULE.parent))


class StubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.server.calls.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
            }
        )
        time.sleep(self.server.delay)  # type: ignore[attr-defined]
        self.send_response(self.server.status)  # type: ignore[attr-defined]
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(self.server.payload).encode())  # type: ignore[attr-defined]
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


class JevRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        self.server.calls = []
        self.server.payload = answer()
        self.server.status = 200
        self.server.delay = 0
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/systemone"
        self.key = mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-key"})
        self.key.start()

    def tearDown(self) -> None:
        self.key.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_active_request_shape_and_sol_mapping(self) -> None:
        result = router.JevRouter("active", _endpoint=self.endpoint).classify("Design a small fix")
        self.assertEqual(result["recommendation"], {"role": "sol-executor", "route": "judgment"})
        self.assertEqual(result["scores"]["judgment"], 0.8)
        call = self.server.calls[0]
        self.assertEqual(call["path"], "/v1/systemone")
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["body"], {
            "model": router.MODEL,
            "state": "Design a small fix",
            "questions": router.QUESTIONS,
        })

    def test_shadow_has_no_role_context_and_redacts_prompt(self) -> None:
        prompt = 'Review api_key="secret value" for alice@example.com; Bearer abc123'
        result = router.JevRouter("shadow", _endpoint=self.endpoint).classify(prompt)
        self.assertEqual(set(result), {"mode", "model", "scores", "route", "score", "lead"})
        self.assertNotIn("role", str(result))
        state = self.server.calls[0]["body"]["state"]
        for secret in ("secret value", "alice@example.com", "abc123"):
            self.assertNotIn(secret, state)
            self.assertNotIn(secret, str(result))
        self.assertIn("Review", state)

    def test_default_off_and_missing_key_make_no_request(self) -> None:
        with mock.patch.object(router, "_api_key", side_effect=AssertionError("called")):
            self.assertIsNone(router.JevRouter(_endpoint=self.endpoint).classify("Design a fix"))
        with mock.patch.object(router, "_api_key", return_value=None):
            self.assertIsNone(router.JevRouter("active", _endpoint=self.endpoint).classify("Design a fix"))
        self.assertEqual(self.server.calls, [])

    def test_file_key_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / ".config/typesafe/api_key"
            key_path.parent.mkdir(parents=True)
            key_path.write_text("file-key\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": ""}), mock.patch.object(
                router.Path, "home", return_value=Path(directory)
            ):
                result = router.JevRouter("active", _endpoint=self.endpoint).classify("Design a fix")
        self.assertIsNotNone(result)
        self.assertEqual(self.server.calls[0]["headers"]["Authorization"], "Bearer file-key")

    def test_deep_and_low_score_mapping(self) -> None:
        self.server.payload = answer(judgment=0.1, deep_judgment=0.91)
        result = router.JevRouter("active", _endpoint=self.endpoint).classify("Architecture choice")
        self.assertEqual(result["recommendation"], {"role": "executor", "route": "deep_judgment"})
        self.server.payload = answer(parent_local=0.35, judgment=0.3, mechanical=0.2, exploration=0.1, deep_judgment=0.05)
        result = router.JevRouter("active", _endpoint=self.endpoint).classify("One command")
        self.assertNotIn("recommendation", result)

    def test_mechanical_and_exploration_bind_to_cheap_roles(self) -> None:
        for label, role in (("mechanical", "mech-executor"), ("exploration", "scout")):
            values = {name: 0.02 for name in router.QUESTIONS}
            values[label] = 0.94
            self.server.payload = answer(**values)
            with self.subTest(label=label):
                result = router.JevRouter("active", _endpoint=self.endpoint).classify("Routine work")
                self.assertEqual(result["recommendation"]["role"], role)

    def test_ambiguous_high_scores_abstain(self) -> None:
        self.server.payload = answer(judgment=0.90, mechanical=0.75)
        result = router.JevRouter("active", _endpoint=self.endpoint).classify("Some work")
        self.assertNotIn("recommendation", result)
        self.assertNotIn("route", result)

    def test_malformed_responses_fail_open(self) -> None:
        invalid = [
            {},
            {"model": router.MODEL, "answers": None},
            answer(judgment=True),
            answer(judgment="0.9"),
            answer(judgment=-0.1),
            answer(judgment=1.1),
            answer(judgment=float("nan")),
            {"model": "jev-latest", "answers": answer()["answers"]},
        ]
        classifier = router.JevRouter("active", _endpoint=self.endpoint)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.server.payload = payload
                self.assertIsNone(classifier.classify("Design a fix"))

    def test_http_error_and_timeout_fail_open(self) -> None:
        classifier = router.JevRouter("active", timeout=0.05, _endpoint=self.endpoint)
        self.server.status = 500
        self.assertIsNone(classifier.classify("Design a fix"))
        self.server.status = 200
        self.server.delay = 0.15
        self.assertIsNone(classifier.classify("Design a fix"))

    def test_invalid_input_and_endpoint_do_not_send(self) -> None:
        classifier = router.JevRouter("active", _endpoint=self.endpoint)
        self.assertIsNone(classifier.classify("x" * (router.MAX_PROMPT_CHARS + 1)))
        self.assertIsNone(classifier.classify(None))
        self.assertEqual(self.server.calls, [])
        with self.assertRaises(ValueError):
            router.JevRouter("active", _endpoint="http://example.com/v1/systemone")
        with self.assertRaises(ValueError):
            router.JevRouter("active", timeout=10, _endpoint=self.endpoint)


if __name__ == "__main__":
    unittest.main()
