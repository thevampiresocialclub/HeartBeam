// Both component surfaces share the existing controls and their event handlers.
// Only the monitor creates an AudioContext. The inspector is a DOM host.

// Help lives in the top layer so neither pane's scrolling can clip it.
// Hover, keyboard focus and tap share the same tooltip; it never changes state.
function hbMountHelp(root, signal) {
  for (const help of root.querySelectorAll('.hb-help')) {
    const button = help.querySelector('.hb-info'), tip = help.querySelector('.hb-help-text');
    const native = typeof tip.showPopover === 'function';
    let open = false, pinned = false, timer;
    if (!native) { tip.removeAttribute('popover'); tip.hidden = true; }
    const close = () => {
      clearTimeout(timer); pinned = false;
      if (!open) return;
      if (native) { if (tip.matches(':popover-open')) tip.hidePopover(); }
      else tip.hidden = true;
      open = false;
    };
    const show = () => {
      clearTimeout(timer);
      if (!open) { if (native) tip.showPopover(); else tip.hidden = false; open = true; }
      const anchor = button.getBoundingClientRect(), box = tip.getBoundingClientRect();
      tip.style.left = `${Math.max(8, Math.min(window.innerWidth - box.width - 8, anchor.right - box.width))}px`;
      const above = anchor.top - box.height - 8;
      tip.style.top = `${Math.max(8, Math.min(window.innerHeight - box.height - 8, above >= 8 ? above : anchor.bottom + 8))}px`;
    };
    const leave = () => { if (!pinned && button.getRootNode().activeElement !== button) timer = setTimeout(close, 120); };
    button.addEventListener('pointerenter', show, {signal});
    button.addEventListener('pointerleave', leave, {signal});
    button.addEventListener('focus', show, {signal});
    button.addEventListener('blur', close, {signal});
    button.addEventListener('click', () => { if (pinned) close(); else { show(); pinned = true; } }, {signal});
    tip.addEventListener('pointerenter', () => clearTimeout(timer), {signal});
    tip.addEventListener('pointerleave', leave, {signal});
    document.addEventListener('pointerdown', event => {
      if (!event.composedPath().includes(help)) close();
    }, {signal});
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && open) { event.preventDefault(); close(); }
    }, {signal});
    window.addEventListener('resize', close, {signal});
    document.addEventListener('scroll', () => {
      if (!open) return;
      const anchor = button.getBoundingClientRect();
      if (anchor.bottom < 0 || anchor.top > window.innerHeight) close();
      else show(); // Firefox can scroll a pane as a keyboard control gains focus.
    }, {signal, capture: true});
    signal.addEventListener('abort', close, {once: true});
  }
}

function hbWorkstationSlot(id) {
  const slots = window.__hbWorkstationSlots ||= new Map();
  if (!slots.has(id)) slots.set(id, {});
  return slots.get(id);
}

function hbAttachControls(id, view) {
  const slot = hbWorkstationSlot(id);
  slot.view = view;
  if (slot.host?.isConnected) slot.host.replaceChildren(view);
  return () => {
    view.remove();
    if (slot.view === view) {
      delete slot.view;
      if (!slot.host?.isConnected) window.__hbWorkstationSlots.delete(id);
    }
  };
}

function hbMountInspector(component) {
  const parent = component.parentElement;
  const id = component.data.project_id;
  const slot = hbWorkstationSlot(id);
  let host = parent._hbInspector;
  if (!host?.isConnected) {
    host = document.createElement('div');
    host.className = 'hb-inspector-host';
    host.setAttribute('aria-label', 'Live lyric controls');
    // Streamlit keeps the component's stylesheet in this shadow root too.
    // Replace only our own host, never the runtime's style nodes.
    parent.querySelectorAll('.hb-inspector-host').forEach(node => node.remove());
    parent.appendChild(host);
    parent._hbInspector = host;
  }
  slot.host = host;
  if (slot.view && slot.view.parentElement !== host) host.replaceChildren(slot.view);
}
