"""Published SDK contract test with local WDA/model HTTP fixtures, no real phone."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
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
                     "Install optional SDK with npm ci --prefix server/midscene")
class MidsceneSDKTests(unittest.TestCase):
    def test_query_and_assert_reuse_session_send_images_and_write_report(self):
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
        env.update(MIDSCENE_MODEL_API_KEY="fixture", MIDSCENE_MODEL_NAME="qwen2.5-vl-72b-instruct",
                   MIDSCENE_MODEL_FAMILY="qwen2.5-vl", MIDSCENE_MODEL_BASE_URL=f"http://127.0.0.1:{port}/v1")
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(["node", str(WORKER)], input=json.dumps({"action": "query",
                "prompt": "Return the screen title as a string", "host": "127.0.0.1", "port": port,
                "sessionId": "borrowed"}), text=True, capture_output=True, cwd=directory, env=env, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["result"], "fixture screen")
            self.assertTrue(Path(result["report"]).is_file(), result)
            for truthy in (True, False):
                model_value = {"StatementIsTruthy": truthy}
                process = subprocess.run(["node", str(WORKER)], input=json.dumps({"action": "assert",
                    "prompt": "The expected title is visible", "host": "127.0.0.1", "port": port,
                    "sessionId": "borrowed"}), text=True, capture_output=True, cwd=directory, env=env, timeout=60)
                self.assertEqual(process.returncode, 0 if truthy else 1, process.stderr)
                self.assertEqual(json.loads(process.stdout)["ok"], truthy)
        self.assertEqual(len(models), 3)
        self.assertIn("data:image/", json.dumps(models))
        self.assertIn(("GET", "/session/borrowed/screenshot"), requests)
        self.assertNotIn(("POST", "/session"), requests)
        self.assertFalse(any(method == "DELETE" for method, _ in requests), requests)
