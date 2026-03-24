from __future__ import annotations

import json
import os
import tempfile
import textwrap
import time
import unittest
import datetime as dt
from pathlib import Path
from unittest import mock

from relay.adapters import CommandResult
from relay.repository import RelayRepository
from relay.service import RelayService
from relay.session_client import SessionClient


FAKE_AGENT = textwrap.dedent(
    """
    import json
    import sys

    def headless(prompt: str) -> None:
        if 'Return JSON only: {"ok":true}' in prompt:
            print(json.dumps({"ok": True}))
            return
        payload = {
            "summary": f"handled: {prompt[:40]}",
            "findings": [],
            "next_action": "done",
            "steps": ["one"],
            "risks": [],
            "changes": ["updated"],
            "followups": [],
            "optimized_prompt": prompt,
            "rationale": "test",
            "warnings": [],
            "sources": [],
            "claims": [],
            "sections": [],
            "citations": [],
            "areas": [],
            "recommended_files": [],
            "key_points": [],
            "handoff_prompt": prompt,
            "details": [prompt],
        }
        print(json.dumps(payload))

    def interactive() -> None:
        print("fake agent ready", flush=True)
        for line in sys.stdin:
            line = line.rstrip("\\n")
            print(f"interactive:{line}", flush=True)

    argv = sys.argv[1:]
    if argv and argv[0] == "exec":
        headless(argv[-1])
    elif argv == ["--version"]:
        print("fake-agent 1.0.0")
    elif argv[:2] == ["auth", "status"]:
        print("=== Authentication Status ===")
        print("✓ Authentication Method: Fake OAuth")
    elif "-p" in argv:
        headless(argv[argv.index("-p") + 1])
    else:
        interactive()
    """
)


