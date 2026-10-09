import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from iphone_use import Runtime
from wda_client import WDAError
import wda_midscene


class MidsceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.runtime = Runtime(self.root, base_url="http://127.0.0.1:18123")
        self.addCleanup(self.runtime.close)
        self.runtime.screen = Mock()
        self.runtime.screen.paused.return_value = False
        self.runtime.client = Mock(host="127.0.0.1", port=18123, session_id="borrowed-session")
        self.runtime.client.request.return_value = {"value": False}
        self.runtime.client.ensure_session.return_value = "borrowed-session"
        self.env = {key: "test-secret" if key.endswith("KEY") else "test" for key in wda_midscene.MODEL_ENV}
        self.config = {"enabled": True, "env": self.env}
        worker = self.root / "worker" / "run.mjs"
        dependency = worker.parent / "node_modules/@midscene/ios/package.json"
        dependency.parent.mkdir(parents=True)
        dependency.write_text("{}")
        self.addCleanup(patch.stopall)
        patch.object(wda_midscene, "WORKER", worker).start()
        patch.object(wda_midscene.shutil, "which", return_value="/usr/bin/node").start()
        self.process = patch.object(wda_midscene.subprocess, "run", return_value=Mock(
            returncode=0, stdout='{"ok":true,"result":"visible text"}')).start()

    def configure(self):
        (self.root / "midscene.json").write_text(json.dumps(self.config))

    def call(self, action="act"):
        return self.runtime.call("pua_midscene", {"action": action, "prompt": "Read this screen"})

    def test_disabled_without_configuration_does_not_contact_phone(self):
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, "midscene_disabled")
        self.runtime.client.request.assert_not_called()
        self.process.assert_not_called()

    def test_model_environment_merge_and_validation(self):
        self.config["env"].pop("MIDSCENE_MODEL_API_KEY")
        self.configure()
        with patch.dict(wda_midscene.os.environ, {"MIDSCENE_MODEL_API_KEY": "inherited"}, clear=True):
            self.assertEqual(wda_midscene.configuration(self.root)[0]["MIDSCENE_MODEL_API_KEY"], "inherited")
        for invalid in ([], {"enabled": True, "env": {"NODE_OPTIONS": "injected"}},
                        {**self.config, "timeout_seconds": True}, {**self.config, "timeout_seconds": 601}):
            (self.root / "midscene.json").write_text(json.dumps(invalid))
            with self.assertRaises(WDAError) as error:
                self.call()
            self.assertEqual(error.exception.code, "midscene_invalid_config")
        self.process.assert_not_called()

    def test_disabling_configuration_takes_effect_without_restart(self):
        self.configure()
        self.assertTrue(self.call("query")["ok"])
        self.config["enabled"] = False
        self.configure()
        with self.assertRaises(WDAError) as error:
            self.call("query")
        self.assertEqual(error.exception.code, "midscene_disabled")
        self.process.assert_called_once()

    def test_missing_optional_dependency_is_actionable_without_phone_access(self):
        self.configure()
        (wda_midscene.WORKER.parent / "node_modules/@midscene/ios/package.json").unlink()
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, "midscene_not_installed")
        self.runtime.client.request.assert_not_called()
        self.process.assert_not_called()

    def test_shared_session_lock_and_no_secret_in_command(self):
        self.configure()
        def execute(command, **kwargs):
            with (self.root / "operation.lock").open("a") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotIn("test-secret", str(command))
            request = json.loads(kwargs["input"])
            self.assertEqual((request["host"], request["port"], request["sessionId"]),
                             ("127.0.0.1", 18123, "borrowed-session"))
            self.assertEqual(kwargs["cwd"], self.root)
            return Mock(returncode=0, stdout='{"ok":true,"result":"visible text"}')
        self.process.side_effect = execute
        self.assertEqual(self.call("query")["result"], "visible text")
        self.assertIsNone(self.runtime.client._settings_session_id)
        self.assertEqual(json.loads((self.root / "session.json").read_text())["session_id"], "borrowed-session")

    def test_busy_device_refuses_worker(self):
        self.configure()
        with (self.root / "operation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaises(WDAError) as error:
                self.call()
        self.assertEqual(error.exception.code, "device_busy")
        self.process.assert_not_called()

    def test_paused_or_locked_device_refuses_worker(self):
        self.configure()
        self.runtime.screen.paused.return_value = True
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, "preview_paused")
        self.runtime.client.request.assert_not_called()
        self.runtime.screen.paused.return_value = False
        self.runtime.client.request.return_value = {"value": True}
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertEqual(error.exception.code, "phone_locked")
        self.process.assert_not_called()

    def test_timeout_is_uncertain_without_replay_or_secret_leak(self):
        self.configure()
        self.process.side_effect = subprocess.TimeoutExpired("node", 180, stderr="test-secret")
        with self.assertRaises(WDAError) as error:
            self.call()
        self.assertTrue(error.exception.uncertain)
        self.assertNotIn("test-secret", str(error.exception))
        self.process.assert_called_once()
        self.assertIsNone(self.runtime.client._settings_session_id)

    def test_assert_failure_is_not_reported_as_success_or_mutation(self):
        self.configure()
        self.process.return_value = Mock(returncode=1, stdout='{"ok":false}', stderr="test-secret")
        with self.assertRaises(WDAError) as error:
            self.call("assert")
        self.assertEqual(error.exception.code, "midscene_failed")
        self.assertFalse(error.exception.uncertain)

    def test_optional_worker_is_shipped_without_node_modules(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import package
        files = {str(rel) for _, rel in package.package_files()}
        self.assertTrue({"server/midscene/run.mjs", "server/midscene/package.json",
                         "server/midscene/package-lock.json", "server/wda_midscene.py"} <= files)
        self.assertFalse(any("node_modules" in name for name in files))
