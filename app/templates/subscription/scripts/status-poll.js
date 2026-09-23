(function () {
  const script = document.currentScript;
  const infoUrl = script.dataset.infoUrl;
  const initialStatus = script.dataset.initialStatus;
  // 'cleared' — перезагрузить, когда устройств снова стало меньше лимита (страница лимита устройств).
  // 'reached' — перезагрузить, когда лимит только что достигнут (страница активной подписки).
  const deviceLimitMode = script.dataset.deviceLimitMode;
  // Токен может стать невалидным навсегда (например, подписку отозвали) — тогда /info
  // отвечает 404, и это тоже повод перезагрузить страницу, чтобы показать актуальное состояние.
  const reloadOnGone = script.dataset.reloadOnGone === 'true';
  const intervalMs = Number(script.dataset.intervalMs) || 60000;

  async function checkStatus() {
    let response;
    try {
      response = await fetch(infoUrl);
    } catch {
      return; // Сеть недоступна — просто попробуем на следующем тике.
    }

    if (!response.ok) {
      if (reloadOnGone && response.status === 404) {
        window.location.reload();
      }
      return;
    }

    const data = await response.json();
    const statusChanged = data.status && data.status !== initialStatus;

    let deviceLimitTriggered = false;
    if (
      deviceLimitMode &&
      typeof data.devices_used === 'number' &&
      typeof data.device_limit === 'number' &&
      data.device_limit > 0
    ) {
      deviceLimitTriggered =
        deviceLimitMode === 'cleared'
          ? data.devices_used < data.device_limit
          : data.devices_used >= data.device_limit;
    }

    if (statusChanged || deviceLimitTriggered) {
      window.location.reload();
    }
  }

  setInterval(checkStatus, intervalMs);
})();
