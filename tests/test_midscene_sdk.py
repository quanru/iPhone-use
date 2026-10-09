"""Published SDK contract test with local WDA/model HTTP fixtures, no real phone."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "server/midscene/run.mjs"


def screenshot():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" +
        chunk(b"IHDR", struct.pack(">2I5B", 100, 200, 8, 2, 0, 0, 0)) +
        chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\xff\xff" * 100) * 200)) +
        chunk(b"IEND", b"")).decode()


@unittest.skipUnless((WORKER.parent / "node_modules/@midscene/ios").exists(),
                     "Install SDK with npm ci --prefix server/midscene")
class MidsceneSDKTests(unittest.TestCase):
    def test_host_actions_without_model_reuse_session_and_append_reports(self):
        requests = []
        models = []
        model_value = "fixture screen"
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def do_DELETE(self):
                self.respond()

            def respond(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                requests.append((self.command, self.path))
                if self.path == "/v1/chat/completions":
                    models.append(body)
                    content = '<data-json>' + json.dumps(model_value) + '</data-json>'
                    if body.get("stream"):
                        chunks = [{"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
                                  {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
                        raw = ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
                        content_type = "text/event-stream"
                    else:
                        raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}).encode()
                        content_type = "application/json"
                else:
                    values = {"/status": {"ready": True},
                              "/session/borrowed/wda/screen": {"scale": 1},
                              "/session/borrowed/window/rect": {"x": 0, "y": 0, "width": 100, "height": 200},
                              "/session/borrowed/screenshot": screenshot()}
                    raw = json.dumps({"sessionId": "borrowed", "value": values.get(self.path, {})}).encode()
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        env = {key: value for key, value in os.environ.items() if not key.startswith("MIDSCENE_")}

        with tempfile.TemporaryDirectory() as directory:
            def run(action, args=None, report_id="shared-task"):
                process = subprocess.run(["node", str(WORKER)], input=json.dumps({"action": action,
                    "args": args or {}, "host": "127.0.0.1", "port": port,
                    "sessionId": "borrowed", "reportId": report_id}), text=True,
                    capture_output=True, cwd=directory, env=env, timeout=60)
                result = json.loads(process.stdout)
                self.assertEqual(process.returncode, 1 if action == "record" and args["passed"] is False else 0,
                                 process.stderr + str(result))
                return result
            result = run("screenshot")
            self.assertTrue(result["ok"])
            self.assertIn("data:image/png", result["screenshot"])
            report = Path(result["report"])
            def executions_in_report():
                dumps = re.findall(r'<script type="midscene_web_dump" data-group-id=[^>]*>(.*?)</script>', report.read_text(), re.S)
                return {execution["id"]: execution for dump in dumps
                        for execution in json.loads(dump)["executions"]}
            original = executions_in_report()
            self.assertEqual(len(original), 2)
            for action, args in [("tap", {"x": 10, "y": 20}),
                                 ("swipe", {"x": 50, "y": 150, "end_x": 50, "end_y": 50}),
                                 ("input", {"text": "hello"}),
                                 ("record", {"text": "Visible fixture", "passed": True}),
                                 ("record", {"text": "Missing fixture", "passed": False})]:
                outcome = run(action, args)
                self.assertEqual(outcome["report"], str(report))
                self.assertTrue(original.keys() <= executions_in_report().keys())
            executions = executions_in_report()
            self.assertEqual(len(executions), 12)
            self.assertTrue(any(t["status"] == "failed" for e in executions.values() for t in e["tasks"]))
            self.assertNotEqual(run("screenshot", report_id="other-task")["report"], str(report))
            self.assertEqual(len(executions_in_report()), 12)
        self.assertEqual(models, [], "Host-driven mode must never invoke a model")
        self.assertIn(("POST", "/session/borrowed/wda/tap"), requests)
        self.assertIn(("GET", "/session/borrowed/screenshot"), requests)
        self.assertNotIn(("POST", "/session"), requests)
        self.assertFalse(any(method == "DELETE" for method, _ in requests), requests)
