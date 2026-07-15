from __future__ import annotations

import json
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "install"))

from verify_dispatch import (  # noqa: E402
    EvidenceError,
    RoleBinding,
    build_codex_command,
    candidate_day_directories,
    classify_exec_failure,
    extract_child_thread_id,
    inspect_dispatch,
    load_jsonl,
    locate_rollout,
    main as verify_main,
    parse_exec_thread_id,
    read_role_binding,
)


PARENT_ID = "019f7000-0000-7000-8000-000000000001"
CHILD_ID = "019f7000-0000-7000-8000-000000000002"
CALL_ID = "call_model_probe"


def parent_events(
    *,
    namespace: str = "agents",
    agent_type: str | None = "scout",
    fork_turns: str | None = "none",
    multi_agent_version: str = "v2",
    parent_model: str = "gpt-5.6-terra",
) -> list[dict]:
    arguments: dict[str, str] = {
        "task_name": "model_probe",
        "message": "Reply with one line.",
    }
    if agent_type is not None:
        arguments["agent_type"] = agent_type
    if fork_turns is not None:
        arguments["fork_turns"] = fork_turns

    return [
        {"type": "session_meta", "payload": {"id": PARENT_ID}},
        {
            "type": "turn_context",
            "payload": {
                "model": parent_model,
                "effort": "low",
                "multi_agent_version": multi_agent_version,
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": namespace,
                "arguments": json.dumps(arguments),
                "call_id": CALL_ID,
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": CALL_ID,
                "agent_thread_id": CHILD_ID,
                "agent_path": "/root/model_probe",
                "kind": "started",
            },
        },
    ]


def child_events(
    *,
    parent_id: str = PARENT_ID,
    model: str = "gpt-5.6-luna",
    effort: str = "low",
) -> list[dict]:
    return [
        {
            "type": "session_meta",
            "payload": {"id": CHILD_ID, "parent_thread_id": parent_id},
        },
        {
            "type": "turn_context",
            "payload": {"model": model, "effort": effort},
        },
    ]


