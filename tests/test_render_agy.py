from __future__ import annotations

import unittest

import render_helpers as rh
from render_helpers import ROOT, render


class AgyRenderTests(rh.HostRenderCase):
    HOST = "agy"
    GOLDEN_COUNT = 9
    SOURCE_REFS = ("shoal@",)
    DIST_FILE = "agents/scout/agent.md"
    SRC_FILE = "agents/executor.md"

    def test_effort_is_never_rendered(self) -> None:
        for rel, data in render.RENDERERS["agy"](ROOT).items():
            if rel.startswith("agents/"):
                self.assertNotIn(b"effort", data.split(b"\n---\n", 1)[0], rel)

    def test_binding_must_declare_effort_unsupported(self) -> None:
        self.edit(self.binding, "supports_effort = false", "supports_effort = true")
        self.assert_rejected("supports_effort")

    def test_role_cannot_set_effort(self) -> None:
        self.edit(self.binding, "[roles.executor]\n", '[roles.executor]\neffort = "high"\n')
        self.assert_rejected("effort")

    def test_model_must_be_flash_pro_or_inherit(self) -> None:
        self.edit(self.binding, 'fast = "flash"', 'fast = "gemini-3"')
        self.assert_rejected("gemini-3")

    def test_read_only_role_needs_tools_without_run_command(self) -> None:
        self.edit(self.binding, '"list_dir", "send_message"]', '"list_dir", "run_command"]')
        self.assert_rejected("run_command")

    def test_read_only_role_without_tools_is_rejected(self) -> None:
        text = self.binding.read_text(encoding="utf-8")
        head, tail = text.split("[roles.scout]\ntools = ", 1)
        self.binding.write_text(head + "[roles.scout]\n" + tail.split("\n", 1)[1], encoding="utf-8")
        self.assert_rejected("scout")

    def test_tiers_map_to_expected_models(self) -> None:
        binding = render.load_toml(ROOT / "hosts" / "agy" / "binding.toml")
        roles = render.load_toml(ROOT / "core" / "roles.toml")["roles"]
        models = {n: render.resolve_model(n, roles, binding) for n in roles}
        self.assertEqual({n for n, m in models.items() if m == "flash"}, {"scout", "mech-executor"})
        self.assertEqual(len(models), 7)


if __name__ == "__main__":
    unittest.main()
