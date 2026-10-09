// Separate authorized AI path. The no-model device worker stays available.
import { readFileSync, existsSync } from 'node:fs';
import { format } from 'node:util';
import { join } from 'node:path';
import { ChatGPTAuth, AuthError } from './chatgpt-auth.mjs';
import { createChatGPTClient } from './chatgpt-client.mjs';

process.umask(0o077);
console.log = (...args) => process.stderr.write(`${format(...args)}\n`);
console.info = console.log;
for (const key of Object.keys(process.env)) {
  if (key.startsWith('MIDSCENE_') || key.startsWith('OPENAI_')) delete process.env[key];
}
let device, agent, request, result = { ok: false }, screenshot, viewport;
let inferenceError;
const parent = process.ppid;
// Exit on parent loss rather than continuing to mutate an unowned device.
const watchdog = setInterval(() => { if (process.ppid !== parent) process.exit(1); }, 250);
watchdog.unref();
try {
  request = JSON.parse(readFileSync(0, 'utf8'));
  if (!['act', 'assert'].includes(request.action) || !/^[A-Za-z0-9_-]{1,64}$/.test(request.reportId) ||
      typeof request.args?.text !== 'string' || !request.args.text.trim() || request.args.text.length > 10000)
    throw new AuthError('invalid_ai_request');
  const auth = new ChatGPTAuth(join(process.cwd(), 'chatgpt'));
  const models = await auth.models();
  // Preserve the service's preferred ordering, limiting to the GPT protocol.
  const model = models.find(item => /^gpt-/.test(item.slug))?.slug;
  if (!model) throw new AuthError('no_compatible_model');
  result.model = model;
  const { IOSAgent, IOSDevice } = await import('@midscene/ios');
  device = new IOSDevice({ wdaHost: request.host, wdaPort: request.port,
    sessionId: request.sessionId, autoDismissKeyboard: false });
  async function guard() {
    if (!(await auth.status()).authorized) throw new AuthError('chatgpt_sign_in_required');
    const state = join(process.cwd(), 'screen-state.json');
    if (existsSync(state) && JSON.parse(readFileSync(state, 'utf8')).paused)
      throw new AuthError('preview_paused');
    const response = await fetch(`http://${request.host}:${request.port}/wda/locked`, { signal: AbortSignal.timeout(5000) });
    if ((await response.json()).value !== false) throw new AuthError('phone_locked');
  }
  const capture = device.screenshotBase64.bind(device);
  device.screenshotBase64 = async () => { await guard(); return capture(); };
  const actions = device.actionSpace.bind(device);
  const allowed = new Set(['Tap', 'Swipe', 'Scroll', 'Input', 'IOSHomeButton', 'Launch']);
  device.actionSpace = () => actions().filter(action => allowed.has(action.name)).map(action => ({
    ...action,
    description: action.name === 'Input' ? 'Append single-line text. Always use mode typeOnly. Never enter credentials or submit.' : action.description,
    call: async (param, context) => {
      await guard();
      if (action.name === 'Input' && (param.mode !== 'typeOnly' || /[\r\n\t]/.test(String(param.value)) || String(param.value).length > 10000))
        throw new AuthError('input_requires_single_line_typeOnly');
      if (action.name === 'Launch' && !/^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$/.test(param.uri))
        throw new AuthError('launch_requires_bundle_id');
      if (action.name === 'Swipe' && param.repeat !== undefined && param.repeat !== 1)
        throw new AuthError('unbounded_action');
      return action.call(param, context);
    },
  }));
  await device.connect();
  viewport = await device.size();
  agent = new IOSAgent(device, { generateReport: true, autoPrintReportMsg: false,
    reportFileName: `iphone-use-${request.reportId}`,
    reportAttributes: { 'data-group-id': `iphone-use-${request.reportId}` },
    cache: false, replanningCycleLimit: 6, waitAfterAction: 600,
    aiActContext: 'Only perform the requested task. If authentication, password, PIN, OTP, or biometric confirmation is required, stop and report failure for user takeover. Never invent credentials. Do not repeat a tap on an unchanged screen; move obscured targets into view. Input must use typeOnly and single-line text; no implicit submit.',
    modelConfig: { MIDSCENE_MODEL_NAME: model, MIDSCENE_MODEL_FAMILY: /^gpt-6/.test(model) ? 'gpt-6' : 'gpt-5',
      MIDSCENE_MODEL_API_KEY: 'oauth-managed-by-iphone-use', MIDSCENE_MODEL_BASE_URL: 'http://127.0.0.1:1',
      MIDSCENE_MODEL_TIMEOUT: 60000, MIDSCENE_MODEL_RETRY_COUNT: 0 },
    createOpenAIClient: createChatGPTClient(auth, { onError: error => { inferenceError = error instanceof AuthError ? error.code : 'chatgpt_inference_failed'; } }),
  });
  if (request.action === 'act') await agent.aiAct(request.args.text);
  else await agent.aiAssert(request.args.text);
  result = { ...result, ok: true, action_complete: true, decision_source: 'chatgpt_oauth' };
} catch (error) {
  let authError = error;
  for (let depth = 0; depth < 8 && authError && !(authError instanceof AuthError); depth++) authError = authError.cause;
  result.error = inferenceError ?? (authError instanceof AuthError ? authError.code :
    error.message?.startsWith('Assertion failed:') && !error.cause ? 'assertion_failed' : 'midscene_ai_failed');
} finally {
  if (device) {
    screenshot = await device.screenshotBase64().catch(() => undefined);
    viewport ??= await device.size().catch(() => undefined);
  }
  if (agent) {
    try { await agent.destroy(); result.report = agent.reportFile; }
    catch { result.ok = false; result.error = 'report_finalize_failed'; }
  } else if (device) await device.destroy().catch(() => {});
  if (screenshot && viewport) Object.assign(result, { screenshot, viewport });
  clearInterval(watchdog);
}
process.stdout.write(JSON.stringify(result), () => process.exit(result.ok ? 0 : 1));
