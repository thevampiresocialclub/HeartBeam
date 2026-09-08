function hbLineTarget(lines, currentLineId, timeMs, direction) {
  if (!lines?.length) return null;
  let index = lines.findIndex(line => line.line_id === currentLineId);
  if (index < 0) index = lines.findLastIndex(line => line.start_ms <= timeMs);
  if (index < 0) return lines[0];
  return lines[Math.max(0, Math.min(lines.length - 1, index + direction))];
}

// Playback gestures have no access to lyric commands. Coordinates are converted
// through the visible viewport, including horizontal zoom and CSS scaling.
class HBWaveformSeek {
  constructor(surface, options) { this.surface = surface; this.options = options; this.pointer = null; }
  get active() { return this.pointer !== null; }
  position(event) {
    const rect = this.surface.getBoundingClientRect(), view = this.options.geometry();
    const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
    return Math.round(Math.max(0, Math.min(view.durationMs,
      (view.scrollLeft + fraction * view.viewport) / Math.max(1, view.width) * view.durationMs)));
  }
  down(event) {
    if (event.button !== 0 || event.isPrimary === false || this.active || !this.options.enabled()) return;
    event.preventDefault(); this.surface.focus({preventScroll: true});
    this.pointer = event.pointerId; this.lastMs = null;
    this.surface.setPointerCapture(event.pointerId); this.move(event);
  }
  move(event) {
    if (event.pointerId !== this.pointer) return;
    if (!this.options.enabled()) { this.cancel(); return; }
    const ms = this.position(event);
    if (ms !== this.lastMs) { this.lastMs = ms; this.options.seek(ms); }
  }
  up(event) { if (event.pointerId === this.pointer) { this.move(event); this.cancel(); } }
  cancel() {
    const pointer = this.pointer; this.pointer = null;
    if (pointer !== null && this.surface.hasPointerCapture(pointer)) this.surface.releasePointerCapture(pointer);
  }
  keyDown(event) {
    if (!this.options.enabled()) return;
    const view = this.options.geometry(), step = event.shiftKey ? 100 : 1000;
    const moves = {ArrowLeft:-step, ArrowDown:-step, ArrowRight:step, ArrowUp:step, PageDown:-10000, PageUp:10000};
    if (event.key === ' ' || event.code === 'Space') {
      event.preventDefault(); event.stopPropagation(); this.options.play(); return;
    }
    let ms;
    if (event.key === 'Home') ms = 0;
    else if (event.key === 'End') ms = view.durationMs;
    else if (event.key in moves) ms = this.options.currentMs() + moves[event.key];
    else return;
    event.preventDefault(); event.stopPropagation();
    this.options.seek(Math.max(0, Math.min(view.durationMs, ms)));
  }
}

function hbFollowPosition(ms, duration, width, viewport, left) {
  const x = ms / Math.max(1, duration) * width;
  if (x < left || x > left + viewport - 16)
    return Math.max(0, Math.min(width - viewport, x - viewport * .2));
  return left;
}

