// P05 preview. ASS owns all text rendering; DOM guides are never exported.
class HBPresentation {
  constructor(root, audio, callbacks, signal) {
    this.root = root; this.audio = audio; this.callbacks = callbacks; this.signal = signal;
    this.$ = selector => root.querySelector(selector);
    this.frame = this.$('.hb-preview'); this.canvas = this.$('.hb-ass');
    this.preview = null; this.ass = null; this.fontKey = null; this.drag = null;
    this.frame.insertAdjacentHTML('afterbegin', '<img class="hb-background" alt="" hidden><video class="hb-background" muted playsinline preload="auto" hidden></video>');
    this.frame.insertAdjacentHTML('beforeend', '<div class="hb-safe" aria-hidden="true"></div><div class="hb-placement-handles"></div>');
    this.frame.insertAdjacentHTML('beforebegin', '<div class="hb-toolbar"><label>Preview line <select class="hb-preview-line" aria-label="Preview lyric line"></select></label><span class="hb-placement-scope"></span></div>');
    this.video = this.$('video.hb-background'); this.video.muted = true;
    this.video.addEventListener('error', () => this.message('Background video cannot play in this browser. Use an H.264 MP4 or choose another background.'), {signal});
    this.$('img.hb-background').addEventListener('error', () => this.message('Background image could not load. Choose another image.'), {signal});
    this.$('.hb-preview-line').addEventListener('change', e => {
      const line = this.preview?.lines.find(line => line.line_id === e.target.value);
      if (line) this.callbacks.select(line.word_id, true, true);
    }, {signal});
    window.addEventListener('pointermove', e => this.pointerMove(e), {signal});
    window.addEventListener('pointerup', e => this.pointerUp(e), {signal});
    window.addEventListener('pointercancel', () => this.cancelDrag(), {signal});
    window.addEventListener('blur', () => this.cancelDrag(), {signal});
    this.frame.addEventListener('keydown', e => {
      if (e.key === 'Escape' && this.drag) { e.preventDefault(); this.cancelDrag(); }
    }, {signal});
    signal.addEventListener('abort', () => this.dispose(), {once: true});
  }
  message(text) { this.$('.hb-preview-status').textContent = text; }
  update(preview, selection) {
    if (!preview) {
      this.preview = null; this.ass?.setTrack(''); this.assText = '';
      this.$('.hb-placement-handles').replaceChildren();
      this.message('Preview unavailable. Correct the reported presentation settings.'); return;
    }
    if (this.drag) this.cancelDrag();
    this.preview = preview; this.selection = selection || {scope: 'song', guides: true, line_ids: []};
    this.frame.style.aspectRatio = `${preview.width} / ${preview.height}`;
    this.$('.hb-safe').hidden = !this.selection.guides;
    this.$('.hb-placement-scope').textContent = `Placement: ${this.selection.label || 'Whole song'} · drag text or use Appearance controls`;
    const chooser = this.$('.hb-preview-line'), selected = chooser.value;
    chooser.replaceChildren(...preview.lines.map((line, index) => {
      const option = document.createElement('option'); option.value = line.line_id;
      option.textContent = `${index + 1}. ${line.label}`; return option;
    }));
    if (preview.lines.some(line => line.line_id === selected)) chooser.value = selected;
    chooser.disabled = !preview.lines.length;
    const bg = preview.background;
    const img = this.$('img.hb-background');
    this.frame.style.background = bg.kind === 'solid' ? bg.value : '#101820';
    img.hidden = bg.kind !== 'image'; this.video.hidden = bg.kind !== 'video';
    if (bg.kind === 'image' && img.getAttribute('src') !== bg.src) img.src = bg.src;
    if (bg.kind === 'video' && this.video.getAttribute('src') !== bg.src) this.video.src = bg.src;
    if (bg.kind !== 'video') { this.video.pause(); this.video.removeAttribute('src'); }
    const fonts = JSON.stringify(preview.fonts);
    if (this.ass && fonts !== this.fontKey) {
      this.ass.dispose(); this.ass = null; URL.revokeObjectURL(this.workerBlob);
    }
    this.fontKey = fonts;
    const message = preview.draft || preview.conflicts ? 'Draft lyric preview: fix untimed words and timing conflicts before export.' : 'Rendered lyrics: same ASS and font files as export. Guides show an approximate text box.';
    if (!this.ass) {
      this.root.dataset.assReady = 'false';
      const absolute = path => new URL(path, location.href).href;
      this.workerBlob = URL.createObjectURL(new Blob([`var Module={locateFile:function(){return ${JSON.stringify(absolute(preview.wasm))}}};importScripts(${JSON.stringify(absolute(preview.worker))});`], {type: 'application/javascript'}));
      this.ass = new SubtitlesOctopus({canvas: this.canvas, subContent: preview.ass,
        workerUrl: this.workerBlob, fonts: preview.fonts.map(absolute), fallbackFont: absolute(preview.fallback_font),
        targetFps: 30, onReady: () => { if (this.signal.aborted) return; this.root.dataset.assReady = 'true'; this.message(message); },
        onError: error => { this.root.dataset.assReady = 'false'; this.message(`Lyric preview failed: ${String(error.message || error)}`); }});
    } else if (this.assText !== preview.ass) this.ass.setTrack(preview.ass);
    this.assText = preview.ass; this.message(message);
    const focused = this.root.getRootNode().activeElement?.dataset?.lineId;
    this.handles = new Map(); this.$('.hb-placement-handles').replaceChildren();
    for (const line of preview.lines) {
      const button = document.createElement('button'); button.className = 'hb-placement'; button.type = 'button';
      button.dataset.lineId = line.line_id; button.setAttribute('aria-label', `Move lyric line: ${line.label}`);
      const label = document.createElement('span'); label.className = 'hb-placement-label'; button.appendChild(label);
      button.addEventListener('pointerdown', e => this.pointerDown(e, line));
      button.addEventListener('keydown', e => this.keyMove(e, line));
      this.handles.set(line.line_id, button); this.$('.hb-placement-handles').appendChild(button);
    }
    this.render(this.audio.currentTime * 1000);
    if (focused) this.handles.get(focused)?.focus({preventScroll: true});
  }
  allowed(line) {
    if (this.callbacks.pending()) return false;
    if (this.selection.scope === 'song' && line.placement_exception) {
      this.message('This line has a placement exception. Choose Selected lyric line to move it, or reset its exception.'); return false;
    }
    if (this.selection.label === 'Lyric lines' && !this.selection.line_ids.includes(line.line_id)) {
      this.message('Choose this line in Lines to style before moving it.'); return false;
    }
    return true;
  }
  targetIds(line) { return this.selection.label === 'Lyric lines' ? this.selection.line_ids : [line.line_id]; }
  position(line, x, y) {
    return {scope: this.selection.scope, line_ids: this.targetIds(line),
      x: Math.round(Math.max(0, Math.min(this.preview.width, x))),
      y: Math.round(Math.max(0, Math.min(this.preview.height, y)))};
  }
  pointerDown(e, line) {
    if (e.button !== 0 || !this.allowed(line)) return;
    e.preventDefault(); e.currentTarget.focus({preventScroll: true});
    this.callbacks.select(line.word_id, false, false);
    this.drag = {line, pointer: e.pointerId, startX: e.clientX, startY: e.clientY, value: this.position(line, line.x, line.y)};
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  pointerMove(e) {
    const drag = this.drag; if (!drag || e.pointerId !== drag.pointer) return;
    const rect = this.frame.getBoundingClientRect();
    drag.value = this.position(drag.line, drag.line.x + (e.clientX - drag.startX) * this.preview.width / rect.width,
      drag.line.y + (e.clientY - drag.startY) * this.preview.height / rect.height);
    this.draftPosition(drag.line, drag.value); this.render(this.audio.currentTime * 1000);
  }
  draftPosition(line, value) {
    // Only the local preview changes during a gesture. One command on release.
    this.draft = {line, value};
    const byName = new Map(this.preview.lines.map(item => [item.ass_name, item]));
    const content = this.preview.ass.split('\n').map(row => {
      if (!row.startsWith('Dialogue:')) return row;
      const item = byName.get(row.split(',')[3]);
      if (!item || (value.scope === 'lines' ? !value.line_ids.includes(item.line_id) : item.placement_exception)) return row;
      return row.replace(/\\pos\(([^,]+),([^)]+)\)/, (_, x, y) =>
        `\\pos(${Number(x) + value.x - item.x},${Number(y) + value.y - item.y})`);
    }).join('\n');
    if (content !== this.assText) { this.ass?.setTrack(content); this.assText = content; }
  }
  pointerUp(e) {
    const drag = this.drag; if (!drag || drag.pointer !== e.pointerId) return;
    this.drag = null; this.callbacks.select(drag.line.word_id, true, false);
    if (drag.value.x !== drag.line.x || drag.value.y !== drag.line.y) {
      this.callbacks.commit('placement', drag.value);
      this.root.dataset.placementX = String(drag.value.x); this.root.dataset.placementY = String(drag.value.y);
    } else this.draft = null;
  }
  cancelDrag() {
    if (!this.drag) return;
    this.drag = null; this.draft = null;
    this.ass?.setTrack(this.preview.ass); this.assText = this.preview.ass;
    this.render(this.audio.currentTime * 1000);
  }
  keyMove(e, line) {
    const directions = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
    const dir = directions[e.key]; if (!dir) return;
    e.preventDefault(); e.stopPropagation(); if (!this.allowed(line)) return;
    const step = e.shiftKey ? 10 : 1, value = this.position(line, line.x + dir[0] * step, line.y + dir[1] * step);
    this.draftPosition(line, value); this.callbacks.select(line.word_id, true, false);
    this.callbacks.commit('placement', value);
  }
  render(ms) {
    if (!this.preview) return;
    this.ass?.setCurrentTime(ms / 1000); this.root.dataset.assClockMs = String(Math.round(ms));
    // The background remains paused. Its frame is sampled from the audio clock,
    // so seeking/looping/rate changes never establish a second running clock.
    if (!this.video.hidden && Number.isFinite(this.video.duration) && this.video.duration > 0) {
      const target = (ms / 1000) % this.video.duration;
      if (!this.video.seeking && Math.abs(this.video.currentTime - target) > .02) this.video.currentTime = target;
      this.root.dataset.backgroundClockMs = String(Math.round(this.video.currentTime * 1000));
    }
    const selected = this.preview.lines.find(line => line.word_id === this.callbacks.selected() || this.callbacks.selectedLine() === line.line_id);
    if (selected) this.$('.hb-preview-line').value = selected.line_id;
    for (const line of this.preview.lines) {
      const button = this.handles?.get(line.line_id); if (!button) continue;
      button.hidden = !this.selection.guides || ms < line.start_ms || ms >= line.end_ms;
      const moved = this.draft && (this.draft.value.scope === 'song' ? !line.placement_exception : this.draft.value.line_ids.includes(line.line_id));
      const dx = moved ? this.draft.value.x - line.x : 0, dy = moved ? this.draft.value.y - line.y : 0;
      button.style.left = `${(line.left + dx) / this.preview.width * 100}%`;
      button.style.top = `${(line.top + dy) / this.preview.height * 100}%`;
      button.style.width = `${line.width / this.preview.width * 100}%`;
      button.style.height = `${line.height / this.preview.height * 100}%`;
      button.setAttribute('aria-pressed', String(selected?.line_id === line.line_id));
      button.title = `X ${Math.round(line.x + dx)}, Y ${Math.round(line.y + dy)}. Drag to move. Arrow keys: 1 px; Shift: 10 px.`;
      button.firstChild.textContent = `${Math.round(line.x + dx)}, ${Math.round(line.y + dy)}${line.exception ? ' · line exception' : ''}`;
    }
  }
  dispose() { this.ass?.dispose(); if (this.workerBlob) URL.revokeObjectURL(this.workerBlob); this.video.pause(); this.video.removeAttribute('src'); }
}
