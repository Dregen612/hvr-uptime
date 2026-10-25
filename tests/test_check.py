#!/usr/bin/env python3
"""Offline end-to-end tests: python3 tests/test_check.py [--script PATH].

Each invocation gets a temporary working directory, a fixed clock, fixture-only
curl, and an allowlisted environment containing dummy Telegram credentials.
The actual check.sh runs unchanged; no FORCE_* hooks or network calls are used.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "check.sh"
NOW = 1800000000
DOWN = f"down {NOW - 1800} {NOW - 600}\n"
SUSPECT = f"suspect {NOW - 300} 0\n"
LIVE_PAGE = '{"isLive":true,"isLiveContent":true}'
OFFLINE_PAGE = '{"isLiveContent":true}'


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "state.txt"
        self.calls = self.root / "calls.jsonl"
        self.messages = self.root / "messages.jsonl"
        self.now = NOW
        self.heartbeat = ""
        self.page = ""
        self.hb_exit = 0
        self.page_exit = 0
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.root),
            "LC_ALL": "C",
            "TG_TOKEN": "offline-test-token",
            "TG_CHAT": "offline-test-chat",
            "FIXTURES": str(self.root),
        }
        self.mock("date", f"""import os, sys
if sys.argv[1:] == ['+%s']:
    print(os.environ['MOCK_NOW'])
else:
    os.execv({shutil.which('date')!r}, ['date'] + sys.argv[1:])
""")
        self.mock("curl", """import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURES'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as f:
    f.write(json.dumps(args) + '\\n')
urls = [a for a in args if a.startswith('https://')]
if len(urls) != 1:
    sys.exit(97)
url = urls[0]
if url.startswith('https://gist.githubusercontent.com/Dregen612/264164455a4e5fa12f3b28a43a6af69d/raw/hb.json?t='):
    sys.stdout.write((root / 'heartbeat').read_text())
    sys.exit(int(os.environ['HB_EXIT']))
if url == 'https://www.youtube.com/@HolyVoltageRadio/live':
    sys.stdout.write((root / 'page').read_text())
    sys.exit(int(os.environ['PAGE_EXIT']))
if url == 'https://api.telegram.org/botoffline-test-token/sendMessage':
    if 'chat_id=offline-test-chat' not in args:
        sys.exit(98)
    message = args[args.index('--data-urlencode') + 1]
    with (root / 'messages.jsonl').open('a') as f:
        f.write(json.dumps(message) + '\\n')
    sys.exit(0)
