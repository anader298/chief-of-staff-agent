"""Tests for the two send gates and the email preflight. Stdlib only, no network, no credentials.

    python3 -m unittest discover -s tests -v

Layer 1: hooks/block_send.sh, the Claude Code PreToolUse hook, refuses a send command before it runs.
Layer 2: tools/mail.py gate_list(), inside the mail tool, refuses outside recipients.
Both open only when outbox/APPROVED is less than an hour old.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "block_send.sh"


def load_mail(config):
    """Import tools/mail.py against a temporary repo with its own config and outbox."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "tools").mkdir()
    (tmp / "outbox").mkdir()
    (tmp / "config").mkdir()
    for n in ("mail.py", "preflight.py"):
        shutil.copy(ROOT / "tools" / n, tmp / "tools" / n)
    if config is not None:
        (tmp / "config" / "mailboxes.json").write_text(json.dumps(config))
    os.environ.pop("COS_MAILBOXES", None)
    spec = importlib.util.spec_from_file_location("mail_under_test", tmp / "tools" / "mail.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, tmp


CONFIG = {"owner_addresses": ["owner@example.com", "owner@work.example"],
          "mailboxes": [{"label": "A", "address": "owner@example.com"}, {"label": "C-work", "address": "owner@work.example"}]}


class MailGate(unittest.TestCase):
    def setUp(self):
        self.m, self.tmp = load_mail(CONFIG)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def blocked(self, rcpts):
        try:
            self.m.gate_list(rcpts)
        except SystemExit as e:
            return str(e)
        return None

    def test_owner_only_passes(self):
        self.assertIsNone(self.blocked(["owner@example.com", "owner@work.example"]))

    def test_outside_recipient_blocked(self):
        self.assertIn("BLOCKED", self.blocked(["owner@example.com", "someone@else.example"]))

    def test_empty_list_blocked(self):
        # the bug behind the one unapproved send: a parser returned no recipients and the gate let it through
        self.assertIn("no recipients", self.blocked([]))

    def test_fresh_approval_opens(self):
        (self.tmp / "outbox" / "APPROVED").touch()
        self.assertIsNone(self.blocked(["someone@else.example"]))

    def test_stale_approval_blocked(self):
        f = self.tmp / "outbox" / "APPROVED"
        f.touch()
        old = time.time() - 3700
        os.utime(f, (old, old))
        self.assertIn("BLOCKED", self.blocked(["someone@else.example"]))

    def test_labels_resolve(self):
        self.assertEqual(self.m.resolve("C-work"), "owner@work.example")
        self.assertEqual(self.m.resolve(""), "owner@example.com")


class MailGateNoConfig(unittest.TestCase):
    def test_missing_config_fails_closed(self):
        m, tmp = load_mail(None)
        try:
            with self.assertRaises(SystemExit):
                m.gate_list(["owner@example.com"])  # no own addresses known, so nobody is "own"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class SendHook(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "outbox").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        env = dict(os.environ, COS_REPO=str(self.tmp))
        r = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=env)
        return r.returncode

    def test_send_blocked(self):
        self.assertEqual(self.run_hook("python3 tools/mail.py send --to x --subject y --body z"), 2)
        self.assertEqual(self.run_hook("cd /tmp && python3 tools/mail.py send-draft --contains y"), 2)
        self.assertEqual(self.run_hook("FOO=1 sendmail someone"), 2)
        self.assertEqual(self.run_hook("python3 -c 'import smtplib; smtplib.SMTP()'"), 2)

    def test_reads_and_drafts_allowed(self):
        self.assertEqual(self.run_hook("python3 tools/mail.py inbox --all --hours 2"), 0)
        self.assertEqual(self.run_hook("python3 tools/mail.py draft --to x --subject y --body z"), 0)
        self.assertEqual(self.run_hook("grep -rn 'mail.py send' tools/"), 0)  # mentioning a send is not sending

    def test_approval_opens_hook(self):
        (self.tmp / "outbox" / "APPROVED").touch()
        self.assertEqual(self.run_hook("python3 tools/mail.py send-draft --contains y"), 0)


class Preflight(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("preflight", ROOT / "tools" / "preflight.py")
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)

    def test_hard_wrapped_paragraph_caught(self):
        body = ("Thanks for the note. I have looked at the numbers you sent over and\n"
                "they line up with what we discussed on the call last week, so I am\n"
                "happy to move ahead on the terms as written.\n")
        self.assertTrue(self.p.wrapped_runs(body))

    def test_one_line_paragraphs_pass(self):
        body = "Thanks for the note. The numbers line up with what we discussed, so I am happy to move ahead.\n\nBest,\nOwner\n"
        self.assertFalse(self.p.wrapped_runs(body))


if __name__ == "__main__":
    unittest.main()
