from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import render_helpers as rh
from render_helpers import ROOT, render


class OpencodeRenderTests(rh.HostRenderCase):
    HOST = "opencode"
    GOLDEN_COUNT = 7
    SOURCE_REFS = ("39bdff9", "b65a243")
    DIST_FILE = "roles/scout.md"
    SRC_FILE = "roles/executor.md"

    def test_omitted_roles_are_not_rendered(self) -> None:
        rendered = render.RENDERERS["opencode"](ROOT)
        catalog, routing = json.loads(rendered["catalog.json"]), json.loads(rendered["routing.json"])
        expected = {"scout", "executor", "verifier", "security-reviewer", "security-executor"}
        self.assertEqual(set(catalog["agents"]), expected)
        self.assertEqual(set(routing["roles"]), expected)
        self.assertNotIn("roles/mech-executor.md", rendered)
        self.assertNotIn("roles/plan-verifier.md", rendered)

    def test_pi_routing_is_not_owned_here(self) -> None:
        self.assertNotIn("pi-routing.json", render.RENDERERS["opencode"](ROOT))

    def test_catalog_agent_model_is_first_routing_candidate(self) -> None:
        rendered = render.RENDERERS["opencode"](ROOT)
        catalog, routing = json.loads(rendered["catalog.json"]), json.loads(rendered["routing.json"])
        for name, agent in catalog["agents"].items():
            self.assertEqual(agent["model"], routing["roles"][name]["candidates"][0])

    def test_omitted_role_cannot_also_be_bound(self) -> None:
        self.edit(self.binding, "[roles.scout]\n", '[roles.mech-executor]\nfallback = "none"\nfallback_candidates = []\n'
                  'required_capabilities = ["tools"]\n\n[roles.scout]\n')
        self.assert_rejected("mech-executor")

    def test_omitted_role_must_exist_in_catalog(self) -> None:
        self.edit(self.binding, '["mech-executor", "plan-verifier"]', '["mech-executor", "plan-verifier", "ghost"]')
        self.assert_rejected("ghost")

    def test_role_missing_from_binding_and_omitted_roles_is_rejected(self) -> None:
        self.edit(self.binding, '["mech-executor", "plan-verifier"]', '["mech-executor"]')
        self.assert_rejected("plan-verifier")

    def test_fallback_none_cannot_have_candidates(self) -> None:
        self.edit(self.binding, 'fallback = "none"\nfallback_candidates = []',
                  'fallback = "none"\nfallback_candidates = [{ provider = "xai", model = "grok-4.6" }]')
        self.assert_rejected("security-reviewer")

    def test_candidate_must_be_in_providers(self) -> None:
        self.edit(self.binding, '{ provider = "xai", model = "grok-4.6" }]\nrequired_capabilities = ["tools", "streaming", "reasoning"]\n\n[roles.verifier]',
                  '{ provider = "xai", model = "grok-9" }]\nrequired_capabilities = ["tools", "streaming", "reasoning"]\n\n[roles.verifier]')
        self.assert_rejected("grok-9")

    def test_candidate_must_support_required_capabilities(self) -> None:
        self.edit(self.binding, 'supported = ["tools", "streaming"]', 'supported = ["tools"]')
        self.assert_rejected("streaming")

    def test_stray_role_md_is_rejected(self) -> None:
        (self.root / "hosts" / "opencode" / "src" / "roles" / "ghost.md").write_text("x\n", encoding="utf-8")
        self.assert_rejected("ghost.md")


class RefreshGoldenTests(unittest.TestCase):
    def test_imports_two_source_repos(self) -> None:
        def make_repo(path: Path, files: dict[str, bytes]) -> str:
            for rel, data in files.items():
                (path / rel).parent.mkdir(parents=True, exist_ok=True)
                (path / rel).write_bytes(data)
            git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "."], check=True)
            subprocess.run([*git, "commit", "-qm", "x"], check=True)
            return subprocess.run([*git, "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sha1 = make_repo(base / "oc", {"roles/scout.md": b"scout\n"})
            sha2 = make_repo(base / "dot", {".opencode/pilotfish/catalog.json": b"{}\n", ".opencode/pilotfish/routing.json": b"[]\n",
                                            ".opencode/pilotfish/pi-routing.json": b"pi\n"})
            args = [sys.executable, str(ROOT / "tools" / "refresh_golden.py"), "--host", "opencode",
                    "--from", str(base / "oc"), "--ref", sha1, "--root", str(base / "root")]
            self.assertEqual(subprocess.run(args, capture_output=True, text=True).returncode, 2)  # 缺 --extra-*
            result = subprocess.run([*args, "--extra-from", str(base / "dot"), "--extra-ref", sha2], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            golden = base / "root" / "tests" / "golden" / "opencode"
            self.assertEqual((golden / "roles" / "scout.md").read_bytes(), b"scout\n")
            self.assertEqual((golden / "catalog.json").read_bytes(), b"{}\n")
            self.assertFalse((golden / "pi-routing.json").exists())
            source = (golden / "SOURCE").read_text()
            self.assertIn(f"ref: {sha1}", source)
            self.assertIn(f"ref: {sha2}", source)


if __name__ == "__main__":
    unittest.main()
