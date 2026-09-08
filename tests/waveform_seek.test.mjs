import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const scope = {};
vm.createContext(scope);
vm.runInContext(fs.readFileSync(new URL('../heartbeam/editor_assets/timeline.js', import.meta.url), 'utf8')
  .replace('export default function (component)', 'function mount(component)') +
  '\nthis.Seek = HBWaveformSeek; this.follow = hbFollowPosition;', scope);

function fixture() {
  const calls = [], captures = new Set();
  const view = {durationMs:100000, width:2000, viewport:500, scrollLeft:500};
  let time = 0, enabled = true, playing = false;
  const surface = {getBoundingClientRect:()=>({left:100, width:250}), focus(){},
    setPointerCapture:id=>captures.add(id), hasPointerCapture:id=>captures.has(id), releasePointerCapture:id=>captures.delete(id)};
  const seek = new scope.Seek(surface, {geometry:()=>view, enabled:()=>enabled,
    seek:ms=>{time=ms; calls.push(ms);}, currentMs:()=>time, play:()=>{playing=!playing;}});
  const event = (x, patch={})=>({clientX:x, button:0, pointerId:7, isPrimary:true, preventDefault(){}, ...patch});
  return {seek, calls, view, captures, event, get time(){return time;}, get playing(){return playing;},
    disable(){enabled=false;}};
}

test('waveform click and drag seek through CSS scale, zoom and horizontal scroll',()=>{
  const f=fixture();
  f.seek.down(f.event(225));
  assert.equal(f.time,37500); assert.equal(f.seek.active,true); assert.equal(f.captures.has(7),true);
  f.seek.move(f.event(300)); assert.equal(f.time,45000);
  f.seek.up(f.event(350)); assert.equal(f.time,50000);
  assert.equal(f.seek.active,false); assert.equal(f.captures.size,0);
  f.seek.move(f.event(100)); assert.equal(f.time,50000);
});

test('dragging outside the waveform clamps to its visible time span',()=>{
  const f=fixture(); f.seek.down(f.event(-100)); assert.equal(f.time,25000);
  f.seek.move(f.event(900)); assert.equal(f.time,50000);
  f.seek.up(f.event(900)); assert.equal(f.calls.length,2);
});

test('cancel and loading changes release capture and ignore late pointer events',()=>{
  const f=fixture(); f.seek.down(f.event(200)); const at=f.time;
  f.seek.move(f.event(300,{pointerId:8})); assert.equal(f.time,at);
  f.seek.cancel(); f.seek.up(f.event(300)); assert.equal(f.time,at);
  f.seek.down(f.event(200)); f.disable(); f.seek.move(f.event(300));
  assert.equal(f.seek.active,false); assert.equal(f.captures.size,0); assert.equal(f.time,at);
});

test('right clicks and additional touches never start a scrub',()=>{
  const f=fixture();
  f.seek.down(f.event(200,{button:2})); f.seek.down(f.event(200,{isPrimary:false}));
  assert.equal(f.calls.length,0); assert.equal(f.seek.active,false);
});

test('waveform keyboard controls seek without bubbling into lyric nudges',()=>{
  const f=fixture(); let prevented=0, stopped=0;
  const key=(key,shiftKey=false)=>({key,shiftKey,preventDefault(){prevented++;},stopPropagation(){stopped++;}});
  f.seek.keyDown(key('ArrowRight')); assert.equal(f.time,1000);
  f.seek.keyDown(key('ArrowLeft',true)); assert.equal(f.time,900);
  f.seek.keyDown(key('End')); assert.equal(f.time,100000);
  f.seek.keyDown(key('ArrowRight')); assert.equal(f.time,100000);
  f.seek.keyDown(key('Home')); assert.equal(f.time,0);
  f.seek.keyDown(key(' ')); assert.equal(f.playing,true);
  assert.equal(prevented,6); assert.equal(stopped,6);
  f.seek.keyDown(key('Tab')); assert.equal(stopped,6);
});

test('zoomed playback follows at the viewport edge and follows loop wraps backward',()=>{
  assert.equal(scope.follow(30000,100000,2000,500,500),500);
  assert.equal(scope.follow(49500,100000,2000,500,500),890);
  assert.equal(scope.follow(10000,100000,2000,500,890),100);
  assert.equal(scope.follow(100000,100000,2000,500,0),1500);
  assert.equal(scope.follow(100000,100000,500,500,0),0);
});
