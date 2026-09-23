"""Security boundaries for the source-owned automatic Plan-review hook."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

import pilotfish_autoroute_gate as gate  # noqa: E402


SESSION = "019f-parent-session"
TURN = "019f-current-turn"
ROOT_STARTED_AT = 1_700_000_000
TRIGGER = (
    "Review the material cross-service production credential migration Plan "
    "and determine whether it is ready for user approval."
)


def prompt_input(prompt: str, *, turn_id: str = TURN) -> dict[str, object]:
    return {
        "session_id": SESSION,
        "turn_id": turn_id,
        "transcript_path": None,
        "cwd": "/workspace",
        "hook_event_name": "UserPromptSubmit",
        "model": "gpt-6-luna",
        "permission_mode": "never",
        "prompt": prompt,
    }


def stop_input(
    transcript: Path,
    *,
    turn_id: str = TURN,
    active: bool = False,
) -> dict[str, object]:
    return {
        "session_id": SESSION,
        "turn_id": turn_id,
        "transcript_path": str(transcript),
        "cwd": "/workspace",
        "hook_event_name": "Stop",
        "model": "gpt-6-luna",
        "permission_mode": "never",
        "stop_hook_active": active,
        "last_assistant_message": "private response",
    }


def write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def task_started(*, started_at: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"type": "task_started", "turn_id": TURN}
    if started_at is not None:
        payload["started_at"] = started_at
    return {
        "type": "event_msg",
        "payload": payload,
    }


def session_meta() -> dict[str, object]:
    return {"type": "session_meta", "payload": {"id": SESSION}}


def child_events(
    child_id: str,
    *,
    output: str = "READY",
    complete: bool = True,
    complete_turn_id: str | None = None,
    model: str = "gpt-6-sol",
    effort: str = "high",
) -> list[dict[str, object]]:
    child_turn = f"{child_id}-turn"
    events: list[dict[str, object]] = [
        {
            "timestamp": "2023-11-14T22:13:21Z",
            "type": "session_meta",
            "payload": {
                "id": child_id,
                "parent_thread_id": SESSION,
                "agent_role": "plan-verifier",
            },
        },
        {
            "type": "turn_context",
            "payload": {"model": model, "effort": effort},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": child_turn,
                "started_at": ROOT_STARTED_AT + 1,
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output}],
            },
        },
    ]
    if complete:
        events.append(
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": complete_turn_id or child_turn,
                },
            }
        )
    return events


class AutorouteHookTests(unittest.TestCase):
    def test_atomic_route_stays_local_and_cheap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()

            payload = gate.handle(
                prompt_input("請執行 `git status`。"),
                codex_home=home,
            )

            self.assertIsInstance(payload, dict)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn('"route":"atomic"', context)
            self.assertIn('"model_policy":"cheap"', context)
            self.assertIn('"required_role":"none"', context)
            self.assertIn('"trigger":"prompt_submit"', context)
            self.assertIn('"purpose":"local_atomic_action"', context)
            self.assertIn('"dispatch":{"mode":"parent_local"}', context)
            self.assertIn('"escalate_on":["unexpected_result","error","retry","target_change","unlisted_next_action"]', context)
            self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_routine_and_uncertain_work_stay_on_cheap_guarded_route(self) -> None:
        prompts = (
            "Astra可以少量出現，但不能隨便就冒出來啊不然會貴死",
            "請用工具檢查這個本地設定。",
            "Luna Max和Luna Medium的速度會差很多嗎？",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "codex-home"
                home.mkdir()

                payload = gate.handle(prompt_input(prompt), codex_home=home)

                self.assertIsInstance(payload, dict)
                context = payload["hookSpecificOutput"]["additionalContext"]
                self.assertIn('"route":"guarded"', context)
                self.assertIn('"model_policy":"cheap"', context)
                self.assertIn('"purpose":"cheap_guarded_probe"', context)
                self.assertIn('"required_role":"none"', context)
                self.assertNotIn("ROUTE_ESCALATION_REQUIRED", context)
                self.assertNotIn("gpt-6-astra@high", context)
                self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_judgment_route_automatically_requires_sol_executor(self) -> None:
        prompts = (
            "請設計這個 parser 的修復流程。",
            "請為這個 parser 選擇適合的工具。",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "codex-home"
                home.mkdir()

                payload = gate.handle(prompt_input(prompt), codex_home=home)

                self.assertIsInstance(payload, dict)
                context = payload["hookSpecificOutput"]["additionalContext"]
                self.assertIn('"route":"judgment"', context)
                self.assertIn('"model_policy":"capable"', context)
                self.assertIn('"required_role":"sol-executor"', context)
                self.assertIn("gpt-6-sol@high", context)
                self.assertNotIn("gpt-6-astra@high", context)
                self.assertIn('"purpose":"bounded_judgment_execution"', context)
                self.assertIn(
                    '"dispatch":{"agent_type":"sol-executor","fork_turns":"none",'
                    '"mode":"typed_role","task_name":"automatic_model_route"}',
                    context,
                )
                marker = gate._route_marker_path(home, SESSION, create=False)
                self.assertIsNotNone(marker)
                self.assertEqual(
                    json.loads(marker.read_text())["required_role"],
                    "sol-executor",
                )

    def test_copied_route_directive_does_not_reopen_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            directive = gate._model_route_output("sol-executor")["reason"]

            payload = gate.handle(
                prompt_input("我看到這段 hook 輸出：\n" + directive),
                codex_home=home,
            )

            self.assertIsInstance(payload, dict)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn('"route":"guarded"', context)
            self.assertIn('"model_policy":"cheap"', context)
            self.assertIn('"required_role":"none"', context)
            self.assertNotIn("gpt-6-sol@high", context)
            self.assertNotIn("gpt-6-astra@high", context)
            self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_qa_route_automatically_requires_sol_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()

            payload = gate.handle(
                prompt_input("請做 QA，確認這個 parser 的修復符合驗收條件。"),
                codex_home=home,
            )

            self.assertIsInstance(payload, dict)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn('"route":"judgment"', context)
            self.assertIn('"required_role":"sol-executor"', context)
            self.assertIn("gpt-6-sol@high", context)
            self.assertNotIn("gpt-6-astra@high", context)

    def test_deep_judgment_route_automatically_requires_strong_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()

            payload = gate.handle(
                prompt_input(
                    "請重新設計跨系統架構，評估兩種資料遷移方案的權衡，並處理衝突證據。"
                ),
                codex_home=home,
            )

            self.assertIsInstance(payload, dict)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn('"route":"deep_judgment"', context)
            self.assertIn('"model_policy":"strong"', context)
            self.assertIn('"required_role":"executor"', context)
            self.assertIn("gpt-6-astra@high", context)
            self.assertIn('"purpose":"bounded_deep_judgment_execution"', context)
            self.assertIn(
                '"dispatch":{"agent_type":"executor","fork_turns":"none",'
                '"mode":"typed_role","task_name":"automatic_model_route"}',
                context,
            )
            self.assertIn('"escalate_on":[]', context)
            marker = gate._route_marker_path(home, SESSION, create=False)
            self.assertIsNotNone(marker)
            self.assertEqual(json.loads(marker.read_text())["required_role"], "executor")

    def test_deep_judgment_route_retries_once_when_executor_was_not_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(
                prompt_input(
                    "請重新設計跨系統架構，評估兩種資料遷移方案的權衡，並處理衝突證據。"
                ),
                codex_home=home,
            )
            write_events(transcript, [session_meta(), task_started()])

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.MODEL_ROUTE_OUTPUT,
            )
            self.assertIn("`fork_turns=none`", gate.MODEL_ROUTE_OUTPUT["reason"])
            self.assertIn("`task_name=automatic_model_route`", gate.MODEL_ROUTE_OUTPUT["reason"])
            marker = gate._route_marker_path(home, SESSION, create=False)
            self.assertTrue(json.loads(marker.read_text())["attempted"])
            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))

    def test_route_continuation_does_not_relock_when_stop_is_already_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(
                prompt_input(
                    "請重新設計跨系統架構，評估兩種資料遷移方案的權衡，並處理衝突證據。"
                ),
                codex_home=home,
            )
            write_events(transcript, [session_meta(), task_started()])

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.MODEL_ROUTE_OUTPUT,
            )
            continuation_turn = "route-continuation"
            continuation = gate.handle(
                prompt_input(
                    gate.MODEL_ROUTE_OUTPUT["reason"],
                    turn_id=continuation_turn,
                ),
                codex_home=home,
            )
            self.assertIsInstance(continuation, dict)
            self.assertIn(
                '"task_name":"automatic_model_route"',
                continuation["hookSpecificOutput"]["additionalContext"],
            )
            write_events(
                transcript,
                [session_meta(), task_started()],
            )
            self.assertIsNone(
                gate.handle(
                    stop_input(
                        transcript,
                        turn_id=continuation_turn,
                        active=True,
                    ),
                    codex_home=home,
                )
            )
            route_marker = gate._route_marker_path(home, SESSION, create=False)
            self.assertIsNotNone(route_marker)
            self.assertFalse(route_marker.exists())

    def test_deep_judgment_route_clears_after_matching_executor_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(
                prompt_input("請重新設計跨服務架構並處理衝突證據。"),
                codex_home=home,
            )
            write_events(
                transcript,
                [
                    session_meta(),
                    task_started(),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "spawn_agent",
                            "call_id": "executor-call",
                            "arguments": json.dumps(
                                {
                                    "message": "Own the bounded implementation.",
                                    "agent_type": "executor",
                                    "task_name": "automatic_model_route",
                                    "fork_turns": "none",
                                }
                            ),
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "sub_agent_activity",
                            "kind": "started",
                            "event_id": "executor-call",
                            "agent_thread_id": "executor-child",
                        },
                    },
                ],
            )

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))
            route_marker = gate._route_marker_path(home, SESSION, create=False)
            self.assertIsNotNone(route_marker)
            self.assertFalse(route_marker.exists())

    def test_judgment_route_clears_after_matching_sol_executor_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(
                prompt_input("請設計這個 parser 的修復流程。"),
                codex_home=home,
            )
            write_events(
                transcript,
                [
                    session_meta(),
                    task_started(),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "spawn_agent",
                            "call_id": "sol-executor-call",
                            "arguments": json.dumps(
                                {
                                    "message": "Own the bounded implementation.",
                                    "agent_type": "sol-executor",
                                    "task_name": "automatic_model_route",
                                    "fork_turns": "none",
                                }
                            ),
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "sub_agent_activity",
                            "kind": "started",
                            "event_id": "sol-executor-call",
                            "agent_thread_id": "sol-executor-child",
                        },
                    },
                ],
            )

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))
            route_marker = gate._route_marker_path(home, SESSION, create=False)
            self.assertIsNotNone(route_marker)
            self.assertFalse(route_marker.exists())

    def test_judgment_route_retries_with_sol_executor_when_child_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(
                prompt_input("請設計這個 parser 的修復流程。"),
                codex_home=home,
            )
            write_events(transcript, [session_meta(), task_started()])

            output = gate.handle(stop_input(transcript), codex_home=home)

            self.assertIsNotNone(output)
            self.assertIn("`agent_type=sol-executor`", output["reason"])
            self.assertIn("`fork_turns=none`", output["reason"])

    def test_missing_review_block_explains_wait_state_and_write_boundary(self) -> None:
        self.assertIn("Status: WAITING_FOR_REVIEW", gate.BLOCK_REASON)
        self.assertIn("not a user decision", gate.BLOCK_REASON)
        self.assertIn("read-only local inspection or preparation", gate.BLOCK_REASON)
        self.assertIn("do not create, rotate, or revoke credentials", gate.BLOCK_REASON)
        self.assertIn("Do not emit PAUSED_NEEDS_USER", gate.BLOCK_REASON)

    def test_explicit_review_intent_is_redacted_and_turn_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            payload = gate.handle(
                prompt_input("快一點處理，先不要額外審查這個本地修改。"),
                codex_home=home,
            )

            self.assertIsInstance(payload, dict)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn('"review_intent":"fast"', context)
            self.assertIn('"scope":"turn"', context)
            self.assertNotIn("本地修改", context)

            gate.handle(
                prompt_input("請修正下一回合的拼字。", turn_id="next-turn"),
                codex_home=home,
            )
            next_payload = gate.handle(
                prompt_input("請修正下一回合的拼字。", turn_id="next-turn"),
                codex_home=home,
            )
            self.assertIsInstance(next_payload, dict)
            self.assertIn(
                '"route":"atomic"',
                next_payload["hookSpecificOutput"]["additionalContext"],
            )
            self.assertNotIn("review_intent", next_payload["hookSpecificOutput"]["additionalContext"])

    def test_ambiguous_or_quoted_review_intent_falls_back_to_default(self) -> None:
        prompts = (
            "不要為了快而跳過驗證，請先說明。",
            "請把『嚴格審查』當成文件範例，不要改變這次模式。",
            "先快一點，但也請完整嚴格審查。",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIsNone(gate.classify_review_intent(prompt))

    def test_strict_intent_preserves_mandatory_review_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            payload = gate.handle(
                prompt_input("請完整嚴格審查這個跨服務 production credential migration Plan。"),
                codex_home=home,
            )
            self.assertIn('"review_intent":"strict"', payload["hookSpecificOutput"]["additionalContext"])
            marker = next((home / gate.MARKER_DIRECTORY).glob("*.json"))
            value = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(value["required_task"], "automatic_plan_review")

    def test_marker_is_private_redacted_and_category_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()

            payload = gate.handle(prompt_input(TRIGGER), codex_home=home)
            self.assertIsInstance(payload, dict)
            self.assertIn(
                '"required_role":"security-reviewer"',
                payload["hookSpecificOutput"]["additionalContext"],
            )

            marker_dir = home / gate.MARKER_DIRECTORY
            markers = list(marker_dir.glob("*.json"))
            self.assertEqual(len(markers), 1)
            marker = json.loads(markers[0].read_text(encoding="utf-8"))
            self.assertEqual(
                set(marker),
                {
                    "schema",
                    "session_id",
                    "turn_id",
                    "categories",
                    "required_task",
                    "attempted",
                    "blocker_fingerprint",
                },
            )
            self.assertEqual(marker["session_id"], SESSION)
            self.assertEqual(marker["turn_id"], TURN)
            self.assertEqual(marker["categories"], sorted(marker["categories"]))
            self.assertEqual(marker["required_task"], "automatic_plan_review")
            self.assertFalse(marker["attempted"])
            self.assertNotIn("credential migration", markers[0].read_text())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(marker_dir.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(markers[0].stat().st_mode), 0o600)

    def test_ordinary_prompt_clears_stale_session_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            gate.handle(prompt_input(TRIGGER), codex_home=home)

            gate.handle(
                prompt_input("Please fix the spelling in this local comment.", turn_id="next-turn"),
                codex_home=home,
            )

            self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_message_content_cannot_spoof_structured_child_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [
                    session_meta(),
                    task_started(started_at=ROOT_STARTED_AT),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "type": "function_call",
                                            "name": "spawn_agent",
                                            "arguments": {"agent_type": "plan-verifier"},
                                            "sub_agent_activity": "started",
                                        }
                                    ),
                                }
                            ],
                        },
                    },
                ],
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_semantic_adjudication_cannot_satisfy_readiness_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [
                    session_meta(),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "spawn_agent",
                            "call_id": "adjudication-call",
                            "arguments": json.dumps(
                                {
                                    "message": "Resolve the fingerprinted Luna disagreement.",
                                    "agent_type": "plan-verifier",
                                    "task_name": "semantic_adjudication",
                                    "fork_turns": "none",
                                }
                            ),
                        },
                    },
                    task_started(),
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "sub_agent_activity",
                            "kind": "started",
                            "event_id": "adjudication-call",
                            "agent_thread_id": "adjudication-child",
                        },
                    },
                ],
            )
            write_events(
                home / "sessions" / "adjudication-child.jsonl",
                child_events("adjudication-child"),
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_structured_spawn_and_matched_activity_clear_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [
                    session_meta(),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "spawn_agent",
                            "call_id": "stale-call",
                            "arguments": json.dumps({"agent_type": "plan-verifier"}),
                        },
                    },
                    task_started(started_at=ROOT_STARTED_AT),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "spawn_agent",
                            "call_id": "current-call",
                            "arguments": json.dumps(
                                {
                                    "message": "Review the Plan only.",
                                    "agent_type": "plan-verifier",
                                    "task_name": "automatic_plan_review",
                                    "fork_turns": "none",
                                }
                            ),
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "sub_agent_activity",
                            "kind": "started",
                            "event_id": "current-call",
                            "agent_thread_id": "child-thread",
                        },
                    },
                ],
            )
            write_events(
                home / "sessions" / "child.jsonl",
                child_events("child-thread"),
            )

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))
            self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_unproven_review_blocks_once_then_waits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(transcript, [session_meta(), task_started()])

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )
            marker = next((home / gate.MARKER_DIRECTORY).glob("*.json"))
            self.assertTrue(json.loads(marker.read_text())["attempted"])
            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))
            self.assertTrue(marker.exists())
            gate.handle(prompt_input("請處理下一個普通拼字修正。"), codex_home=home)
            self.assertFalse(marker.exists())

    def test_same_review_blocker_does_not_repeat_after_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "rollout.jsonl"

            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(transcript, [session_meta(), task_started()])
            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

            next_turn = "next-turn"
            gate.handle(
                prompt_input(TRIGGER, turn_id=next_turn),
                codex_home=home,
            )
            write_events(
                transcript,
                [
                    session_meta(),
                    task_started(started_at=ROOT_STARTED_AT + 1),
                ],
            )
            self.assertIsNone(
                gate.handle(
                    stop_input(transcript, turn_id=next_turn),
                    codex_home=home,
                )
            )

    def test_complete_intrinsically_linked_child_suppresses_duplicate_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "2026" / "08" / "root.jsonl"
            child = home / "sessions" / "2026" / "08" / "child.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [session_meta(), task_started(started_at=ROOT_STARTED_AT)],
            )
            write_events(child, child_events("linked-child"))

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))
            self.assertEqual(list((home / gate.MARKER_DIRECTORY).glob("*.json")), [])

    def test_incomplete_intrinsically_linked_child_keeps_single_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "root.jsonl"
            child = home / "sessions" / "child.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [session_meta(), task_started(started_at=ROOT_STARTED_AT)],
            )
            write_events(child, child_events("incomplete-child", complete=False))

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_wrong_completion_turn_keeps_single_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "root.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [session_meta(), task_started(started_at=ROOT_STARTED_AT)],
            )
            write_events(
                home / "sessions" / "child.jsonl",
                child_events("wrong-turn-child", complete_turn_id="another-turn"),
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_direct_chain_wrong_binding_or_incomplete_child_retries(self) -> None:
        cases = (
            {"model": "gpt-6-luna"},
            {"complete": False},
        )
        for child_options in cases:
            with self.subTest(child_options=child_options), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / "codex-home"
                home.mkdir()
                transcript = home / "sessions" / "root.jsonl"
                gate.handle(prompt_input(TRIGGER), codex_home=home)
                write_events(
                    transcript,
                    [
                        session_meta(),
                        task_started(started_at=ROOT_STARTED_AT),
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "function_call",
                                "name": "spawn_agent",
                                "call_id": "direct-call",
                                "arguments": json.dumps(
                                    {
                                        "message": "Review the Plan only.",
                                        "agent_type": "plan-verifier",
                                        "task_name": "automatic_plan_review",
                                        "fork_turns": "none",
                                    }
                                ),
                            },
                        },
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "sub_agent_activity",
                                "kind": "started",
                                "event_id": "direct-call",
                                "agent_thread_id": "direct-child",
                            },
                        },
                    ],
                )
                write_events(
                    home / "sessions" / "child.jsonl",
                    child_events("direct-child", **child_options),
                )

                self.assertEqual(
                    gate.handle(stop_input(transcript), codex_home=home),
                    gate.BLOCK_OUTPUT,
                )

    def test_two_intrinsically_linked_children_are_ambiguous_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "root.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [session_meta(), task_started(started_at=ROOT_STARTED_AT)],
            )
            write_events(home / "sessions" / "child-a.jsonl", child_events("child-a"))
            write_events(home / "sessions" / "child-b.jsonl", child_events("child-b"))

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_root_message_content_cannot_spoof_intrinsic_child_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            transcript = home / "sessions" / "root.jsonl"
            gate.handle(prompt_input(TRIGGER), codex_home=home)
            write_events(
                transcript,
                [
                    session_meta(),
                    task_started(started_at=ROOT_STARTED_AT),
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(child_events("spoofed-child")),
                                }
                            ],
                        },
                    },
                ],
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_untrusted_transcripts_are_terminal_misses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "codex-home"
            sessions = home / "sessions"
            sessions.mkdir(parents=True)
            outside = root / "outside.jsonl"
            write_events(outside, [task_started()])
            symlink = sessions / "symlink.jsonl"
            os.symlink(outside, symlink)
            oversize = sessions / "oversize.jsonl"
            oversize.write_bytes(b"x" * (gate.MAX_TRANSCRIPT_BYTES + 1))

            for transcript in (outside, symlink, oversize):
                with self.subTest(transcript=transcript.name):
                    gate.handle(prompt_input(TRIGGER), codex_home=home)
                    self.assertIsNone(
                        gate.handle(stop_input(transcript), codex_home=home)
                    )
                    self.assertEqual(
                        list((home / gate.MARKER_DIRECTORY).glob("*.json")),
                        [],
                    )


class ScanBoundaryTests(unittest.TestCase):
    """Environment noise must not decide whether a review is proven."""

    def _turn_home(self, directory: str) -> Path:
        home = Path(directory) / "codex-home"
        home.mkdir()
        gate.handle(prompt_input(TRIGGER), codex_home=home)
        return home

    def _current_root(self, home: Path) -> Path:
        transcript = home / "sessions" / "2023" / "11" / "14" / "root.jsonl"
        write_events(
            transcript,
            [session_meta(), task_started(started_at=ROOT_STARTED_AT)],
        )
        return transcript

    def _current_root_with_allowed_child(self, home: Path, child_id: str) -> Path:
        transcript = home / "sessions" / "2023" / "11" / "14" / "root.jsonl"
        write_events(
            transcript,
            [
                session_meta(),
                task_started(started_at=ROOT_STARTED_AT),
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "spawn_agent",
                        "call_id": "current-call",
                        "arguments": json.dumps(
                            {
                                "message": "Review the Plan only.",
                                "agent_type": "plan-verifier",
                                "task_name": "automatic_plan_review",
                                "fork_turns": "none",
                            }
                        ),
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "sub_agent_activity",
                        "kind": "started",
                        "event_id": "current-call",
                        "agent_thread_id": child_id,
                    },
                },
            ],
        )
        return transcript

    def test_allowed_child_plus_another_linked_verifier_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root_with_allowed_child(home, "child-a")
            day = transcript.parent
            write_events(day / "child-a.jsonl", child_events("child-a"))
            write_events(day / "child-b.jsonl", child_events("child-b"))

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_stale_dated_subtree_is_pruned_and_cannot_prove_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root(home)
            write_events(
                home / "sessions" / "2022" / "12" / "31" / "child.jsonl",
                child_events("stale-child"),
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_stale_subtree_volume_does_not_exhaust_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root(home)
            stale = home / "sessions" / "2021" / "05" / "09"
            stale.mkdir(parents=True)
            for index in range(gate.MAX_SCAN_ENTRIES + 1):
                (stale / f"rollout-{index}.jsonl").write_bytes(b"")
            write_events(
                home / "sessions" / "2023" / "11" / "14" / "child.jsonl",
                child_events("linked-child"),
            )

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))

    def test_non_evidence_neighbours_do_not_discard_a_proven_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root(home)
            day = home / "sessions" / "2023" / "11" / "14"
            os.symlink(transcript, day / "symlinked.jsonl")
            os.symlink(day, home / "sessions" / "2023" / "11" / "aliased-day")
            (day / "notes.txt").write_text("unrelated", encoding="utf-8")
            write_events(day / "child.jsonl", child_events("linked-child"))

            self.assertIsNone(gate.handle(stop_input(transcript), codex_home=home))

    def test_malformed_or_oversized_duplicate_child_stays_fail_closed(self) -> None:
        for candidate_kind in ("malformed", "oversized"):
            with self.subTest(candidate_kind=candidate_kind), tempfile.TemporaryDirectory() as directory:
                home = self._turn_home(directory)
                transcript = self._current_root_with_allowed_child(home, "child-a")
                day = transcript.parent
                write_events(day / "child-a.jsonl", child_events("child-a"))
                duplicate = day / "child-b.jsonl"
                encoded = "".join(
                    json.dumps(event) + "\n" for event in child_events("child-b")
                ).encode("utf-8")
                if candidate_kind == "malformed":
                    duplicate.write_bytes(encoded + b'{"type": "partial"')
                else:
                    duplicate.write_bytes(
                        encoded + b"x" * (gate.MAX_TRANSCRIPT_BYTES + 1)
                    )

                self.assertEqual(
                    gate.handle(stop_input(transcript), codex_home=home),
                    gate.BLOCK_OUTPUT,
                )

    def test_safe_read_failure_for_duplicate_child_stays_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root_with_allowed_child(home, "child-a")
            day = transcript.parent
            write_events(day / "child-a.jsonl", child_events("child-a"))
            write_events(day / "child-b.jsonl", child_events("child-b"))
            original_read = gate._read_scanned_jsonl

            def read_or_fail(
                directory_fd: int,
                name: str,
                expected: os.stat_result,
            ) -> list[dict[str, object]]:
                if name == "child-b.jsonl":
                    raise gate._ScanRejected
                return original_read(directory_fd, name, expected)

            with mock.patch.object(
                gate,
                "_read_scanned_jsonl",
                side_effect=read_or_fail,
            ):
                self.assertEqual(
                    gate.handle(stop_input(transcript), codex_home=home),
                    gate.BLOCK_OUTPUT,
                )

    def test_candidate_budget_exhaustion_stays_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root(home)
            day = home / "sessions" / "2023" / "11" / "14"
            for index in range(gate.MAX_SCAN_CANDIDATES + 1):
                write_events(day / f"noise-{index}.jsonl", [session_meta()])
            write_events(day / "child.jsonl", child_events("linked-child"))

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_linked_child_with_wrong_binding_still_rejects_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = self._turn_home(directory)
            transcript = self._current_root(home)
            day = home / "sessions" / "2023" / "11" / "14"
            write_events(
                day / "child.jsonl",
                child_events("linked-child", model="gpt-6-luna"),
            )

            self.assertEqual(
                gate.handle(stop_input(transcript), codex_home=home),
                gate.BLOCK_OUTPUT,
            )

    def test_prunable_subtree_only_skips_well_formed_past_dates(self) -> None:
        cutoff = gate._scan_cutoff(ROOT_STARTED_AT)
        self.assertEqual(cutoff, (2023, 11, 13))
        for parts in (("2022",), ("2023", "10"), ("2023", "11", "12")):
            with self.subTest(parts=parts):
                self.assertTrue(gate._prunable_subtree(parts, cutoff))
        for parts in (
            ("2023",),
            ("2023", "11"),
            ("2023", "11", "14"),
            ("2024",),
            ("archive",),
            ("2023", "13"),
            ("2023", "11", "14", "extra"),
        ):
            with self.subTest(parts=parts):
                self.assertFalse(gate._prunable_subtree(parts, cutoff))


class TriggerCorpusTests(unittest.TestCase):
    """Pin the trigger surface: every extra trigger buys a Sol review."""

    ROUTINE = (
        "幫我把這個 function 的變數命名改一致",
        "跑一下測試看有沒有壞",
        "這段 code 為什麼會噴 TypeError",
        "驗證一下我這個 SQL 有沒有寫錯",
        "幫我規劃這週的 refactor 順序",
        "幫我規劃怎麼驗證這個 parser 的輸出",
        "計畫把這個表單的必填欄位改掉",
        "這個 plan 我想先做前兩步",
        "幫我規劃把 log 從 console 改成 structured logging",
        "說明一下登入流程怎麼運作",
        "add a unit test for the parser",
        "plan how to validate the CSV import",
        "what does this deploy script do?",
        "rename the config key and update the docs",
    )
    MATERIAL = {
        "幫我規劃把使用者密碼欄位遷移到 argon2 的方案，之後要上正式環境": ("data", "release"),
        "這個方案會刪除舊的訂單資料表，請先幫我做核准前的規劃": ("data", "irreversible"),
        "Plan the production rollout for the new authentication service": (
            "release",
            "security",
        ),
        "Draft a plan to send customer emails through a third-party provider": ("external",),
    }

    def test_routine_prompts_never_trigger_a_sol_review(self) -> None:
        for prompt in self.ROUTINE:
            with self.subTest(prompt=prompt):
                self.assertEqual(gate.classify_prompt(prompt), ())

    def test_material_prompts_trigger_their_declared_categories(self) -> None:
        for prompt, expected in self.MATERIAL.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(gate.classify_prompt(prompt), tuple(sorted(expected)))

    def test_selective_sol_review_requires_security_or_multiple_risks(self) -> None:
        self.assertFalse(gate.requires_sol_review(("data",)))
        self.assertFalse(gate.requires_sol_review(("release",)))
        self.assertTrue(gate.requires_sol_review(("security",)))
        self.assertTrue(gate.requires_sol_review(("data", "irreversible")))

    def test_single_nonsecurity_risk_does_not_create_review_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "codex-home"
            home.mkdir()
            session_id = "session-single-risk"
            gate.handle(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": session_id,
                    "turn_id": "turn-single-risk",
                    "prompt": "Plan the database change.",
                },
                codex_home=home,
            )
            marker = gate._marker_path(home, session_id, create=False)
            self.assertTrue(marker is None or not marker.exists())

    def test_generic_chinese_validation_is_not_a_security_boundary(self) -> None:
        self.assertEqual(gate.classify_prompt("規劃如何驗證這份報表"), ())
        self.assertEqual(
            gate.classify_prompt("規劃身分驗證流程的調整"), ("security",)
        )

    def test_a_risk_word_alone_is_never_enough(self) -> None:
        for prompt in ("直接刪掉這個 table", "deploy to production now"):
            with self.subTest(prompt=prompt):
                self.assertEqual(gate.classify_prompt(prompt), ())


class LaunchProbeTests(unittest.TestCase):
    """The registered command must be able to prove it launched at all."""

    def test_selftest_reports_a_launchable_gate(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "pilotfish_autoroute_gate.py"), "--selftest"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), gate.SELFTEST_OK)
        self.assertIn(str(gate.SCHEMA), gate.SELFTEST_OK)

    def test_unknown_arguments_stay_silent(self) -> None:
        self.assertEqual(gate.main(["--unknown"]), 0)


if __name__ == "__main__":
    unittest.main()
