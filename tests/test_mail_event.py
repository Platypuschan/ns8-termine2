import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVENT = ROOT / "imageroot/events/smarthost-changed/10restart"


class MailEventTest(unittest.TestCase):
    def run_event(self, settings, active=True, discovery_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            commands = state / "commands"
            commands.mkdir()
            program = r"""#!/usr/bin/env python3
import os,sys
from pathlib import Path
command = Path(sys.argv[0]).name
with open(os.environ["EVENT_LOG"], "a") as stream:
    stream.write(command + " " + " ".join(sys.argv[1:]) + "\n")
if command == "systemctl" and "is-active" in sys.argv:
    sys.exit(0 if os.environ["SERVICE_ACTIVE"] == "1" else 3)
if command == "runagent" and os.environ["DISCOVERY_FAIL"] == "1":
    sys.exit(1)
"""
            for name in ("systemctl", "runagent"):
                executable = commands / name
                executable.write_text(program)
                executable.chmod(0o755)
            (state / "termine.json").write_text(json.dumps(settings, separators=(",", ":")))
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       EVENT_LOG=str(state / "calls"), SERVICE_ACTIVE=str(int(active)),
                       DISCOVERY_FAIL=str(int(discovery_fails)))
            result = subprocess.run(["bash", str(EVENT)], cwd=state, env=env, capture_output=True, text=True)
            calls = (state / "calls").read_text().splitlines() if (state / "calls").exists() else []
            return result.returncode, calls

    def test_smarthost_erneuert_mailkonfiguration_und_beide_container(self):
        status, calls = self.run_event({"mail_mode": "smarthost"})
        self.assertEqual(status, 0)
        self.assertEqual(calls, [
            "systemctl --user is-active --quiet pretix-app.service",
            "runagent discover-mail",
            "systemctl --user restart pretix-app.service",
            "systemctl --user try-restart cron-app.service",
        ])

    def test_externes_smtp_bleibt_unberuehrt_auch_mit_kompaktem_json(self):
        status, calls = self.run_event({"mail_mode": "external"})
        self.assertEqual((status, calls), (0, []))

    def test_inaktive_app_wird_nicht_unbeabsichtigt_gestartet(self):
        status, calls = self.run_event({"mail_mode": "smarthost"}, active=False)
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 1)

    def test_discovery_fehler_verhindert_neustart_mit_alten_zugangsdaten(self):
        status, calls = self.run_event({"mail_mode": "smarthost"}, discovery_fails=True)
        self.assertNotEqual(status, 0)
        self.assertFalse(any("restart" in call for call in calls))
