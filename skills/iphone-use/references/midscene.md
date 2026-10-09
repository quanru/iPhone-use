# Midscene control and ChatGPT authorization

Explicit device actions use the current chat model's decisions without a second model request. After separate ChatGPT consent, `act` and `assert` call real Midscene `aiAct` and `aiAssert` through an OAuth-authorized Responses adapter. Both paths reuse the existing PUA session and operation lock. No external provider configuration or API key is needed. Legacy midscene.json is ignored.

## Continue with ChatGPT

First read `pua_midscene(action="settings")`. The persistent mode defaults to `steps`; set `mode="steps"` for explicit actions/reports or `mode="ai"` for AI tasks only on user request. Settings work without Node, phone access or OAuth. Mode changes serialize with device operations. Authorization never changes the mode. Disabling retains authorization and reports; new installations and upgrades without an explicit preference use steps, never ai.

Only in ai mode, check auth_status and use act/assert after consent. In steps mode, do not invoke AI or initiate sign-in. In off mode, use original PUA controls.

| action | Extra fields | Result |
| --- | --- | --- |
| auth_status | none | Authorization status and pending login; no device required |
| auth_login | none | Opens **Continue with ChatGPT** in the system browser; returns a local launch URL |
| auth_cancel | none | Cancel pending consent; then auth_login can start a fresh attempt |
| auth_logout | none | Attempts revocation and removes local tokens; reports whether remote revocation was confirmed |
| models | none | Current account's available model catalog |
| act | text | Real aiAct, at most 6 planning cycles and a 180-second worker deadline |
| assert | text | Real aiAssert; a false condition returns an error and native assertion report |

The user completes OpenAI login and consent themselves. Do not inspect authentication pages, copy codes, read stored tokens, or use Codex/ChatGPT credential files. Sign-in expires after ten minutes. Await the user's completion, then check auth_status; a pending URL is not authorization. Failed or denied consent preserves the existing account. Credentials are owner-only files in `<state-dir>/chatgpt`, with serialized rotating-token refresh. This implementation supports one registered account per state directory; sign-out retains its registration for reauthorization.

ChatGPT plan usage needs separate permission, even inside ChatGPT. Requests use the account catalog's first visible GPT model and return its slug as `model`. This does not inherit the chat page's selected model or conversation history. Send all needed task context in `text`, including exact bundle IDs resolved through `pua_apps`. Review usage/access in ChatGPT Settings. Never silently fall back to an API key, another provider, or a second run after errors.

Use the same report_id for act/assert and explicit actions in one task. Bound each act to a concrete goal; inspect its result before requesting more. For authentication, request user takeover and resume only after fresh observation. AI input supports append-only, single-line `typeOnly`, without implicit submit; app launch requires a bundle ID. Raw PUA requests, URL launch, keyboard shortcuts and unlimited repeated gestures are excluded from the AI action space. Sending, purchasing and other externally consequential tasks still require the user's task authorization.

Reports from act/assert are native SDK AI reports. An assertion evaluating false is a failed check even if its internal evaluation task status is `finished`; use its output and the tool error. A timeout can leave a partial report and uncertain device state. Inspect before continuing, never replay. Tokens are never included in model prompts or report configuration. Report/model timing does not include all adapter telemetry yet.

Official protocol: [registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [preview constraints](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Install

Use Node.js 22.19+ (24 tested), then `npm ci --prefix <plugin-root>/server/midscene`. No model configuration file is required. Plugin updates may require reinstalling SDK dependencies.

## Action arguments

First obtain `pua_ready` with `ready=true`. Call `pua_midscene` with one action and exactly the fields below, plus an optional `report_id`:

| action | Fields | Behavior |
| --- | --- | --- |
| screenshot | none | Capture the current screen |
| tap | x, y | Tap once in iPhone points |
| swipe | x, y, end_x, end_y | One finger gesture from start to end, 500 ms |
| input | text | Append single-line text at current focus; no clear, automatic keyboard dismissal, or submit |
| home | none | Return to the Home screen |
| launch | text | Launch an installed app by bundle ID; no URL/deep link |
| record | text, passed | Record the host's evidence and boolean verdict; false produces an error and a failed report entry |

Example sequence (use the actual returned ID, not the placeholder):

```json
{"action":"screenshot"}
{"action":"launch","text":"com.apple.Preferences","report_id":"RETURNED_ID"}
{"action":"tap","x":150,"y":250,"report_id":"RETURNED_ID"}
{"action":"record","text":"Observed the expected page heading","passed":true,"report_id":"RETURNED_ID"}
```

The tap is an argument example, not a known target: choose coordinates from the actual screenshot. Convert screenshot pixels with `image.pixel_to_point`; coordinates must fit the current viewport. Inspect each resulting screenshot before choosing the next action. Scroll covered targets away from search bars or keyboards. Do not repeat unchanged taps.

Input does not check whether a focused field is secure. The host must inspect the screen, pause using `pua_screen`, and hand authentication to the user before entering passwords or verification codes. Authorized sending is a separate explicit action; never replay uncertain input or submission.

## Task reports

Omit report_id on the first call; keep its returned ID on later calls in the same task. IDs use 1–64 ASCII letters, digits, underscores or hyphens. A new task uses a new ID. The SDK writes native Action Space entries for Tap, Swipe, Input, Launch and IOSHomeButton, with parameters, measured duration and before/after captures. Screenshot and host verdict entries remain Log records. It appends these entries to one HTML report under the private state directory's midscene_run/report. Reuse requires the same state directory. The ID does not deduplicate or retry actions.

Each explicit-action response contains decision_source=chat_host, report_id, report, viewport and an image. The host's verdict is not an independent Midscene AI assertion. A failed action or host verdict returns midscene_failed with report/image evidence when available. Mutations are uncertain on failure; inspect current state before continuing. The 60-second worker timeout can leave a partial report. Preflight failures produce no execution. Ordinary PUA operations do not appear in Midscene reports.

Reports contain screenshots and task content. Keep them local unless the user authorizes sharing. Do not run an independent CLI against the same phone concurrently.

A returned `report` path is an actual report even when no AI inference was performed. Include its link in the final response; do not describe it as missing merely because aiAct/aiAssert was not used. Reports made by older plugin versions may contain only screenshot logs; those historical logs are not relabeled as native actions.
