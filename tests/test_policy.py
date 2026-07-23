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
        self.assertIn('positive integer string from `"1"` through `"3"`', policy)
        self.assertIn("Never retry the task with an untyped child", policy)
        self.assertRegex(policy, r"Do not pass a\s+`service_tier` override")
        self.assertRegex(policy, r"inherited from the\s+parent session")
        self.assertRegex(policy, r"fail\s+closed")
        self.assertNotIn('fork_turns = "all"', policy)

    def test_plan_ready_is_bare_and_revise_has_every_blocker_field(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()

        self.assertIn("`READY` must be the entire response", policy)
        self.assertIn("the bare uppercase word", policy)
        self.assertIn("`REVISE` is never a bare response", policy)
        for field in (
            "`Blocker`",
            "`Evidence`",
            "`Minimum revision`",
            "`Acceptance check`",
        ):
            self.assertIn(field, policy)
        self.assertIn("explicit `evidence gap`", policy)
        for label in (
            "`Blocker: ...`",
            "`Evidence:",
            "`Minimum revision: ...`",
            "`Acceptance check: ...`",
        ):
            self.assertIn(label, policy)
        self.assertRegex(
            policy,
            r"protocol\s+failure, not a readiness verdict",
        )
        self.assertIn("same unchanged readiness unit once per unit epoch", policy)
        self.assertIn(
            "separate from the two valid automatic `REVISE` rounds",
            policy,
        )

    def test_plan_epoch_brakes_automatic_revise_without_fake_reset(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()

        self.assertIn("program envelope", policy)
        for envelope_field in (
            "outcome and non-goals",
            "cross-cutting architecture/security/privacy",
            "dependency DAG",
            "integration and rollback",
            "global budget",
        ):
            self.assertIn(envelope_field, policy)
        for slice_field in (
            "stable slice ID",
            "exclusive ownership",
            "stable prerequisites",
            "acceptance checks",
            "rollback",
            "cosmetic fragmentation",
        ):
            self.assertIn(slice_field, policy)
        self.assertRegex(
            policy,
            r"smallest\s+genuinely independently approvable",
        )
        self.assertIn("stable readiness-unit ID", policy)
        self.assertIn(
            "per `(stable readiness-unit ID, Plan epoch)`",
            policy,
        )
        self.assertIn("The envelope is its own readiness unit", policy)
        self.assertIn("must return `READY` before", policy)
        self.assertIn("never bundles the envelope with a", policy)
        self.assertIn("review only the next executable slice by", policy)
        self.assertIn("stop readiness review and present", policy)
        self.assertIn("Keep downstream slices in", policy)
        self.assertIn("Fully specify only the next executable slice", policy)
        self.assertIn("Missing future detail is not a blocker", policy)
        self.assertIn("explicitly requests a batch", policy)
        self.assertIn("A paused envelope keeps every dependent slice", policy)
        self.assertIn("After each `REVISE`", policy)
        self.assertIn("fresh `plan-verifier`", policy)
        self.assertRegex(policy, r"genuine slice\s+split or narrowing")
        self.assertRegex(
            policy,
            r"dependencies and\s+acceptance are independently meaningful",
        )
        self.assertIn("second automatic", policy)
        self.assertIn("pause only that unit", policy)
        self.assertIn("Never treat this cap as `READY`", policy)
        self.assertRegex(policy, r"silently\s+overrule")
        self.assertIn("A readiness unit's Plan epoch changes only when the user materially changes", policy)
        self.assertIn("superficial rewrite", policy)
        self.assertRegex(policy, r"Unrelated\s+`READY` slices may proceed")
        self.assertIn("blocked prerequisites and cross-cutting slices still", policy)
        self.assertIn("User-directed continuation is allowed", policy)
        self.assertIn("not a silent count reset", policy)
        self.assertIn(
            "whether the unit is an envelope or a slice",
            policy,
        )

    def test_envelope_is_an_independent_gate_before_slice_readiness(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        plan = (AGENT_DIR / "plan-verifier.toml").read_text()

        for phrase in (
            "exactly one readiness unit at a time",
            "the envelope first, then one slice",
            "envelope must be `READY` before any child slice readiness review",
            "stable readiness-unit ID",
        ):
            self.assertIn(phrase, policy)
        for phrase in (
            "Review exactly one",
            "either the program envelope or one",
            "Never review both in one call",
            "evidence that its envelope already received `READY`",
            "reviewed before its envelope is `READY`",
        ):
            self.assertIn(phrase, plan)

    def test_security_ordering_approval_and_verifier_vocab_stay_separate(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        plan = (AGENT_DIR / "plan-verifier.toml").read_text()
        outcome = (AGENT_DIR / "verifier.toml").read_text()
        security = (AGENT_DIR / "security-reviewer.toml").read_text()

        self.assertRegex(
            policy,
            r"finish the read-only\s+`security-reviewer`",
        )
        self.assertIn("before the first `plan-verifier` call", policy)
        self.assertRegex(policy, r"Never\s+launch those reviews concurrently")
        self.assertIn("`READY` is readiness only, never user approval", policy)
        self.assertIn("wait for explicit user approval", policy)
        self.assertIn("A ready slice may execute while unrelated or later", policy)
        self.assertIn("blocked prerequisites and cross-cutting", policy)
        self.assertIn("only `CONFIRMED` or `REFUTED`", policy)

        self.assertNotIn("CONFIRMED", plan)
        self.assertNotIn("REFUTED", plan)
        self.assertNotIn("READY", outcome)
        self.assertNotIn("REVISE", outcome)
        self.assertRegex(
            security,
            r"before the first\s+plan-verifier review",
        )
        self.assertIn("does not", security)


if __name__ == "__main__":
    unittest.main()
