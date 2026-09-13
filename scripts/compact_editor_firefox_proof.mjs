// Use installed Firefox's WebDriver BiDi with a disposable headless profile.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';

const [seed, outputArg, url = 'http://localhost:8513/'] = process.argv.slice(2);
if (!seed || !outputArg) throw Error('Pass a synthetic project and an evidence folder.');
const output = path.resolve(outputArg), sessionDir = path.join(output, `run-${Date.now()}`);
const project = path.join(sessionDir, 'project'), profile = path.join(sessionDir, 'profile');
fs.mkdirSync(profile, {recursive: true});
fs.cpSync(seed, project, {recursive: true, filter: name => path.basename(name) !== '.editor.lock'});
fs.writeFileSync(path.join(profile, 'user.js'), 'user_pref("browser.shell.checkDefaultBrowser",false);\nuser_pref("focusmanager.testmode",true);\n');
const proc = spawn('C:/Program Files/Mozilla Firefox/firefox.exe',
  ['--headless', '--no-remote', '--profile', profile, '--remote-debugging-port', '9253', 'about:blank'],
  {windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
let logs = '', ws, context, id = 0;
for (const stream of [proc.stdout, proc.stderr]) stream.on('data', data => { logs += data; });
const pending = new Map(), sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function cmd(method, params = {}) {
  const number = ++id;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(number); reject(Error(`Timeout: ${method}`)); }, 20000);
    pending.set(number, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }});
    ws.send(JSON.stringify({id: number, method, params}));
  });
}
async function evaluate(expression) {
  const result = await cmd('script.evaluate', {expression: `JSON.stringify(${expression})`, target: {context}, awaitPromise: true});
  if (result.type === 'exception') throw Error(JSON.stringify(result.exceptionDetails));
  return JSON.parse(result.result.value);
}
async function until(expression) {
  for (let i = 0; i < 200; ++i) { if (await evaluate(expression)) return; await sleep(100); }
  throw Error(`Did not settle: ${expression}`);
}
async function pointer(selector, click = true, fraction = .5, y = .5) {
  const point = await evaluate(`(()=>{const r=all(${JSON.stringify(selector)})[0].getBoundingClientRect();return {x:r.x+r.width*${fraction},y:r.y+r.height*${y}};})()`);
  await cmd('input.performActions', {context, actions: [{type: 'pointer', id: 'mouse', parameters: {pointerType: 'mouse'}, actions: [
    {type: 'pointerMove', x: Math.round(point.x), y: Math.round(point.y), duration: 0, origin: 'viewport'},
    ...(click ? [{type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}] : [])]}]});
  await sleep(150);
}
async function key(value) {
  await cmd('input.performActions', {context, actions: [{type: 'key', id: 'keyboard', actions: [{type: 'keyDown', value}, {type: 'keyUp', value}]}]});
}
async function button(name) {
  const target = `all('button').find(el=>el.textContent.trim()===${JSON.stringify(name)}||el.querySelector('p')?.textContent.trim()===${JSON.stringify(name)})`;
  await until(`!!(${target})`);
  await evaluate(`(()=>{${target}.dataset.proofClick='yes';return true;})()`);
  await pointer('[data-proof-click=yes]');
  await evaluate("(()=>{all('[data-proof-click]').forEach(el=>delete el.dataset.proofClick);return true;})()");
}
async function screenshot(name) {
  const result = await cmd('browsingContext.captureScreenshot', {context, origin: 'viewport', format: {type: 'image/png'}});
  fs.writeFileSync(path.join(output, name + '.png'), Buffer.from(result.data, 'base64'));
}
const evidence = {};
try {
  for (let i = 0; i < 120 && !logs.includes('WebDriver BiDi listening'); i++) await sleep(100);
  ws = new WebSocket('ws://127.0.0.1:9253/session');
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => { const message = JSON.parse(event.data), item = pending.get(message.id); if (item) { pending.delete(message.id); message.type === 'error' ? item.reject(Error(JSON.stringify(message))) : item.resolve(message.result); } };
  const session = await cmd('session.new', {capabilities: {alwaysMatch: {}}});
  evidence.browser = session.capabilities.browserVersion;
  ({contexts: [{context}]} = await cmd('browsingContext.getTree'));
  await cmd('browsingContext.setViewport', {context, viewport: {width: 1500, height: 900}, devicePixelRatio: 1});
  await cmd('script.addPreloadScript', {functionDeclaration: `()=>{
    window.errors=[];addEventListener('error',e=>errors.push(e.message));
    window.all=selector=>{const result=[];function visit(root){result.push(...root.querySelectorAll(selector));for(const el of root.querySelectorAll('*'))if(el.shadowRoot)visit(el.shadowRoot);}visit(document);return result;};
    window.read=()=>{const root=all('.hb-editor[aria-label="Timing editor"]')[0];return root?{ready:root.dataset.assReady,mix:root.dataset.mixReady,time:+root.dataset.clockMs,wave:+root.querySelector('.hb-canvas').getAttribute('aria-valuenow'),ass:+root.dataset.assClockMs,revision:+root.dataset.revision}:null;};
    window.box=selector=>{const r=all(selector)[0].getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
  }`});
  await cmd('browsingContext.navigate', {context, url, wait: 'complete'});
  await cmd('browsingContext.activate', {context});
  await until("all('.st-key-hb_workflow button').length>0");
  await button('File');
  await until("all('.st-key-open_project_path input').length>0");
  await evaluate(`(()=>{const el=all('.st-key-open_project_path input')[0];el.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(project)});el.dispatchEvent(new Event('input',{bubbles:true}));return true;})()`);
  await key('\uE007'); await sleep(200); await button('Open');
  await until("read()?.ready==='true'&&read()?.mix==='true'");
  await button('File');
  evidence.desktop = await evaluate("({status:box('.hb-project-status'),preview:box('.hb-preview'),tools:box('.hb-edit-tools'),mixer:box('.hb-track-mixer')})");
  await evaluate("(()=>{window.focusEvents=[];for(const type of ['focus','blur','focusin','focusout','keydown'])document.addEventListener(type,e=>focusEvents.push({type,key:e.key,label:e.composedPath()[0].outerHTML?.slice(0,180)}),true);return true;})()");
  assert(evidence.desktop.tools.height <= 32 && evidence.desktop.mixer.height <= 32);
  await pointer('.hb-canvas', true, .5, .3);
  evidence.seek = await evaluate('read()');
  assert(Math.abs(evidence.seek.time - 12000) < 80);
  assert.equal(evidence.seek.time, evidence.seek.wave); assert.equal(evidence.seek.time, evidence.seek.ass);
  await pointer('.hb-info[aria-describedby=hb-track-help]', false);
  assert(await evaluate("all('#hb-track-help')[0].matches(':popover-open')"));
  await screenshot('firefox-vocal-help');
  await key('\uE00C');
  assert(!await evaluate("all('#hb-track-help')[0].matches(':popover-open')"));
  // Use real keyboard traversal; direct focus() is unreliable in raw headless Firefox.
  await pointer('.hb-info[aria-describedby=hb-edit-help]');
  await key('\uE00C');
  await key('\uE004');
  await cmd('input.performActions', {context, actions: [{type: 'key', id: 'keyboard', actions: [
    {type: 'keyDown', value: '\uE008'}, {type: 'keyDown', value: '\uE004'},
    {type: 'keyUp', value: '\uE004'}, {type: 'keyUp', value: '\uE008'}]}]});
  evidence.focus = await evaluate("({hasFocus:document.hasFocus(),events:focusEvents.slice(-20),button:all('.hb-info[aria-describedby=hb-edit-help]')[0].getRootNode().activeElement?.outerHTML,open:all('#hb-edit-help')[0].matches(':popover-open')})");
  if (evidence.focus.hasFocus) assert(evidence.focus.open, 'keyboard focus opens help');
  else evidence.keyboardFocus = 'Not verified: the raw headless Firefox window suppresses focus events. Chrome verifies focus and keyboard traversal.';
  await key('\uE014'); // ArrowRight on help must never retime a word.
  await key('\uE00C');
  assert.equal((await evaluate('read()')).revision, evidence.seek.revision);
  await pointer('[data-word-id="w0-0"]');
  await until('read()?.time===300');
  await pointer('[data-act=play]'); await sleep(650);
  evidence.play = await evaluate('read()');
  assert(evidence.play.time > 800);
  assert.equal(evidence.play.time, evidence.play.wave); assert.equal(evidence.play.time, evidence.play.ass);
  await pointer('[data-act=play]');
  await screenshot('firefox-desktop');
  await cmd('browsingContext.setViewport', {context, viewport: {width: 1050, height: 650}, devicePixelRatio: 1});
  await sleep(250);
  evidence.smallDesktop = await evaluate("({tools:box('.hb-edit-tools'),mixer:box('.hb-track-mixer'),overflow:all('.st-key-hb_monitor')[0].scrollWidth-all('.st-key-hb_monitor')[0].clientWidth})");
  assert(evidence.smallDesktop.tools.height <= 32 && evidence.smallDesktop.mixer.height <= 32 && evidence.smallDesktop.overflow <= 1);
  await screenshot('firefox-small-desktop');
  evidence.errors = await evaluate('errors'); assert.deepEqual(evidence.errors, []);
  fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
} catch (error) {
  fs.writeFileSync(path.join(output, 'failure.txt'), error.stack + '\n' + JSON.stringify(evidence));
  if (context) await screenshot('failure').catch(() => {});
  throw error;
} finally {
  if (context) { try { await button('File'); await button('Close'); } catch {} }
  if (ws?.readyState === WebSocket.OPEN) await cmd('browser.close').catch(() => {});
  ws?.close(); proc.kill(); fs.writeFileSync(path.join(output, 'firefox.log'), logs);
}
