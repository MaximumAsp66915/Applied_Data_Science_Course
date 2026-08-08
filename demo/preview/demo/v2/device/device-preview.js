// Device shell definitions.
// Widths/heights are scaled-down px sizes for the on-screen phone frame,
// but the ASPECT RATIO of each shell matches the device's real CSS
// (logical) viewport - not its native panel resolution - as closely as
// possible. Sources checked Aug 2026:
//   iPhone 17 Pro Max   -> 440 x 956  CSS px (DPR 3)
//   Samsung S24 Ultra   -> 384 x 824  CSS px (DPR 3.75)
//   Samsung S26 Ultra   -> 412 x 891  CSS px (DPR 3.5)
//   iPad Pro 13"        -> 1032 x 1376 CSS px
//   Galaxy Z Fold 7     -> 984 x 1092 CSS px (inner screen, unfolded)
//   Galaxy Z Flip 7     -> 360 x 840  CSS px (main screen)
//   MacBook Pro 14"     -> 1512 x 982 CSS px (DPR 2)
//
// NOTE on sizing strategy: none of this scales devices via JS-measured
// transforms anymore. Browser/page zoom changes what a "CSS pixel" maps to
// physically, and any fit-to-container logic driven by getBoundingClientRect
// / ResizeObserver reacts to that (it looks like a real resize to those
// APIs) and ends up fighting the zoom, shrinking things back down. Sizing
// is handled purely in CSS now (max-width/max-height: 100% + aspect-ratio),
// which scales naturally with the page and with browser zoom, no JS
// recalculation involved.
const deviceDefinitions = {
  'iphone-17-pro-max': {
    label: 'iPhone 17 Pro Max',
    shell: { width: 396, height: 861, radius: 64, padding: 12, screenRadius: 52, screenTop: 58, screenBottom: 0 },
    buttons: true,
    island: true,
    homeIndicator: true,
    frameClass: 'iphone'
  },
  's24-ultra': {
    label: 'Samsung S24 Ultra',
    // Real device: flat titanium frame, near-flat (very subtle curve) front
    // glass, squared-off corners with a small radius, centered punch-hole
    // camera, flush volume+power buttons on the right edge only (no mute
    // switch - Samsung doesn't have one), S-Pen slot at the bottom.
    shell: { width: 384, height: 824, radius: 26, padding: 8, screenRadius: 20, screenTop: 0, screenBottom: 0 },
    buttons: true,
    island: false,
    punchHole: true,
    homeIndicator: false,
    sPen: true,
    frameClass: 'android samsung'
  },
  's26-ultra': {
    label: 'Samsung S26 Ultra',
    shell: { width: 412, height: 891, radius: 28, padding: 8, screenRadius: 22, screenTop: 0, screenBottom: 0 },
    buttons: true,
    island: false,
    punchHole: true,
    homeIndicator: false,
    sPen: true,
    frameClass: 'android samsung'
  },
  'ipad-pro': {
    label: 'iPad Pro',
    shell: { width: 620, height: 826, radius: 44, padding: 18, screenRadius: 24, screenTop: 0, screenBottom: 0 },
    buttons: false,
    island: false,
    camDot: true,
    homeIndicator: true,
    frameClass: 'ipad'
  },
  'z-fold-7': {
    label: 'Galaxy Z Fold 7 (unfolded)',
    shell: { width: 492, height: 546, radius: 22, padding: 10, screenRadius: 14, screenTop: 0, screenBottom: 0 },
    buttons: true,
    island: false,
    punchHole: true,
    homeIndicator: false,
    hingeLine: true,
    frameClass: 'android samsung foldable'
  },
  'z-flip-7': {
    label: 'Galaxy Z Flip 7',
    shell: { width: 324, height: 756, radius: 30, padding: 8, screenRadius: 22, screenTop: 0, screenBottom: 0 },
    buttons: true,
    island: false,
    punchHole: true,
    homeIndicator: false,
    hingeLine: true,
    frameClass: 'android samsung'
  },
  'macbook-pro-14': {
    label: 'MacBook Pro 14"',
    shell: { width: 756, height: 491, radius: 18, padding: 16, screenRadius: 8, screenTop: 0, screenBottom: 0 },
    buttons: false,
    island: false,
    camDot: true,
    homeIndicator: false,
    frameClass: 'laptop'
  }
};