class DispatchEvidenceTests(unittest.TestCase):
    binding = RoleBinding(model="gpt-5.6-luna", effort="low")

    def test_adapter_proves_exact_child_uses_a_different_model(self) -> None:
        verdict = inspect_dispatch(
            parent_events(),
            child_events(),
            expected_role=self.binding,
            expected_namespace="agents",
        )

        self.assertEqual(verdict.status, "ADAPTER_OK")
        self.assertEqual(verdict.reason, "verified_distinct_model")
        self.assertEqual(verdict.parent_thread_id, PARENT_ID)
        self.assertEqual(verdict.child_thread_id, CHILD_ID)
        self.assertEqual(verdict.parent_model, "gpt-5.6-terra")
        self.assertEqual(verdict.child_model, "gpt-5.6-luna")

    def test_native_namespace_reports_native_ok(self) -> None:
        unproven = inspect_dispatch(
            parent_events(namespace="collaboration"),
            child_events(),
            expected_role=self.binding,
            expected_namespace="collaboration",
        )
        verdict = inspect_dispatch(
            parent_events(namespace="collaboration"),
            child_events(),
            expected_role=self.binding,
            expected_namespace="collaboration",
            adapter_free=True,
        )

        self.assertEqual(unproven.status, "FAILED")
        self.assertEqual(unproven.reason, "native_adapter_state_unproven")
        self.assertEqual(verdict.status, "NATIVE_OK")

    def test_v1_is_skipped_as_adapter_not_exercised(self) -> None:
        verdict = inspect_dispatch(
            parent_events(multi_agent_version="v1"),
            child_events(),
            expected_role=self.binding,
            expected_namespace="agents",
        )

        self.assertEqual(verdict.status, "SKIPPED")
        self.assertEqual(verdict.reason, "adapter_not_exercised")

    def test_namespace_role_and_context_mismatches_fail_closed(self) -> None:
        cases = (
            (parent_events(namespace="collaboration"), "namespace_mismatch"),
            (parent_events(agent_type=None), "agent_type_mismatch"),
            (parent_events(fork_turns="all"), "fork_turns_mismatch"),
        )

        for events, reason in cases:
            with self.subTest(reason=reason):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(verdict.status, "FAILED")
                self.assertEqual(verdict.reason, reason)

    def test_missing_ambiguous_or_invalid_spawn_evidence_fails_closed(self) -> None:
        missing_activity = parent_events()[:-1]
        duplicate_spawn = parent_events()
        duplicate_spawn.insert(3, dict(duplicate_spawn[2]))
        invalid_task = parent_events()
        invalid_arguments = json.loads(invalid_task[2]["payload"]["arguments"])
        invalid_arguments["task_name"] = "Bad-Task"
        invalid_task[2]["payload"]["arguments"] = json.dumps(invalid_arguments)
        invalid_task[3]["payload"]["agent_path"] = "/root/Bad-Task"

        cases = (
            (missing_activity, "child_activity_missing"),
            (duplicate_spawn, "spawn_call_ambiguous"),
            (invalid_task, "task_name_mismatch"),
        )
        for events, reason in cases:
            with self.subTest(reason=reason):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual((verdict.status, verdict.reason), ("FAILED", reason))

    def test_missing_or_empty_correlation_ids_fail_closed(self) -> None:
        for missing_value in (None, ""):
            events = parent_events()
            if missing_value is None:
                events[2]["payload"].pop("call_id")
                events[3]["payload"].pop("event_id")
            else:
                events[2]["payload"]["call_id"] = missing_value
                events[3]["payload"]["event_id"] = missing_value

            with self.subTest(missing_value=missing_value):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "spawn_call_id_missing"),
                )
                with self.assertRaises(EvidenceError):
                    extract_child_thread_id(events)

    def test_missing_or_mismatched_activity_event_id_fails_closed(self) -> None:
        for event_id in (None, "", "different-call"):
            events = parent_events()
            if event_id is None:
                events[3]["payload"].pop("event_id")
            else:
                events[3]["payload"]["event_id"] = event_id

            with self.subTest(event_id=event_id):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "child_activity_missing"),
                )
                with self.assertRaises(EvidenceError):
                    extract_child_thread_id(events)

    def test_non_object_spawn_arguments_fail_closed(self) -> None:
        for arguments in ([], "scout", None, 1):
            events = parent_events()
            events[2]["payload"]["arguments"] = json.dumps(arguments)

            with self.subTest(arguments=arguments):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "spawn_arguments_invalid"),
                )
                with self.assertRaises(EvidenceError):
                    extract_child_thread_id(events)

    def test_parent_child_and_role_binding_mismatches_fail_closed(self) -> None:
        cases = (
            (child_events(parent_id="wrong-parent"), "parent_child_mismatch"),
            (child_events(model="gpt-5.6-sol"), "child_model_mismatch"),
            (child_events(effort="medium"), "child_effort_mismatch"),
        )

        for events, reason in cases:
            with self.subTest(reason=reason):
                verdict = inspect_dispatch(
                    parent_events(),
                    events,
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(verdict.status, "FAILED")
                self.assertEqual(verdict.reason, reason)

    def test_conflicting_turn_context_evidence_fails_closed(self) -> None:
        conflicting_parent = parent_events()
        conflicting_parent.insert(
            2,
            {
                "type": "turn_context",
                "payload": {
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                    "multi_agent_version": "v2",
                },
            },
        )
        conflicting_child = child_events()
        conflicting_child.append(
            {
                "type": "turn_context",
                "payload": {"model": "gpt-5.6-sol", "effort": "max"},
            }
        )

        cases = (
            (conflicting_parent, child_events(), "parent_context_conflict"),
            (parent_events(), conflicting_child, "child_context_conflict"),
        )
        for parents, children, reason in cases:
            with self.subTest(reason=reason):
                verdict = inspect_dispatch(
                    parents,
                    children,
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual((verdict.status, verdict.reason), ("FAILED", reason))

    def test_invalid_turn_context_required_fields_fail_closed(self) -> None:
        parent_cases = (
            ("model", []),
            ("effort", None),
            ("multi_agent_version", 2),
        )
        for field, value in parent_cases:
            events = parent_events()
            events[1]["payload"][field] = value
            with self.subTest(side="parent", field=field):
                verdict = inspect_dispatch(
                    events,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "parent_context_invalid"),
                )

        for field, value in (("model", []), ("effort", "")):
            events = child_events()
            events[1]["payload"][field] = value
            with self.subTest(side="child", field=field):
                verdict = inspect_dispatch(
                    parent_events(),
                    events,
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "child_context_invalid"),
                )

    def test_malformed_turn_context_payload_alongside_valid_evidence_fails_closed(
        self,
    ) -> None:
        for malformed in (
            {"type": "turn_context"},
            {"type": "turn_context", "payload": None},
        ):
            parents = parent_events() + [malformed]
            with self.subTest(side="parent", malformed=malformed):
                verdict = inspect_dispatch(
                    parents,
                    child_events(),
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "parent_context_invalid"),
                )

            children = child_events() + [malformed]
            with self.subTest(side="child", malformed=malformed):
                verdict = inspect_dispatch(
                    parent_events(),
                    children,
                    expected_role=self.binding,
                    expected_namespace="agents",
                )
                self.assertEqual(
                    (verdict.status, verdict.reason),
                    ("FAILED", "child_context_invalid"),
                )

    def test_malformed_relevant_parent_evidence_payload_fails_closed(self) -> None:
        expected_reasons = {
            "session_meta": "parent_evidence_invalid",
            "turn_context": "parent_context_invalid",
            "response_item": "parent_evidence_invalid",
            "event_msg": "parent_evidence_invalid",
        }
        for event_type, reason in expected_reasons.items():
            for payload in ("missing", None, []):
                malformed = {"type": event_type}
                if payload != "missing":
                    malformed["payload"] = payload
                events = parent_events() + [malformed]

                with self.subTest(event_type=event_type, payload=payload):
                    verdict = inspect_dispatch(
                        events,
                        child_events(),
                        expected_role=self.binding,
                        expected_namespace="agents",
                    )
                    self.assertEqual(
                        (verdict.status, verdict.reason),
                        ("FAILED", reason),
                    )

    def test_malformed_relevant_child_evidence_payload_fails_closed(self) -> None:
        expected_reasons = {
            "session_meta": "child_evidence_invalid",
            "turn_context": "child_context_invalid",
        }
        for event_type, reason in expected_reasons.items():
            for payload in ("missing", None, []):
                malformed = {"type": event_type}
                if payload != "missing":
                    malformed["payload"] = payload
                events = child_events() + [malformed]

                with self.subTest(event_type=event_type, payload=payload):
                    verdict = inspect_dispatch(
                        parent_events(),
                        events,
                        expected_role=self.binding,
                        expected_namespace="agents",
                    )
                    self.assertEqual(
                        (verdict.status, verdict.reason),
                        ("FAILED", reason),
                    )

    def test_malformed_relevant_extractor_evidence_raises(self) -> None:
        for event_type in ("response_item", "event_msg"):
            for payload in ("missing", None, []):
                malformed = {"type": event_type}
                if payload != "missing":
                    malformed["payload"] = payload

                with self.subTest(event_type=event_type, payload=payload):
                    with self.assertRaises(EvidenceError):
                        extract_child_thread_id(parent_events() + [malformed])

    def test_non_evidence_events_do_not_require_payload_objects(self) -> None:
        extras = [
            {"type": "unknown"},
            {"type": "normal", "payload": None},
            {"type": "diagnostic", "payload": []},
        ]

        verdict = inspect_dispatch(
            parent_events() + extras,
            child_events() + extras,
            expected_role=self.binding,
            expected_namespace="agents",
        )

        self.assertEqual(verdict.status, "ADAPTER_OK")
        self.assertEqual(extract_child_thread_id(parent_events() + extras), CHILD_ID)

    def test_non_object_outer_evidence_event_fails_closed(self) -> None:
        malformed = parent_events() + [None]

        verdict = inspect_dispatch(
            malformed,
            child_events(),
            expected_role=self.binding,
            expected_namespace="agents",
        )

        self.assertEqual(
            (verdict.status, verdict.reason),
            ("FAILED", "parent_evidence_invalid"),
        )
        with self.assertRaises(EvidenceError):
            extract_child_thread_id(malformed)

    def test_duplicate_consistent_turn_context_evidence_is_accepted(self) -> None:
        parents = parent_events()
        parents.insert(2, dict(parents[1], payload=dict(parents[1]["payload"])))
        children = child_events()
        children.append(dict(children[1], payload=dict(children[1]["payload"])))

        verdict = inspect_dispatch(
            parents,
            children,
            expected_role=self.binding,
            expected_namespace="agents",
        )

        self.assertEqual(verdict.status, "ADAPTER_OK")

    def test_inherited_parent_model_never_passes(self) -> None:
        inherited = RoleBinding(model="gpt-5.6-terra", effort="low")

        verdict = inspect_dispatch(
            parent_events(),
            child_events(model="gpt-5.6-terra"),
            expected_role=inherited,
            expected_namespace="agents",
        )

        self.assertEqual(verdict.status, "FAILED")
        self.assertEqual(verdict.reason, "inherited_parent_model")


