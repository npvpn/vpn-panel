(function () {
  const script = document.currentScript;
  const infoUrl = script.dataset.infoUrl;
  const initialStatus = script.dataset.initialStatus;
  const trackDeviceLimit = script.dataset.deviceLimit != null;
  const intervalMs = Number(script.dataset.intervalMs) || 60000;

  async function checkStatus() {
    try {
      const response = await fetch(infoUrl);
      if (!response.ok) return;
      const data = await response.json();

      const statusChanged = data.status && data.status !== initialStatus;
      // Лимит устройств сравниваем с актуальным data.device_limit из ответа,
      // а не с тем, что был при загрузке страницы — его тоже могли поменять в админке.
      const deviceLimitCleared =
        trackDeviceLimit &&
        typeof data.devices_used === 'number' &&
        typeof data.device_limit === 'number' &&
        data.device_limit > 0 &&
        data.devices_used < data.device_limit;

      if (statusChanged || deviceLimitCleared) {
        window.location.reload();
      }
    } catch {
      // Сеть недоступна — просто попробуем на следующем тике.
    }
  }

  setInterval(checkStatus, intervalMs);
})();
