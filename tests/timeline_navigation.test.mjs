import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../heartbeam/editor_assets/timeline.js', import.meta.url), 'utf8')
  .replace('export default function (component)', 'function mount(component)');
const context = {console}; vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.lineTarget = hbLineTarget;`, context);
const target = context.lineTarget;
const lines = [
  {line_id:'a', start_ms:500, end_ms:1800},
  {line_id:'b', start_ms:1800, end_ms:3800},
  {line_id:'c', start_ms:3800, end_ms:5800},
];

test('next and previous lyric navigation uses the preview display boundaries',()=>{
  assert.equal(target(lines, null, 0, 1).line_id, 'a');
  assert.equal(target(lines, null, 1000, 1).line_id, 'b');
  assert.equal(target(lines, null, 4200, -1).line_id, 'b');
});

test('selected lyric wins and navigation clamps at song ends',()=>{
  assert.equal(target(lines, 'b', 0, 1).line_id, 'c');
  assert.equal(target(lines, 'a', 9000, -1).line_id, 'a');
  assert.equal(target(lines, 'c', 0, 1).line_id, 'c');
  assert.equal(target([], null, 0, 1), null);
});
