// Both component surfaces share the existing controls and their event handlers.
// Only the monitor creates an AudioContext. The inspector is a DOM host.
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
