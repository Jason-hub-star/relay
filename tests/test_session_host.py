from __future__ import annotations

import unittest

from relay.session_host import _normalize_terminal_text, _should_auto_accept_trust


class SessionHostTests(unittest.TestCase):
    def test_normalize_terminal_text_strips_ansi_sequences(self) -> None:
        raw = "\x1b[38;5;220mQuick\x1b[39m safety check"
        self.assertEqual(_normalize_terminal_text(raw), "Quick safety check")

    def test_should_auto_accept_claude_trust_prompt(self) -> None:
        transcript = (
            "\x1b[38;5;220mQuick\x1b[39m safety check\n"
            "Yes, I trust this folder\n"
            "Enter to confirm\n"
        )
        self.assertTrue(_should_auto_accept_trust(["claude", "--dangerously-skip-permissions"], transcript))

    def test_should_not_auto_accept_for_non_claude_commands(self) -> None:
        transcript = "Quick safety check\nYes, I trust this folder\nEnter to confirm\n"
        self.assertFalse(_should_auto_accept_trust(["codex"], transcript))


if __name__ == "__main__":
    unittest.main()