function buildShellDom(deviceKey, pagePath) {
  const device = deviceDefinitions[deviceKey] || deviceDefinitions['iphone-17-pro-max'];
  const aspect = device.shell.width / device.shell.height;

  const shell = document.createElement('div');
  shell.className = 'demo-device-shell';
  shell.setAttribute('data-device', deviceKey);
  shell.setAttribute('data-frame', device.frameClass || '');
  // Intrinsic size comes from CSS custom properties (used as the natural
  // width/height at scale 1); actual on-screen size is governed by CSS
  // (max-width/max-height/aspect-ratio) so it scales with the page and with
  // browser zoom with no JS involved.
  shell.style.setProperty('--w', `${device.shell.width}px`);
  shell.style.setProperty('--h', `${device.shell.height}px`);
  shell.style.aspectRatio = `${device.shell.width} / ${device.shell.height}`;
  shell.style.borderRadius = `${device.shell.radius}px`;
  shell.style.padding = `${device.shell.padding}px`;

  // .demo-device-frame is the element that actually gets clipped
  // (overflow: hidden + border-radius). Keeping this separate from the
  // outer .demo-device-shell (which holds the button nubs that sit
  // outside the 0-100% box) means the rounded-corner clip never depends
  // on a transform:scale() up the tree, so it renders correctly at any
  // zoom level.
  const frameEl = document.createElement('div');
  frameEl.className = 'demo-device-frame';

  const screen = document.createElement('div');
  screen.className = 'demo-device-screen';
  screen.style.borderRadius = `${device.shell.screenRadius}px`;

  if (device.island) {
    const island = document.createElement('div');
    island.className = 'demo-device-island';
    screen.appendChild(island);
  }

  if (device.punchHole) {
    const hole = document.createElement('div');
    hole.className = 'demo-device-punch-hole';
    screen.appendChild(hole);
  }

  if (device.camDot) {
    const cam = document.createElement('div');
    cam.className = 'demo-device-cam-dot';
    screen.appendChild(cam);
  }

  if (device.hingeLine) {
    const hinge = document.createElement('div');
    hinge.className = 'demo-device-hinge-line';
    screen.appendChild(hinge);
  }

  const content = document.createElement('div');
  content.className = 'demo-device-content';
  // top/bottom insets are driven by CSS (see device-preview.css) for known
  // device types; only apply an inline override here if a device defines
  // a nonzero inset that CSS doesn't already special-case.
  if (device.shell.screenTop) content.style.top = `${device.shell.screenTop}px`;
  if (device.shell.screenBottom) content.style.bottom = `${device.shell.screenBottom}px`;

  const frame = document.createElement('iframe');
  frame.src = pagePath;
  frame.setAttribute('loading', 'eager');
  frame.setAttribute('title', `${device.label} preview`);
  content.appendChild(frame);
  screen.appendChild(content);

  if (device.homeIndicator) {
    const indicator = document.createElement('div');
    indicator.className = 'demo-device-home-indicator';
    screen.appendChild(indicator);
  }

  if (device.buttons) {
    const isSamsung = (device.frameClass || '').includes('samsung');
    // Samsung phones: no mute switch, just volume rocker + power, both on
    // the right edge. iPhone: mute switch on the left, volume up/down on
    // the left, power on the right.
    const buttons = isSamsung ? ['vol-rocker', 'power-samsung'] : ['mute', 'vol-up', 'vol-down', 'power'];
    buttons.forEach((name) => {
      const btn = document.createElement('div');
      btn.className = `demo-device-button demo-device-${name}`;
      shell.appendChild(btn);
    });
  }

  if (device.sPen) {
    const sPen = document.createElement('div');
    sPen.className = 'demo-device-spen-slot';
    shell.appendChild(sPen);
  }

  frameEl.appendChild(screen);
  shell.appendChild(frameEl);
  return { shell, frame, device, aspect };
}

// NOTE: the label above the device is now a fixed static caption. Callers
// pass the literal text to show via options.staticLabel ("SUT MUSIC - DEMO")
// - it is intentionally never set to device.label anymore.
function setDevicePreviewLayout(container, labelEl, deviceKey, pagePath, options = {}) {
  const { shell, frame, device } = buildShellDom(deviceKey, pagePath);
  container.innerHTML = '';
  container.appendChild(shell);

  if (labelEl && options.staticLabel) {
    labelEl.textContent = options.staticLabel;
  }

  // Sizing is CSS-only from here (see .demo-device-shell / .demo-index-stage
  // / .demo-clip-scene rules) - no JS measurement, no transform: scale()
  // driven by ResizeObserver or visualViewport. That's deliberate: any
  // JS-computed "fit" scale reacts to browser zoom the same way it reacts to
  // a real resize (they both change what getBoundingClientRect reports),
  // so it ends up cancelling the zoom out. Letting CSS max-width/max-height
  // + aspect-ratio do the fitting means native browser zoom just works.

  return { shell, frame, device };
}

window.devicePreview = {
  deviceDefinitions,
  setDevicePreviewLayout
};
