# Default host-driven Midscene control

The current chat model reads screenshots, selects explicit actions, and verifies results. `pua_midscene` executes these actions through the Midscene iOS SDK using the existing PUA connection and operation lock. It never calls aiAct, aiQuery, aiAssert, or an external model. No API key, provider, model selection, or extra sign-in is needed. Legacy midscene.json model configuration is ignored; remove its env block if migrating.

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

Omit report_id on the first call; keep its returned ID on later calls in the same task. IDs use 1–64 ASCII letters, digits, underscores or hyphens. A new task uses a new ID. The SDK appends before/after captures and host verdicts to one HTML report under the private state directory's midscene_run/report. Reuse requires the same state directory. The ID does not deduplicate or retry actions.

Each response contains decision_source=chat_host, report_id, report, viewport and an image. The host's verdict is not an independent Midscene AI assertion. A failed action or host verdict returns midscene_failed with report/image evidence when available. Mutations are uncertain on failure; inspect current state before continuing. The 60-second worker timeout can leave a partial report. Preflight failures produce no execution. Ordinary PUA operations do not appear in Midscene reports.

Reports contain screenshots and task content. Keep them local unless the user authorizes sharing. Do not run an independent CLI against the same phone concurrently.
