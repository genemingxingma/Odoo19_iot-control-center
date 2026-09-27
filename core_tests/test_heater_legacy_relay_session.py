import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("relay_session", ROOT / "tools/heater_legacy_relay_session.py")
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


class Client:
    def exec_command(self, command):
        assert command == "hostname"
        return None, io.BytesIO(b"imytestth\n"), None

    def close(self):
        pass


class DetectionSessionTests(unittest.TestCase):
    def run_session(self, observations, fail_on=False, foreign=False):
        current = {"relay_state":"off", "desired_relay_state":"off",
                   "relay_command_state":"confirmed", "last_command_id":"baseline",
                   "control_inhibited":True, "safety_tripped":False, "session_owned":False}
        actions = []

        def remote(client, config, action="read", expected=None, owner=None):
            if foreign and action == "read" and actions:
                current.update(last_command_id="operator", session_owned=False)
            if action != "read":
                self.assertEqual(expected, current["last_command_id"])
                actions.append(action)
                current.update(relay_state=action, desired_relay_state=action,
                               last_command_id=str(len(actions)), session_owned=True)
                if fail_on and action == "on":
                    raise RuntimeError("Transport failed after commit")
            return dict(current)

        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(session, "PRIVATE", Path(tmp)))
            stack.enter_context(patch.object(session, "read_config", return_value={}))
            stack.enter_context(patch.object(session, "connect", return_value=Client()))
            stack.enter_context(patch.object(session, "remote", side_effect=remote))
            stack.enter_context(patch.object(session, "observer", side_effect=observations))
            stack.enter_context(patch.object(session, "confirmed", side_effect=lambda *a: dict(current)))
            stack.enter_context(patch.object(session.time, "sleep"))
            stack.enter_context(patch.object(session.time, "monotonic", side_effect=range(0, 100000, 100)))
            stack.enter_context(patch.object(session.sys, "argv", ["test", "--execute-authorized-detection"]))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            error = None
            try:
                session.main()
            except RuntimeError as caught:
                error = str(caught)
            receipt = json.loads((Path(tmp) / "powercycle-session.json").read_text())
        return actions, receipt, error

    def test_first_request_stops_retries_and_restores_off(self):
        actions, receipt, error = self.run_session([{}, {}, {"123456":{"chip_id":"123456"}}])
        self.assertEqual(actions, ["on", "off"])
        self.assertIsNone(error)
        self.assertEqual(receipt["status"], "detected")
        self.assertEqual(receipt["final"]["relay_state"], "off")
        self.assertFalse(receipt["firmware_served"])

    def test_missing_requests_have_three_attempt_bound(self):
        actions, receipt, error = self.run_session(lambda: {})
        self.assertEqual(actions, ["on", "off"] * 3)
        self.assertIsNone(error)
        self.assertEqual(len(receipt["attempts"]), 3)
        self.assertEqual(receipt["status"], "no_device_after_three_attempts")

    def test_observer_failure_during_on_stops_the_load(self):
        actions, receipt, error = self.run_session([{}, {}, RuntimeError("Observer unavailable")])
        self.assertEqual(actions, ["on", "off"])
        self.assertEqual(receipt["final"]["relay_state"], "off")
        self.assertEqual(error, "Observer unavailable")

    def test_transport_failure_after_on_commit_is_cleaned_up(self):
        actions, receipt, error = self.run_session([{}, {}], fail_on=True)
        self.assertEqual(actions, ["on", "off"])
        self.assertEqual(receipt["final"]["relay_state"], "off")
        self.assertEqual(error, "Transport failed after commit")

    def test_concurrent_operator_command_is_not_overwritten(self):
        actions, receipt, error = self.run_session([{}, {}], fail_on=True, foreign=True)
        self.assertEqual(actions, ["on"])
        self.assertIn("Concurrent intent", error)
        self.assertNotIn("final", receipt)

    def test_no_authorization_flag_performs_no_io(self):
        with patch.object(session.sys, "argv", ["test"]), patch.object(session, "observer") as observe:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                session.main()
            observe.assert_not_called()

    def test_remote_scope_and_watchdog_guards_are_present(self):
        source = session.REMOTE
        for required in ("browse(57)", "== '06458F'", "company_id.id == 1", "'max_on_sec':360",
                         "not device.safety_tripped", "FOR UPDATE NOWAIT", "maintenance_session",
                         "== EXPECTED", "installed_version == '19.0.2.6.1'"):
            self.assertIn(required, source)
        for forbidden in ("action_reset", "action_unbind", "network_set", "safety_tripped':False"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
