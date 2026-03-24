from __future__ import annotations

import unittest
from unittest import mock

from relay.adapters import build_live_command, check_agent_readiness


class AdapterTests(unittest.TestCase):
    def test_claude_live_command_adds_skip_permissions_flag(self) -> None:
        agent = {"kind": "claude", "launch_command": "/Users/family/.local/bin/claude"}
        command = build_live_command(agent)
        self.assertEqual(command[-1], "--dangerously-skip-permissions")

    def test_claude_live_command_does_not_duplicate_skip_permissions_flag(self) -> None:
        agent = {
            "kind": "claude",
            "launch_command": "/Users/family/.local/bin/claude --dangerously-skip-permissions",
        }
        command = build_live_command(agent)
        self.assertEqual(command.count("--dangerously-skip-permissions"), 1)

    def test_non_claude_live_command_is_unchanged(self) -> None:
        agent = {"kind": "codex", "launch_command": "/Users/family/.local/bin/codex"}
        command = build_live_command(agent)
        self.assertEqual(command, ["/Users/family/.local/bin/codex"])

    def test_gemini_readiness_detects_missing_login(self) -> None:
        agent = {"kind": "gemini", "launch_command": "gemini"}
        with mock.patch(
            "relay.adapters.run_command",
            return_value=mock.Mock(stdout="", stderr="Missing cached credentials. Please sign in.", returncode=1),
        ):
            result = check_agent_readiness(agent, cwd=".")
        self.assertEqual(result.status, "needs_login")

    def test_qwen_readiness_detects_ready_auth_status(self) -> None:
        agent = {"kind": "qwen", "launch_command": "qwen"}
        with mock.patch(
            "relay.adapters.run_command",
            return_value=mock.Mock(
                stdout="=== Authentication Status ===\n✓ Authentication Method: Qwen OAuth",
                stderr="",
                returncode=0,
            ),
        ):
            result = check_agent_readiness(agent, cwd=".")
        self.assertEqual(result.status, "ready")


if __name__ == "__main__":
    unittest.main()
