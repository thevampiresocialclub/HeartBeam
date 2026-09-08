// Optional developer proof. Use a synthetic project named "Waveform playback test".
// HEARTBEAM_PLAYWRIGHT can point to a bundled Playwright installation.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.HEARTBEAM_PLAYWRIGHT || 'playwright');
const root = path.resolve(process.argv[2]);
const manifest = path.join(root, 'project.json');
const saved = fs.readFileSync(manifest, 'utf8');
assert.equal(JSON.parse(saved).name, 'Waveform playback test', 'Use the disposable synthetic fixture only.');
const output = path.resolve(process.argv[3] || path.join(root, '..', 'browser-proof'));
fs.mkdirSync(output, {recursive:true});
const browser = await chromium.launch({channel:'chrome', headless:true});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors = [], checks = {};
page.on('pageerror', error=>errors.push(error.message));
const wave = page.getByRole('slider', {name:'Waveform song position', exact:true});
const read = ()=>wave.evaluate(el=>{
  const root=el.closest('.hb-editor'), scroll=el.closest('.hb-scroll');
  const video=root.querySelector('video');
  return {time:Number(root.dataset.clockMs),wave:Number(el.getAttribute('aria-valuenow')),
    ass:Number(root.dataset.assClockMs),field:Number(root.querySelector('.hb-seek').value)*1000,
    paused:root.querySelector('[data-act="play"]').getAttribute('aria-label')==='Play',
    source:root.dataset.sourceId,revision:Number(root.dataset.revision),
    zoom:Number(root.dataset.zoom),left:scroll.scrollLeft,viewport:scroll.clientWidth,
    full:scroll.querySelector('.hb-track').getBoundingClientRect().width,
    duration:Number(el.getAttribute('aria-valuemax')),video:video.currentTime,videoDuration:video.duration};
});
async function waitUntil(check) {
  for (let i=0;i<150;i++) { if (await check()) return; await page.waitForTimeout(50); }
  throw new Error('Browser state did not settle');
}
async function point(fraction,y=50) {
  await wave.scrollIntoViewIfNeeded(); const box=await wave.boundingBox();
  return {x:box.x+box.width*fraction,y:box.y+y};
}
async function click(fraction) { const p=await point(fraction); await page.mouse.click(p.x,p.y); await page.waitForTimeout(100); }
function synced(state) {
  assert.equal(state.wave,state.time); assert.equal(state.ass,state.time);
  assert.ok(Math.abs(state.field-state.time)<=6, JSON.stringify(state));
  if (Number.isFinite(state.videoDuration)) assert.ok(Math.abs(state.video-state.time/1000%state.videoDuration)<.15);
}
try {
  await page.goto(process.env.HEARTBEAM_URL || 'http://localhost:8505/');
  await page.getByRole('button',{name:'keyboard_double_arrow_right',exact:true}).click();
  await page.getByRole('textbox',{name:'Open project folder',exact:true}).fill(root);
  await page.getByRole('textbox',{name:'Open project folder',exact:true}).press('Enter');
  await page.getByRole('button',{name:'Open',exact:true}).click();
  await wave.waitFor({state:'visible'});
  await waitUntil(async()=>await wave.getAttribute('aria-disabled')==='false');
  const initial=await read();
  assert.equal(initial.source,'karaoke');
  await page.getByRole('spinbutton',{name:'Seek seconds',exact:true}).fill('6.1');
  await page.waitForTimeout(100);
  assert.equal((await read()).field,6100); // A draft is not overwritten while typing.
  await click(.35);
  checks.pausedClick=await read(); synced(checks.pausedClick);
  assert.ok(Math.abs(checks.pausedClick.time-2800)<20); assert.equal(checks.pausedClick.paused,true);
  let p=await point(.2); await page.mouse.move(p.x,p.y); await page.mouse.down();
  p=await point(.65); await page.mouse.move(p.x,p.y,{steps:12});
  checks.dragHeld=await read(); assert.ok(Math.abs(checks.dragHeld.time-5200)<20);
  await page.mouse.up(); await page.waitForTimeout(100);
  checks.pausedDrag=await read(); synced(checks.pausedDrag); assert.equal(checks.pausedDrag.paused,true);
  await click(.1); await page.getByRole('button',{name:'Play',exact:true}).click();
  await page.waitForTimeout(250);
  p=await point(.5); await page.mouse.move(p.x,p.y); await page.mouse.down();
  p=await point(.25); await page.mouse.move(p.x,p.y,{steps:10}); await page.mouse.up();
  checks.playingScrub=await read(); assert.equal(checks.playingScrub.paused,false);
  await page.waitForTimeout(350);
  checks.afterScrub=await read(); synced(checks.afterScrub);
  assert.ok(checks.afterScrub.time>checks.playingScrub.time+250);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await wave.press('Home'); await wave.press('ArrowRight'); await wave.press('Shift+ArrowRight');
  await page.waitForTimeout(100); checks.keyboard=await read(); assert.equal(checks.keyboard.time,1100);
  await page.getByRole('slider',{name:'Zoom',exact:true}).press('End');
  await page.getByRole('button',{name:'Play',exact:true}).click(); await page.waitForTimeout(700);
  checks.follow=await read();
  const x=checks.follow.time/checks.follow.duration*checks.follow.full-checks.follow.left;
  assert.ok(checks.follow.left>0 && x>=0 && x<=checks.follow.viewport, JSON.stringify(checks.follow));
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('checkbox',{name:'Follow playback',exact:true}).uncheck();
  await wave.press('Home'); const fixed=await read();
  await page.getByRole('button',{name:'Play',exact:true}).click(); await page.waitForTimeout(700);
  assert.equal((await read()).left,fixed.left);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('slider',{name:'Zoom',exact:true}).press('Home');
  await page.getByRole('checkbox',{name:'Follow playback',exact:true}).check();
  await click(.4); const sourceTime=(await read()).time;
  for (const source of ['original','mix','karaoke']) {
    await page.getByRole('combobox',{name:'Listen to',exact:true}).selectOption(source);
    await waitUntil(async()=>(await read()).source===source && await wave.getAttribute('aria-disabled')==='false');
    const state=await read(); synced(state); assert.ok(Math.abs(state.time-sourceTime)<20);
  }
  checks.sources=await read(); assert.equal(checks.sources.revision,initial.revision);
  assert.equal(fs.readFileSync(manifest,'utf8'),saved);
  // The lower lane remains a timing editor, with exactly one undoable command.
  await page.getByRole('button',{name:'Bright',exact:true}).click(); await page.waitForTimeout(200);
  const before=await read(); checks.beforeWordEdit=before; p=await point(.1,122);
  await page.mouse.move(p.x,p.y); await page.mouse.down(); await page.mouse.move(p.x+4,p.y,{steps:4}); await page.mouse.up();
  await waitUntil(async()=>(await read()).revision===before.revision+1);
  checks.afterWordEdit=await read(); assert.ok(Math.abs(checks.afterWordEdit.time-before.time)<20, JSON.stringify(checks.afterWordEdit));
  await page.locator('.hb-preview-head').locator('..').locator('[data-act="undo"]').click();
  await waitUntil(async()=>(await read()).revision===before.revision+2);
  checks.wordEditUndo=await read();
  assert.ok(Math.abs(checks.wordEditUndo.time-before.time)<20, JSON.stringify(checks.wordEditUndo));
  await page.getByRole('button',{name:'Play',exact:true}).click();
  const playingBefore=await read(); p=await point(.1,122);
  await page.mouse.move(p.x,p.y); await page.mouse.down(); await page.mouse.move(p.x+4,p.y,{steps:4}); await page.mouse.up();
  await waitUntil(async()=>(await read()).revision===playingBefore.revision+1);
  checks.editWhilePlaying=await read();
  assert.equal(checks.editWhilePlaying.paused,false); assert.ok(checks.editWhilePlaying.time>playingBefore.time);
  await page.locator('.hb-preview-head').locator('..').locator('[data-act="undo"]').click();
  await waitUntil(async()=>(await read()).revision===playingBefore.revision+2);
  checks.undoWhilePlaying=await read();
  assert.equal(checks.undoWhilePlaying.paused,false); assert.ok(checks.undoWhilePlaying.time>checks.editWhilePlaying.time);
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('button',{name:'Loop selection',exact:true}).click();
  await click(.8); checks.seekOutsideLoop=await read();
  assert.ok(Math.abs(checks.seekOutsideLoop.time-6400)<20);
  assert.equal(await page.getByRole('button',{name:'Loop selection',exact:true}).getAttribute('aria-pressed'),'false');
  await page.getByRole('button',{name:'2 · Review timing',exact:true}).click();
  await waitUntil(async()=>(await read()).source==='original' && await wave.getAttribute('aria-disabled')==='false');
  await click(.6); checks.review=await read(); synced(checks.review);
  assert.ok(Math.abs(checks.review.time-4800)<20);
  assert.equal(await wave.count(),1);
  p=await point(.5); await page.mouse.move(p.x,p.y); await page.mouse.wheel(0,500);
  await page.waitForTimeout(150);
  const header=await page.locator('.hb-preview-head').boundingBox();
  const monitor=await page.locator('.st-key-hb_monitor').boundingBox();
  assert.ok(header.y>=monitor.y-1 && header.y+header.height<=monitor.y+monitor.height);
  checks.playRemainsVisible={header,monitor};
  await page.screenshot({path:path.join(output,'waveform-review.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify({passed:true,checks:Object.keys(checks),output}));
} catch (error) {
  fs.writeFileSync(path.join(output,'failure.txt'),`${error.stack}\n${await page.locator('body').innerText()}\n${JSON.stringify(errors)}`);
  await page.screenshot({path:path.join(output,'failure.png')});
  throw error;
} finally {
  // Release the app's single-writer lease before disconnecting the browser.
  const close=page.getByRole('button',{name:'Close',exact:true});
  if (await close.isVisible()) { await close.click(); await page.waitForTimeout(200); }
  await browser.close();
}
