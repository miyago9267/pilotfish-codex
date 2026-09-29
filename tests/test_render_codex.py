from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import render  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "codex"
RENDER = ROOT / "tools" / "render.py"
POLICY = "agents-md.orchestration.md"
MIRROR = render.MIRRORS["codex"][POLICY]


def golden_files() -> dict[str, bytes]:
    return {
        p.relative_to(GOLDEN).as_posix(): p.read_bytes()
        for p in GOLDEN.rglob("*")
        if p.is_file() and p.name != "SOURCE"
    }


def run_render(root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER), "--host", "codex", "--root", str(root), *flags],
        capture_output=True,
        text=True,
    )


def make_root(root: Path) -> None:
    shutil.copytree(ROOT / "core", root / "core")
    shutil.copytree(ROOT / "hosts" / "codex", root / "hosts" / "codex")
    shutil.copytree(ROOT / "templates", root / "templates")
    (root / MIRROR).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / MIRROR, root / MIRROR)


class GoldenTests(unittest.TestCase):
    def test_render_is_byte_identical_to_golden(self) -> None:
        golden = golden_files()
        self.assertEqual(len(golden), 12)
        rendered = render.RENDERERS["codex"](ROOT)
        self.assertEqual(sorted(rendered), sorted(golden))
        for rel, data in golden.items():
            self.assertEqual(rendered[rel], data, rel)

    def test_golden_records_source(self) -> None:
        self.assertRegex((GOLDEN / "SOURCE").read_text(encoding="utf-8"), r"(?m)^ref: shoal@[0-9a-f]{7}$")

    def test_committed_templates_match_golden(self) -> None:
        dist = ROOT / "templates"
        actual = {p.relative_to(dist).as_posix(): p.read_bytes() for p in dist.rglob("*") if p.is_file()}
        self.assertEqual(actual, golden_files())

    def test_plugin_policy_mirror_is_rendered(self) -> None:
        self.assertEqual((ROOT / MIRROR).read_bytes(), render.RENDERERS["codex"](ROOT)[POLICY])


class CheckCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        make_root(self.root)

    def test_check_passes_when_dist_matches(self) -> None:
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_fails_when_one_byte_changes(self) -> None:
        target = self.root / "templates" / "agents" / "scout.toml"
        target.write_bytes(target.read_bytes() + b"x")
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("agents/scout.toml", result.stderr)

    def test_check_fails_on_extra_or_missing_file(self) -> None:
        dist = self.root / "templates"
        (dist / "extra.md").write_text("x", encoding="utf-8")
        (dist / "agents" / "stray.toml").write_text("x", encoding="utf-8")
        (dist / "hooks.json").unlink()
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("多出: extra.md", result.stderr)
        self.assertIn("多出: agents/stray.toml", result.stderr)
        self.assertIn("缺少: hooks.json", result.stderr)

    def test_check_fails_when_plugin_policy_copy_drifts_or_disappears(self) -> None:
        mirror = self.root / MIRROR
        mirror.write_bytes(mirror.read_bytes() + b"\n")
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn(MIRROR, result.stderr)
        mirror.unlink()
        self.assertIn(f"缺少: {MIRROR}", run_render(self.root, "--check").stderr)

    def test_check_fails_when_source_changes_without_rewriting_dist(self) -> None:
        body = self.root / "hosts" / "codex" / "src" / "agents" / "executor.md"
        body.write_text(body.read_text(encoding="utf-8") + "extra line\n", encoding="utf-8")
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("agents/executor.toml", result.stderr)

    def test_write_repairs_dist_and_mirror(self) -> None:
        dist = self.root / "templates"
        (dist / "agents" / "scout.toml").write_bytes(b"broken")
        (dist / "extra.md").write_text("x", encoding="utf-8")
        (self.root / MIRROR).write_bytes(b"broken")
        self.assertEqual(run_render(self.root, "--write").returncode, 0)
        self.assertEqual(run_render(self.root, "--check").returncode, 0)
        self.assertFalse((dist / "extra.md").exists())
        self.assertEqual((self.root / MIRROR).read_bytes(), (ROOT / MIRROR).read_bytes())


class BindingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        make_root(self.root)
        self.roles = self.root / "core" / "roles.toml"
        self.binding = self.root / "hosts" / "codex" / "binding.toml"

    def edit(self, path: Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def assert_rejected(self, expected: str) -> None:
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(expected, result.stderr)

    def test_read_only_role_must_use_read_only_sandbox(self) -> None:
        self.edit(self.binding, 'effort = "low"\nsandbox_mode = "read-only"', 'effort = "low"\nsandbox_mode = "workspace-write"')
        self.assert_rejected("scout")

    def test_read_only_role_without_sandbox_is_rejected(self) -> None:
        self.edit(self.binding, 'effort = "low"\nsandbox_mode = "read-only"\n', 'effort = "low"\n')
        self.assert_rejected("scout")

    def test_write_role_cannot_be_read_only(self) -> None:
        self.edit(self.binding, '[roles.executor]\neffort = "high"', '[roles.executor]\neffort = "high"\nsandbox_mode = "read-only"')
        self.assert_rejected("executor")

    def test_every_role_needs_a_binding(self) -> None:
        self.roles.write_text(
            self.roles.read_text(encoding="utf-8")
            + '\n[roles.ghost]\naccess = "write"\ntier = "fast"\nsecurity = false\n',
            encoding="utf-8",
        )
        self.assert_rejected("ghost")

    def test_binding_must_declare_security_avoid_frontier(self) -> None:
        self.edit(self.binding, "security_avoid_frontier = false\n", "")
        self.assert_rejected("security_avoid_frontier")

    def test_unknown_root_tier_is_rejected(self) -> None:
        self.edit(self.binding, '[root]\ntier = "fast"', '[root]\ntier = "nope"')
        self.assert_rejected("[root].tier")

    def test_security_roles_may_use_frontier_model_when_host_allows_it(self) -> None:
        # 預設設定：security role 用 sol，而 sol 同時是 frontier tier 的 model，且 --check 通過
        self.assertEqual(run_render(self.root, "--check").returncode, 0)

    def test_security_roles_are_rejected_when_host_avoids_frontier(self) -> None:
        self.edit(self.binding, "security_avoid_frontier = false", "security_avoid_frontier = true")
        self.assert_rejected("security-reviewer")

    def test_developer_instructions_cannot_break_the_toml_string(self) -> None:
        body = self.root / "hosts" / "codex" / "src" / "agents" / "scout.md"
        body.write_text('bad """ body\n', encoding="utf-8")
        self.assert_rejected("scout")


class CatalogTests(unittest.TestCase):
    def test_binding_tiers_cover_expected_models(self) -> None:
        binding = render.load_toml(ROOT / "hosts" / "codex" / "binding.toml")
        roles = render.load_toml(ROOT / "core" / "roles.toml")["roles"]
        models = {n: render.resolve_model(n, roles, binding) for n in roles}
        self.assertEqual(models["scout"], "gpt-6-luna")
        self.assertEqual(models["mech-executor"], "gpt-6-luna")
        self.assertEqual(models["executor"], "gpt-6-astra")
        self.assertEqual(models["plan-verifier"], "gpt-6-sol")
        self.assertEqual(binding["extra_roles"]["sol-executor"]["model"], "gpt-6-sol")
        self.assertNotIn("Explore", binding.get("extra_roles", {}))

    def test_claude_output_does_not_depend_on_fast_vs_standard_split(self) -> None:
        binding = render.load_toml(ROOT / "hosts" / "claude" / "binding.toml")
        self.assertEqual(binding["tiers"]["fast"], binding["tiers"]["standard"])


if __name__ == "__main__":
    unittest.main()
