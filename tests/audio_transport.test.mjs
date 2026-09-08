import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

class Buffer {
  constructor(channels, length, sr) { this.numberOfChannels=channels; this.length=length; this.sampleRate=sr; this.duration=length/sr; this.data=Array.from({length:channels},()=>new Float32Array(length)); }
  getChannelData(ch) { return this.data[ch]; }
}
class Context {
  constructor({sampleRate=8000}={}) { this.sampleRate=sampleRate; this.currentTime=0; this.destination={}; this.starts=[]; }
  createBuffer(c,n,sr) { return new Buffer(c,n,sr); }
  // Deliberately omit cancelAndHoldAtTime: Firefox does not implement it.
  createGain() { return {gain:{value:0,events:[],setTargetAtTime(v){this.value=v;},
    setValueAtTime(v,t){this.events.push(['set',v,t]);},
    linearRampToValueAtTime(v,t){this.events.push(['ramp',v,t]);},
    cancelScheduledValues(t){this.events=this.events.filter(e=>e[2]<t);this.events.push(['cancel',t]);}},connect(){},disconnect(){}}; }
  createBufferSource() { const context=this; return {playbackRate:{value:1},connect(){},disconnect(){},stop(){},start(t,offset){context.starts.push([t,offset]);}}; }
  async resume() {}
  close() {}
}
const scope={EventTarget,Event,AudioContext:Context,queueMicrotask,fetch,setTimeout,clearTimeout};
vm.createContext(scope);
vm.runInContext(fs.readFileSync(new URL('../heartbeam/editor_assets/audio_transport.js',import.meta.url),'utf8')+'\nthis.Transport=HBTransport;',scope);

function fixture() {
  const transport=new scope.Transport(), context=transport.ensureContext(8000);
  const clean=context.createBuffer(2,32000,8000), original=context.createBuffer(2,32000,8000);
  clean.data.forEach(a=>a.fill(.1)); original.data.forEach(a=>a.fill(.5));
  transport.decoded=async url=>url==='clean'?clean:original;
  transport.buffer=clean; transport.duration=4; transport.readyState=4; transport.src='karaoke';
  const data={clean:'clean',original:'original',sample_rate:8000,revision:1,knots:[[0,.2],[32000,.2]],
    templates:[[[0,0],[32000,0]],[[0,1],[32000,1]]],selection:{value:.2}};
  return {transport,context,data};
}

test('preparing a mix while another source plays never adds elapsed time twice',async()=>{
  const {transport:t,context:c,data}=fixture();
  await t.play(); c.currentTime=1.25;
  await t.configureMix(data); assert.equal(t.currentTime,1.25);
  t.audition(.8); assert.equal(t.currentTime,1.25);
  c.currentTime=1.5; assert.equal(t.currentTime,1.5);
});

test('selection alone preserves the existing mix; slider audition uses compiled templates',async()=>{
  const {transport:t,data}=fixture(); await t.configureMix(data);
  assert.ok(Math.abs(t.mix.base.getChannelData(0)[12000]-.2)<1e-7);
  t.audition(.7);
  assert.equal(t.mix.base.getChannelData(0)[12000],0);
  assert.equal(t.mix.delta.getChannelData(0)[12000],1);
  assert.equal(t.amount,.7);
});

test('mix signals and envelopes start at the same clock and loop boundaries',async()=>{
  const {transport:t,context:c,data}=fixture(); await t.configureMix(data);
  t.src='heartbeam:mix'; t.currentTime=1; t.setLoop([1,2]); await t.play();
  assert.equal(t.nodes.length,5);
  for(const node of t.nodes) { assert.equal(node.loop,true); assert.equal(node.loopStart,1); assert.equal(node.loopEnd,2); }
  assert.ok(c.starts.every(([at,offset])=>at===0 && offset===1));
  c.currentTime=100.25; assert.equal(t.currentTime,1.25); // no visual timer required
});

test('changing speed or seeking preserves a single song position',async()=>{
  const {transport:t,context:c}=fixture(); await t.play(); c.currentTime=1;
  t.playbackRate=.5; assert.equal(t.currentTime,1);
  c.currentTime=2; assert.equal(t.currentTime,1.5);
  t.currentTime=2.5; assert.equal(t.currentTime,2.5);
  c.currentTime=3; assert.equal(t.currentTime,3);
});

test('repeated scrubbing keeps Play or Pause state and resumes from the latest seek',async()=>{
  const {transport:t,context:c}=fixture();
  t.currentTime=2; assert.equal(t.paused,true); assert.equal(t.nodes.length,0);
  await t.play(); c.currentTime=.2;
  for (const time of [1.8,.4,2.5,1.2]) { t.currentTime=time; assert.equal(t.paused,false); assert.equal(t.currentTime,time); }
  c.currentTime=.7; assert.equal(t.currentTime,1.7);
  t.pause(); t.currentTime=.8; c.currentTime=1.5;
  assert.equal(t.paused,true); assert.equal(t.currentTime,.8); assert.equal(t.nodes.length,0);
});

test('seeking preserves the fade level even before the previous fade-in finishes',async()=>{
  const {transport:t,context:c,data}=fixture();
  await t.configureMix(data); t.src='heartbeam:mix'; await t.play();
  const first=t.output.gain, level=t.mix.headroom;
  c.currentTime=.005; t.currentTime=2;
  assert.equal(t.paused,false); assert.equal(c.starts.at(-1)[1],2);
  assert.ok(Math.abs(first.events.at(-2)[1]-level/3)<1e-12);
  assert.deepEqual(first.events.slice(0,2),[['set',0,0],['cancel',.005]]);
  assert.equal(first.events.at(-2)[0],'ramp'); assert.equal(first.events.at(-2)[2],.005);
  assert.deepEqual(first.events.at(-1),['ramp',0,.020]);
  const second=t.output.gain;
  c.currentTime=.008; t.currentTime=1;
  assert.ok(Math.abs(second.events.at(-2)[1]-level*.2)<1e-12);
  const third=t.output.gain;
  c.currentTime=.030; t.currentTime=3;
  assert.equal(third.events.at(-2)[1],level); // Full level after fade-in.
  assert.equal(t.retired.size,3);
  t.pause(); assert.equal(t.nodes.length,0); assert.equal(t.retired.size,0);
});

test('stale reference preparation cannot replace a newer preview',async()=>{
  const {transport:t,data}=fixture(); const original=t.decoded; let release;
  t.decoded=url=>url==='slow'?new Promise(r=>release=r):original(url);
  const stale=t.configureMix({...data,clean:'slow',revision:1});
  const latest=t.configureMix({...data,revision:2});
  await latest; release(await original('clean')); await stale;
  assert.equal(t.mix.revision,2);
});
