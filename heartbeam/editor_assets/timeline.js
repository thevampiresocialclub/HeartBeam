// HeartBeam timing editor: waveform, transport and word handles.
//
// Everything high-frequency happens here and never touches Python: playback,
// the playhead, dragging a word boundary, hover, zoom. Python hears from us
// exactly once per COMMITTED gesture -- one drag equals one trigger equals one
// undo step. That is the whole architectural bet of P03, and it is why a
// 250-word song stays responsive while Streamlit reruns are measured in
// hundreds of milliseconds.
//
// The audio element is the single clock. The playhead, the highlighted word and
// the loop all read from it rather than keeping their own timers, so nothing can
// drift out of sync with what you actually hear.

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;

  // Streamlit re-invokes this module on every data change with the SAME parent
  // element. Appending blindly stacks a second timeline (and a second <audio>)
  // on every rerun, so remove our previous root first. Only our own node is
  // touched: clearing the parent would destroy the HTML/CSS Streamlit mounted.
  parentElement.querySelectorAll(".hb-editor").forEach((node) => node.remove());
  // Listeners attached to window survive node removal, so abort the previous
  // mount's listeners explicitly rather than leaking one set per rerun.
  if (parentElement._hbAbort) parentElement._hbAbort.abort();
  const controller = new AbortController();
  parentElement._hbAbort = controller;
  const signal = controller.signal;

  const root = document.createElement("div");
  root.className = "hb-editor";
  parentElement.appendChild(root);

  root.innerHTML = `
    <div class="hb-toolbar">
      <button class="hb-btn" data-act="play" title="Play/pause (space)">Play</button>
      <button class="hb-btn" data-act="loop" title="Loop the selected word">Loop</button>
      <span class="hb-time"><span class="hb-cur">0:00.00</span> / <span class="hb-dur">0:00.00</span></span>
      <label class="hb-speed">Speed
        <select class="hb-rate">
          <option value="0.5">0.5x</option>
          <option value="0.75">0.75x</option>
          <option value="1" selected>1x</option>
          <option value="1.5">1.5x</option>
        </select>
      </label>
      <label class="hb-zoomwrap">Zoom
        <input class="hb-zoom" type="range" min="1" max="20" step="1" value="1">
      </label>
      <span class="hb-sel"></span>
    </div>
    <div class="hb-scroll"><canvas class="hb-canvas"></canvas></div>
    <div class="hb-hint">Drag a word's edge to change its timing. Click to select and seek.
      Space plays. Shift+click sets the loop.</div>
  `;

  const canvas = root.querySelector(".hb-canvas");
  const scroller = root.querySelector(".hb-scroll");
  const ctx = canvas.getContext("2d");
  const curEl = root.querySelector(".hb-cur");
  const durEl = root.querySelector(".hb-dur");
  const selEl = root.querySelector(".hb-sel");

  const state = {
    words: (data && data.words) || [],
    peaks: (data && data.peaks) || { mins: [], maxs: [], duration_ms: 0 },
    durationMs: (data && data.duration_ms) || 0,
    selectedId: (data && data.selected_id) || null,
    zoom: 1,
    looping: false,
    drag: null,          // {wordId, edge, startX, origStart, origEnd}
    dpr: window.devicePixelRatio || 1,
  };

  const audio = new Audio();
  audio.preload = "auto";
  // Attach it to the DOM (hidden). A detached Audio() works, but an attached
  // one can be inspected by devtools and by tests, which is the difference
  // between "playback is broken" and knowing exactly why.
  audio.className = "hb-audio";
  audio.hidden = true;
  root.appendChild(audio);
  if (data && data.audio_src) audio.src = data.audio_src;

  // Surface load failures instead of dying quietly. A data URL that is too
  // large or mistyped otherwise looks identical to "the song is silent".
  audio.addEventListener("error", () => {
    const err = audio.error;
    setStatus(`audio failed to load (code ${err ? err.code : "?"})`, true);
  }, { signal });

  const HANDLE_PX = 6;
  const ROW_TOP = 0.62;      // fraction of height where word blocks start

  const fmt = (ms) => {
    if (!isFinite(ms)) ms = 0;
    const t = Math.max(0, ms) / 1000;
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return `${m}:${s.toFixed(2).padStart(5, "0")}`;
  };

  function contentWidth() {
    return Math.max(scroller.clientWidth * state.zoom, scroller.clientWidth);
  }
  function msToX(ms) {
    if (!state.durationMs) return 0;
    return (ms / state.durationMs) * contentWidth();
  }
  function xToMs(x) {
    const w = contentWidth();
    return w ? (x / w) * state.durationMs : 0;
  }

  function resize() {
    const w = contentWidth();
    const h = 150;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    canvas.width = Math.floor(w * state.dpr);
    canvas.height = Math.floor(h * state.dpr);
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    draw();
  }

  function draw() {
    const w = contentWidth();
    const h = 150;
    const waveH = h * ROW_TOP;
    ctx.clearRect(0, 0, w, h);

    // Waveform. Peaks are quantised to +/-127 in Python.
    const mins = state.peaks.mins || [];
    const maxs = state.peaks.maxs || [];
    const n = mins.length;
    if (n) {
      ctx.strokeStyle = "rgba(130,150,180,0.85)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      const mid = waveH / 2;
      for (let px = 0; px < w; px++) {
        const i = Math.min(n - 1, Math.floor((px / w) * n));
        const lo = (mins[i] / 127) * (waveH / 2);
        const hi = (maxs[i] / 127) * (waveH / 2);
        ctx.moveTo(px + 0.5, mid - hi);
        ctx.lineTo(px + 0.5, mid - lo);
      }
      ctx.stroke();
    }

    // Word blocks.
    const blockTop = waveH + 6;
    const blockH = h - blockTop - 4;
    ctx.font = "12px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (const word of state.words) {
      if (word.start_ms == null || word.end_ms == null) continue;
      const x0 = msToX(word.start_ms);
      const x1 = Math.max(x0 + 2, msToX(word.end_ms));
      const selected = word.id === state.selectedId;
      ctx.fillStyle = selected ? "rgba(255,215,0,0.35)"
        : word.low_confidence ? "rgba(230,120,90,0.28)"
          : "rgba(120,170,255,0.22)";
      ctx.fillRect(x0, blockTop, x1 - x0, blockH);
      ctx.strokeStyle = selected ? "rgba(255,215,0,0.95)" : "rgba(120,170,255,0.55)";
      ctx.lineWidth = selected ? 2 : 1;
      ctx.strokeRect(x0 + 0.5, blockTop + 0.5, x1 - x0 - 1, blockH - 1);
      ctx.fillStyle = "rgba(235,240,250,0.95)";
      ctx.save();
      ctx.beginPath();
      ctx.rect(x0 + 2, blockTop, Math.max(0, x1 - x0 - 4), blockH);
      ctx.clip();
      ctx.fillText(word.text, x0 + 4, blockTop + blockH / 2);
      ctx.restore();
    }

    // Unresolved words get a marker on the baseline so they are findable.
    for (const word of state.words) {
      if (word.start_ms != null && word.end_ms != null) continue;
      ctx.fillStyle = "rgba(230,120,90,0.9)";
      ctx.fillRect(0, h - 3, w, 1);
      break;
    }

    // Playhead.
    const px = msToX(audio.currentTime * 1000);
    ctx.strokeStyle = "rgba(255,90,120,0.95)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(px, 0);
    ctx.lineTo(px, h);
    ctx.stroke();
  }

  function wordAt(ms) {
    return state.words.find(
      (w) => w.start_ms != null && w.end_ms != null &&
        ms >= w.start_ms && ms < w.end_ms);
  }

  function hitTest(x) {
    // Edge handles win over the body so a boundary is always grabbable.
    for (const word of state.words) {
      if (word.start_ms == null || word.end_ms == null) continue;
      const x0 = msToX(word.start_ms);
      const x1 = msToX(word.end_ms);
      if (Math.abs(x - x0) <= HANDLE_PX) return { word, edge: "start" };
      if (Math.abs(x - x1) <= HANDLE_PX) return { word, edge: "end" };
    }
    const ms = xToMs(x);
    const word = wordAt(ms);
    return word ? { word, edge: null } : null;
  }

  function localX(evt) {
    const rect = canvas.getBoundingClientRect();
    return evt.clientX - rect.left;
  }

  function select(word) {
    state.selectedId = word ? word.id : null;
    selEl.textContent = word ? `Selected: ${word.text}` : "";
    draw();
    if (word) setTriggerValue("selected", word.id);
  }

  canvas.addEventListener("mousedown", (evt) => {
    const x = localX(evt);
    const hit = hitTest(x);
    if (!hit) return;
    if (evt.shiftKey) {
      state.looping = true;
      select(hit.word);
      return;
    }
    if (hit.edge) {
      // Grabbing a handle also selects the word, so it is obvious what is
      // about to move.
      select(hit.word);
      state.drag = {
        wordId: hit.word.id, edge: hit.edge, startX: x,
        origStart: hit.word.start_ms, origEnd: hit.word.end_ms,
      };
      canvas.style.cursor = "ew-resize";
    } else {
      select(hit.word);
      audio.currentTime = hit.word.start_ms / 1000;
      draw();
    }
  });

  canvas.addEventListener("mousemove", (evt) => {
    const x = localX(evt);
    if (!state.drag) {
      const hit = hitTest(x);
      canvas.style.cursor = hit ? (hit.edge ? "ew-resize" : "pointer") : "default";
      return;
    }
    // Live preview only. Python hears nothing until mouseup.
    const word = state.words.find((w) => w.id === state.drag.wordId);
    if (!word) return;
    const deltaMs = xToMs(x) - xToMs(state.drag.startX);
    if (state.drag.edge === "start") {
      word.start_ms = Math.max(0, Math.min(state.drag.origStart + deltaMs, word.end_ms - 10));
    } else {
      word.end_ms = Math.min(state.durationMs,
        Math.max(state.drag.origEnd + deltaMs, word.start_ms + 10));
    }
    draw();
  });

  function commitDrag() {
    if (!state.drag) return;
    const drag = state.drag;
    const word = state.words.find((w) => w.id === drag.wordId);
    state.drag = null;
    canvas.style.cursor = "default";
    if (!word) return;
    const start = Math.round(word.start_ms);
    const end = Math.round(word.end_ms);
    word.start_ms = start;
    word.end_ms = end;
    draw();

    // A click that merely landed on a handle is a SELECTION, not an edit.
    // Without this, clicking near a boundary commits an unchanged timing:
    // it marks the project dirty and consumes an undo step for no change,
    // which the contract explicitly forbids.
    if (start === Math.round(drag.origStart) && end === Math.round(drag.origEnd)) {
      return;
    }
    // One committed gesture, one message, one undo step.
    setTriggerValue("timing_edit", {
      word_id: word.id, start_ms: start, end_ms: end, nonce: Date.now(),
    });
  }

  window.addEventListener("mouseup", commitDrag, { signal });

  root.querySelector('[data-act="play"]').addEventListener("click", togglePlay);
  root.querySelector('[data-act="loop"]').addEventListener("click", () => {
    state.looping = !state.looping;
    root.querySelector('[data-act="loop"]').classList.toggle("on", state.looping);
  });
  root.querySelector(".hb-rate").addEventListener("change", (e) => {
    // Rate changes how fast the clock advances. It must never touch stored
    // timestamps, which is why nothing is sent to Python here.
    audio.playbackRate = parseFloat(e.target.value);
  });
  root.querySelector(".hb-zoom").addEventListener("input", (e) => {
    state.zoom = parseInt(e.target.value, 10);
    resize();
  });

  function setStatus(message, isError) {
    const el = root.querySelector(".hb-hint");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("err", !!isError);
  }

  function togglePlay() {
    const btn = root.querySelector('[data-act="play"]');
    if (audio.paused) {
      audio.play().then(() => {
        btn.textContent = "Pause";
      }).catch((err) => {
        // Report rather than swallow: an autoplay rejection and a decode
        // failure are different problems and used to look identical.
        btn.textContent = "Play";
        setStatus(`could not start playback: ${err && err.name ? err.name : err}`, true);
      });
    } else {
      audio.pause();
      btn.textContent = "Play";
    }
  }

  // Space plays, but never while the user is typing in a text box.
  window.addEventListener("keydown", (evt) => {
    const t = evt.target;
    const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
      t.isContentEditable);
    if (typing) return;
    if (evt.code === "Space") { evt.preventDefault(); togglePlay(); }
  }, { signal });

  audio.addEventListener("loadedmetadata", () => {
    if (!state.durationMs && isFinite(audio.duration)) {
      state.durationMs = audio.duration * 1000;
    }
    durEl.textContent = fmt(state.durationMs);
    resize();
  });

  // The display is driven by TWO schedulers on purpose. requestAnimationFrame
  // gives a smooth playhead when the page is compositing, but it does not fire
  // at all in a background tab, an occluded window or an embedded webview --
  // and audio keeps playing regardless. Relying on rAF alone lets the playhead
  // and clock freeze while the song advances, which is precisely the drift the
  // editor exists to avoid. A modest interval guarantees updates everywhere;
  // the timestamp guard stops the two schedulers doing double work.
  let lastTickMs = 0;
  const MIN_TICK_GAP_MS = 25;

  function tick() {
    if (signal.aborted) return true;          // superseded by a newer mount
    const now = performance.now();
    if (now - lastTickMs < MIN_TICK_GAP_MS) return false;
    lastTickMs = now;
    render();
    return false;
  }

  function render() {
    const ms = audio.currentTime * 1000;
    curEl.textContent = fmt(ms);
    if (state.looping && state.selectedId) {
      const word = state.words.find((w) => w.id === state.selectedId);
      if (word && word.start_ms != null) {
        const pad = 250;
        if (ms > word.end_ms + pad) audio.currentTime = Math.max(0, word.start_ms - pad) / 1000;
      }
    }
    draw();
  }

  function rafLoop() {
    if (tick()) return;                        // aborted
    requestAnimationFrame(rafLoop);
  }

  const intervalId = setInterval(() => {
    if (tick()) clearInterval(intervalId);
  }, 60);
  signal.addEventListener("abort", () => {
    clearInterval(intervalId);
    audio.pause();
  });

  durEl.textContent = fmt(state.durationMs);
  resize();
  requestAnimationFrame(rafLoop);
  window.addEventListener("resize", resize, { signal });
}
