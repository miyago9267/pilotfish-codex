from __future__ import annotations

import tomllib
import unittest

import render_helpers as rh
from render_helpers import ROOT, render


class GrokRenderTests(rh.HostRenderCase):
    HOST = "grok"
    GOLDEN_COUNT = 15
    SOURCE_REFS = ("b65a243",)
    DIST_FILE = "roles/scout.toml"
    SRC_FILE = "agents/executor.md"

    def test_vendored_files_are_copied_verbatim(self) -> None:
        src = ROOT / "hosts" / "grok" / "src"
        rendered = render.RENDERERS["grok"](ROOT)
        for path in src.rglob("*"):
            if path.is_file():
                self.assertEqual(rendered[path.relative_to(src).as_posix()], path.read_bytes())

    def test_role_toml_carries_reasoning_effort(self) -> None:
        rendered = render.RENDERERS["grok"](ROOT)
        efforts = {n: tomllib.loads(rendered[f"roles/{n}.toml"].decode())["reasoning_effort"]
                   for n in ("scout", "mech-executor", "security-reviewer")}
        self.assertEqual(efforts, {"scout": "low", "mech-executor": "low", "security-reviewer": "high"})

    def test_agent_model_must_match_binding(self) -> None:
        self.edit(self.binding, 'fast = "inherit"', 'fast = "grok-4.5"')
        self.assert_rejected("scout")

    def test_read_only_role_must_use_read_only_capability(self) -> None:
        self.edit(self.binding, 'capability_mode = "read-only"', 'capability_mode = "all"')
        self.assert_rejected("capability_mode")

    def test_write_role_cannot_use_read_only_capability(self) -> None:
        self.edit(self.binding, '[roles.executor]\neffort = "medium"\ncapability_mode = "all"',
                  '[roles.executor]\neffort = "medium"\ncapability_mode = "read-only"')
        self.assert_rejected("executor")


class UpstreamLockTests(unittest.TestCase):
    def test_lock_pins_every_vendored_or_forked_host(self) -> None:
        lock = tomllib.loads((ROOT / "upstream.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["grok"]["upstream"], "Nanako0129/pilotfish-grok")
        self.assertEqual(lock["grok"]["version"], "v1.0.6")
        self.assertEqual(lock["claude"]["upstream"], "Nanako0129/pilotfish")
        self.assertEqual(lock["claude"]["version"], "v1.4.2")
        self.assertEqual(lock["codex"]["version"], "v1.3.0")
        for host, entry in lock.items():
            for key in ("upstream", "version", "kind", "source"):
                self.assertIn(key, entry, f"{host}.{key}")


if __name__ == "__main__":
    unittest.main()
