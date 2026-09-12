import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../heartbeam/editor_assets/presentation.js', import.meta.url), 'utf8');
const context = {console}; vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.Presentation = HBPresentation; globalThis.scenePosition = hbScenePosition;`, context);
const Prototype = context.Presentation.prototype;

test('preview fits portrait and landscape without changing its playback clock', () => {
  context.window = {innerWidth: 1440, innerHeight: 900};
  context.devicePixelRatio = 2;
  context.document = {documentElement: {style: {setProperty() {}}}};
  const pane = {getBoundingClientRect: () => ({top: 150})};
  const obj = Object.create(Prototype), calls = [];
  obj.frame = {style: {}, getBoundingClientRect: () => ({height: 200})};
  obj.root = {isConnected: true, clientWidth: 760,
    getRootNode: () => ({host: {closest: () => pane}}),
    getBoundingClientRect: () => ({height: 500})};
  obj.audio = {currentTime: 7.25};
  obj.ass = {resize: (...size) => calls.push(size)};
  obj.preview = {width: 1920, height: 1080};
  obj.fit();
  assert.equal(parseFloat(obj.frame.style.width), 760);
  obj.preview = {width: 1080, height: 1920};
  obj.fit();
  assert.ok(parseFloat(obj.frame.style.width) < 250);
  const [w, h] = calls.at(-1);
  assert.ok(h > w && h <= 868);
  assert.equal(obj.audio.currentTime, 7.25);
  context.devicePixelRatio = 1;
  obj.fit();
  assert.ok(Math.abs(calls.at(-1)[0] * 2 - w) <= 1);
});
function subject() {
  const line = {line_id:'a', ass_name:'Line0', x:960,y:850,word_id:'w0'};
  const another = {line_id:'b', ass_name:'Line1', x:200,y:120,word_id:'w1'};
  const obj = Object.create(Prototype), commits=[], selections=[], tracks=[];
  Object.assign(obj, {preview:{width:1920,height:1080,lines:[line,another], ass:'Dialogue: 0,0,4,Line0,,0,0,0,,{\\pos(960,850)}A\nDialogue: 0,4,8,Line1,,0,0,0,,{\\pos(200,120)}B'},
    selection:{scope:'lines',label:'Selected lyric line',line_ids:['a']},
    frame:{getBoundingClientRect:()=>({width:600,height:337.5})},
    ass:{setTrack:text=>tracks.push(text)},audio:{currentTime:0},root:{dataset:{}},
    callbacks:{pending:()=>false,select:(...args)=>selections.push(args),commit:(...args)=>commits.push(args)},
    render:()=>{},message:()=>{}});
  return {obj,line,another,commits,selections,tracks};
}
test('CSS-scaled dragging changes only local ASS until release, one command',()=>{
  const {obj,line,commits,tracks} = subject();
  obj.pointerDown({button:0,pointerId:1,clientX:300,clientY:200,preventDefault(){},currentTarget:{focus(){},setPointerCapture(){}}},line);
  obj.pointerMove({pointerId:1,clientX:340,clientY:155});
  obj.pointerMove({pointerId:1,clientX:350,clientY:150});
  assert.equal(commits.length,0);
  assert.match(tracks.at(-1),/\\pos\(1120,690\)/);
  assert.match(tracks.at(-1),/\\pos\(200,120\)/);
  obj.pointerUp({pointerId:1}); obj.pointerUp({pointerId:1});
  assert.equal(commits.length,1);
  assert.equal(commits[0][0],'placement');
  assert.equal(commits[0][1].x,1120); assert.equal(commits[0][1].y,690);
});
test('cancelled drag restores ASS and never commits',()=>{
  const {obj,line,commits,tracks}=subject();
  obj.drag={line,pointer:1,value:obj.position(line,100,200)};
  obj.cancelDrag();
  assert.equal(commits.length,0); assert.equal(tracks.at(-1),obj.preview.ass);
});
test('placement keyboard arrows cannot bubble into timing nudges',()=>{
  const {obj,line,commits}=subject(); let stopped=false,prevented=false;
  obj.keyMove({key:'ArrowRight',shiftKey:true,preventDefault(){prevented=true},stopPropagation(){stopped=true}},line);
  assert.equal(stopped,true); assert.equal(prevented,true);
  assert.equal(commits[0][0],'placement'); assert.equal(commits[0][1].x,970);
});
test('song placement preserves explicit line positions',()=>{
  const {obj,line,another,tracks}=subject(); another.placement_exception=true;
  obj.selection={scope:'song',label:'Whole song'};
  obj.draftPosition(line,obj.position(line,500,600));
  assert.match(tracks.at(-1),/\\pos\(500,600\)/);
  assert.match(tracks.at(-1),/\\pos\(200,120\)/);
  assert.equal(obj.allowed(another),false);
});

test('moving preview guides share the compiled scene position across seeks',()=>{
  const line={segments:[{start_ms:1000,end_ms:2000,from_top:300,to_top:200,move_ms:200}]};
  assert.equal(context.scenePosition(line,999),null);
  assert.equal(context.scenePosition(line,1000),300);
  assert.equal(context.scenePosition(line,1100),250);
  assert.equal(context.scenePosition(line,1500),200);
  assert.equal(context.scenePosition(line,2000),null);
  assert.equal(context.scenePosition(line,1050),275);
});

test('dragging a rolling line translates motion and clipping without changing timing',()=>{
  const {obj,line,tracks}=subject();
  obj.preview.ass='Dialogue: 0,1,4,Line0,,0,0,0,,{\\move(960,700,960,600,0,220)\\clip(0,600,1920,900)}{\\kt-10\\kf40}A';
  obj.draftPosition(line,obj.position(line,980,870));
  assert.match(tracks.at(-1),/\\move\(980,720,980,620,0,220\)/);
  assert.match(tracks.at(-1),/\\clip\(0,620,1920,920\)/);
  assert.match(tracks.at(-1),/\\kt-10\\kf40/);
});
