from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from relay.repository import RelayRepository
from relay.service import RelayService
from relay.workflow_store import WorkflowStore
from relay.tui import (
    as_plain_text,
    build_status_strip,
    build_status_strip_with_mode,
    export_file_name,
    filter_slash_commands,
    friendly_status_label,
    friendly_task_label,
    initial_stream_index,
    move_command_selection,
    next_stream_index,
    normalize_display_text,
    prefers_fast_direct_route,
    normalized_select_value,
    resolve_slash_command,
    should_prompt_for_workflow,
    should_show_command_overlay,
    split_transcript_for_streaming,
    summarize_result,
    thinking_label,
    toggle_progress_drawer_state,
    RelayShellApp,
    workflow_preview,
)

FAKE_AGENT = textwrap.dedent(
    """
    import json
    import sys

    def headless(prompt: str) -> None:
        print(json.dumps({"summary": f"handled: {prompt[:40]}", "details": [prompt]}))

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
        print("fake agent ready", flush=True)
        for line in sys.stdin:
            print(f"interactive:{line.rstrip()}", flush=True)
    """
)


class TuiHelpersTests(unittest.TestCase):
    def _create_service(self) -> tuple[tempfile.TemporaryDirectory[str], RelayService, Path]:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db = root / "relay.db"
        fake = root / "fake_agent.py"
        fake.write_text(FAKE_AGENT, encoding="utf-8")
        repo = RelayRepository(db)
        service = RelayService(repo)
        launch = f"{os.environ.get('PYTHON', 'python3')} {fake}"
        service.add_agent(name="claude-main", kind="claude", launch_command=launch, resume_strategy="native")
        service.add_agent(name="codex-main", kind="codex", launch_command=launch, resume_strategy="native")
        service.add_agent(name="gemini-main", kind="gemini", launch_command=launch, resume_strategy="native")
        service.add_agent(name="qwen-main", kind="qwen", launch_command=launch, resume_strategy="native")
        return tempdir, service, root

    def test_child_friendly_labels_are_used(self) -> None:
        self.assertEqual(friendly_task_label("optimize_prompt"), "Simplify")
        self.assertEqual(friendly_status_label("needs_login"), "Needs Login")

    def test_status_strip_shows_relay_version(self) -> None:
        strip = build_status_strip(
            [{"name": "claude-main"}],
            {"claude-main": {"status": "ready"}},
        )
        self.assertIn("Relay v0.1.0", strip.plain)

    def test_status_strip_shows_approval_mode(self) -> None:
        strip = build_status_strip_with_mode(
            [{"name": "claude-main"}],
            {"claude-main": {"status": "ready"}},
            approval_mode="default",
            main_provider="claude-main",
            workflow_main="gemini-main",
        )
        self.assertIn("Approval: default", strip.plain)
        self.assertIn("Provider: claude-main", strip.plain)
        self.assertIn("Workflow Main: gemini-main", strip.plain)
        self.assertTrue(strip.plain.startswith("Provider: claude-main"))

    def test_summarize_result_prefers_summary_like_fields(self) -> None:
        summary = summarize_result({"optimized_prompt": "Make the prompt shorter and clearer."})
        self.assertIn("Make the prompt shorter", summary)

    def test_slash_overlay_opens_and_filters(self) -> None:
        self.assertTrue(should_show_command_overlay("/"))
        self.assertFalse(should_show_command_overlay("hello"))
        commands = filter_slash_commands("/work")
        self.assertTrue(any(item["name"] == "/workflow" for item in commands))
        export_commands = filter_slash_commands("/export")
        self.assertTrue(any(item["name"] == "/export transcript" for item in export_commands))
        copy_commands = filter_slash_commands("/copy")
        self.assertTrue(any(item["name"] == "/copy transcript" for item in copy_commands))
        approval_commands = filter_slash_commands("/approval")
        self.assertTrue(any(item["name"] == "/approval-mode" for item in approval_commands))

    def test_command_selection_helpers(self) -> None:
        commands = filter_slash_commands("/")
        self.assertGreaterEqual(len(commands), 2)
        self.assertEqual(move_command_selection(0, commands, 1), 1)
        self.assertEqual(resolve_slash_command("/", 1), commands[1]["name"])
        self.assertEqual(resolve_slash_command("/appro", 0), "/approval-mode")
        self.assertEqual(resolve_slash_command("/approval-mode plan", 0), "/approval-mode plan")

    def test_workflow_prompting_and_preview_helpers(self) -> None:
        self.assertTrue(should_prompt_for_workflow("Review this code", None))
        self.assertFalse(should_prompt_for_workflow("/workflow", None))
        preview = workflow_preview(
            {
                "main_agent": "claude-main",
                "mode": "workflow",
                "send_back": True,
                "steps": [{"agent_name": "codex-main", "task_type": "review"}],
            }
        )
        self.assertIn("claude-main", preview)
        self.assertIn("Send Back", preview)

    def test_fast_direct_route_prefers_short_questions(self) -> None:
        self.assertTrue(prefers_fast_direct_route("2+2"))
        self.assertFalse(prefers_fast_direct_route("Please review this diff and suggest code changes"))
        self.assertFalse(prefers_fast_direct_route("def add(a, b):\n    return a + b"))

    def test_progress_drawer_toggle_helper(self) -> None:
        self.assertTrue(toggle_progress_drawer_state(False))
        self.assertFalse(toggle_progress_drawer_state(True))

    def test_display_text_normalization_strips_ansi_and_keeps_brackets_literal(self) -> None:
        raw = "\x1b[31m[hello]\x1b[0m world"
        normalized = normalize_display_text(raw)
        self.assertEqual(normalized, "[hello] world")
        visual = as_plain_text(raw)
        self.assertEqual(str(visual), "[hello] world")

    def test_export_file_name_uses_stable_suffix(self) -> None:
        name = export_file_name("transcript")
        self.assertTrue(name.endswith("-transcript.txt"))

    def test_thinking_label_and_stream_helpers(self) -> None:
        self.assertIn("Thinking with claude-main", thinking_label("claude-main", 1))
        prefix, body = split_transcript_for_streaming("> 2+2\n\n2 + 2 = 4")
        self.assertEqual(prefix, "> 2+2\n\n")
        self.assertEqual(body, "2 + 2 = 4")
        self.assertEqual(next_stream_index("hello", 0, chunk_size=2), 5)
        self.assertEqual(next_stream_index("hello\nworld", 0, chunk_size=2), 11)
        self.assertEqual(initial_stream_index("short answer"), len("short answer"))
        self.assertGreaterEqual(initial_stream_index("First sentence. Second sentence. Third sentence."), len("First sentence. "))

    def test_normalized_select_value_rejects_textual_null_sentinel(self) -> None:
        class FakeSelect:
            value = "Select.NULL"

        self.assertIsNone(normalized_select_value(FakeSelect()))

    def test_app_opens_a_fresh_session_instead_of_reusing_old_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            db = root / "relay.db"
            fake = root / "fake_agent.py"
            fake.write_text(FAKE_AGENT, encoding="utf-8")
            repo = RelayRepository(db)
            service = RelayService(repo)
            launch = f"{os.environ.get('PYTHON', 'python3')} {fake}"
            service.add_agent(name="claude-main", kind="claude", launch_command=launch, resume_strategy="native")
            old_session = service.open_session(agent_name="claude-main", label="old", cwd=str(root))
            app = RelayShellApp(service)
            try:
                new_session = app._ensure_main_session("claude-main")
                self.assertNotEqual(new_session["id"], old_session["id"])
                self.assertEqual(app.current_session_id, new_session["id"])
            finally:
                service.close_session(old_session["id"])
                if app.current_session_id and app.current_session_id != old_session["id"]:
                    service.close_session(app.current_session_id)

    def test_direct_prompt_workflow_uses_headless_main_agent(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        workflow = {
            "id": "workflow_direct",
            "name": "Direct",
            "main_agent": "claude-main",
            "mode": "direct",
            "send_back": False,
            "steps": [],
        }
        with mock.patch.object(app, "_ensure_main_session", side_effect=AssertionError("live session should not open")):
            payload = app._run_prompt_workflow("2+2", workflow)
        self.assertIsNone(payload["session_id"])
        self.assertIn("> 2+2", payload["transcript"])
        self.assertIn("handled:", payload["summary"])
        self.assertIn("handled:", payload["transcript"])

    def test_step_workflow_uses_helper_origin_and_finishes(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        previous_cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, previous_cwd)
        app = RelayShellApp(service)
        workflow = {
            "id": "workflow_steps",
            "name": "Claude -> Codex -> Send Back",
            "main_agent": "claude-main",
            "mode": "workflow",
            "send_back": True,
            "steps": [
                {
                    "id": "step_1",
                    "agent_name": "codex-main",
                    "task_type": "custom",
                    "label": "Answer briefly",
                }
            ],
        }
        with mock.patch.object(app, "_ensure_main_session", side_effect=AssertionError("live session should not open")):
            payload = app._run_prompt_workflow("2+2", workflow)
        self.assertIsNone(payload["session_id"])
        self.assertEqual(len(payload["views"]), 1)
        self.assertEqual(payload["views"][0]["run"]["status"], "completed")
        self.assertIsNotNone(payload["final_output"])
        self.assertIn("> 2+2", payload["transcript"])
        self.assertIn("[Original - claude-main]", payload["transcript"])
        self.assertIn("[Custom - codex-main]", payload["transcript"])
        self.assertIn("[Final - claude-main]", payload["transcript"])

    def test_failed_workflow_transcript_shows_original_step_and_status(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        workflow = {
            "id": "workflow_fail",
            "name": "Gemini -> Codex Build -> Send Back",
            "main_agent": "gemini-main",
            "mode": "workflow",
            "send_back": True,
            "steps": [{"id": "step_1", "agent_name": "codex-main", "task_type": "implement", "label": "Implement next steps"}],
        }
        original_output = {
            "agent": {"name": "gemini-main"},
            "display_text": "Original guidance",
            "raw_output": "Original guidance",
        }
        failed_view = {
            "packet": {"task_type": "implement"},
            "target_agent": {"name": "codex-main"},
            "run": {"status": "failed", "error": "relay headless timeout after 45s"},
            "result": {
                "normalized_result": {"summary": "relay headless timeout after 45s", "changes": ["relay headless timeout after 45s"], "followups": []},
                "raw_output": "relay headless timeout after 45s",
            },
        }
        transcript = app._build_workflow_transcript(
            "내 문서 참조후 핵심지침말해줘",
            workflow,
            original_output,
            None,
            [failed_view],
            failed_view,
        )
        self.assertIn("[Original - gemini-main]", transcript)
        self.assertIn("[Build - codex-main (Failed)]", transcript)
        self.assertIn("[Workflow Status]", transcript)

    def test_workflow_modal_top_save_button_pins_workflow(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        from relay.tui import WorkflowSetupScreen

        screen = WorkflowSetupScreen(service=service, store=WorkflowStore(root / "workflow_state.json"), prompt_text="2+2")
        with mock.patch.object(screen, "_build_workflow_from_form", return_value={"id": "wf", "name": "Test", "main_agent": "claude-main", "mode": "direct", "send_back": False, "steps": []}), \
             mock.patch.object(screen, "query_one") as query_one, \
             mock.patch.object(screen, "dismiss") as dismiss:
            checkbox = mock.Mock()
            checkbox.value = False
            select = mock.Mock()
            select.value = "__custom__"
            query_one.side_effect = lambda selector, *_args, **_kwargs: checkbox if selector == "#workflow-pin" else select
            event = mock.Mock()
            event.button.id = "save-use-top"
            screen.on_button_pressed(event)
        payload = dismiss.call_args[0][0]
        self.assertTrue(payload["set_active"])

    def test_workflow_modal_mount_focuses_main_agent_select(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        from relay.tui import WorkflowSetupScreen

        screen = WorkflowSetupScreen(service=service, store=WorkflowStore(root / "workflow_state.json"), prompt_text="2+2")
        with mock.patch.object(screen, "call_after_refresh") as call_after_refresh:
            screen.on_mount()
        callback = call_after_refresh.call_args[0][0]
        select = mock.Mock()
        with mock.patch.object(screen, "query_one", return_value=select):
            callback()
        select.focus.assert_called_once()

    def test_prompt_uses_direct_mode_after_workflow_modal_has_been_seen(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        app.store.mark_seen()
        started = {}

        def fake_start(prompt: str, workflow: dict[str, object] | None) -> None:
            started["prompt"] = prompt
            started["workflow"] = workflow

        with mock.patch.object(app, "_start_prompt_run", side_effect=fake_start):
            class FakeInput:
                id = "prompt-input"
                value = "2+2"

            class FakeEvent:
                input = FakeInput()
                value = "2+2"

            app.on_input_submitted(FakeEvent())
        self.assertEqual(started["prompt"], "2+2")
        self.assertIsNotNone(started["workflow"])
        self.assertEqual(started["workflow"]["mode"], "direct")

    def test_default_direct_workflow_prefers_fast_agent_for_short_prompt(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        workflow = app._default_direct_workflow("2+2")
        self.assertEqual(workflow["main_agent"], "claude-main")

    def test_provider_command_updates_main_provider(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        with mock.patch.object(app, "_add_notice"), mock.patch.object(app, "refresh_ui"):
            app._handle_slash_command("/provider use qwen-main")
        self.assertEqual(app.store.get_main_provider(), "qwen-main")

    def test_provider_show_command_reports_main_provider(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        app.store.set_main_provider("gemini-main")
        with mock.patch.object(app, "_add_notice") as add_notice:
            app._handle_slash_command("/provider")
        self.assertIn("Main provider: gemini-main", add_notice.call_args[0][0])

    def test_agents_command_shows_recommendations(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        with mock.patch.object(app, "_add_notice") as add_notice, mock.patch.object(app, "_refresh_logins"):
            app.login_status = {name: {"status": "ready"} for name in ["claude-main", "codex-main", "gemini-main", "qwen-main"]}
            app._handle_slash_command("/agents")
        text = add_notice.call_args[0][0]
        self.assertIn("recommended for", text)
        self.assertIn("Approval mode:", text)

    def test_approval_mode_command_updates_store(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        store_path = root / "workflow_state.json"
        app = RelayShellApp(service, store=WorkflowStore(store_path))
        with mock.patch.object(app, "_add_notice"), mock.patch.object(app, "refresh_ui"):
            app._handle_slash_command("/approval-mode plan")
        self.assertEqual(app.store.get_approval_mode(), "plan")

    def test_approval_mode_show_command_reports_current_mode(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        with mock.patch.object(app, "_add_notice") as add_notice:
            app._handle_slash_command("/approval-mode")
        self.assertIn("Approval mode: default", add_notice.call_args[0][0])

    def test_approval_mode_default_command_updates_store(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        store_path = root / "workflow_state.json"
        app = RelayShellApp(service, store=WorkflowStore(store_path))
        app.store.set_approval_mode("plan")
        with mock.patch.object(app, "_add_notice"), mock.patch.object(app, "refresh_ui"):
            app._handle_slash_command("/approval-mode default")
        self.assertEqual(app.store.get_approval_mode(), "default")

    def test_plan_mode_blocks_implement_workflow(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service, store=WorkflowStore(root / "workflow_state.json"))
        app.store.set_approval_mode("plan")
        workflow = {
            "id": "workflow_steps",
            "name": "Build Flow",
            "main_agent": "claude-main",
            "mode": "workflow",
            "send_back": True,
            "steps": [{"id": "step_1", "agent_name": "codex-main", "task_type": "implement", "label": ""}],
        }
        with mock.patch.object(app, "_add_notice") as add_notice:
            app._start_prompt_run("make a change", workflow)
        self.assertIsNone(app._active_future)
        self.assertIn("Approval mode 'plan' blocks implement steps", add_notice.call_args[0][0])

    def test_trace_last_formats_recent_events(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event("prompt_submitted", {"prompt": "2+2", "workflow": {"id": "wf_1"}})
        service.append_event("direct_started", {"prompt": "2+2", "workflow_id": "wf_1", "main_agent": "qwen-main"})
        service.append_event(
            "workflow_finished",
            {"prompt": "2+2", "workflow": {"id": "wf_1"}, "summary": "4"},
        )
        trace = app._format_trace_last()
        self.assertIn("Last trace:", trace)
        self.assertIn("start   qwen-main", trace)
        self.assertIn("final   4", trace)

    def test_trace_last_is_written_into_transcript_body(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event("prompt_submitted", {"prompt": "2+2", "workflow": {"id": "wf_1"}})
        service.append_event("direct_started", {"prompt": "2+2", "workflow_id": "wf_1", "main_agent": "qwen-main"})
        service.append_event("workflow_finished", {"prompt": "2+2", "workflow": {"id": "wf_1"}, "summary": "4"})
        with mock.patch.object(app, "refresh_ui"):
            app._handle_slash_command("/trace last")
        visible = app._visible_transcript_text()
        self.assertIn("Last trace:", visible)
        self.assertIn("start   qwen-main", visible)

    def test_visible_transcript_hides_system_notices_during_chat(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        app._add_notice("Relay is ready.", kind="system")
        app._add_notice("No pinned workflow. Using direct mode.", kind="hint")
        app._add_notice("Main provider: claude-main", kind="command")
        app._last_transcript = "> 2+2\n\n4"
        visible = app._visible_transcript_text()
        self.assertNotIn("Relay is ready.", visible)
        self.assertNotIn("No pinned workflow.", visible)
        self.assertIn("Main provider: claude-main", visible)
        self.assertIn("> 2+2", visible)
        self.assertIn("\n\n4", visible)

    def test_finish_background_work_skips_workflow_finished_notice_for_direct_mode(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        payload = {
            "session_id": None,
            "workflow": {"id": "wf_direct", "mode": "direct"},
            "summary": "4",
            "transcript": "> 2+2\n\n4",
        }
        app._finish_background_work(payload)
        visible = app._visible_transcript_text()
        self.assertNotIn("Workflow finished:", visible)
        self.assertIn("> 2+2", visible)
        self.assertEqual(app._streaming_target, "4")

    def test_current_transcript_shows_thinking_while_direct_prompt_is_running(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        app = RelayShellApp(service)
        app._running_prompt = "2+2"
        app._running_provider = "claude-main"
        app._thinking_tick = 1
        app._active_future = object()
        app.current_progress["status"] = "running"
        visible = app._current_transcript_tail()
        self.assertIn("> 2+2", visible)
        self.assertIn("Thinking with claude-main", visible)

    def test_rerun_last_reuses_latest_prompt_and_workflow(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event("prompt_submitted", {"prompt": "2+2", "workflow": {"id": "wf_1", "name": "Direct", "main_agent": "qwen-main", "mode": "direct", "send_back": False, "steps": []}})
        service.append_event("workflow_finished", {"prompt": "2+2", "workflow": {"id": "wf_1"}, "summary": "4"})
        started = {}
        with mock.patch.object(app, "_start_prompt_run", side_effect=lambda prompt, workflow: started.update({"prompt": prompt, "workflow": workflow})):
            app._handle_slash_command("/rerun last")
        self.assertEqual(started["prompt"], "2+2")
        self.assertEqual(started["workflow"]["id"], "wf_1")

    def test_resume_last_reuses_latest_prompt_and_workflow(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event(
            "prompt_submitted",
            {
                "prompt": "2+2",
                "workflow": {"id": "wf_1", "name": "Direct", "main_agent": "qwen-main", "mode": "direct", "send_back": False, "steps": []},
            },
        )
        started = {}
        with mock.patch.object(app, "_start_prompt_run", side_effect=lambda prompt, workflow: started.update({"prompt": prompt, "workflow": workflow})):
            app._handle_slash_command("/resume last")
        self.assertEqual(started["prompt"], "2+2")
        self.assertEqual(started["workflow"]["id"], "wf_1")

    def test_resume_last_sets_resume_from_next_incomplete_step(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event(
            "prompt_submitted",
            {
                "prompt": "finish this",
                "workflow": {
                    "id": "wf_resume",
                    "name": "Review Flow",
                    "main_agent": "claude-main",
                    "mode": "workflow",
                    "send_back": True,
                    "steps": [
                        {"id": "step_1", "agent_name": "codex-main", "task_type": "review", "label": ""},
                        {"id": "step_2", "agent_name": "gemini-main", "task_type": "web_research", "label": ""},
                    ],
                },
            },
        )
        service.append_event("workflow_step_finished", {"prompt": "finish this", "workflow_id": "wf_resume", "step_index": 0, "status": "completed", "run_id": "run_prev", "step": {"agent_name": "codex-main", "task_type": "review"}, "normalized_result": {"summary": "done"}})
        service.append_event("workflow_step_finished", {"prompt": "finish this", "workflow_id": "wf_resume", "step_index": 1, "status": "failed", "error": "timeout"})
        started = {}
        with mock.patch.object(app, "_start_prompt_run", side_effect=lambda prompt, workflow: started.update({"prompt": prompt, "workflow": workflow})), mock.patch.object(app, "_add_notice") as add_notice:
            app._handle_slash_command("/resume last")
        self.assertEqual(started["prompt"], "finish this")
        self.assertEqual(started["workflow"]["resume_from_step"], 1)
        self.assertEqual(started["workflow"]["resume_parent_run_id"], "run_prev")
        self.assertIn("after failure: timeout", add_notice.call_args[0][0])

    def test_resume_last_can_resume_send_back_only(self) -> None:
        tempdir, service, root = self._create_service()
        self.addCleanup(tempdir.cleanup)
        old_home = os.environ.get("RELAY_HOME")
        os.environ["RELAY_HOME"] = str(root)
        self.addCleanup(lambda: os.environ.__setitem__("RELAY_HOME", old_home) if old_home is not None else os.environ.pop("RELAY_HOME", None))
        app = RelayShellApp(service)
        service.append_event(
            "prompt_submitted",
            {
                "prompt": "wrap up",
                "workflow": {
                    "id": "wf_send",
                    "name": "Review Flow",
                    "main_agent": "claude-main",
                    "mode": "workflow",
                    "send_back": True,
                    "steps": [
                        {"id": "step_1", "agent_name": "codex-main", "task_type": "review", "label": ""},
                    ],
                },
            },
        )
        service.append_event("workflow_step_finished", {"prompt": "wrap up", "workflow_id": "wf_send", "step_index": 0, "status": "completed", "run_id": "run_done", "step": {"agent_name": "codex-main", "task_type": "review"}, "normalized_result": {"summary": "done"}})
        service.append_event("workflow_send_back_finished", {"prompt": "wrap up", "workflow_id": "wf_send", "status": "failed"})
        service.append_event("workflow_finished", {"prompt": "wrap up", "workflow": {"id": "wf_send"}, "summary": "done"})
        started = {}
        with mock.patch.object(app, "_start_prompt_run", side_effect=lambda prompt, workflow: started.update({"prompt": prompt, "workflow": workflow})), mock.patch.object(app, "_add_notice") as add_notice:
            app._handle_slash_command("/resume last")
        self.assertEqual(started["workflow"]["resume_from_step"], 1)
        self.assertEqual(started["workflow"]["resume_parent_run_id"], "run_done")
        self.assertIn("send-back", add_notice.call_args[0][0].lower())


if __name__ == "__main__":
    unittest.main()
