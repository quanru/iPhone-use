"""Optional Midscene worker, called while Runtime holds its device operation lock."""
import json
import os
import re
import uuid
from pathlib import Path
import shutil
import subprocess

from wda_client import WDAError


MODEL_ENV = {"MIDSCENE_MODEL_API_KEY", "MIDSCENE_MODEL_NAME",
             "MIDSCENE_MODEL_BASE_URL", "MIDSCENE_MODEL_FAMILY"}
WORKER = Path(__file__).parent / "midscene" / "run.mjs"


def configuration(state_dir):
    path = Path(state_dir) / "midscene.json"
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError()
        if config.get("enabled") is not True:
            raise WDAError("midscene_disabled", "Enable Midscene in the private state directory's midscene.json; see the Midscene setup guide.")
        env = config.get("env", {})
        timeout = config.get("timeout_seconds", 180)
        if (not isinstance(env, dict) or set(env) - MODEL_ENV
                or any(not isinstance(v, str) or not v.strip() for v in env.values())
                or type(timeout) is not int or not 10 <= timeout <= 600):
            raise ValueError()
        merged = {**os.environ, **env}
        if any(not merged.get(key, "").strip() for key in MODEL_ENV):
            raise WDAError("midscene_not_configured", "Set all four MIDSCENE_MODEL_* variables in midscene.json env or the MCP server environment.")
        return merged, timeout
    except (ValueError, OSError):
        raise WDAError("midscene_invalid_config", "Invalid midscene.json: expected enabled, env model variables and timeout_seconds (10–600).") from None


def run(runtime, action, prompt, report_id=None):
    if report_id is None:
        report_id = uuid.uuid4().hex
    if not isinstance(report_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", report_id):
        raise WDAError("invalid_arguments", "report_id must contain 1–64 letters, digits, underscores or hyphens.")
    env, timeout = configuration(runtime.state_dir)
    node = shutil.which("node")
    if not node or not (WORKER.parent / "node_modules/@midscene/ios/package.json").is_file():
        raise WDAError("midscene_not_installed", "Install Node.js and run npm ci --prefix <plugin-root>/server/midscene before enabling Midscene.")
    if runtime.screen.paused():
        raise WDAError("preview_paused", "Resume after the user finishes authentication before using Midscene.", details={"action_executed": False})
    if runtime.client.request("GET", "/wda/locked").get("value") is not False:
        raise WDAError("phone_locked", "Unlock the iPhone before using Midscene.")
    session_id = runtime.client.ensure_session()
    request = {"action": action, "prompt": prompt, "host": runtime.client.host,
               "port": runtime.client.port, "sessionId": session_id, "reportId": report_id}
    details = {"action_complete": False, "report_id": report_id}
    try:
        # Prompts and credentials never appear in process arguments or MCP stdout.
        process = subprocess.run([node, str(WORKER)], input=json.dumps(request),
                                 text=True, capture_output=True, env=env,
                                 cwd=runtime.state_dir, timeout=timeout)
        result = json.loads(process.stdout)
        if isinstance(result, dict) and isinstance(result.get("report"), str):
            details["report"] = result["report"]
        if process.returncode or not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError()
        return {**result, "report_id": report_id}
    except (subprocess.TimeoutExpired, ValueError, OSError):
        # Do not expose provider errors: these can contain credentials or screen data.
        raise WDAError("midscene_failed", "Midscene failed or timed out. Inspect the current screen before continuing; do not replay the task.",
                       uncertain=action == "act", details=details) from None
    finally:
        # Midscene configures the borrowed WDA session. Reapply PUA's settings
        # before its next session request, including after a killed worker.
        runtime.client.reapply_settings()
