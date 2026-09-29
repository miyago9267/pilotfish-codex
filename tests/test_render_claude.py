from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import render  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "claude"
RENDER = ROOT / "tools" / "render.py"


def golden_files() -> dict[str, bytes]:
    return {
        p.relative_to(GOLDEN).as_posix(): p.read_bytes()
        for p in GOLDEN.rglob("*")
        if p.is_file() and p.name != "SOURCE"
    }


def run_render(root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDER), "--host", "claude", "--root", str(root), *flags],
        capture_output=True,
        text=True,
    )


class GoldenTests(unittest.TestCase):
    def test_render_is_byte_identical_to_golden(self) -> None:
        golden = golden_files()
        self.assertEqual(len(golden), 13)
        rendered = render.RENDERERS["claude"](ROOT)
        self.assertEqual(sorted(rendered), sorted(golden))
        for rel, data in golden.items():
            self.assertEqual(rendered[rel], data, rel)

    def test_golden_records_source(self) -> None:
        self.assertIn("ref: 1ea9841", (GOLDEN / "SOURCE").read_text(encoding="utf-8"))

    def test_committed_dist_matches_golden(self) -> None:
        dist = ROOT / "hosts" / "claude" / "dist"
        actual = {p.relative_to(dist).as_posix(): p.read_bytes() for p in dist.rglob("*") if p.is_file()}
        self.assertEqual(actual, golden_files())


class CheckCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(ROOT / "core", self.root / "core")
        shutil.copytree(ROOT / "hosts" / "claude", self.root / "hosts" / "claude")

    def test_check_passes_when_dist_matches(self) -> None:
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_fails_when_one_byte_changes(self) -> None:
        target = self.root / "hosts" / "claude" / "dist" / "agents" / "scout.md"
        target.write_bytes(target.read_bytes() + b"x")
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("agents/scout.md", result.stderr)

    def test_check_fails_on_extra_or_missing_file(self) -> None:
        dist = self.root / "hosts" / "claude" / "dist"
        (dist / "extra.md").write_text("x", encoding="utf-8")
        (dist / "settings.snippet.json").unlink()
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("extra.md", result.stderr)
        self.assertIn("settings.snippet.json", result.stderr)

    def test_write_repairs_dist(self) -> None:
        dist = self.root / "hosts" / "claude" / "dist"
        (dist / "agents" / "scout.md").write_bytes(b"broken")
        (dist / "extra.md").write_text("x", encoding="utf-8")
        self.assertEqual(run_render(self.root, "--write").returncode, 0)
        self.assertEqual(run_render(self.root, "--check").returncode, 0)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(ROOT / "core", self.root / "core")
        shutil.copytree(ROOT / "hosts" / "claude", self.root / "hosts" / "claude")
        self.roles = self.root / "core" / "roles.toml"
        self.binding = self.root / "hosts" / "claude" / "binding.toml"

    def assert_rejected(self, expected: str) -> None:
        result = run_render(self.root, "--check")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(expected, result.stderr)

    def edit(self, path: Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_security_role_cannot_resolve_to_frontier_model(self) -> None:
        self.edit(
            self.roles,
            '[roles.security-reviewer]\naccess = "read-only"\ntier = "strong"',
            '[roles.security-reviewer]\naccess = "read-only"\ntier = "frontier"',
        )
        self.assert_rejected("security-reviewer")

    def test_security_check_compares_resolved_model_not_tier_name(self) -> None:
        # strong 被改成和 frontier 同一個 model，security role 一樣要被擋
        self.edit(self.binding, 'strong = "opus"', 'strong = "fable"')
        self.assert_rejected("frontier")

    def test_read_only_role_must_use_tools_allowlist(self) -> None:
        self.edit(self.binding, '[roles.scout]\neffort = "low"\ntools = ["Read", "Glob", "Grep"]',
                  '[roles.scout]\neffort = "low"\ndisallowedTools = ["Agent"]')
        self.assert_rejected("scout")

    def test_read_only_role_cannot_include_write_tools(self) -> None:
        self.edit(self.binding, 'tools = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]',
                  'tools = ["Read", "Bash", "Edit"]')
        self.assert_rejected("Bash")

    def test_every_role_needs_a_binding(self) -> None:
        self.roles.write_text(
            self.roles.read_text(encoding="utf-8")
            + '\n[roles.ghost]\naccess = "write"\ntier = "fast"\nsecurity = false\n',
            encoding="utf-8",
        )
        self.assert_rejected("ghost")


class RolesCatalogTests(unittest.TestCase):
    def test_roles_toml_has_no_model_names(self) -> None:
        text = (ROOT / "core" / "roles.toml").read_text(encoding="utf-8").lower()
        for needle in ("opus", "sonnet", "haiku", "fable", "gpt-", "gemini", "claude"):
            self.assertNotIn(needle, text)

    def test_catalog_shape(self) -> None:
        roles = render.load_toml(ROOT / "core" / "roles.toml")["roles"]
        self.assertNotIn("Explore", roles)
        self.assertEqual(
            {n for n, r in roles.items() if r["security"]},
            {"security-reviewer", "security-executor"},
        )
        self.assertTrue(all(r["access"] in render.ACCESS and r["tier"] in render.TIERS for r in roles.values()))


class RefreshGoldenTests(unittest.TestCase):
    def test_reimports_from_a_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = Path(tmp) / "src", Path(tmp) / "root"
            (repo / "templates" / "agents").mkdir(parents=True)
            (repo / "templates" / "agents" / "a.md").write_bytes(b"hello\n")
            git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "."], check=True)
            subprocess.run([*git, "commit", "-qm", "x"], check=True)
            sha = subprocess.run([*git, "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "refresh_golden.py"), "--host", "claude",
                 "--from", str(repo), "--ref", sha, "--root", str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "tests/golden/claude/agents/a.md").read_bytes(), b"hello\n")
            self.assertTrue(re.search(rf"ref: {sha}", (root / "tests/golden/claude/SOURCE").read_text()))


if __name__ == "__main__":
    unittest.main()
