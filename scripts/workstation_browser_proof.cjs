// Development-only browser proof. NODE_PATH may point to the bundled Playwright.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const [project, output, url = 'http://localhost:8504/'] = process.argv.slice(2);
  if (!project || !output) throw new Error('Pass a proof project and an evidence folder.');
  fs.mkdirSync(output, {recursive: true});
  const copy = path.join(output, `session-${Date.now()}`);
  fs.cpSync(project, copy, {recursive: true, filter: source => path.basename(source) !== '.editor.lock'});
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  const page = await browser.newPage({viewport: {width: 1500, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const AudioContext = window.AudioContext;
    window.hbProofClocks = [];
    window.AudioContext = class extends AudioContext {
      constructor(...args) { super(...args); window.hbProofClocks.push(this); }
    };
  });
  try {
    await page.goto(url);
    await page.getByRole('button', {name: 'keyboard_double_arrow_right', exact: true}).click();
    await page.getByRole('textbox', {name: 'Open project folder', exact: true}).fill(copy);
    await page.getByRole('textbox', {name: 'Open project folder', exact: true}).press('Tab');
    await page.waitForTimeout(400);
    await page.getByRole('button', {name: 'Open', exact: true}).click();
    await page.getByRole('heading', {name: 'Video preview', exact: true}).waitFor();
    const collapse = page.locator('[data-testid="stSidebarCollapseButton"] button');
    if (await collapse.isVisible()) await collapse.click();
    const monitor = page.locator('.hb-editor[aria-label="Timing editor"]');
    const clock = () => monitor.getAttribute('data-clock-ms').then(Number);
    const sameMonitor = await monitor.elementHandle();
    const monitorBox = await page.locator('.st-key-hb_monitor').boundingBox();
    const inspectorBox = await page.locator('.st-key-hb_inspector').boundingBox();
    assert(inspectorBox.x > monitorBox.x + monitorBox.width - 1, 'inspector is to the right');
    assert(Math.abs(inspectorBox.y - monitorBox.y) < 5, 'panes share their top edge');
    assert.equal(await page.getByRole('button', {name: 'Generate karaoke', exact: true}).count(), 0);
    await page.getByRole('button', {name: 'Play', exact: true}).waitFor();
    await page.waitForFunction(() => window.hbProofClocks.length === 1);
    await page.getByRole('button', {name: 'Play', exact: true}).click();
    await page.waitForTimeout(1500);
    const played = await clock();
    assert(played > 1000 && played < 3000, `playback advanced: ${played}`);
    assert.equal(await page.getByRole('button', {name: 'Pause', exact: true}).count(), 1);
    assert.equal(await monitor.getAttribute('data-ass-ready'), 'true');
    assert(await page.locator('.hb-live-controls .hb-word.singing').count() > 0);
    const backgroundTime = await page.locator('video.hb-background').evaluate(el => el.currentTime);
    assert(backgroundTime > .1, 'background follows the song clock');
    await page.getByRole('button', {name: 'Pause', exact: true}).click();
    const paused = await clock();
    await page.waitForTimeout(200);
    assert(Math.abs(await clock() - paused) < 50);
    await page.screenshot({path: path.join(output, 'workstation-desktop.png')});
    const beforeWave = await page.locator('.hb-canvas').evaluate(el => el.toDataURL());
    const beforePreview = await page.locator('.hb-ass').evaluate(el => el.toDataURL());
    await page.getByRole('button', {name: 'Next lyric', exact: true}).click();
    await page.waitForTimeout(400);
    assert(await clock() >= 4000, 'lyric navigation seeks both views');
    assert.notEqual(await page.locator('.hb-canvas').evaluate(el => el.toDataURL()), beforeWave);
    assert.notEqual(await page.locator('.hb-ass').evaluate(el => el.toDataURL()), beforePreview);
    // Applying a right-pane form must keep the existing AudioContext and monitor.
    await page.getByRole('button', {name: 'Play', exact: true}).click();
    await page.getByRole('spinbutton', {name: 'Lyric font size', exact: true}).fill('104');
    await page.getByRole('button', {name: 'Apply lyric appearance', exact: true}).click();
    await page.waitForTimeout(700);
    assert(await sameMonitor.evaluate(el => el.isConnected));
    assert.equal(await page.evaluate(() => window.hbProofClocks.length), 1);
    const afterEdit = await clock();
    assert(afterEdit > 4000 && afterEdit < 8000, 'playback continues during appearance edits');
    await page.getByRole('button', {name: 'Pause', exact: true}).click();
    const scrolled = await page.locator('.st-key-hb_inspector').evaluate(el => el.scrollTop);
    assert(scrolled > 0, 'inspector scrolls separately');
    assert((await page.getByRole('button', {name: 'Play', exact: true}).boundingBox()).y < 300);
    await page.getByRole('button', {name: 'Bright', exact: true}).click();
    await page.waitForTimeout(500);
    assert(Math.abs(await clock() - 500) < 50, 'right-pane word click seeks the shared player');
    await page.getByRole('tab', {name: 'Vocals', exact: true}).click();
    await page.locator('.hb-vocal-level').press('End');
    await page.waitForTimeout(600);
    assert.equal(await page.locator('.hb-vocal-level').inputValue(), '100');
    assert.equal(await page.evaluate(() => window.hbProofClocks.length), 1);
    await page.getByRole('tab', {name: 'Lyrics', exact: true}).click();
    await page.getByRole('textbox', {name: 'Edit lyrics', exact: true}).waitFor();
    await page.getByRole('button', {name: '1 · Separate audio', exact: true}).click();
    await page.getByRole('button', {name: 'Save project and edit video', exact: true}).waitFor();
    await page.waitForTimeout(200);
    assert(await page.evaluate(() => window.hbProofClocks.every(c => c.state === 'closed')));
    await page.getByRole('button', {name: '2 · Edit video', exact: true}).click();
    await page.getByRole('button', {name: 'Play', exact: true}).waitFor();
    assert.equal(await monitor.count(), 1);
    assert.equal(await page.locator('.hb-inspector-host .hb-live-controls').count(), 1);
    await page.setViewportSize({width: 760, height: 1000});
    await page.waitForTimeout(300);
    const smallLeft = await page.locator('.st-key-hb_monitor').boundingBox();
    const smallRight = await page.locator('.st-key-hb_inspector').boundingBox();
    assert(smallRight.y > smallLeft.y, 'narrow layout stacks without squeezed controls');
    await page.screenshot({path: path.join(output, 'workstation-narrow.png')});
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'browser-evidence.json'), JSON.stringify({
      monitorBox, inspectorBox, played_ms: played, paused_ms: paused,
      after_appearance_edit_ms: afterEdit,
      background_seconds: backgroundTime, independent_scroll: scrolled,
      errors, result: 'passed'
    }, null, 2));
    console.log('Workstation browser proof passed.');
  } catch (error) {
    await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    throw error;
  } finally {
    const close = page.getByRole('button', {name: 'Close', exact: true});
    if (await close.count()) {
      if (!await close.isVisible()) await page.getByRole('button', {name: 'keyboard_double_arrow_right', exact: true}).click().catch(() => {});
      await close.click({timeout: 1000}).catch(() => {});
    }
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
