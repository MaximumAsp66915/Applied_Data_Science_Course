const deviceDefinitions = {
  'iphone-17-pro-max': {
    label: 'iPhone 17 Pro Max',
    shell: { width: 387, height: 812, radius: 64, padding: 12, screenRadius: 52, screenTop: 58, screenBottom: 0 },
    buttons: true,
    island: true,
    homeIndicator: true,
    iframeScale: 1,
    frameClass: 'iphone'
  },
  's24-ultra': {
    label: 'Samsung S24 Ultra',
    shell: { width: 390, height: 844, radius: 58, padding: 14, screenRadius: 46, screenTop: 54, screenBottom: 0 },
    buttons: true,
    island: true,
    homeIndicator: true,
    iframeScale: 1,
    frameClass: 'android'
  },
  's26-ultra': {
    label: 'Samsung S26 Ultra',
    shell: { width: 396, height: 860, radius: 60, padding: 14, screenRadius: 48, screenTop: 56, screenBottom: 0 },
    buttons: true,
    island: true,
    homeIndicator: true,
    iframeScale: 1,
    frameClass: 'android'
  },
  'ipad-pro': {
    label: 'iPad Pro',
    shell: { width: 820, height: 1180, radius: 44, padding: 18, screenRadius: 32, screenTop: 0, screenBottom: 0 },
    buttons: false,
    island: true,
    homeIndicator: true,
    iframeScale: 1,
    frameClass: 'ipad'
  }
};

function createDevicePreview(container, deviceKey, pagePath, options = {}) {
  const device = deviceDefinitions[deviceKey] || deviceDefinitions['iphone-17-pro-max'];
  const shell = document.createElement('div');
  shell.className = 'demo-device-shell';
  shell.setAttribute('data-device', deviceKey);
  shell.style.width = `${device.shell.width}px`;
  shell.style.height = `${device.shell.height}px`;
  shell.style.borderRadius = `${device.shell.radius}px`;
  shell.style.padding = `${device.shell.padding}px`;

  const screen = document.createElement('div');
  screen.className = 'demo-device-screen';
  screen.style.borderRadius = `${device.shell.screenRadius}px`;

  if (device.island) {
    const island = document.createElement('div');
    island.className = 'demo-device-island';
    screen.appendChild(island);
  }

  const content = document.createElement('div');
  content.className = 'demo-device-content';
  content.style.top = `${device.shell.screenTop}px`;
  content.style.bottom = `${device.shell.screenBottom}px`;

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
    const buttons = ['mute', 'vol-up', 'vol-down', 'power'];
    buttons.forEach((name) => {
      const btn = document.createElement('div');
      btn.className = `demo-device-button demo-device-${name}`;
      shell.appendChild(btn);
    });
  }

  shell.appendChild(screen);
  container.innerHTML = '';
  container.appendChild(shell);

  const activeScale = options.scale || 1;
  shell.style.transform = `scale(${activeScale})`;
  shell.style.transformOrigin = 'center center';
}

function fitDeviceIntoView(deviceShell, viewportHeight, viewportWidth, safePadding = 24) {
  const shellWidth = deviceShell.offsetWidth;
  const shellHeight = deviceShell.offsetHeight;
  const availableHeight = Math.max(220, viewportHeight - safePadding * 2);
  const availableWidth = Math.max(260, viewportWidth - safePadding * 2);
  const maxScaleHeight = availableHeight / shellHeight;
  const maxScaleWidth = availableWidth / shellWidth;
  const scale = Math.min(maxScaleHeight, maxScaleWidth, 1);
  deviceShell.style.transform = `scale(${scale})`;
  return scale;
}

function setDevicePreviewLayout(container, labelEl, deviceKey, pagePath, options = {}) {
  const device = deviceDefinitions[deviceKey] || deviceDefinitions['iphone-17-pro-max'];
  const shell = document.createElement('div');
  shell.className = 'demo-device-shell';
  shell.setAttribute('data-device', deviceKey);
  shell.style.width = `${device.shell.width}px`;
  shell.style.height = `${device.shell.height}px`;
  shell.style.borderRadius = `${device.shell.radius}px`;
  shell.style.padding = `${device.shell.padding}px`;

  const screen = document.createElement('div');
  screen.className = 'demo-device-screen';
  screen.style.borderRadius = `${device.shell.screenRadius}px`;

  if (device.island) {
    const island = document.createElement('div');
    island.className = 'demo-device-island';
    screen.appendChild(island);
  }

  const content = document.createElement('div');
  content.className = 'demo-device-content';
  content.style.top = `${device.shell.screenTop}px`;
  content.style.bottom = `${device.shell.screenBottom}px`;

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
    const buttons = ['mute', 'vol-up', 'vol-down', 'power'];
    buttons.forEach((name) => {
      const btn = document.createElement('div');
      btn.className = `demo-device-button demo-device-${name}`;
      shell.appendChild(btn);
    });
  }

  shell.appendChild(screen);
  container.innerHTML = '';
  container.appendChild(shell);

  if (labelEl) {
    labelEl.textContent = device.label;
  }

  const applyFit = () => {
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    const margin = options.margin || 24;
    const sceneTarget = options.scene || container.parentElement || container;
    const sceneWidth = sceneTarget.scrollWidth || sceneTarget.offsetWidth || shell.offsetWidth;
    const sceneHeight = sceneTarget.scrollHeight || sceneTarget.offsetHeight || shell.offsetHeight;
    const safeHeight = Math.max(220, viewportHeight - 240);
    const safeWidth = Math.max(260, viewportWidth - margin * 2);
    const maxScaleHeight = safeHeight / sceneHeight;
    const maxScaleWidth = safeWidth / sceneWidth;
    const baseScale = Math.min(maxScaleHeight, maxScaleWidth, 1);
    const zoomScale = window.visualViewport?.scale || 1;
    const scale = Math.min(1, baseScale * zoomScale);
    sceneTarget.style.transform = `scale(${scale})`;
    sceneTarget.style.transformOrigin = 'center center';
  };

  applyFit();
  window.addEventListener('resize', applyFit);
  window.visualViewport?.addEventListener('resize', applyFit);
  return { shell, frame };
}

window.devicePreview = {
  deviceDefinitions,
  createDevicePreview,
  fitDeviceIntoView,
  setDevicePreviewLayout
};
