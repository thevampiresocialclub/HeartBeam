// The audio element is the only playback clock. Browser-only audition state
// survives Streamlit reruns; only selections and committed edits cross the bridge.
export default function (component) {
  const parent = component.parentElement;
  if (parent._hbTimeline?.projectId === component.data.project_id &&
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
    <div class="hb-toolbar">
      <button class="hb-btn" data-act="play">Play</button>
      <button class="hb-btn" data-act="loop" aria-pressed="false">Loop selected word</button>
      <label>Listen to <select class="hb-source"></select></label>
      <span class="hb-time"><span class="hb-cur">0:00.00</span> / <span class="hb-dur"></span></span>
      <label>Speed <select class="hb-rate"><option value="0.5">0.5x</option><option value="0.75">0.75x</option><option value="1" selected>1x</option><option value="1.5">1.5x</option></select></label>
      <label>Zoom <input class="hb-zoom" type="range" min="1" max="20" step="1" value="1"></label>
      <label>Seek seconds <input class="hb-seek" type="number" min="0" step="0.01" value="0"></label>
      <button class="hb-btn" data-act="seek">Seek</button>
      <span class="hb-sel"></span>
    </div>
    <input class="hb-position" aria-label="Song position" type="range" min="0" step="1" value="0">
    <div class="hb-scroll"><div class="hb-track"><canvas class="hb-canvas" aria-label="Waveform and word timing"></canvas></div></div>
    <div class="hb-hint" role="status" aria-live="polite"></div>
    <details class="hb-lyrics" open><summary>Lyrics — select a word to seek</summary><div class="hb-lines"></div></details>`;
  parent.appendChild(root);
  const $ = selector => root.querySelector(selector);
  const audio = document.createElement('audio');
  audio.className = 'hb-audio'; audio.hidden = true; audio.preload = 'auto'; root.appendChild(audio);
  const canvas = $('.hb-canvas'), ctx = canvas.getContext('2d'), scroll = $('.hb-scroll');
  const sourceSelect = $('.hb-source'), playButton = $('[data-act="play"]');
  const hint = 'Drag a word edge to change timing. Select a lyric to seek. Space plays when the editor has focus.';
  const state = { words: [], sources: [], durationMs: 0, selectedId: null,
    zoom: 1, looping: false, drag: null, sourceId: null, sourceKey: null,
    peaks: {mins: [], maxs: []}, busy: false, pending: null, switchEpoch: 0,
    peakEpoch: 0, peakKey: null, lastServerSelection: null };
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
  function status(message = hint, error = false) { $('.hb-hint').textContent = message; $('.hb-hint').classList.toggle('err', error); }
  function buttons() {
    playButton.textContent = audio.paused ? 'Play' : 'Pause';
    playButton.disabled = state.busy || !state.sourceId;
    $('[data-act="loop"]').classList.toggle('on', state.looping);
    $('[data-act="loop"]').setAttribute('aria-pressed', String(state.looping));
    $('[data-act="loop"]').disabled = currentWord()?.start_ms == null;
    $('[data-act="seek"]').disabled = state.busy;
    $('.hb-position').disabled = state.busy;
  }
  function seek(ms) {
    const seconds = Math.max(0, Math.min(state.durationMs, ms)) / 1000;
    if (state.busy && state.pending) state.pending.time = seconds;
    else if (audio.readyState) audio.currentTime = seconds;
    const x = msToX(ms);
    if (x < scroll.scrollLeft || x > scroll.scrollLeft + scroll.clientWidth)
      scroll.scrollLeft = Math.max(0, x - scroll.clientWidth / 3);
    render();
  }
  function select(word, notify = false, shouldSeek = false) {
    state.selectedId = word?.id || null;
    if (word?.start_ms == null) state.looping = false;
    $('.hb-sel').textContent = word ? `Selected: ${word.text}${word.start_ms == null ? ' (needs timing)' : ''}` : '';
    for (const [id, button] of wordButtons) button.setAttribute('aria-pressed', String(id === state.selectedId));
    if (shouldSeek && word?.start_ms != null) seek(word.start_ms);
    buttons(); draw();
    // Selection is persistent component state. A one-shot trigger can be lost
    // when a nearby Python button causes another rerun before it is consumed.
    if (notify && word) bridge.setStateValue('selection', {
      word_id: word.id, nonce: `${Date.now()}:${++selectionSequence}`,
    });
  }
  function rebuildLyrics() {
    const focusedId = root.getRootNode().activeElement?.dataset?.wordId;
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
  function draw() {
    const viewport = scroll.clientWidth, fullWidth = width(), offset = scroll.scrollLeft;
    ctx.clearRect(0, 0, viewport, 150);
    const {mins, maxs} = state.peaks, n = mins.length;
    if (n) {
      ctx.strokeStyle = 'rgba(130,150,180,0.85)'; ctx.lineWidth = 1; ctx.beginPath();
      for (let x = 0; x < viewport; x++) {
        const start = Math.min(n - 1, Math.floor((x + offset) / fullWidth * n));
        const end = Math.min(n, Math.max(start + 1, Math.ceil((x + offset + 1) / fullWidth * n)));
        let lo = mins[start], hi = maxs[start];
        for (let i = start + 1; i < end; i++) { lo = Math.min(lo, mins[i]); hi = Math.max(hi, maxs[i]); }
        ctx.moveTo(x + .5, 46 - hi / 127 * 45); ctx.lineTo(x + .5, 46 - lo / 127 * 45);
      } ctx.stroke();
    }
    ctx.font = '12px system-ui, sans-serif'; ctx.textBaseline = 'middle';
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
    const x = msToX(audio.currentTime * 1000) - offset;
    ctx.strokeStyle = 'rgba(255,90,120,.95)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 150); ctx.stroke();
  }
  function hitTest(x) {
    for (const word of state.words) {
      if (word.start_ms == null || word.end_ms == null) continue;
      if (Math.abs(x - msToX(word.start_ms)) <= 6) return {word, edge: 'start'};
      if (Math.abs(x - msToX(word.end_ms)) <= 6) return {word, edge: 'end'};
    }
    const word = wordAt(xToMs(x)); return word ? {word, edge: null} : null;
  }
  const localX = event => event.clientX - canvas.getBoundingClientRect().left + scroll.scrollLeft;
  canvas.addEventListener('mousedown', event => {
    if (state.busy) return;
    const x = localX(event), hit = hitTest(x);
    if (!hit) { seek(xToMs(x)); return; }
    if (event.shiftKey) { state.looping = true; select(hit.word, true, true); return; }
    select(hit.word, !hit.edge, !hit.edge);
    if (hit.edge) state.drag = {wordId: hit.word.id, edge: hit.edge, startX: x, origStart: hit.word.start_ms, origEnd: hit.word.end_ms};
  });
  window.addEventListener('mousemove', event => {
    const x = localX(event), drag = state.drag;
    if (!drag) { if (event.target === canvas) canvas.style.cursor = hitTest(x)?.edge ? 'ew-resize' : 'pointer'; return; }
    const word = state.words.find(w => w.id === drag.wordId); if (!word) return;
    const delta = xToMs(x) - xToMs(drag.startX);
    if (drag.edge === 'start') word.start_ms = Math.round(Math.max(0, Math.min(drag.origStart + delta, word.end_ms - 10)));
    else word.end_ms = Math.round(Math.min(state.durationMs, Math.max(drag.origEnd + delta, word.start_ms + 10)));
    draw();
  }, {signal});
  window.addEventListener('mouseup', () => {
    const drag = state.drag; if (!drag) return; state.drag = null;
    const word = state.words.find(w => w.id === drag.wordId); if (!word) return;
    if (word.start_ms === drag.origStart && word.end_ms === drag.origEnd) { select(word, true, true); return; }
    bridge.setTriggerValue('timing_edit', {word_id: word.id, start_ms: word.start_ms, end_ms: word.end_ms, nonce: Date.now()});
  }, {signal});
  async function togglePlay() {
    if (state.busy || !state.sourceId) return;
    if (!audio.paused) audio.pause();
    else { try { await audio.play(); } catch (error) { status(`Could not start playback: ${error.message}`, true); } }
    buttons();
  }
  playButton.addEventListener('click', togglePlay);
  $('[data-act="loop"]').addEventListener('click', () => { state.looping = !state.looping; if (state.looping) seek(Math.max(0, currentWord().start_ms - 250)); buttons(); });
  $('[data-act="seek"]').addEventListener('click', () => seek(Number($('.hb-seek').value) * 1000));
  $('.hb-seek').addEventListener('keydown', e => { if (e.key === 'Enter') seek(Number(e.target.value) * 1000); });
  $('.hb-position').addEventListener('input', e => seek(Number(e.target.value)));
  sourceSelect.addEventListener('change', e => { void switchSource(e.target.value); });
  $('.hb-rate').addEventListener('change', e => { audio.playbackRate = Number(e.target.value); if (state.pending) state.pending.rate = audio.playbackRate; });
  $('.hb-zoom').addEventListener('input', e => { const start = xToMs(scroll.scrollLeft); state.zoom = Number(e.target.value); resize(); scroll.scrollLeft = msToX(start); draw(); });
  scroll.addEventListener('scroll', draw);
  root.addEventListener('keydown', e => {
    if (e.target.closest('input, textarea, select, button, summary, [contenteditable="true"]')) return;
    if (e.code === 'Space') { e.preventDefault(); void togglePlay(); }
  });
  audio.addEventListener('play', buttons); audio.addEventListener('pause', buttons);
  audio.addEventListener('ended', () => { if (state.looping && currentWord()?.start_ms != null) { seek(Math.max(0, currentWord().start_ms - 250)); void togglePlay(); } else buttons(); });
  audio.addEventListener('error', () => { if (!state.busy) status(`Audio failed (code ${audio.error?.code || '?'})`, true); });
  function render() {
    let ms = audio.currentTime * 1000;
    const word = currentWord();
    if (!state.busy && !audio.paused && state.looping && word?.end_ms != null && ms >= word.end_ms + 250) {
      audio.currentTime = Math.max(0, word.start_ms - 250) / 1000; ms = audio.currentTime * 1000;
    }
    $('.hb-cur').textContent = fmt(ms); $('.hb-position').value = String(Math.round(ms));
    const singing = wordAt(ms)?.id;
    for (const [id, button] of wordButtons) button.classList.toggle('singing', id === singing);
    root.dataset.clockMs = String(Math.round(ms)); root.dataset.sourceId = state.sourceId || '';
    root.dataset.selectedId = state.selectedId || ''; root.dataset.zoom = String(state.zoom);
    draw();
  }
  function tick() {
    if (!root.isConnected) { destroy(); return; }
    const now = performance.now(); if (now - lastTick < 25) return; lastTick = now; render();
  }
  function frame() { if (signal.aborted) return; tick(); rafId = requestAnimationFrame(frame); }
  const interval = setInterval(tick, 60); // rAF can stop while audio continues
  const observer = new ResizeObserver(resize); observer.observe(scroll);
  function destroy() { controller.abort(); sourceAbort?.abort(); peakAbort?.abort(); clearInterval(interval); cancelAnimationFrame(rafId); observer.disconnect(); audio.pause(); audio.removeAttribute('src'); audio.load(); root.remove(); }
  function update(next) {
    bridge = next; const data = next.data;
    state.words = data.words.map(word => ({...word})); state.sources = data.sources; state.durationMs = data.duration_ms;
    const signature = JSON.stringify(state.sources.map(s => [s.id, s.label, s.available, s.reason]));
    if (sourceSelect.dataset.signature !== signature) {
      sourceSelect.replaceChildren(...state.sources.map(source => { const option = document.createElement('option'); option.value = source.id;
        option.textContent = source.available ? source.label : `${source.label} — unavailable`; option.disabled = !source.available; option.title = source.reason || ''; return option; }));
      sourceSelect.dataset.signature = signature;
    }
    if (state.sourceId) sourceSelect.value = state.sourceId;
    $('.hb-dur').textContent = fmt(state.durationMs); $('.hb-position').max = String(state.durationMs); $('.hb-seek').max = String(state.durationMs / 1000);
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
  }
  parent._hbTimeline = {projectId: component.data.project_id, root, update, destroy};
  status(); update(component); rafId = requestAnimationFrame(frame);
}