// The AudioContext is the only playback clock. Browser-only audition state
// survives Streamlit reruns; only selections and committed edits cross the bridge.
export default function (component) {
  const parent = component.parentElement;
  if (parent._hbTimeline?.projectId === component.data.project_id &&
      parent._hbTimeline.version === component.data.frontend_version &&
      parent._hbTimeline.root.isConnected) {
    parent._hbTimeline.update(component);
    return;
  }
  parent._hbTimeline?.destroy();
  parent._hbAbort?.abort(); // clean up a mount from the previous implementation
  parent.querySelectorAll('.hb-editor').forEach(node => node.remove());
  const controller = new AbortController(), signal = controller.signal;
  let bridge = component;
  const root = document.createElement('div');
  root.className = 'hb-editor'; root.tabIndex = 0;
  root.setAttribute('aria-label', 'Timing editor');
  root.innerHTML = `
    <div class="hb-preview-head">
      <div class="hb-preview-actions">
        <button class="hb-btn hb-primary" data-act="play" aria-label="Play">▶ Play</button>
        <button class="hb-btn" data-act="restart">Restart</button>
        <button class="hb-btn" data-act="previous-line">Previous lyric</button>
        <button class="hb-btn" data-act="next-line">Next lyric</button>
      </div>
      <span class="hb-time"><span class="hb-cur">0:00.00</span> / <span class="hb-dur"></span></span>
    </div>
    <div class="hb-toolbar">
      <label>Listen to <select class="hb-source"></select></label>
      <label>Speed <select class="hb-rate"><option value="0.5">0.5x</option><option value="0.75">0.75x</option><option value="1" selected>1x</option><option value="1.5">1.5x</option></select></label>
    </div>
    <div class="hb-preview"><canvas class="hb-ass" width="960" height="540" aria-label="Rendered lyric preview"></canvas></div>
    <div class="hb-preview-status" role="status">Loading lyric preview…</div>
    <div class="hb-toolbar hb-waveform-tools">
      <strong>Waveform · click or drag to seek</strong>
      <label>Zoom <input class="hb-zoom" type="range" min="1" max="20" step="1" value="1"></label>
      <label><input class="hb-follow" type="checkbox" checked> Follow playback</label>
    </div>
    <div class="hb-scroll"><div class="hb-track"><canvas class="hb-canvas" tabindex="0" role="slider" aria-label="Waveform song position" aria-valuemin="0" aria-valuenow="0" aria-valuemax="0" aria-orientation="horizontal" aria-description="Click or drag the waveform to seek. Arrow keys seek one second, Shift seeks a tenth of a second. Home and End go to the start and end. Space plays or pauses. Lyric timing blocks are below the waveform."></canvas></div></div>
    <div class="hb-toolbar hb-seek-tools">
      <label>Seek seconds <input class="hb-seek" type="number" min="0" step="0.01" value="0"></label>
      <button class="hb-btn" data-act="seek">Seek</button>
      <span class="hb-sel"></span>
    </div>
    <div class="hb-toolbar"><button class="hb-btn" data-act="loop" aria-pressed="false">Loop selection</button><label>Before (ms) <input class="hb-before" type="number" min="0" max="5000" step="50" value="250"></label>
      <label>After (ms) <input class="hb-after" type="number" min="0" max="5000" step="50" value="250"></label>
      <button class="hb-btn" data-act="undo">Undo</button><button class="hb-btn" data-act="redo">Redo</button></div>
    <div class="hb-vocal-lane" aria-label="Vocal regions"></div>
    <div class="hb-vocal" hidden><strong class="hb-vocal-title"></strong>
      <label>Vocal level <input class="hb-vocal-level" type="range" min="0" max="100" step="1" value="0"><output class="hb-vocal-value">0%</output></label>
      <p>0% = processed karaoke · 100% = original vocal level. Separation may also affect backing vocals. Draft audition has fixed headroom; final audio is mastered once.</p></div>
    <div class="hb-hint" role="status" aria-live="polite"></div>
    <details class="hb-lyrics" open><summary>Lyrics — select a word to seek</summary><div class="hb-lines"></div></details>`;
  parent.appendChild(root);
  const controls = document.createElement('div');
  controls.className = 'hb-editor hb-live-controls'; controls.tabIndex = 0;
  controls.append(root.querySelector('.hb-lyrics'), root.querySelector('.hb-vocal'));
  const releaseControls = hbAttachControls(component.data.project_id, controls);
  const $ = selector => root.querySelector(selector) || controls.querySelector(selector);
  const audio = new HBTransport();
  const canvas = $('.hb-canvas'), ctx = canvas.getContext('2d'), scroll = $('.hb-scroll');
  const sourceSelect = $('.hb-source'), playButton = $('[data-act="play"]');
  const hint = 'Click or drag the waveform to seek. Drag lyric blocks below it to edit timing. With the waveform focused, arrows seek; with a word selected, arrows nudge timing. Space plays. Ctrl+Z undoes.';
  const state = { words: [], sources: [], durationMs: 0, selectedId: null,
    zoom: 1, looping: false, drag: null, sourceId: null, sourceKey: null,
    peaks: {mins: [], maxs: []}, busy: false, pending: null, switchEpoch: 0,
    peakEpoch: 0, peakKey: null, lastServerSelection: null, revision: 0, pendingCommand: null, mix: null };
  let mixSignature = null;
  const wordButtons = new Map(), peaksCache = new Map();
  let sourceAbort = null, peakAbort = null, rafId = 0, lastTick = 0, selectionSequence = 0;
  const fmt = ms => { const s = Math.max(0, ms || 0) / 1000;
    return `${Math.floor(s / 60)}:${(s % 60).toFixed(2).padStart(5, '0')}`; };
  const currentWord = () => state.words.find(w => w.id === state.selectedId);
  const currentSource = () => state.sources.find(s => s.id === state.sourceId);
  const width = () => Math.max(1, scroll.clientWidth) * state.zoom;
  const msToX = ms => ms / (state.durationMs || 1) * width();
  const xToMs = x => x / width() * state.durationMs;
  const wordAt = ms => state.words.find(w => w.start_ms != null && w.end_ms != null && ms >= w.start_ms && ms < w.end_ms);
  const waveformSeek = new HBWaveformSeek(canvas, {
    geometry: () => ({durationMs: state.durationMs, width: width(), viewport: scroll.clientWidth, scrollLeft: scroll.scrollLeft}),
    enabled: () => !state.busy && !!state.sourceId,
    currentMs: () => audio.currentTime * 1000,
    seek: ms => seek(ms, true), play: togglePlay,
  });
  const presentation = new HBPresentation(root, audio, {
    seek: ms => seek(ms, true),
    commit, select: (id, notify, shouldSeek) => select(state.words.find(w => w.id === id), notify, shouldSeek),
    pending: () => !!state.pendingCommand, selected: () => state.selectedId,
    selectedLine: () => currentWord()?.line_id,
  }, signal);
  function commit(kind, payload = {}) {
    if (state.pendingCommand) return;
    const id = crypto.randomUUID(); state.pendingCommand = {id, at: performance.now()};
    bridge.setTriggerValue('command', {id, base_revision: state.revision, kind, payload});
    root.dataset.lastCommand = id; root.dataset.commandState = 'pending';
    requestAnimationFrame(() => { root.dataset.commitPaintMs = (performance.now() - state.pendingCommand?.at || 0).toFixed(1); });
  }
  function loopBounds() {
    if (state.phraseLoop) return [state.phraseLoop.start_ms / 1000, state.phraseLoop.end_ms / 1000];
    const selected = state.mix?.selection, word = currentWord();
    const range = state.sourceId === 'mix' && selected && !selected.song ? selected : word;
    if (range?.start_ms == null || range?.end_ms == null) return null;
    return [Math.max(0, range.start_ms - Number($('.hb-before').value)) / 1000,
            Math.min(state.durationMs, range.end_ms + Number($('.hb-after').value)) / 1000];
  }
  function syncLoop() { audio.setLoop(state.looping ? loopBounds() : null); }
  function status(message = hint, error = false) { $('.hb-hint').textContent = message; $('.hb-hint').classList.toggle('err', error); }
  function buttons() {
    playButton.textContent = audio.paused ? '▶ Play' : 'Ⅱ Pause';
    playButton.setAttribute('aria-label', audio.paused ? 'Play' : 'Pause');
    playButton.setAttribute('aria-pressed', String(!audio.paused));
    playButton.disabled = state.busy || !state.sourceId;
    $('[data-act="loop"]').classList.toggle('on', state.looping);
    $('[data-act="loop"]').setAttribute('aria-pressed', String(state.looping));
    $('[data-act="loop"]').disabled = !loopBounds();
    $('[data-act="undo"]').disabled = !bridge.data.can_undo || !!state.pendingCommand;
    $('[data-act="redo"]').disabled = !bridge.data.can_redo || !!state.pendingCommand;
    $('[data-act="seek"]').disabled = state.busy;
    for (const action of ['previous-line', 'next-line', 'restart'])
      $(`[data-act="${action}"]`).disabled = state.busy || !presentation.preview?.lines?.length;
    canvas.setAttribute('aria-disabled', String(state.busy || !state.sourceId));
  }
  function seek(ms, explicit = false) {
    if (!Number.isFinite(ms)) return;
    const seconds = Math.max(0, Math.min(state.durationMs, ms)) / 1000;
    if (explicit) { $('.hb-seek').dataset.editing = ''; $('.hb-seek').value = seconds.toFixed(2); }
    // An explicit seek outside a loop must land where the user points, rather
    // than wrapping straight back to the old lyric selection.
    if (explicit && audio.loopRange && (seconds < audio.loopRange[0] || seconds >= audio.loopRange[1])) {
      state.looping = false; syncLoop(); buttons();
    }
    if (state.busy && state.pending) state.pending.time = seconds;
    else if (audio.readyState) audio.currentTime = seconds;
    const x = msToX(ms);
    if (!waveformSeek.active && (x < scroll.scrollLeft || x > scroll.scrollLeft + scroll.clientWidth))
      scroll.scrollLeft = Math.max(0, x - scroll.clientWidth / 3);
    render();
  }
  function select(word, notify = false, shouldSeek = false) {
    if (word?.id !== state.selectedId) state.phraseLoop = null;
    state.selectedId = word?.id || null;
    if (word?.start_ms == null && !state.phraseLoop) state.looping = false;
    $('.hb-sel').textContent = word ? `Selected: ${word.text}${word.start_ms == null ? ' (needs timing)' : ''}` : '';
    for (const [id, button] of wordButtons) button.setAttribute('aria-pressed', String(id === state.selectedId));
    syncLoop();
    if (shouldSeek && word?.start_ms != null) seek(word.start_ms);
    buttons(); draw();
    // Selection is persistent component state. A one-shot trigger can be lost
    // when a nearby Python button causes another rerun before it is consumed.
    if (notify && word) bridge.setStateValue('selection', {
      word_id: word.id, nonce: `${Date.now()}:${++selectionSequence}`,
    });
  }
  function rebuildLyrics() {
    const focusedId = controls.getRootNode().activeElement?.dataset?.wordId;
    const scrollTop = $('.hb-lines').scrollTop;
    const lines = new Map(), fragment = document.createDocumentFragment(); wordButtons.clear();
    for (const word of state.words) {
      if (!lines.has(word.line_id)) { const line = document.createElement('div'); line.className = 'hb-line'; lines.set(word.line_id, line); fragment.appendChild(line); }
      const button = document.createElement('button'); button.type = 'button'; button.className = 'hb-word';
      button.textContent = word.text; button.dataset.wordId = word.id;
      button.setAttribute('aria-pressed', String(word.id === state.selectedId));
      button.classList.toggle('needs-timing', word.start_ms == null);
      button.title = word.start_ms == null ? 'Needs timing' : `${fmt(word.start_ms)} – ${fmt(word.end_ms)}`;
      button.addEventListener('click', () => select(state.words.find(w => w.id === word.id), true, true));
      wordButtons.set(word.id, button); lines.get(word.line_id).appendChild(button);
    }
    $('.hb-lines').replaceChildren(fragment);
    $('.hb-lines').scrollTop = scrollTop;
    if (focusedId) wordButtons.get(focusedId)?.focus({preventScroll: true});
  }
  function waitFor(event, abortSignal) {
    return new Promise((resolve, reject) => {
      let timer;
      const clean = () => { clearTimeout(timer); audio.removeEventListener(event, done); audio.removeEventListener('error', fail); abortSignal.removeEventListener('abort', aborted); };
      const done = () => { clean(); resolve(); };
      const fail = () => { clean(); reject(new Error(`Audio could not load (code ${audio.error?.code || '?'})`)); };
      const aborted = () => { clean(); reject(new DOMException('Superseded', 'AbortError')); };
      timer = setTimeout(() => { clean(); reject(new Error('Audio loading timed out.')); }, 15000);
      audio.addEventListener(event, done); audio.addEventListener('error', fail); abortSignal.addEventListener('abort', aborted);
      if (abortSignal.aborted) aborted();
    });
  }
  async function loadAudio(source, snapshot, abortSignal) {
    const metadata = waitFor('loadedmetadata', abortSignal);
    audio.src = source.src; audio.load(); await metadata;
    const target = Math.min(snapshot.time, Number.isFinite(audio.duration) ? audio.duration : snapshot.time);
    if (Math.abs(audio.currentTime - target) > 0.0005) {
      const positioned = waitFor('seeked', abortSignal); audio.currentTime = target; await positioned;
    }
    audio.playbackRate = snapshot.rate;
    return Math.abs(audio.currentTime - target) * 1000;
  }
  async function switchSource(id) {
    const source = state.sources.find(s => s.id === id && s.available);
    if (!source || (!state.busy && state.sourceId === id && state.sourceKey === source.key)) return;
    const snapshot = state.pending || {time: audio.currentTime || 0, playing: !audio.paused, rate: audio.playbackRate};
    const previous = currentSource();
    sourceAbort?.abort(); sourceAbort = new AbortController();
    const ownSignal = sourceAbort.signal, epoch = ++state.switchEpoch, started = performance.now();
    state.pending = snapshot; state.busy = true; audio.pause(); buttons(); status(`Loading ${source.label}…`);
    try {
      const errorMs = await loadAudio(source, snapshot, ownSignal);
      if (epoch !== state.switchEpoch || signal.aborted) return;
      state.sourceId = source.id; state.sourceKey = source.key; sourceSelect.value = source.id;
      syncLoop();
      root.dataset.switchSeekErrorMs = errorMs.toFixed(3);
      root.dataset.switchLatencyMs = (performance.now() - started).toFixed(1);
      root.dataset.switchCount = String(Number(root.dataset.switchCount || 0) + 1);
      status(); void loadPeaks(); // waveform delivery must not delay resuming audio
      if (snapshot.playing) await audio.play();
    } catch (error) {
      if (ownSignal.aborted || signal.aborted) return;
      status(`${source.label}: ${error.message}`, true);
      if (previous?.available && previous.id !== source.id) {
        try { await loadAudio(previous, snapshot, ownSignal);
          if (ownSignal.aborted) return;
          state.sourceId = previous.id; state.sourceKey = previous.key; sourceSelect.value = previous.id;
          if (snapshot.playing) await audio.play();
        } catch { state.sourceId = null; }
      } else if (!audio.readyState) state.sourceId = null;
    } finally {
      if (epoch === state.switchEpoch) { state.busy = false; state.pending = null; buttons(); render(); }
    }
  }
  async function loadPeaks() {
    const levels = currentSource()?.levels || [];
    if (!levels.length) return;
    const level = levels.find(l => l.buckets >= width() * 2) || levels[levels.length - 1];
    if (state.peakKey === level.src) return;
    state.peakKey = level.src;
    peakAbort?.abort(); peakAbort = new AbortController(); const epoch = ++state.peakEpoch;
    try {
      let peaks = peaksCache.get(level.src);
      if (!peaks) { const response = await fetch(level.src, {signal: peakAbort.signal});
        if (!response.ok) throw new Error(`Waveform request failed (${response.status})`);
        peaks = await response.json(); peaksCache.set(level.src, peaks); }
      if (epoch !== state.peakEpoch || signal.aborted) return;
      state.peaks = peaks; root.dataset.peakBuckets = String(peaks.mins.length); draw();
    } catch (error) { if (error.name !== 'AbortError') { state.peakKey = null; status(error.message, true); } }
  }
  function resize() {
    const dpr = window.devicePixelRatio || 1, viewport = Math.max(1, scroll.clientWidth);
    $('.hb-track').style.width = `${width()}px`;
    canvas.style.width = `${viewport}px`; canvas.style.height = '150px';
    canvas.width = Math.round(viewport * dpr); canvas.height = Math.round(150 * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw(); void loadPeaks();
  }
  function draw(ms = audio.currentTime * 1000) {
    const viewport = scroll.clientWidth, fullWidth = width(), offset = scroll.scrollLeft;
    const playhead = msToX(ms) - offset;
    ctx.clearRect(0, 0, viewport, 150);
    ctx.fillStyle = 'oklch(65% .11 255 / .16)';
    ctx.fillRect(0, 0, Math.max(0, Math.min(viewport, playhead)), 96);
    const {mins, maxs} = state.peaks, n = mins.length;
    if (n) {
      ctx.strokeStyle = 'rgba(130,150,180,0.85)'; ctx.lineWidth = 1; ctx.beginPath();
      for (let x = 0; x < viewport; x++) {
        const start = Math.min(n - 1, Math.floor((x + offset) / fullWidth * n));
        const end = Math.min(n, Math.max(start + 1, Math.ceil((x + offset + 1) / fullWidth * n)));
        let lo = mins[start], hi = maxs[start];
        for (let i = start + 1; i < end; i++) { lo = Math.min(lo, mins[i]); hi = Math.max(hi, maxs[i]); }
        ctx.moveTo(x + .5, 59 - hi / 127 * 35); ctx.lineTo(x + .5, 59 - lo / 127 * 35);
      } ctx.stroke();
    }
    ctx.font = '12px system-ui, sans-serif'; ctx.textBaseline = 'middle';
    ctx.fillStyle = 'oklch(88% .02 255)';
    ctx.textAlign = 'left'; ctx.fillText(fmt(xToMs(offset)), 6, 12);
    ctx.textAlign = 'right'; ctx.fillText(fmt(xToMs(offset + viewport)), viewport - 6, 12);
    ctx.textAlign = 'left';
    for (const word of state.words) {
      if (word.start_ms == null || word.end_ms == null) continue;
      const left = msToX(word.start_ms) - offset, right = Math.max(left + 2, msToX(word.end_ms) - offset);
      if (right < 0 || left > viewport) continue;
      const selected = word.id === state.selectedId;
      ctx.fillStyle = selected ? 'rgba(255,215,0,.35)' : word.low_confidence ? 'rgba(230,120,90,.28)' : 'rgba(120,170,255,.22)';
      ctx.fillRect(left, 99, right - left, 47);
      ctx.strokeStyle = selected ? 'rgba(255,215,0,.95)' : 'rgba(120,170,255,.55)'; ctx.lineWidth = selected ? 2 : 1;
      ctx.strokeRect(left + .5, 99.5, right - left - 1, 46);
      ctx.save(); ctx.beginPath(); ctx.rect(left + 2, 99, Math.max(0, right - left - 4), 47); ctx.clip();
      ctx.fillStyle = 'rgba(235,240,250,.95)'; ctx.fillText(word.text, left + 4, 122); ctx.restore();
    }
    const x = Math.max(1, Math.min(viewport - 1, playhead));
    if (playhead < 0 || playhead > viewport) return;
    ctx.strokeStyle = 'rgba(255,90,120,.95)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 150); ctx.stroke();
    ctx.fillStyle = 'rgba(255,90,120,.95)'; ctx.beginPath(); ctx.moveTo(x-5, 0); ctx.lineTo(x+5, 0); ctx.lineTo(x, 8); ctx.fill();
  }
  function hitTest(x) {
    for (const word of state.words) {
      if (word.start_ms == null || word.end_ms == null) continue;
      if (Math.abs(x - msToX(word.start_ms)) <= 6) return {word, edge: 'start'};
      if (Math.abs(x - msToX(word.end_ms)) <= 6) return {word, edge: 'end'};
    }
    const word = wordAt(xToMs(x)); return word ? {word, edge: null} : null;
  }
  const localX = event => (event.clientX - canvas.getBoundingClientRect().left) / Math.max(1, canvas.getBoundingClientRect().width) * scroll.clientWidth + scroll.scrollLeft;
  const wordLane = event => (event.clientY - canvas.getBoundingClientRect().top) / Math.max(1, canvas.getBoundingClientRect().height) * 150 >= 99;
  canvas.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.isPrimary === false || state.busy || waveformSeek.active || state.drag) return;
    if (!wordLane(event)) { waveformSeek.down(event); return; }
    if (state.pendingCommand) return;
    event.preventDefault(); root.focus({preventScroll: true});
    const x = localX(event), hit = hitTest(x);
    if (!hit) { waveformSeek.down(event); return; }
    if (event.shiftKey) { state.looping = true; select(hit.word, true, true); return; }
    select(hit.word, false, false);
    state.drag = {wordId: hit.word.id, edge: hit.edge || 'both', startX: x, origStart: hit.word.start_ms, origEnd: hit.word.end_ms, pointer: event.pointerId};
    canvas.setPointerCapture(event.pointerId);
  });
  window.addEventListener('pointermove', event => {
    if (waveformSeek.active) { waveformSeek.move(event); return; }
    const x = localX(event), drag = state.drag;
    if (!drag) { if (event.composedPath().includes(canvas)) canvas.style.cursor = wordLane(event) && hitTest(x)?.edge ? 'ew-resize' : 'pointer'; return; }
    if (event.pointerId !== drag.pointer) return;
    const word = state.words.find(w => w.id === drag.wordId); if (!word) return;
    const delta = xToMs(x) - xToMs(drag.startX);
    if (drag.edge === 'start') word.start_ms = Math.round(Math.max(0, Math.min(drag.origStart + delta, word.end_ms - 10)));
    else if (drag.edge === 'end') word.end_ms = Math.round(Math.min(state.durationMs, Math.max(drag.origEnd + delta, word.start_ms + 10)));
    else { const shift = Math.round(Math.max(-drag.origStart, Math.min(state.durationMs - drag.origEnd, delta)));
      word.start_ms = drag.origStart + shift; word.end_ms = drag.origEnd + shift; }
    draw();
  }, {signal});
  window.addEventListener('pointerup', event => {
    waveformSeek.up(event);
    const drag = state.drag; if (!drag || event.pointerId !== drag.pointer) return; state.drag = null;
    if (canvas.hasPointerCapture(drag.pointer)) canvas.releasePointerCapture(drag.pointer);
    const word = state.words.find(w => w.id === drag.wordId); if (!word) return;
    if (word.start_ms === drag.origStart && word.end_ms === drag.origEnd) { select(word, true, true); return; }
    commit('timing', {word_id: word.id, start_ms: word.start_ms, end_ms: word.end_ms});
  }, {signal});
  function cancelGesture() {
    waveformSeek.cancel();
    const drag = state.drag; state.drag = null;
    if (!drag) return;
    const word = state.words.find(w => w.id === drag.wordId);
    if (word) { word.start_ms = drag.origStart; word.end_ms = drag.origEnd; }
    if (canvas.hasPointerCapture(drag.pointer)) canvas.releasePointerCapture(drag.pointer);
    draw();
  }
  canvas.addEventListener('lostpointercapture', cancelGesture);
  window.addEventListener('pointercancel', cancelGesture, {signal});
  window.addEventListener('blur', cancelGesture, {signal});
  canvas.addEventListener('keydown', event => waveformSeek.keyDown(event));
  async function togglePlay() {
    if (state.busy || !state.sourceId) return;
    if (!audio.paused) audio.pause();
    else { try { await audio.play(); } catch (error) { status(`Could not start playback: ${error.message}`, true); } }
    buttons();
  }
  playButton.addEventListener('click', togglePlay);
  function navigateLine(direction) {
    const target = hbLineTarget(presentation.preview?.lines, currentWord()?.line_id,
                                audio.currentTime * 1000, direction);
    if (!target) return;
    select(state.words.find(word => word.id === target.word_id), true, false);
    seek(target.start_ms);
  }
  $('[data-act="previous-line"]').addEventListener('click', () => navigateLine(-1));
  $('[data-act="next-line"]').addEventListener('click', () => navigateLine(1));
  $('[data-act="restart"]').addEventListener('click', () => seek(0, true));
  $('[data-act="loop"]').addEventListener('click', () => { state.looping = !state.looping; syncLoop(); if (state.looping && loopBounds()) seek(loopBounds()[0] * 1000); buttons(); });
  for (const selector of ['.hb-before', '.hb-after']) $(selector).addEventListener('change', e => {
    e.target.value = String(Math.max(0, Math.min(5000, Math.round(Number(e.target.value) || 0)))); syncLoop(); });
  $('[data-act="undo"]').addEventListener('click', () => commit('undo'));
  $('[data-act="redo"]').addEventListener('click', () => commit('redo'));
  $('[data-act="seek"]').addEventListener('click', () => { seek(Number($('.hb-seek').value) * 1000, true); $('.hb-seek').dataset.editing = ''; });
  $('.hb-seek').addEventListener('input', e => { e.target.dataset.editing = 'true'; });
  $('.hb-seek').addEventListener('keydown', e => { if (e.key === 'Enter') { seek(Number(e.target.value) * 1000, true); e.target.dataset.editing = ''; } });
  $('.hb-seek').addEventListener('blur', e => { if (!e.target.dataset.editing) render(); });
  sourceSelect.addEventListener('change', e => { void switchSource(e.target.value); });
  $('.hb-rate').addEventListener('change', e => { audio.playbackRate = Number(e.target.value); if (state.pending) state.pending.rate = audio.playbackRate; });
  $('.hb-zoom').addEventListener('input', e => { const start = xToMs(scroll.scrollLeft); state.zoom = Number(e.target.value); resize(); scroll.scrollLeft = msToX(start); draw(); });
  scroll.addEventListener('scroll', () => draw());
  function shortcuts(e) {
    if (e.target.closest('input, textarea, select, summary, [contenteditable="true"]')) return;
    if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ') { e.preventDefault(); commit(e.shiftKey ? 'redo' : 'undo'); return; }
    if (e.code === 'ArrowLeft' || e.code === 'ArrowRight') {
      const word = currentWord(); if (!word || word.start_ms == null || state.pendingCommand) return;
      e.preventDefault(); const delta = (e.shiftKey ? 100 : 10) * (e.code === 'ArrowLeft' ? -1 : 1);
      word.start_ms += delta; word.end_ms += delta; draw();
      commit('timing', {word_id: word.id, start_ms: word.start_ms, end_ms: word.end_ms}); return;
    }
    if (e.target.closest('button')) return;
    if (e.code === 'Space') { e.preventDefault(); void togglePlay(); }
  }
  root.addEventListener('keydown', shortcuts);
  controls.addEventListener('keydown', shortcuts);
  audio.addEventListener('play', buttons); audio.addEventListener('pause', buttons);
  audio.addEventListener('ended', () => { if (state.looping && currentWord()?.start_ms != null) { seek(Math.max(0, currentWord().start_ms - 250)); void togglePlay(); } else buttons(); });
  audio.addEventListener('error', () => { if (!state.busy) status(`Audio failed (code ${audio.error?.code || '?'})`, true); });
  function render() {
    let ms = audio.currentTime * 1000;
    if (!audio.paused && $('.hb-follow').checked && !waveformSeek.active && !state.drag)
      scroll.scrollLeft = hbFollowPosition(ms, state.durationMs, width(), scroll.clientWidth, scroll.scrollLeft);
    presentation.render(ms);
    $('.hb-cur').textContent = fmt(ms);
    if (!$('.hb-seek').dataset.editing && $('.hb-seek').getRootNode().activeElement !== $('.hb-seek'))
      $('.hb-seek').value = (ms / 1000).toFixed(2);
    canvas.setAttribute('aria-valuenow', String(Math.round(ms)));
    canvas.setAttribute('aria-valuetext', `${fmt(ms)} of ${fmt(state.durationMs)}`);
    canvas.dataset.clockMs = String(Math.round(ms));
    const singing = wordAt(ms)?.id;
    for (const [id, button] of wordButtons) button.classList.toggle('singing', id === singing);
    root.dataset.clockMs = String(Math.round(ms)); root.dataset.sourceId = state.sourceId || '';
    root.dataset.selectedId = state.selectedId || ''; root.dataset.zoom = String(state.zoom);
    draw(ms);
  }
  function tick() {
    if (!root.isConnected) { destroy(); return; }
    const now = performance.now(); if (now - lastTick < 25) return; lastTick = now; render();
  }
  function frame() { if (signal.aborted) return; tick(); rafId = requestAnimationFrame(frame); }
  const interval = setInterval(tick, 60); // rAF can stop while audio continues
  const observer = new ResizeObserver(resize); observer.observe(scroll);
  function destroy() { cancelGesture(); controller.abort(); sourceAbort?.abort(); peakAbort?.abort(); clearInterval(interval); cancelAnimationFrame(rafId); observer.disconnect(); audio.dispose(); releaseControls(); root.remove(); }
  async function updateMix(data) {
    state.mix = data;
    $('.hb-vocal').hidden = !data?.selection;
    $('.hb-vocal-level').disabled = true;
    $('.hb-vocal-lane').replaceChildren();
    if (!data) return;
    for (const region of data.regions) {
      const button = document.createElement('button'); button.className = 'hb-region';
      button.style.left = `${region.start_ms / state.durationMs * 100}%`;
      button.style.width = `${(region.end_ms - region.start_ms) / state.durationMs * 100}%`;
      button.textContent = `${Math.round(region.value * 100)}%`; button.title = `Vocal region ${fmt(region.start_ms)}–${fmt(region.end_ms)}: ${Math.round(region.value * 100)}%`;
      button.addEventListener('click', () => { seek(region.start_ms); bridge.setStateValue('region_selection', {id: region.id, nonce: crypto.randomUUID()}); });
      $('.hb-vocal-lane').appendChild(button);
    }
    if (data.selection) {
      $('.hb-vocal-title').textContent = data.selection.label;
      $('.hb-vocal-level').value = Math.round(data.selection.value * 100);
      $('.hb-vocal-value').textContent = `${Math.round(data.selection.value * 100)}%`;
    }
    const signature = JSON.stringify({...data, revision: undefined});
    if (mixSignature === signature) { $('.hb-vocal-level').disabled = !!state.pendingCommand;
      root.dataset.mixRevision = String(data.revision); return; }
    mixSignature = signature;
    try {
      const ready = await audio.configureMix(data);
      if (!ready || signal.aborted) return;
      root.dataset.mixRevision = String(data.revision); $('.hb-vocal-level').disabled = !!state.pendingCommand;
      root.dataset.mixReady = 'true';
      // Warm each saved audition source after references load. Switching a
      // cached source then uses the current clock without a decode pause.
      for (const source of state.sources)
        if (source.available && source.src !== 'heartbeam:mix') void audio.decoded(source.src).catch(() => {});
      const mixSource = state.sources.find(s => s.id === 'mix');
      if (mixSource) { mixSource.available = true; const option = sourceSelect.querySelector('option[value="mix"]');
        if (option) { option.disabled = false; option.textContent = mixSource.label; } }
    } catch (e) { root.dataset.mixReady = 'false'; status(`Vocal audition: ${e.message}`, true); }
  }
  $('.hb-vocal-level').addEventListener('input', e => {
    const value = Number(e.target.value) / 100;
    $('.hb-vocal-value').textContent = `${Math.round(value * 100)}%`; audio.audition(value);
    root.dataset.auditionValue = String(value);
    if (state.sourceId !== 'mix') void switchSource('mix');
  });
  $('.hb-vocal-level').addEventListener('change', e => {
    commit('vocal', {...state.mix.selection, value: Number(e.target.value) / 100});
    e.target.disabled = true;
  });
  function update(next) {
    bridge = next; const data = next.data;
    // Streamlit can deliver the pre-command snapshot once before the handler
    // reruns. Keep the optimistic gesture visible until its explicit ACK.
    if (state.pendingCommand && data.command_ack !== state.pendingCommand.id && data.revision <= state.revision) return;
    if (state.pendingCommand && data.command_ack === state.pendingCommand.id) {
      root.dataset.commandAckMs = (performance.now() - state.pendingCommand.at).toFixed(1);
      state.pendingCommand = null; root.dataset.commandState = 'ready';
    }
    state.revision = data.revision; root.dataset.revision = String(data.revision);
    root.dataset.frontendVersion = data.frontend_version;
    state.words = data.words.map(word => ({...word})); state.sources = data.sources; state.durationMs = data.duration_ms;
    if (audio.mix) { const source = state.sources.find(s => s.id === 'mix'); if (source) source.available = true; }
    const signature = JSON.stringify(state.sources.map(s => [s.id, s.label, s.available, s.reason]));
    if (sourceSelect.dataset.signature !== signature) {
      sourceSelect.replaceChildren(...state.sources.map(source => { const option = document.createElement('option'); option.value = source.id;
        option.textContent = source.available ? source.label : `${source.label} — unavailable`; option.disabled = !source.available; option.title = source.reason || ''; return option; }));
      sourceSelect.dataset.signature = signature;
    }
    if (state.sourceId) sourceSelect.value = state.sourceId;
    $('.hb-dur').textContent = fmt(state.durationMs); canvas.setAttribute('aria-valuemax', String(state.durationMs)); $('.hb-seek').max = String(state.durationMs / 1000);
    rebuildLyrics();
    // Ignore the stale echo immediately after a local selection; Python's next
    // explicit navigation changes this value and seeks using the same clock.
    if (data.selected_id !== state.lastServerSelection) {
      state.lastServerSelection = data.selected_id;
      if (data.selected_id !== state.selectedId) select(state.words.find(w => w.id === data.selected_id), false, true);
    } else select(currentWord());
    const source = currentSource();
    if (!state.busy && (!source?.available || source.key !== state.sourceKey))
      void switchSource(source?.available ? source.id : state.sources.find(s => s.available)?.id);
    resize(); render();
    presentation.draft = null;
    presentation.update(data.preview, data.presentation_selection); void updateMix(data.mix); syncLoop(); buttons();
    const navigation = data.lyric_navigation;
    if (navigation && navigation.id !== state.lastNavigation) {
      state.lastNavigation = navigation.id;
      // A new page can mount after another line was selected. Do not replay an
      // older review-panel request over the server's current selection.
      if (navigation.word_id === data.selected_id) {
        select(state.words.find(w => w.id === navigation.word_id), false, false);
        if (Number.isFinite(navigation.start_ms)) seek(navigation.start_ms, true);
        render();
      }
    }
    const audition = data.phrase_audition;
    if (audition && audition.id !== state.lastAudition && Number.isFinite(audition.start_ms) &&
        Number.isFinite(audition.end_ms) && 0 <= audition.start_ms && audition.start_ms < audition.end_ms && audition.end_ms <= state.durationMs) {
      state.lastAudition = audition.id; state.phraseLoop = audition; state.looping = true;
      syncLoop(); seek(audition.start_ms); buttons();
      status('Phrase loop ready. Press Play to listen; selecting another word returns to word looping.');
    }
  }
  parent._hbTimeline = {projectId: component.data.project_id, version: component.data.frontend_version, root, update, destroy};
  status(); update(component); rafId = requestAnimationFrame(frame);
}
