import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  isConnected = true;
  children = [];
  setAttribute() {}
  querySelectorAll() { return []; }
  appendChild(child) { this.children.push(child); child.parentElement = this; }
  replaceChildren(...children) {
    for (const child of this.children) child.parentElement = null;
    this.children = children;
    for (const child of children) child.parentElement = this;
  }
  remove() {
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this);
    this.parentElement = null;
  }
}
function fixture() {
  const context = {window: {}, document: {createElement: () => new Element()}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(new URL('../heartbeam/editor_assets/workstation.js', import.meta.url), 'utf8'), context);
  return context;
}

for (const order of ['monitor-first', 'inspector-first']) {
  test(`live controls retain identity and handlers when mounted ${order}`, () => {
    const api = fixture(), parent = new Element(), controls = new Element();
    const handler = () => 'same player'; controls.onClick = handler;
    let release;
    if (order === 'monitor-first') release = api.hbAttachControls('song', controls);
    api.hbMountInspector({parentElement: parent, data: {project_id: 'song'}});
    if (order === 'inspector-first') release = api.hbAttachControls('song', controls);
    assert.equal(parent.children[0].children[0], controls);
    assert.equal(controls.onClick, handler);
    api.hbMountInspector({parentElement: parent, data: {project_id: 'song'}});
    assert.equal(parent.children.length, 1);
    assert.equal(parent.children[0].children.length, 1);
    release();
    assert.equal(parent.children[0].children.length, 0);
  });
}

test('replacing the monitor keeps the inspector and cannot detach a newer view', () => {
  const api = fixture(), parent = new Element(), old = new Element(), next = new Element();
  api.hbMountInspector({parentElement: parent, data: {project_id: 'song'}});
  const release = api.hbAttachControls('song', old);
  api.hbAttachControls('song', next);
  release();
  assert.equal(parent.children[0].children[0], next);
  const other = new Element(); api.hbAttachControls('other-song', other);
  assert.equal(parent.children[0].children[0], next);
});
