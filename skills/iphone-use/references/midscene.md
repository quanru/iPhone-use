# Optional Midscene integration

Midscene adds screenshot-based natural-language actions, extraction, and assertions through `pua_midscene`. It is disabled by default. Existing PUA tools keep working without its SDK or model credentials.

Installing this plugin does not require another ChatGPT sign-in. When ChatGPT or Codex uses the existing PUA screenshot and gesture tools, the host model makes the decisions. `pua_midscene` instead runs a separate model-driven loop inside Midscene: this integration does not inherit the host's model configuration, conversation, or subscription credentials. Qwen is only one model option; configure a compatible provider for Midscene, or leave it disabled and use the existing PUA tools.

## Configure

Use Node.js 22.19 or newer (Node.js 24 is tested). In the installed plugin directory, install the pinned optional SDK:

```sh
npm ci --prefix server/midscene
```

Create `midscene.json` in the same private state directory as the device configuration. This is normally `~/.local/share/iphone-use`; reuse the existing state directory for legacy installations. `--state-dir` or `IPHONE_USE_STATE_DIR` can override it. Use the directory used by the running MCP server, not the source checkout.

```json
{
  "enabled": true,
  "timeout_seconds": 180,
  "env": {
    "MIDSCENE_MODEL_API_KEY": "your-provider-api-key",
    "MIDSCENE_MODEL_NAME": "your-vision-model",
    "MIDSCENE_MODEL_BASE_URL": "https://your-provider.example/v1",
    "MIDSCENE_MODEL_FAMILY": "your-supported-model-family"
  }
}
```

Set the file permissions to `0600`. Choose a compatible vision model using [Midscene model configuration](https://midscenejs.com/model-common-config.html). These four variables may instead come from the MCP server's environment; the file's `env` values take precedence. Do not put credentials in prompts, tracked plugin manifests, or PRs. Configuration is read on every call; setting `enabled` to `false` disables the integration without restarting the server. Plugin updates may require running the optional SDK install again.

Midscene sends screenshots and prompts to the configured model provider. Its local HTML reports can contain screen and task content and are written under the private state directory. The live widget remains available, but individual Midscene gestures do not produce PUA cursor effects.

## Use

First obtain `pua_ready` with `ready=true`. Then call:

```json
{"action":"act","prompt":"Open Settings and navigate to Display & Brightness"}
```

```json
{"action":"query","prompt":"What display settings are visible? Return their names."}
```

```json
{"action":"assert","prompt":"The Display & Brightness settings page is visible"}
```

All examples are arguments for `pua_midscene`. Use bounded tasks and verify the final result. `act` can perform multiple actions, including submission when instructed: do not include an unauthorized send, purchase, or other commitment. Passwords, verification codes, and Face ID remain user-controlled. Split tasks before authentication, pause the screen, and wait for the user's completion before resuming.

The agent receives iOS-specific guidance to scroll partially obscured targets into the unobstructed screen area before tapping, and to reconsider unchanged screens instead of repeating the same tap. This is model guidance, not a deterministic retry limit; verify the final screen independently.

The worker uses the existing PUA endpoint and session under PUA's cross-process operation lock. It does not install/start PUA or create a second session. Cleanup detaches the borrowed session; PUA reapplies its session settings on the next request. Do not run a separate Midscene CLI against the phone concurrently.

`timeout_seconds` is an integer from 10 to 600. A timeout kills the worker, but actions already sent may have taken effect. `midscene_failed` for an `act` is uncertain: inspect a fresh `pua_observe(mode="screenshot")` and continue only the remaining work. Do not replay the task or silently switch to another controller. A failed assertion also returns `midscene_failed`; it does not prove the condition holds.
