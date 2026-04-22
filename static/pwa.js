let deferredInstallPrompt = null;

function setInstallVisibility(visible) {
  document.querySelectorAll('[data-role="install-app"]').forEach((button) => {
    button.hidden = !visible;
    button.disabled = !visible;
  });
}

function isStandaloneMode() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try {
    await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    document.documentElement.dataset.pwaReady = '1';
  } catch (error) {
    console.warn('service worker register failed', error);
  }
}

function bindInstallButtons() {
  document.querySelectorAll('[data-role="install-app"]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!deferredInstallPrompt) return;
      deferredInstallPrompt.prompt();
      const result = await deferredInstallPrompt.userChoice;
      if (result && result.outcome !== 'accepted') {
        console.info('install dismissed');
      }
      deferredInstallPrompt = null;
      setInstallVisibility(false);
    });
  });
}

window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  if (!isStandaloneMode()) {
    setInstallVisibility(true);
  }
});

window.addEventListener('appinstalled', () => {
  deferredInstallPrompt = null;
  setInstallVisibility(false);
});

window.addEventListener('DOMContentLoaded', () => {
  bindInstallButtons();
  if (isStandaloneMode()) {
    document.documentElement.dataset.displayMode = 'standalone';
    setInstallVisibility(false);
  }
  registerServiceWorker();
});
