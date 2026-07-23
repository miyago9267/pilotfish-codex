from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "templates" / "agents"


class PolicyTests(unittest.TestCase):
    def test_stamp_and_roles_remain_consistent(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        version = (ROOT / "VERSION").read_text().strip()
        self.assertIn(f"<!-- pilotfish-codex v{version} -->", policy)
        for path in AGENTS.glob("*.toml"):
            self.assertEqual(tomllib.loads(path.read_text())["name"], path.stem)
            self.assertIn(f"`{path.stem}`", policy)

    def test_native_spawn_policy_is_typed_bounded_and_no_override(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        for phrase in (
            "non-empty `message`", "known `agent_type`", "`task_name` matching `[a-z0-9_]+`",
            '`fork_turns = "none"`', '`"1"` through `"3"`', "full-history named-role fork",
            "child `model`, `reasoning_effort`, `service_tier`, or", "never retry with an untyped child",
            "namespace-neutral", "Current receipt validation is post-hoc",
        ):
            self.assertIn(phrase, policy)
        self.assertNotIn("agents.spawn_agent", policy)

    def test_policy_proactively_routes_suitable_work_and_parallel_surfaces(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "active delegation signal",
            "proactively delegate",
            "parallel independent discovery",
            "start them in parallel",
            "material Plan to `plan-verifier` before approval",
            "pre-approval security evidence to `security-reviewer`",
            "fully specified mechanical repetition to `mech-executor`",
            "approved, bounded implementation requiring judgment to `executor`",
            "non-trivial implementation",
            "fresh `verifier` for an independent refutation pass",
        ):
            self.assertIn(phrase, policy)

    def test_policy_keeps_parent_accountability_and_local_escape_hatches(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "The parent session remains responsible and accountable throughout",
            "reconciles findings",
            "integrates writes",
            "makes final judgment",
            "small, local, already-stable edit",
            "tightly coupled unknown bug",
            "all-or-nothing child-creation boundary",
            "No untyped fallback is permitted",
            "must not silently substitute an untyped child",
            "takes the bounded work locally",
        ):
            self.assertIn(phrase, policy)

    def test_policy_uses_rebuttable_mechanical_default(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "Stable multi-file mechanical repetition",
            "complete one-shot brief",
            "exclusive ownership",
            "per-item acceptance",
            "dispatch exactly one `mech-executor` before the main session edits by default",
            "main session owns per-item triage, exceptions, integration, and acceptance",
            "must not edit the worker-owned scope",
            "specific named blocker before editing",
            "evolving or coupled evidence",
            "ownership or integration conflict",
            "typed worker unavailability",
            "non-positive net benefit",
            "slightly faster is insufficient",
            "default is rebuttable, not unconditional",
        ):
            self.assertIn(phrase, policy)

    def test_policy_uses_net_benefit_and_stable_recurrence_contracts(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "Outside that qualifying mechanical shape, choose delegation by net benefit",
            "lower cost or quota use",
            "preservation of scarce main-session context",
            "true parallelism",
            "isolated ownership",
            "fresh-context independence",
            "context reconstruction, coordination, integration, and verification cost",
            "Recurring or homogeneous work",
            "stable, complete one-shot brief, not a numeric trigger",
            "remaining items must be independent and the same shape",
            "main session retains triage, exceptions, integration, and acceptance",
        ):
            self.assertIn(phrase, policy)

    def test_policy_verifies_at_smallest_coherent_boundary(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "smallest coherent integration boundary",
            "complete claim can be independently refuted",
            "Verify earlier for security changes",
            "serialization or other data boundaries",
            "irreversible operations",
            "work that could block later integration",
            "substantially unchanged Plan",
            "material revision or new evidence",
        ):
            self.assertIn(phrase, policy)

    def test_policy_schedules_native_parallel_calls_back_to_back(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        policy = " ".join(policy.split())
        for phrase in (
            "Schedule eligible calls by data dependency",
            "independent typed calls are ready",
            "`spawn_agent` calls back-to-back",
            "exclusive file ownership",
            "continue only on disjoint scope",
            "collect every result before dependent work",
        ):
            self.assertIn(phrase, policy)
        self.assertNotIn("run_in_background", policy)
        self.assertNotIn("worktree", policy)

    def test_verifier_contracts_converge_without_crossing_boundaries(self) -> None:
        policy = (ROOT / "templates" / "agents-md.orchestration.md").read_text()
        plan = (AGENTS / "plan-verifier.toml").read_text()
        outcome = (AGENTS / "verifier.toml").read_text()
        security = (AGENTS / "security-reviewer.toml").read_text()
        normalized_policy = " ".join(policy.split())

        for phrase in (
            "program envelope",
            "next executable slice",
            "scope, non-goals",
            "acceptance that proves the slice outcome",
            "slice-local budget",
            "stop conditions",
            "Blocker:",
            "Evidence:",
            "Minimum revision:",
            "Acceptance check:",
            "use a fresh `plan-verifier`",
            "two automatic `REVISE` verdicts for the same unit",
            "surface the blockers and options to the user",
            "substantially unchanged Plan",
            "findings and dispositions into the Plan",
            "two consecutive `REFUTED` verdicts for that claim",
            "stop automatic fix-and-reverify",
        ):
            self.assertIn(phrase, normalized_policy)
        self.assertNotIn("Plan epoch", policy)
        self.assertNotIn("format-recovery", policy)

        self.assertIn("Return exactly one form", plan)
        self.assertIn("explicit outcome, scope and non-goals", plan)
        self.assertIn("acceptance that proves the slice outcome", plan)
        self.assertIn("a slice-local budget", plan)
        self.assertIn("slice-local stop conditions", plan)
        self.assertIn("completed security-reviewer findings", plan)
        self.assertNotIn("CONFIRMED", plan)
        self.assertNotIn("REFUTED", plan)
        self.assertNotIn("READY", outcome)
        self.assertNotIn("REVISE", outcome)
        self.assertIn("first plan-verifier review", security)


if __name__ == "__main__":
    unittest.main()
