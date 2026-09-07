// One AudioContext clock for every source, waveform, loop and ASS frame.
// Compiled envelope buffers run on the audio thread, including background tabs.
class HBTransport extends EventTarget {
  constructor() {
    super(); this.context = null; this.cache = new Map(); this.nodes = []; this.retired = new Set();
    this._time = 0; this._rate = 1; this._paused = true; this.readyState = 0;
    this.duration = 0; this.loadEpoch = 0; this.loopRange = null; this.mix = null;
  }
  get paused() { return this._paused; }
  get playbackRate() { return this._rate; }
  set playbackRate(value) { this._time = this.currentTime; this._rate = value; this.restart(); }
  get currentTime() {
    let time = this._time + (!this._paused ? Math.max(0, this.context.currentTime - this.anchor) * this._rate : 0);
    if (this.loopRange && time >= this.loopRange[1])
      time = this.loopRange[0] + (time - this.loopRange[0]) % (this.loopRange[1] - this.loopRange[0]);
    return Math.min(this.duration, time);
  }
  set currentTime(time) {
    this._time = Math.max(0, Math.min(this.duration, time)); this.restart();
    queueMicrotask(() => this.dispatchEvent(new Event('seeked')));
  }
  ensureContext(sr) { if (!this.context) this.context = new AudioContext(sr ? {sampleRate: sr} : {}); return this.context; }
  async decoded(url) {
    if (!this.cache.has(url)) this.cache.set(url, (async () => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Audio request failed (${response.status})`);
      return this.ensureContext().decodeAudioData(await response.arrayBuffer());
    })().catch(e => { this.cache.delete(url); throw e; }));
    return this.cache.get(url);
  }
  async load() {
    const epoch = ++this.loadEpoch;
    try {
      let buffer;
      if (this.src === 'heartbeam:mix') {
        if (!this.mix) throw new Error('Calibrated vocal references have not loaded.');
        buffer = this.mix.clean;
      } else buffer = await this.decoded(this.src);
      if (epoch !== this.loadEpoch) return;
      this.buffer = buffer; this.duration = buffer.duration; this.readyState = 4;
      this.dispatchEvent(new Event('loadedmetadata'));
    } catch (error) {
      if (epoch !== this.loadEpoch) return;
      this.error = {code: error.message}; this.dispatchEvent(new Event('error'));
    }
  }
  async play() {
    if (!this.readyState) return;
    await this.ensureContext().resume();
    if (!this._paused) return;
    if (this._time >= this.duration) this._time = this.loopRange?.[0] || 0;
    this._paused = false; this.restart(); this.dispatchEvent(new Event('play'));
  }
  pause() {
    this._time = this.currentTime; this._paused = true; this.stopNodes();
    this.dispatchEvent(new Event('pause'));
  }
  setLoop(range) {
    if (range) range = [Math.max(0, range[0]), Math.min(this.duration, range[1])];
    if (range && range[1] <= range[0]) range = null;
    if (JSON.stringify(range) === JSON.stringify(this.loopRange)) return;
    this._time = this.currentTime; this.loopRange = range; this.restart();
  }
  stopNodes() {
    for (const node of this.nodes) { try { node.stop(); } catch {} node.disconnect(); }
    this.nodes = [];
    for (const node of this.gains || []) node.disconnect(); this.gains = [];
    for (const old of this.retired) {
      clearTimeout(old.timer);
      for (const node of old.nodes) { try { node.stop(); } catch {} node.disconnect(); }
      for (const gain of old.gains) gain.disconnect();
    }
    this.retired.clear(); this.output = null;
  }
  restart() {
    if (!this.context) return;
    this.anchor = this.context.currentTime;
    if (this._paused || !this.buffer) { this.stopNodes(); return; }
    // A new mix/seek is crossfaded on the audio thread. Retiring sources keep
    // running for 20 ms, so changing a level mid-word cannot splice waveforms.
    const old = {nodes: this.nodes, gains: this.gains || [], timer: null};
    if (old.nodes.length && this.output) {
      this.output.gain.cancelAndHoldAtTime(this.context.currentTime);
      this.output.gain.linearRampToValueAtTime(0, this.context.currentTime + .015);
      for (const node of old.nodes) { try { node.stop(this.context.currentTime + .020); } catch {} }
      this.retired.add(old);
      old.timer = setTimeout(() => { old.nodes.forEach(n => n.disconnect()); old.gains.forEach(n => n.disconnect()); this.retired.delete(old); }, 80);
    }
    this.nodes = []; this.gains = [];
    if (this.loopRange && this._time >= this.loopRange[1]) this._time = this.loopRange[0];
    const context = this.context, startAt = context.currentTime;
    this.anchor = startAt;
    const gain = value => { const g = context.createGain(); g.gain.value = value; this.gains.push(g); return g; };
    const output = this.output = gain(0); output.connect(context.destination);
    output.gain.setValueAtTime(0, startAt);
    output.gain.linearRampToValueAtTime(this.src === 'heartbeam:mix' ? this.mix.headroom : 1, startAt + .015);
    const source = (buffer, target) => {
      const node = context.createBufferSource(); node.buffer = buffer; node.playbackRate.value = this._rate;
      if (this.loopRange) { node.loop = true; [node.loopStart, node.loopEnd] = this.loopRange; }
      node.connect(target); node.start(startAt, this._time); this.nodes.push(node); return node;
    };
    let main;
    if (this.src === 'heartbeam:mix' && this.mix) {
      const mix = this.mix;
      main = source(mix.clean, output);
      const base = gain(0); base.connect(output); source(mix.residual, base); source(mix.base, base.gain);
      const delta = gain(0), amount = gain(this.amount ?? 0);
      delta.connect(amount); amount.connect(output); source(mix.residual, delta); source(mix.delta, delta.gain);
      this.amountNode = amount;
    } else {
      this.amountNode = null; main = source(this.buffer, output);
    }
    main.onended = () => {
      if (this.nodes[0] === main && !this.loopRange && !this._paused) {
        this._time = this.duration; this._paused = true; this.stopNodes(); this.dispatchEvent(new Event('ended'));
      }
    };
  }
  envelope(knots, basis, inputSampleRate) {
    const buffer = this.context.createBuffer(1, basis.length, basis.sampleRate), values = buffer.getChannelData(0);
    const ratio = basis.sampleRate / inputSampleRate;
    for (let k = 0; k < knots.length - 1; k++) {
      const [left, a] = knots[k], [right, b] = knots[k + 1];
      const start = Math.max(0, Math.ceil(left * ratio)), end = Math.min(values.length, Math.ceil(right * ratio));
      if (a === b) values.fill(a, start, end);
      else for (let i = start; i < end; i++) values[i] = a + (b - a) * (i / ratio - left) / (right - left);
    }
    return buffer;
  }
  async configureMix(data) {
    const token = this.mixToken = (this.mixToken || 0) + 1;
    if (!data) { this.mix = null; return; }
    this.ensureContext(data.sample_rate);
    const [clean, original] = await Promise.all([this.decoded(data.clean), this.decoded(data.original)]);
    if (token !== this.mixToken) return false;
    if (clean.length !== original.length || clean.sampleRate !== original.sampleRate || clean.numberOfChannels !== original.numberOfChannels)
      throw new Error('Decoded vocal references do not share a sample basis.');
    let residual = this.mix?.clean === clean && this.mix?.original === original ? this.mix.residual : null;
    let headroom = this.mix?.headroom;
    if (!residual) {
      residual = this.context.createBuffer(clean.numberOfChannels, clean.length, clean.sampleRate);
      let peak = 1;
      for (let ch = 0; ch < clean.numberOfChannels; ch++) {
        const c = clean.getChannelData(ch), o = original.getChannelData(ch), d = residual.getChannelData(ch);
        for (let i = 0; i < c.length; i++) { d[i] = o[i] - c[i]; peak = Math.max(peak, Math.abs(c[i]), Math.abs(o[i])); }
      }
      headroom = .95 / peak;
    }
    const templates = data.templates || [data.knots, data.knots];
    const templateBase = this.envelope(templates[0], clean, data.sample_rate);
    const templateDelta = this.envelope(templates[1], clean, data.sample_rate);
    const a = templateBase.getChannelData(0), b = templateDelta.getChannelData(0);
    for (let i = 0; i < b.length; i++) b[i] -= a[i];
    if (token !== this.mixToken) return false;
    const base = this.envelope(data.knots, clean, data.sample_rate);
    const delta = this.context.createBuffer(1, clean.length, clean.sampleRate);
    this.mix = {clean, original, residual, headroom, base, delta, templateBase, templateDelta, revision: data.revision};
    this.amount = data.selection?.value ?? 0;
    if (this.src === 'heartbeam:mix') { this._time = this.currentTime; this.buffer = clean; this.duration = clean.duration; this.restart(); }
    return true;
  }
  audition(value) {
    this.amount = value;
    if (this.mix && !this.mix.previewing) {
      if (this.src === 'heartbeam:mix') this._time = this.currentTime;
      this.mix.previewing = true;
      this.mix.base = this.mix.templateBase; this.mix.delta = this.mix.templateDelta;
      if (this.src === 'heartbeam:mix') this.restart();
    }
    if (this.amountNode) this.amountNode.gain.setTargetAtTime(value, this.context.currentTime, .008);
  }
  dispose() { this.pause(); this.loadEpoch++; this.mixToken++; this.cache.clear(); this.context?.close(); }
}
