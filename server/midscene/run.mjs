// One invocation per locked Runtime call; stdout is exclusively the JSON result.
import { readFileSync } from 'node:fs';
import { format } from 'node:util';

console.log = (...args) => process.stderr.write(`${format(...args)}\n`);
console.info = console.log;

let device;
let agent;
let result;
let exitCode = 0;
try {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(request.reportId ?? '')) throw new Error('Invalid report ID');
  const reportFileName = `iphone-use-${request.reportId}`;
  const { IOSDevice, IOSAgent } = await import('@midscene/ios');
  device = new IOSDevice({
    wdaHost: request.host,
    wdaPort: request.port,
    sessionId: request.sessionId,
  });
  await device.connect();
  agent = new IOSAgent(device, {
    reportFileName,
    reportAttributes: { 'data-group-id': reportFileName },
    aiContexts: {
      aiAct: 'iOS may show list rows through translucent fixed search bars, tab bars, or the keyboard. '
        + 'A visible label behind an overlay is not tappable. Scroll the list to move the entire target '
        + 'into the unobstructed middle of the screen before tapping. Scroll direction down reveals '
        + 'items farther down the list (content moves upward); up reveals earlier items. '
        + 'If a tap leaves the screen unchanged, inspect for an overlay and change the approach; '
        + 'do not keep tapping the same obstructed target. Confirm the destination screen before finishing.',
    },
  });
  let value;
  if (request.action === 'act') value = await agent.aiAct(request.prompt);
  else if (request.action === 'query') value = await agent.aiQuery(request.prompt);
  else if (request.action === 'assert') value = await agent.aiAssert(request.prompt);
  else throw new Error('Unsupported action');
  result = { ok: true, action: request.action, result: value ?? null, report: agent.reportFile ?? null };
} catch {
  result = { ok: false };
  exitCode = 1;
} finally {
  // The SDK detaches borrowed sessions without deleting them.
  if (agent) await agent.destroy().catch(() => {});
  else if (device) await device.destroy().catch(() => {});
  if (agent) result.report = agent.reportFile ?? null;
}
process.stdout.write(JSON.stringify(result), () => process.exit(exitCode));