# Never fall through to a real curl, even for an unexpected URL.
sys.exit(99)
""")
        # check.sh invokes python3 by name; retain the current interpreter.
        (self.bin / "python3").symlink_to(os.sys.executable)

    def mock(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{os.sys.executable}\n" + source)
        path.chmod(0o755)

    def hb(self, age=1, youtube="live"):
        self.heartbeat = json.dumps({"ts": self.now - age * 60, "youtube": youtube})

    def run_check(self):
        (self.root / "heartbeat").write_text(self.heartbeat)
        (self.root / "page").write_text(self.page)
        before = len(self.read_jsonl(self.calls))
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT)], cwd=self.root,
            env={**self.env, "MOCK_NOW": str(self.now),
                 "HB_EXIT": str(self.hb_exit), "PAGE_EXIT": str(self.page_exit)},
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        calls = self.read_jsonl(self.calls)[before:]
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("gist.githubusercontent.com", " ".join(calls[0]))
        self.assertIn("https://www.youtube.com/@HolyVoltageRadio/live", calls[1])
        for call in calls[2:]:
            self.assertIn("https://api.telegram.org/botoffline-test-token/sendMessage", call)
        return result.stdout

    @staticmethod
    def read_jsonl(path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_unknown(self, state):
        if state is not None:
            self.state.write_text(state)
        out = self.run_check()
        self.assertTrue(out.startswith("UNKNOWN "), out)
        self.assertNotIn("OK ", out)
        self.assertEqual(self.state.read_text() if self.state.exists() else None, state)
        self.assertEqual(self.read_jsonl(self.messages), [])

    def test_unavailable_preserves_alerted_down(self):
        self.assert_unknown(DOWN)

    def test_malformed_heartbeat_and_unrecognized_page_preserve_down(self):
        self.heartbeat = "not-json"
        self.page = "<html>consent page</html>"
        self.assert_unknown(DOWN)

    def test_failed_requests_preserve_down(self):
        self.hb_exit = self.page_exit = 28
        self.assert_unknown(DOWN)

    def test_unavailable_preserves_pending_suspect(self):
        self.assert_unknown(SUSPECT)

    def test_unavailable_preserves_up(self):
        self.assert_unknown("up 0 0\n")

    def test_unavailable_does_not_create_state(self):
        self.assert_unknown(None)

    def test_fresh_unknown_heartbeat_is_not_recovery(self):
        self.hb(youtube="unknown")
        self.assert_unknown(DOWN)

    def test_unknown_preserves_legacy_state_bytes(self):
        self.assert_unknown("down 1799998200 1799999400")

    def assert_recovery(self):
        self.state.write_text(DOWN)
        self.assertTrue(self.run_check().startswith("OK "))
        self.assertEqual(self.state.read_text(), "up 0 0\n")
        messages = self.read_jsonl(self.messages)
        self.assertEqual(len(messages), 1)
        self.assertIn("confirmed live again", messages[0])

    def test_public_live_recovers_with_unreadable_heartbeat(self):
        self.heartbeat = "not-json"
        self.page = LIVE_PAGE
        self.assert_recovery()

    def test_public_live_overrides_stale_heartbeat(self):
        self.hb(age=37, youtube="notlive")
        self.page = LIVE_PAGE
        self.assert_recovery()

    def test_fresh_live_heartbeat_recovers_with_unknown_page(self):
        self.hb(age=19)
        self.assert_recovery()

    def test_recovery_is_sent_once(self):
        self.page = LIVE_PAGE
        self.assert_recovery()
        self.run_check()
        self.assertEqual(len(self.read_jsonl(self.messages)), 1)

    def test_no_recovery_message_without_previous_alert(self):
        self.page = LIVE_PAGE
        for state in ["up 0 0\n", SUSPECT, f"down {NOW - 300} 0\n"]:
            with self.subTest(state=state):
                self.state.write_text(state)
                self.run_check()
                self.assertEqual(self.state.read_text(), "up 0 0\n")
                self.assertEqual(self.read_jsonl(self.messages), [])

    def assert_two_bad_readings(self):
        self.state.write_text("up 0 0\n")
        self.assertTrue(self.run_check().startswith("SUSPECT "))
        self.assertEqual(self.state.read_text(), f"suspect {NOW} 0\n")
        self.assertEqual(self.read_jsonl(self.messages), [])
        self.now += 300
        self.assertTrue(self.run_check().startswith("DOWN:"))
        self.assertEqual(self.state.read_text(), f"down {NOW} {self.now}\n")
        self.assertEqual(len(self.read_jsonl(self.messages)), 1)
        self.assertIn("confirmed twice", self.read_jsonl(self.messages)[0])

    def test_public_notlive_requires_two_bad_readings(self):
        self.page = OFFLINE_PAGE
        self.assert_two_bad_readings()

    def test_stale_live_heartbeat_is_not_positive_recovery(self):
        self.hb(age=20)
        self.assert_two_bad_readings()

    def test_fresh_notlive_heartbeat_requires_two_bad_readings(self):
        self.hb(youtube="notlive")
        self.assert_two_bad_readings()

    def test_public_notlive_blocks_heartbeat_recovery(self):
        self.hb()
        self.page = OFFLINE_PAGE
        self.state.write_text(DOWN)
        self.assertTrue(self.run_check().startswith("DOWN:"))
        self.assertEqual(self.state.read_text(), DOWN)
        self.assertEqual(self.read_jsonl(self.messages), [])

    def test_unknown_between_bad_readings_preserves_pending_confirmation(self):
        self.state.write_text("up 0 0\n")
        self.page = OFFLINE_PAGE
        self.run_check()
        pending = self.state.read_text()
        self.now += 300
        self.page = ""
        self.assert_unknown(pending)
        self.now += 300
        self.page = OFFLINE_PAGE
        self.assertTrue(self.run_check().startswith("DOWN:"))
        self.assertEqual(self.state.read_text(), f"down {NOW} {self.now}\n")
        self.assertEqual(len(self.read_jsonl(self.messages)), 1)

    def test_reminder_timer_survives_unknown(self):
        self.assert_unknown(DOWN)
        self.page = OFFLINE_PAGE
        self.assertTrue(self.run_check().startswith("DOWN:"))
        self.assertEqual(self.read_jsonl(self.messages), [])
        self.now += 3000  # Exactly one hour after the previous alert.
        self.assertTrue(self.run_check().startswith("DOWN:"))
        self.assertEqual(len(self.read_jsonl(self.messages)), 1)
        self.assertEqual(self.state.read_text(), f"down {NOW - 1800} {self.now}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=SCRIPT)
    args, remaining = parser.parse_known_args()
    SCRIPT = args.script.resolve(strict=True)
    unittest.main(argv=[__file__, *remaining])