class ServiceTests(unittest.TestCase):
    def _create_service(self) -> tuple[tempfile.TemporaryDirectory[str], RelayRepository, RelayService, Path]:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db = root / "relay.db"
        fake = root / "fake_agent.py"
        fake.write_text(FAKE_AGENT, encoding="utf-8")
        repo = RelayRepository(db)
        service = RelayService(repo)
        launch = f"{os.environ.get('PYTHON', 'python3')} {fake}"
        service.add_agent(name="claude-main", kind="claude", launch_command=launch, resume_strategy="native")
        service.add_agent(name="codex-review", kind="codex", launch_command=launch, resume_strategy="native")
        service.add_agent(name="gemini-util", kind="gemini", launch_command=launch, resume_strategy="native")
        service.add_agent(name="qwen-util", kind="qwen", launch_command=launch, resume_strategy="native")
        return tempdir, repo, service, root

    def _open_session(self, service: RelayService, cwd: str) -> dict[str, object]:
        session = service.open_session(agent_name="claude-main", label="main", cwd=cwd)
        client = SessionClient(session["external_session_ref"])  # type: ignore[index]
        client.send("Initial plan for auth flow")
        time.sleep(0.2)
        return session

    def test_delegate_and_return_roundtrip(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            delegated = service.delegate(
                from_session_id=session["id"],
                to_agent_name="codex-review",
                task_type="review",
                title="Review auth",
            )
            run_id = delegated["run"]["id"]
            self.assertEqual(delegated["run"]["status"], "completed")
            returned = service.return_run(run_id=run_id)
            self.assertEqual(returned["run"]["return_status"], "returned")
            transcript = service.transcript(session["id"])
            self.assertIn("Contributor:", transcript)
        finally:
            service.close_session(session["id"])

    def test_delegate_chain_preserves_origin_and_default_context_policy(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            review_run = service.delegate(
                from_session_id=session["id"],
                to_agent_name="codex-review",
                task_type="review",
                title="Review auth",
            )
            tree_run = service.delegate(
                from_session_id=session["id"],
                to_agent_name="gemini-util",
                task_type="tree_explore",
                title="Explore tree",
                parent_run_id=review_run["run"]["id"],
            )
            self.assertEqual(review_run["packet"]["context_policy"], "full")
            self.assertEqual(tree_run["packet"]["context_policy"], "compact")
            self.assertEqual(tree_run["run"]["origin_session_id"], session["id"])
            self.assertEqual(tree_run["packet"]["parent_run_id"], review_run["run"]["id"])
            self.assertEqual(
                tree_run["packet"]["input_payload"]["parent_result"],
                review_run["result"]["normalized_result"],
            )
        finally:
            service.close_session(session["id"])

    def test_return_falls_back_to_new_prompt_when_live_send_fails(self) -> None:
        tempdir, repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            delegated = service.delegate(
                from_session_id=session["id"],
                to_agent_name="codex-review",
                task_type="review",
                title="Review auth",
            )
            with mock.patch("relay.service.send_to_live_session", return_value=False):
                returned = service.return_run(run_id=delegated["run"]["id"])
            self.assertEqual(returned["run"]["return_status"], "returned")
            with repo.connect() as conn:
                row = conn.execute(
                    "SELECT attempt_mode, final_mode, status, fallback_output FROM return_events WHERE run_id = ?",
                    (delegated["run"]["id"],),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["attempt_mode"], "resume")
            self.assertEqual(row["final_mode"], "fallback-new-prompt")
            self.assertEqual(row["status"], "success")
            self.assertTrue(row["fallback_output"])
        finally:
            service.close_session(session["id"])

    def test_return_is_idempotent_and_archive_marks_run(self) -> None:
        tempdir, repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            delegated = service.delegate(
                from_session_id=session["id"],
                to_agent_name="codex-review",
                task_type="review",
                title="Review auth",
            )
            first = service.return_run(run_id=delegated["run"]["id"])
            second = service.return_run(run_id=delegated["run"]["id"])
            archived = service.archive_run(delegated["run"]["id"])
            self.assertEqual(first["run"]["return_status"], "returned")
            self.assertEqual(second["run"]["return_status"], "returned")
            self.assertEqual(archived["run"]["status"], "archived")
            self.assertEqual(archived["run"]["archived"], 1)
            with repo.connect() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) AS count FROM return_events WHERE run_id = ?",
                    (delegated["run"]["id"],),
                ).fetchone()["count"]
            self.assertEqual(count, 1)
        finally:
            service.close_session(session["id"])

    def test_non_json_output_uses_fallback_normalization(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            with mock.patch(
                "relay.service.run_headless",
                return_value=CommandResult(stdout="plain text result without json", stderr="", returncode=0),
            ):
                delegated = service.delegate(
                    from_session_id=session["id"],
                    to_agent_name="gemini-util",
                    task_type="optimize_prompt",
                    title="Optimize this prompt",
                )
            normalized = delegated["result"]["normalized_result"]
            self.assertEqual(normalized["optimized_prompt"], "plain text result without json")
            self.assertEqual(normalized["rationale"], "Fallback from non-JSON output.")
        finally:
            service.close_session(session["id"])

    def test_run_direct_prompt_returns_display_text(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        result = service.run_direct_prompt(agent_name="claude-main", prompt="2+2", cwd=str(root))
        self.assertEqual(result["status"], "completed")
        self.assertIn("handled:", result["display_text"])

    def test_preset_run_uses_template_instruction_and_task(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            delegated = service.run_preset(
                preset_name="Strict Review",
                from_session_id=session["id"],
                to_agent_name="codex-review",
            )
            self.assertEqual(delegated["packet"]["task_type"], "review")
            self.assertIn("bugs, regressions", delegated["packet"]["instructions"])
            self.assertEqual(delegated["packet"]["context_policy"], "full")
        finally:
            service.close_session(session["id"])

    def test_codex_timeout_retries_with_compact_context(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            with mock.patch(
                "relay.service.run_headless",
                side_effect=[
                    CommandResult(stdout="", stderr="relay headless timeout after 60s", returncode=124),
                    CommandResult(
                        stdout='{"summary":"compact ok","findings":[],"next_action":"done"}',
                        stderr="",
                        returncode=0,
                    ),
                ],
            ):
                delegated = service.delegate(
                    from_session_id=session["id"],
                    to_agent_name="codex-review",
                    task_type="review",
                    title="Review auth",
                )
            self.assertEqual(delegated["run"]["status"], "completed")
            self.assertEqual(delegated["packet"]["context_policy"], "compact")
            self.assertIn("compact handoff context", delegated["packet"]["instructions"])
            self.assertEqual(delegated["result"]["normalized_result"]["summary"], "compact ok")
        finally:
            service.close_session(session["id"])

    def test_codex_implement_starts_with_compact_context(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        session = self._open_session(service, str(root))
        try:
            delegated = service.delegate(
                from_session_id=session["id"],
                to_agent_name="codex-review",
                task_type="implement",
                title="Implement auth changes",
                )
            self.assertEqual(delegated["packet"]["context_policy"], "compact")
            self.assertIn("compact handoff context", delegated["packet"]["instructions"].lower())
            self.assertIn("aggressive compact handoff", delegated["packet"]["instructions"].lower())
            self.assertLessEqual(len(delegated["packet"]["input_payload"]["goal"]), 300)
            self.assertLessEqual(len(delegated["packet"]["input_payload"]["artifacts"]["conversation_excerpt"]), 1200)
        finally:
            service.close_session(session["id"])

    def test_agent_profiles_expose_recommendations(self) -> None:
        tempdir, _repo, service, _root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        profiles = {item["name"]: item for item in service.list_agent_profiles()}
        self.assertIn("direct", profiles["claude-main"]["recommended_for"])
        self.assertIn("review", profiles["codex-review"]["recommended_for"])
        self.assertIn("research", profiles["gemini-util"]["recommended_for"])
        self.assertIn("fast-direct", profiles["qwen-util"]["recommended_for"])

    def test_last_prompt_context_returns_latest_prompt_and_status(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(
            lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None)
        )
        service.append_event("prompt_submitted", {"prompt": "2+2", "workflow": {"id": "wf_1", "main_agent": "qwen-main"}})
        service.append_event("direct_started", {"prompt": "2+2", "workflow_id": "wf_1", "main_agent": "qwen-main"})
        service.append_event("workflow_finished", {"prompt": "2+2", "workflow": {"id": "wf_1"}, "summary": "4"})
        last = service.last_prompt_context()
        assert last is not None
        self.assertEqual(last["prompt"], "2+2")
        self.assertTrue(last["finished"])
        self.assertEqual(last["summary"], "4")

    def test_last_prompt_context_tracks_completed_step_indexes(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(
            lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None)
        )
        service.append_event("prompt_submitted", {"prompt": "ship it", "workflow": {"id": "wf_2", "steps": [{}, {}]}})
        service.append_event("workflow_step_finished", {"prompt": "ship it", "workflow_id": "wf_2", "step_index": 0, "status": "completed", "run_id": "run_1", "step": {"agent_name": "codex-main", "task_type": "review"}, "normalized_result": {"summary": "ok"}})
        service.append_event("workflow_step_finished", {"prompt": "ship it", "workflow_id": "wf_2", "step_index": 1, "status": "failed", "error": "network timeout"})
        last = service.last_prompt_context()
        assert last is not None
        self.assertEqual(last["completed_step_indexes"], [0])
        self.assertEqual(last["failed_step_index"], 1)
        self.assertEqual(last["failed_step_error"], "network timeout")
        self.assertEqual(last["last_completed_step"]["run_id"], "run_1")

    def test_append_and_read_recent_events(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        first = service.append_event("test_started", {"prompt": "2+2"})
        second = service.append_event("test_finished", {"summary": "4"})
        events = service.recent_events(limit=10)
        self.assertEqual(events[-2]["event_type"], "test_started")
        self.assertEqual(events[-1]["event_type"], "test_finished")
        self.assertEqual(events[-1]["payload"]["summary"], "4")

    def test_check_logins_reports_ready_agents(self) -> None:
        tempdir, _repo, service, _root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        statuses = service.check_logins(cwd=os.getcwd())
        by_name = {item["agent_name"]: item for item in statuses}
        self.assertEqual(by_name["claude-main"]["status"], "ready")
        self.assertEqual(by_name["codex-review"]["status"], "ready")
        self.assertEqual(by_name["gemini-util"]["status"], "ready")
        self.assertEqual(by_name["qwen-util"]["status"], "ready")

    def test_launch_login_rechecks_after_login_flow(self) -> None:
        tempdir, _repo, service, _root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        with mock.patch(
            "relay.service.check_agent_readiness",
            side_effect=[
                mock.Mock(status="needs_login", message="Please sign in to Gemini.", details="", login_command=["gemini"]),
                mock.Mock(status="ready", message="Signed in and ready to use.", details="", login_command=["gemini"]),
            ],
        ), mock.patch("relay.service.launch_login_flow") as launch_login:
            status = service.launch_login("gemini-util", cwd=os.getcwd())
        launch_login.assert_called_once()
        self.assertEqual(status["status"], "ready")

    def test_build_parallel_test_matrix_skips_blocked_agents(self) -> None:
        tempdir, _repo, service, _root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        readiness = [
            {"agent_name": "claude-main", "kind": "claude", "status": "ready"},
            {"agent_name": "codex-review", "kind": "codex", "status": "ready"},
            {"agent_name": "gemini-util", "kind": "gemini", "status": "needs_login"},
            {"agent_name": "qwen-util", "kind": "qwen", "status": "ready"},
        ]
        scenarios = service.build_parallel_test_matrix(readiness, cwd=os.getcwd())
        titles = {item["title"] for item in scenarios}
        self.assertIn("Claude direct handoff", titles)
        self.assertIn("Codex direct handoff", titles)
        self.assertIn("Qwen direct handoff", titles)
        self.assertNotIn("Gemini direct handoff", titles)

    def test_run_test_scenario_records_real_runs_using_helper_origin(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        scenario = {
            "id": "matrix_0001",
            "title": "Fake chain",
            "task_label": "optimize_prompt -> implement",
            "steps": [
                {"agent_name": "gemini-util", "task_type": "optimize_prompt", "title": "Optimize"},
                {"agent_name": "qwen-util", "task_type": "implement", "title": "Implement"},
            ],
            "cwd": str(root),
            "experimental": False,
        }
        result = service.run_test_scenario(scenario)
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["run_ids"]), 2)

    def test_cleanup_stale_state_closes_dead_sessions_and_fails_old_runs(self) -> None:
        tempdir, repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        agent = repo.get_agent(name="claude-main")
        session = repo.add_session(
            agent_id=agent["id"],
            label="stale",
            cwd=str(root),
            external_session_ref=str(root / "missing.sock"),
            status="active",
            metadata={},
        )
        snapshot = repo.add_context_snapshot(
            session_id=session["id"],
            summary="summary",
            goal="goal",
            task_type_hint="custom",
            artifacts={},
            token_estimate=0,
        )
        packet = repo.add_task_packet(
            origin_session_id=session["id"],
            target_agent_id=agent["id"],
            task_type="custom",
            title="title",
            context_policy="compact",
            instructions="instructions",
            origin_snapshot_id=snapshot["id"],
            input_payload={"goal": "goal", "artifacts": {}, "parent_result": {}},
        )
        run = repo.add_run(packet_id=packet["id"], origin_session_id=session["id"], status="running", return_status="pending")
        old = "2020-01-01T00:00:00Z"
        with repo.connect() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (old, session["id"]))
            conn.execute("UPDATE runs SET created_at = ? WHERE id = ?", (old, run["id"]))
        result = service.cleanup_stale_state(now=dt.datetime(2026, 3, 24, 10, 0, 0), session_stale_seconds=1, run_stale_seconds=1)
        self.assertEqual(result["closed_sessions"], 1)
        self.assertEqual(result["failed_runs"], 1)
        self.assertEqual(repo.get_session(session["id"])["status"], "closed")
        self.assertEqual(repo.get_run(run["id"])["status"], "failed")

    def test_last_trace_events_returns_recent_execution_group(self) -> None:
        tempdir, _repo, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        service.append_event("prompt_submitted", {"prompt": "2+2", "workflow": {"id": "wf_1"}})
        service.append_event("direct_started", {"prompt": "2+2", "workflow_id": "wf_1", "main_agent": "qwen-main"})
        service.append_event("direct_finished", {"prompt": "2+2", "workflow_id": "wf_1", "status": "completed"})
        service.append_event("workflow_finished", {"prompt": "2+2", "workflow": {"id": "wf_1"}, "summary": "4"})
        trace = service.last_trace_events()
        self.assertEqual([item["event_type"] for item in trace], ["prompt_submitted", "direct_started", "direct_finished", "workflow_finished"])


if __name__ == "__main__":
    unittest.main()
