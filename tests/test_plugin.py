import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "plugins" / "pilotfish-codex"


class PluginPackageTests(unittest.TestCase):
    def test_marketplace_and_manifest_describe_the_same_plugin(self) -> None:
        marketplace = json.loads(
            (ROOT / "plugin" / ".agents" / "plugins" / "marketplace.json").read_text()
        )
        manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text())
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(entry["source"]["path"], "./plugins/pilotfish-codex")
        self.assertEqual(manifest["version"], "1.7.2")

    def test_skill_is_complete_and_references_exist(self) -> None:
        skill = PLUGIN / "skills" / "pilotfish-orchestration"
        text = (skill / "SKILL.md").read_text()
        self.assertIn("pilotfish-orchestration", text)
        self.assertNotIn("TODO", text)
        for reference in (
            "orchestration-policy.md",
            "role-contract.md",
            "verification-contract.md",
            "recovery-contract.md",
        ):
            self.assertTrue((skill / "references" / reference).is_file())
        self.assertTrue((skill / "agents" / "openai.yaml").is_file())

if __name__ == "__main__":
    unittest.main()
