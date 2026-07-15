from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "templates" / "agents"
BASH_CAPABLE_ROLES = (
    "executor",
    "mech-executor",
    "security-executor",
    "verifier",
)


class PolicyTests(unittest.TestCase):
    def test_version_matches_policy_stamp(self) -> None:
        version = (ROOT / "VERSION").read_text().strip()
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()

        self.assertIn(f"<!-- pilotfish-codex v{version} -->", policy)

    def test_policy_routes_by_role_instead_of_model(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        models = set()

        for path in AGENT_DIR.glob("*.toml"):
            with path.open("rb") as file:
                models.add(tomllib.load(file)["model"])

        for model in models:
            self.assertNotIn(model, policy)

        self.assertIn("smallest useful execution shape", policy)
        self.assertIn("Keep a single unknown bug", policy)

    def test_agent_names_match_filenames_and_remain_leaf_roles(self) -> None:
        for path in AGENT_DIR.glob("*.toml"):
            content = path.read_text()
            with path.open("rb") as file:
                config = tomllib.load(file)

            self.assertEqual(path.stem, config["name"])
            self.assertIn("Never spawn further subagents", content)

    def test_long_running_roles_use_exact_context_handoff(self) -> None:
        for role in BASH_CAPABLE_ROLES:
            content = (AGENT_DIR / f"{role}.toml").read_text()

            self.assertNotIn("launch it detached", content)
            self.assertIn("Never detach", content)
            self.assertIn("exact command", content)
            self.assertIn("absolute working directory", content)
            self.assertIn("completion criterion", content)

    def test_named_role_transport_is_typed_bounded_and_fail_closed(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()

        self.assertEqual(policy.count("pilotfish-codex:spawn-transport:begin"), 1)
        self.assertEqual(policy.count("pilotfish-codex:spawn-transport:end"), 1)
        self.assertIn("`agents.spawn_agent`", policy)
        self.assertIn("`agent_type`", policy)
        self.assertIn("`task_name`", policy)
        self.assertIn("`[a-z0-9_]+`", policy)
        self.assertIn('`fork_turns = "none"`', policy)
        self.assertIn("bounded positive integer string", policy)
        self.assertIn("Never retry the task with an untyped child", policy)
        self.assertRegex(policy, r"fail\s+closed")
        self.assertNotIn('fork_turns = "all"', policy)


if __name__ == "__main__":
    unittest.main()
