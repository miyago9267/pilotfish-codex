"""Offline behavior tests for the scripted installer (`install/install.py`).

Everything runs against temp directories; no Codex process, no network, no
user `~/.codex` access."""

from __future__ import annotations

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "install"))

from install import (  # noqa: E402
    InstallAbort,
    active_instruction_file,
    install,
    merge_config_text,
    merge_instruction_text,
    parse_codex_version,
)

POLICY_BLOCK = (REPO_ROOT / "templates" / "agents-md.orchestration.md").read_text(
    encoding="utf-8"
)


class ConfigMergeTest(unittest.TestCase):
    def test_empty_config_gets_every_managed_key(self) -> None:
        text, notes = merge_config_text("")
        config = tomllib.loads(text)
        self.assertEqual(config["model"], "gpt-5.6-sol")
        self.assertTrue(config["features"]["multi_agent"])
        adapter = config["features"]["multi_agent_v2"]
        self.assertIs(adapter["hide_spawn_agent_metadata"], False)
        self.assertEqual(adapter["tool_namespace"], "agents")
        self.assertEqual(adapter["max_concurrent_threads_per_session"], 4)
        self.assertEqual(config["agents"], {"max_threads": 3, "max_depth": 1})
        self.assertTrue(notes)

    def test_unrelated_content_and_comments_survive_byte_for_byte(self) -> None:
        original = (
            "# my precious comment\n"
            'model = "gpt-5.6-sol"\n'
            "\n"
            "[mcp_servers.playwright]\n"
            'command = "npx"  # inline note\n'
            "\n"
            "[features]\n"
            "multi_agent = true\n"
            "\n"
            "[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\n"
            'tool_namespace = "agents"\n'
            "max_concurrent_threads_per_session = 4\n"
            "\n"
            "[agents]\n"
            "max_threads = 3\n"
            "max_depth = 1\n"
        )
        text, _ = merge_config_text(original)
        self.assertEqual(text, original)

    def test_partial_adapter_is_repaired_without_touching_neighbors(self) -> None:
        original = (
            "[features]\n"
            "multi_agent = true\n"
            "js_repl = false\n"
            "\n"
            "[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\n"
        )
        text, notes = merge_config_text(original)
        config = tomllib.loads(text)
        adapter = config["features"]["multi_agent_v2"]
        self.assertEqual(adapter["tool_namespace"], "agents")
        self.assertEqual(adapter["max_concurrent_threads_per_session"], 4)
        self.assertIs(config["features"]["js_repl"], False)
        self.assertIn('repaired tool_namespace = "agents"', notes)

    def test_valid_user_concurrency_is_kept(self) -> None:
        original = (
            "[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\n"
            'tool_namespace = "agents"\n'
            "max_concurrent_threads_per_session = 6\n"
        )
        text, notes = merge_config_text(original)
        config = tomllib.loads(text)
        self.assertEqual(
            config["features"]["multi_agent_v2"][
                "max_concurrent_threads_per_session"
            ],
            6,
        )
        self.assertIn("kept user concurrency 6 (recommended 4)", notes)

    def test_invalid_concurrency_is_replaced(self) -> None:
        original = (
            "[features.multi_agent_v2]\n"
            "hide_spawn_agent_metadata = false\n"
            'tool_namespace = "agents"\n'
            'max_concurrent_threads_per_session = "4"\n'
        )
        text, _ = merge_config_text(original)
        self.assertEqual(
            tomllib.loads(text)["features"]["multi_agent_v2"][
                "max_concurrent_threads_per_session"
            ],
            4,
        )

    def test_existing_model_is_never_replaced(self) -> None:
        text, _ = merge_config_text('model = "gpt-5.5"\n')
        self.assertEqual(tomllib.loads(text)["model"], "gpt-5.5")

    def test_forced_enable_aborts(self) -> None:
        original = (
            "[features.multi_agent_v2]\n"
            "enabled = true\n"
            "hide_spawn_agent_metadata = false\n"
        )
        with self.assertRaises(InstallAbort):
            merge_config_text(original)

    def test_explicit_multi_agent_opt_out_aborts(self) -> None:
        with self.assertRaises(InstallAbort):
            merge_config_text("[features]\nmulti_agent = false\n")

    def test_invalid_toml_aborts(self) -> None:
        with self.assertRaises(InstallAbort):
            merge_config_text("model = \n")