class DispatchRolloutLocationTests(unittest.TestCase):
    def test_exec_thread_id_accepts_current_json_event_shapes(self) -> None:
        direct = json.dumps({"type": "thread.started", "thread_id": PARENT_ID})
        nested = json.dumps(
            {"type": "thread.started", "thread": {"id": PARENT_ID}}
        )

        self.assertEqual(parse_exec_thread_id(direct), PARENT_ID)
        self.assertEqual(parse_exec_thread_id(nested), PARENT_ID)

    def test_exec_thread_id_rejects_missing_or_ambiguous_ids(self) -> None:
        with self.assertRaises(EvidenceError):
            parse_exec_thread_id(json.dumps({"type": "turn.completed"}))

        duplicate = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": PARENT_ID}),
                json.dumps({"type": "thread.started", "thread_id": CHILD_ID}),
            )
        )
        with self.assertRaises(EvidenceError):
            parse_exec_thread_id(duplicate)

    def test_exec_thread_id_rejects_non_object_json_events(self) -> None:
        for event in ([], "thread.started", None, 1):
            with self.subTest(event=event):
                with self.assertRaises(EvidenceError):
                    parse_exec_thread_id(json.dumps(event))

    def test_rollout_lookup_is_exact_and_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = root / "2026" / "07" / "15"
            day.mkdir(parents=True)
            expected = day / f"rollout-test-{PARENT_ID}.jsonl"
            expected.write_text("{}\n", encoding="utf-8")

            self.assertEqual(locate_rollout(root, PARENT_ID, [day]), expected.resolve())

            duplicate_day = root / "2026" / "07" / "16"
            duplicate_day.mkdir(parents=True)
            (duplicate_day / f"rollout-duplicate-{PARENT_ID}.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )

            with self.assertRaises(EvidenceError):
                locate_rollout(root, PARENT_ID, [day, duplicate_day])

    def test_rollout_rejects_non_object_payloads_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            rollout.write_text(
                json.dumps({"type": "response_item", "payload": "not-an-object"})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceError):
                load_jsonl(rollout)

        hostile = [
            {"type": "session_meta", "payload": "spoof"},
            {"type": "turn_context", "payload": None},
        ]
        verdict = inspect_dispatch(
            hostile,
            [],
            expected_role=RoleBinding(model="gpt-5.6-luna", effort="low"),
            expected_namespace="agents",
        )
        self.assertEqual(verdict.status, "FAILED")

    def test_rollout_loader_ignores_non_evidence_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            event = {"type": "diagnostic", "payload": ["normal", "data"]}
            rollout.write_text(json.dumps(event) + "\n", encoding="utf-8")

            self.assertEqual(load_jsonl(rollout), [event])

    def test_rollout_lookup_treats_glob_metacharacters_literally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = root / "2026" / "07" / "15"
            day.mkdir(parents=True)
            (day / "rollout-test-abcd1.jsonl").write_text("{}\n", encoding="utf-8")

            for hostile in ("abcd?", "abcd[1]", "abc*", "*", "**/abcd1"):
                with self.assertRaises(EvidenceError):
                    locate_rollout(root, hostile, [day])

            literal = day / "rollout-test-abcd[1].jsonl"
            literal.write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                locate_rollout(root, "abcd[1]", [day]), literal.resolve()
            )

    def test_rollout_lookup_does_not_fall_back_to_fuzzy_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = root / "2026" / "07" / "15"
            day.mkdir(parents=True)
            (day / f"prefix-{PARENT_ID}-suffix.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )

            with self.assertRaises(EvidenceError):
                locate_rollout(root, PARENT_ID, [day])

    def test_rollout_lookup_rejects_candidates_outside_the_session_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / f"rollout-test-{PARENT_ID}.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )

            with self.assertRaises(EvidenceError):
                locate_rollout(sessions, PARENT_ID, [outside])

    def test_rollout_lookup_rejects_symlinks_that_escape_the_session_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            day = sessions / "2026" / "07" / "15"
            day.mkdir(parents=True)
            outside = root / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            (day / f"rollout-test-{PARENT_ID}.jsonl").symlink_to(outside)

            with self.assertRaises(EvidenceError):
                locate_rollout(sessions, PARENT_ID, [day])

    def test_exact_child_id_comes_from_the_correlated_activity(self) -> None:
        self.assertEqual(extract_child_thread_id(parent_events()), CHILD_ID)

        ambiguous = parent_events() + [parent_events()[-1]]
        with self.assertRaises(EvidenceError):
            extract_child_thread_id(ambiguous)


class DispatchLiveContractTests(unittest.TestCase):
    def test_role_binding_reads_only_model_and_effort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scout.toml"
            path.write_text(
                """
name = "scout"
model = "gpt-5.6-luna"
model_reasoning_effort = "low"
developer_instructions = "ignored by binding reader"
""".lstrip(),
                encoding="utf-8",
            )

            self.assertEqual(
                read_role_binding(path),
                RoleBinding(model="gpt-5.6-luna", effort="low"),
            )

    def test_role_binding_rejects_missing_or_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scout.toml"
            path.write_text('model = "gpt-5.6-luna"\n', encoding="utf-8")
            with self.assertRaises(EvidenceError):
                read_role_binding(path)

    def test_adapter_and_native_commands_isolate_the_transport(self) -> None:
        adapter = build_codex_command(
            codex_bin="codex",
            cwd=ROOT,
            mode="adapter",
            parent_model="gpt-5.6-terra",
        )
        native = build_codex_command(
            codex_bin="codex",
            cwd=ROOT,
            mode="native",
            parent_model="gpt-5.6-terra",
        )

        self.assertIn("--json", adapter)
        self.assertIn("--strict-config", adapter)
        self.assertNotIn("--ignore-user-config", adapter)
        self.assertIn("agents.spawn_agent", adapter[-1])
        self.assertIn("agent_type='scout'", adapter[-1])
        self.assertIn("fork_turns='none'", adapter[-1])

        self.assertIn("--ignore-user-config", native)
        self.assertNotIn(
            "features.multi_agent_v2.hide_spawn_agent_metadata=false",
            native,
        )
        self.assertIn("collaboration.spawn_agent", native[-1])
        self.assertNotIn("agents.spawn_agent", native[-1])

    def test_native_live_probe_skips_before_quota_without_schema_introspection(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = verify_main(
                [
                    "--live",
                    "--yes",
                    "--mode",
                    "native",
                    "--codex-bin",
                    "must-not-be-called",
                ]
            )

        self.assertEqual(result, 2)
        self.assertIn(
            "SKIPPED reason=native_schema_introspection_unavailable",
            stdout.getvalue(),
        )
        self.assertNotIn("spends real model quota", stderr.getvalue())

    def test_failed_preflight_prints_cost_safety_warning(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = verify_main(
                    [
                        "--live",
                        "--yes",
                        "--codex-home",
                        directory,
                        "--repository-root",
                        str(ROOT),
                    ]
                )

        self.assertEqual(result, 1)
        self.assertEqual(
            stdout.getvalue().strip(),
            "FAILED reason=role_preflight_failed",
        )
        self.assertIn("role preflight failed:", stderr.getvalue())
        self.assertIn("role file not found:", stderr.getvalue())
        self.assertIn("stop named-role dispatch", stderr.getvalue())
        self.assertNotIn("spends real model quota", stderr.getvalue())

    def test_exec_failures_distinguish_unavailable_prerequisites(self) -> None:
        auth = classify_exec_failure(stdout="", stderr="Not logged in")
        model = classify_exec_failure(
            stdout="",
            stderr="Requested model is unavailable",
        )
        runtime = classify_exec_failure(stdout="", stderr="unexpected failure")

        self.assertEqual(
            (auth.status, auth.reason),
            ("SKIPPED", "auth_unavailable"),
        )
        self.assertEqual(
            (model.status, model.reason),
            ("SKIPPED", "parent_model_unavailable"),
        )
        self.assertEqual(
            (runtime.status, runtime.reason),
            ("FAILED", "codex_exec_failed"),
        )

    def test_day_lookup_is_bounded_to_explicit_dates(self) -> None:
        from datetime import datetime, timezone

        root = Path("/sessions")
        started = datetime(2026, 7, 15, 23, 59, tzinfo=timezone.utc)
        ended = datetime(2026, 7, 16, 0, 1, tzinfo=timezone.utc)

        directories = candidate_day_directories(root, started, ended)

        self.assertEqual(
            directories,
            [root / "2026" / "07" / "15", root / "2026" / "07" / "16"],
        )

    def test_live_probe_requires_two_explicit_opt_ins(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = verify_main([])
        self.assertEqual(result, 2)
        self.assertIn("SKIPPED reason=live_flag_required", stdout.getvalue())

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = verify_main(["--live"])
        self.assertEqual(result, 2)
        self.assertIn("SKIPPED reason=operator_opt_in_required", stdout.getvalue())

    def test_preflight_rejects_role_drift_before_codex_or_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            agents = codex_home / "agents"
            agents.mkdir()
            installed = agents / "scout.toml"
            shutil.copy2(ROOT / "templates" / "agents" / "scout.toml", installed)
            content = installed.read_text(encoding="utf-8")
            installed.write_text(
                content.replace(
                    "Report the direct answer",
                    "Report a direct answer",
                ),
                encoding="utf-8",
            )
            shutil.copy2(
                ROOT / "templates" / "config.snippet.toml",
                codex_home / "config.toml",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = verify_main(
                    [
                        "--live",
                        "--yes",
                        "--codex-home",
                        str(codex_home),
                        "--codex-bin",
                        "must-not-be-called",
                    ]
                )

        self.assertEqual(result, 1)
        self.assertIn("FAILED reason=installed_role_drift", stdout.getvalue())
        self.assertNotIn("spends real model quota", stderr.getvalue())

    def test_concurrency_one_skips_before_codex_or_quota(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            agents = codex_home / "agents"
            agents.mkdir()
            shutil.copy2(
                ROOT / "templates" / "agents" / "scout.toml",
                agents / "scout.toml",
            )
            config = (ROOT / "templates" / "config.snippet.toml").read_text(
                encoding="utf-8"
            )
            (codex_home / "config.toml").write_text(
                config.replace(
                    "max_concurrent_threads_per_session = 4",
                    "max_concurrent_threads_per_session = 1",
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = verify_main(
                    [
                        "--live",
                        "--yes",
                        "--codex-home",
                        str(codex_home),
                        "--codex-bin",
                        "must-not-be-called",
                    ]
                )

        self.assertEqual(result, 2)
        self.assertIn("SKIPPED reason=child_delegation_disabled", stdout.getvalue())
        self.assertNotIn("spends real model quota", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
