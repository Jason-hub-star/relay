from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relay.repository import RelayRepository


class RepositoryTests(unittest.TestCase):
    def test_agent_session_and_presets_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = RelayRepository(Path(tmp) / "relay.db")
            agent = repo.add_agent(
                name="claude-main",
                kind="claude",
                launch_command="claude",
                resume_strategy="native",
                supports={"resume_same_session": True},
            )
            session = repo.add_session(
                agent_id=agent["id"],
                label="main",
                cwd=tmp,
                external_session_ref="/tmp/test.sock",
                status="active",
                metadata={"transcript_path": "/tmp/log"},
            )
            self.assertEqual(agent["name"], "claude-main")
            self.assertEqual(session["label"], "main")
            self.assertGreaterEqual(len(repo.list_presets()), 3)


if __name__ == "__main__":
    unittest.main()