class InstructionMergeTest(unittest.TestCase):
    def test_appends_block_to_fresh_file(self) -> None:
        text, action = merge_instruction_text("", POLICY_BLOCK)
        self.assertEqual(action, "appended")
        self.assertIn("pilotfish-codex:begin", text)
        self.assertTrue(text.endswith("pilotfish-codex:end -->\n"))

    def test_replaces_existing_block_and_keeps_surroundings(self) -> None:
        stale = (
            "# My rules\n\n"
            "<!-- pilotfish-codex:begin -->\nOLD CONTENT\n"
            "<!-- pilotfish-codex:end -->\n\n# More rules\n"
        )
        text, action = merge_instruction_text(stale, POLICY_BLOCK)
        self.assertEqual(action, "replaced")
        self.assertNotIn("OLD CONTENT", text)
        self.assertIn("# My rules", text)
        self.assertIn("# More rules", text)
        self.assertEqual(text.count("pilotfish-codex:begin"), 1)

    def test_unmatched_markers_abort(self) -> None:
        with self.assertRaises(InstallAbort):
            merge_instruction_text("<!-- pilotfish-codex:begin -->\n", POLICY_BLOCK)

    def test_multiple_marker_pairs_abort(self) -> None:
        doubled = (
            "<!-- pilotfish-codex:begin -->a<!-- pilotfish-codex:end -->\n"
            "<!-- pilotfish-codex:begin -->b<!-- pilotfish-codex:end -->\n"
        )
        with self.assertRaises(InstallAbort):
            merge_instruction_text(doubled, POLICY_BLOCK)


class EndToEndTempHomeTest(unittest.TestCase):
    def _run(self, home: Path, dry_run: bool = False) -> int:
        return install(
            source_root=REPO_ROOT,
            codex_home=home,
            dry_run=dry_run,
            check_codex=False,
        )

    def test_fresh_home_full_install_is_valid_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            self.assertEqual(self._run(home), 0)
            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(
                config["features"]["multi_agent_v2"]["tool_namespace"], "agents"
            )
            for role in ("scout", "executor", "verifier"):
                self.assertTrue((home / "agents" / f"{role}.toml").is_file())
            agents_md = (home / "AGENTS.md").read_text()
            self.assertIn("### Orchestration", agents_md)

            before = sorted(p.name for p in home.rglob("*"))
            self.assertEqual(self._run(home), 0)
            after = sorted(p.name for p in home.rglob("*"))
            self.assertEqual(before, after, "second run must change nothing")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            self.assertEqual(self._run(home, dry_run=True), 0)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "agents").exists())
            self.assertFalse((home / "AGENTS.md").exists())

    def test_drifted_role_is_updated_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            agents = home / "agents"
            agents.mkdir(parents=True)
            (agents / "scout.toml").write_text('name = "scout"\n')
            self.assertEqual(self._run(home), 0)
            backups = list(agents.glob("scout.toml.pilotfish-codex-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn(
                "gpt-5.6-luna", (agents / "scout.toml").read_text()
            )

    def test_config_backup_created_before_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            home.mkdir(parents=True)
            (home / "config.toml").write_text("[features]\nmulti_agent = true\n")
            self.assertEqual(self._run(home), 0)
            backups = list(home.glob("config.toml.pilotfish-codex-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                backups[0].read_text(), "[features]\nmulti_agent = true\n"
            )

    def test_nonempty_override_file_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            home.mkdir(parents=True)
            (home / "AGENTS.override.md").write_text("# override rules\n")
            (home / "AGENTS.md").write_text("# plain rules\n")
            self.assertEqual(
                active_instruction_file(home), home / "AGENTS.override.md"
            )
            self.assertEqual(self._run(home), 0)
            self.assertIn(
                "### Orchestration", (home / "AGENTS.override.md").read_text()
            )
            self.assertNotIn("### Orchestration", (home / "AGENTS.md").read_text())

    def test_forced_enable_aborts_with_exit_2_and_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "codex-home"
            home.mkdir(parents=True)
            hostile = "[features.multi_agent_v2]\nenabled = true\n"
            (home / "config.toml").write_text(hostile)
            with self.assertRaises(InstallAbort):
                self._run(home)
            self.assertEqual((home / "config.toml").read_text(), hostile)
            self.assertFalse((home / "agents").exists())


class VersionParseTest(unittest.TestCase):
    def test_parses_and_rejects(self) -> None:
        self.assertEqual(parse_codex_version("codex-cli 0.144.4"), (0, 144, 4))
        self.assertIsNone(parse_codex_version("garbage"))


if __name__ == "__main__":
    unittest.main()
