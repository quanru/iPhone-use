// Host decides from screenshots. This worker executes one explicit device action;
// it never calls aiAct/aiQuery/aiAssert or an external model.
import { readFileSync } from 'node:fs';
import { format } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';

console.log = (...args) => process.stderr.write(`${format(...args)}\n`);
console.info = console.log;
let device;
let agent;
let screenshot;
let viewport;
let result;
let exitCode = 0;
let action;
try {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  action = request.action;
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(request.reportId ?? '')) throw new Error('Invalid report ID');
  const reportFileName = `iphone-use-${request.reportId}`;
  const { IOSDevice, IOSAgent } = await import('@midscene/ios');
  device = new IOSDevice({ wdaHost: request.host, wdaPort: request.port,
    sessionId: request.sessionId, autoDismissKeyboard: false });
  await device.connect();
  agent = new IOSAgent(device, {
    reportFileName,
    reportAttributes: { 'data-group-id': reportFileName },
    modelConfig: {},
    createOpenAIClient: () => { throw new Error('Host-driven mode does not call models'); },
  });
  viewport = await device.size();
  const args = request.args ?? {};
  const point = (x, y) => {
    if (![x, y].every(Number.isFinite) || x < 0 || y < 0 || x >= viewport.width || y >= viewport.height)
      throw new Error('Point outside viewport');
    return { x, y };
  };
  // Capture before dispatch: a failed initial capture must not execute an action.
  screenshot = await device.screenshotBase64();
  await agent.recordToReport(`Before ${action}`, { screenshotBase64: screenshot,
    content: JSON.stringify({ decision_source: 'chat_host', action, args }) });
  // Do not return this pre-action frame as the resulting screen if dispatch fails.
  screenshot = undefined;
  if (action === 'tap') await device.tapPoint(point(args.x, args.y));
  else if (action === 'swipe') await device.swipePoint(point(args.x, args.y), point(args.end_x, args.end_y), 500);
  else if (action === 'input') await device.typeText(args.text, { autoDismissKeyboard: false });
  else if (action === 'home') await device.home();
  else if (action === 'launch') await device.launch(args.text);
  else if (!['screenshot', 'record'].includes(action)) throw new Error('Unsupported action');
  // Dispatch completion can precede iOS navigation animation; never retry it.
  if (['tap', 'swipe', 'input', 'home', 'launch'].includes(action)) await delay(600);
  screenshot = await device.screenshotBase64();
  viewport = await device.size();
  if (action === 'record' && args.passed === false) {
    await agent.recordErrorToReport('Host verification failed', {
      error: new Error('Host reported the condition was not met'), content: args.text, screenshotBase64: screenshot,
    });
    result = { ok: false };
    exitCode = 1;
  } else {
    await agent.recordToReport(action === 'record' ? 'Host verification passed' : `After ${action}`, {
      screenshotBase64: screenshot, content: action === 'record' ? args.text : 'Command completed; host must inspect the returned screen.',
    });
    result = { ok: true, action, action_complete: true, decision_source: 'chat_host' };
  }
} catch {
  result = { ok: false };
  exitCode = 1;
  if (agent) {
    // Best effort, fresh capture only. Never repeat the failed device action.
    screenshot = await device.screenshotBase64().catch(() => undefined);
    if (screenshot) await agent.recordErrorToReport(`Failed ${action}`, {
      error: new Error('Device action or capture failed; inspect state before continuing'), screenshotBase64: screenshot,
    }).catch(() => {});
  }
} finally {
  if (agent) {
    try { await agent.destroy(); } catch { result.ok = false; exitCode = 1; }
    result.report = agent.reportFile ?? null;
  } else if (device) await device.destroy().catch(() => {});
  if (screenshot && viewport) Object.assign(result, { screenshot, viewport });
}
process.stdout.write(JSON.stringify(result), () => process.exit(exitCode));
