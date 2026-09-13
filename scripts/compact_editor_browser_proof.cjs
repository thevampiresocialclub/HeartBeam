// Development-only acceptance proof; pass the synthetic seed and evidence folder.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const [seed, output, url = 'http://localhost:8513/'] = process.argv.slice(2);
  if (!seed || !output) throw Error('Pass a synthetic project and an evidence folder.');
  fs.mkdirSync(output, {recursive: true});
  const project = path.join(output, `session-${Date.now()}`);
  fs.cpSync(seed, project, {recursive: true, filter: name => path.basename(name) !== '.editor.lock'});
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  const page = await browser.newPage({viewport: {width: 1500, height: 900}});
  const errors = [], evidence = {sizes: []};
  page.on('pageerror', error => errors.push(error.message));
  const monitor = page.locator('.hb-editor[aria-label="Timing editor"]');
  const clock = async () => Number(await monitor.getAttribute('data-clock-ms'));
  const revision = async () => Number(await monitor.getAttribute('data-revision'));
  const menu = page.getByRole('button', {name: 'File', exact: true});
  async function closeMenu() {
    if (await page.getByRole('button', {name: 'Close', exact: true}).isVisible()) await menu.click();
  }
  async function measure(width, height) {
    await page.setViewportSize({width, height});
    await page.waitForTimeout(300);
    const boxes = {width, height};
    for (const [name, selector] of Object.entries({status: '.hb-project-status',
      monitor: '.st-key-hb_monitor', inspector: '.st-key-hb_inspector', settings: '.st-key-hb_settings',
      preview: '.hb-preview', mixer: '.hb-track-mixer', tools: '.hb-edit-tools',
      waveform: '.hb-canvas', lyrics: '.hb-live-controls .hb-lines', workflow: '.st-key-hb_workflow'}))
      boxes[name] = await page.locator(selector).boundingBox();
    boxes.overflow = await page.locator('.st-key-hb_monitor').evaluate(el => el.scrollWidth - el.clientWidth);
    boxes.pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert(boxes.overflow <= 1 && boxes.pageOverflow <= 1, `no horizontal clipping at ${width}: ${JSON.stringify(boxes)}`);
    assert(Math.abs(boxes.preview.width / boxes.preview.height - 16 / 9) < .01);
    assert.equal(Math.round(boxes.lyrics.height), 84);
    if (width >= 1000) {
      assert(boxes.tools.height <= 32, `one editing row at ${width}: ${boxes.tools.height}`);
      assert(boxes.mixer.height <= 32, `one vocal row at ${width}`);
      assert(boxes.monitor.y <= 100, `compact project status at ${width}: ${boxes.monitor.y}`);
      assert(Math.abs(boxes.inspector.y - boxes.monitor.y) < 2);
      assert(boxes.tools.y + boxes.tools.height <= height, 'editing controls remain visible');
      const deploy = await page.getByRole('button', {name: 'Deploy', exact: true}).boundingBox();
      assert(boxes.workflow.x + boxes.workflow.width < deploy.x, 'navigation clears Deploy');
    } else assert(boxes.inspector.y > boxes.monitor.y, 'narrow panes stack');
    await page.screenshot({path: path.join(output, `${width}x${height}.png`)});
    evidence.sizes.push(boxes);
  }
  try {
    await page.goto(url);
    await menu.click();
    await page.getByRole('textbox', {name: 'Open project folder', exact: true}).fill(project);
    await page.getByRole('button', {name: 'Open', exact: true}).click();
    await page.locator('.hb-editor[data-mix-ready="true"][data-ass-ready="true"]').waitFor();
    await closeMenu();
    const before = await revision();
    await page.getByRole('button', {name: 'Follow', exact: true}).click();
    await page.waitForTimeout(250);
    assert(Math.abs(await clock() - 300) < 70);
    for (const [width, height] of [[1500, 900], [1280, 720], [1050, 650], [760, 900], [390, 844]])
      await measure(width, height);
    await page.setViewportSize({width: 1500, height: 900});
    await page.waitForTimeout(300);
    const initialPreview = await page.locator('.hb-preview').boundingBox();
    const help = page.getByRole('button', {name: 'About vocal levels', exact: true});
    await help.hover();
    assert(await page.locator('#hb-track-help').isVisible(), 'hover explains levels');
    const tooltip = await page.locator('#hb-track-help').boundingBox();
    assert(tooltip.x >= 0 && tooltip.y >= 0 && tooltip.y + tooltip.height <= 900, 'tooltip fits viewport');
    await page.screenshot({path: path.join(output, 'vocal-help.png')});
    await help.focus();
    await help.press('ArrowRight');
    assert.equal(await revision(), before, 'help keys never nudge selected words');
    await help.press('Escape');
    assert(!await page.locator('#hb-track-help').isVisible(), 'Escape dismisses help');
    await help.click();
    assert(await page.locator('#hb-track-help').isVisible(), 'tap opens help');
    await help.click();
    assert(!await page.locator('#hb-track-help').isVisible(), 'tap again dismisses help');
    const shortcuts = page.getByRole('button', {name: 'Editing controls and shortcuts', exact: true});
    await shortcuts.focus();
    assert(await page.locator('#hb-edit-help').isVisible(), 'keyboard focus explains toolbar');
    assert.deepEqual(await page.locator('.hb-preview').boundingBox(), initialPreview, 'help does not resize preview');
    await shortcuts.press('Escape');
    await shortcuts.press('Tab');
    await page.keyboard.press('Shift+Tab');
    assert(await page.locator('#hb-edit-help').isVisible(), 'Tab navigation opens help');
    await page.keyboard.press('Escape');
    const wave = await page.locator('.hb-canvas').boundingBox();
    await page.locator('.hb-canvas').click({position: {x: wave.width / 2, y: 35}});
    assert(Math.abs(await clock() - 12000) < 90);
    await page.getByRole('spinbutton', {name: 'Seek seconds', exact: true}).fill('2');
    await page.getByRole('button', {name: 'Seek', exact: true}).click();
    assert(Math.abs(await clock() - 2000) < 70);
    await page.getByRole('button', {name: 'Follow', exact: true}).click();
    await page.waitForTimeout(200);
    // Original playback loops the word; the mix can use the selected lyric region.
    await page.locator('.hb-source').selectOption('original');
    await page.waitForTimeout(300);
    await page.getByRole('button', {name: 'Loop selection', exact: true}).click();
    await page.getByRole('button', {name: 'Play', exact: true}).click();
    await page.waitForTimeout(1100);
    assert(await clock() < 950, 'loop repeats selected word');
    await page.getByRole('button', {name: 'Pause', exact: true}).click();
    await page.getByRole('button', {name: 'Loop selection', exact: true}).click();
    const lead = page.getByRole('spinbutton', {name: 'Lead vocals percent', exact: true});
    await lead.fill('5'); await lead.press('Enter');
    await page.waitForFunction(() => {
      const visit = root => [...root.querySelectorAll('*')].some(el =>
        el.matches?.('.hb-editor[data-command-state="ready"][data-revision="1"]') || el.shadowRoot && visit(el.shadowRoot));
      return visit(document);
    });
    await page.getByRole('button', {name: 'Undo', exact: true}).click();
    await page.waitForTimeout(450);
    assert.equal(await lead.inputValue(), '3');
    await page.getByRole('button', {name: 'Redo', exact: true}).click();
    await page.waitForTimeout(450);
    assert.equal(await lead.inputValue(), '5');
    const lyricsBefore = await page.locator('.hb-lines').boundingBox();
    await page.locator('.st-key-hb_settings').evaluate(el => { el.scrollTop = 300; });
    assert.deepEqual(await page.locator('.hb-lines').boundingBox(), lyricsBefore, 'lyrics remain fixed while settings scroll');
    evidence.errors = errors;
    assert.deepEqual(errors, []);
    const failedProject = path.join(output, `unavailable-audio-${Date.now()}`);
    fs.cpSync(seed, failedProject, {recursive: true, filter: name => path.basename(name) !== '.editor.lock'});
    const errorPage = await browser.newPage({viewport: {width: 1280, height: 720}});
    try {
      await errorPage.route('**/media/*.wav', route => route.fulfill({status: 503, body: 'Test audio failure'}));
      await errorPage.goto(url);
      await errorPage.getByRole('button', {name: 'File', exact: true}).click();
      await errorPage.getByRole('textbox', {name: 'Open project folder', exact: true}).fill(failedProject);
      await errorPage.getByRole('button', {name: 'Open', exact: true}).click();
      await errorPage.locator('.hb-hint.err').waitFor({state: 'visible'});
      await errorPage.getByRole('button', {name: 'File', exact: true}).click();
      evidence.audioError = await errorPage.locator('.hb-hint.err').textContent();
      assert(evidence.audioError.length > 0, 'load failure remains visible outside help');
      await errorPage.screenshot({path: path.join(output, 'audio-error.png')});
    } finally {
      if (!await errorPage.getByRole('button', {name: 'Close', exact: true}).isVisible())
        await errorPage.getByRole('button', {name: 'File', exact: true}).click().catch(() => {});
      await errorPage.getByRole('button', {name: 'Close', exact: true}).click({timeout: 1500}).catch(() => {});
      await errorPage.close();
    }
    evidence.result = 'passed';
    fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify(evidence));
  } catch (error) {
    await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    fs.writeFileSync(path.join(output, 'failure.txt'), error.stack + '\n' + JSON.stringify(evidence));
    throw error;
  } finally {
    if (!await page.getByRole('button', {name: 'Close', exact: true}).isVisible()) await menu.click().catch(() => {});
    await page.getByRole('button', {name: 'Close', exact: true}).click({timeout: 1500}).catch(() => {});
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
