// NPVPN-2224, NPVPN-2314: поддержка на странице подписки — Chatwoot-чат с identity от бота или Telegram.
(function () {
  'use strict';

  var READY_TIMEOUT_MS = 15000;
  var IDENTITY_TIMEOUT_MS = 15000;
  var TEXT_FAILED_TG = 'Чат недоступен, напишите в Telegram';
  var TEXT_FAILED_LATER = 'Чат недоступен, попробуйте позже';
  var sdkPromise = null;
  // меню, из которого сейчас запущен чат: chatwoot:error приходит асинхронно, уже после
  // setUser, и ошибку нужно показать там, откуда открывали
  var activeChat = null;
  var LAST_TOKEN_KEY = 'cw_sub_token';

  // Страницы разных подписок в одном браузере (общее устройство): Chatwoot держит
  // переписку в cookie, и следующий открыл бы чат предыдущего. Сессию чата оставляем,
  // только если точно знаем, что она этой же подписки; иначе (подписка сменилась, первый
  // заход после выкладки — токена ещё нет, хранилище недоступно) забываем её до запуска
  // SDK (reset() после run() перезагружает виджет без chatwoot:ready). Свою историю
  // владелец получит обратно по identity.
  // Вызывать вплотную к run(): cookie общие для вкладок, и пока грузится скрипт, другая
  // вкладка могла запустить чат своей подписки. Проверка и run() — подряд, без await,
  // поэтому вклиниться другая вкладка не успевает
  function forgetPreviousChat(cfg) {
    var last = null;
    try {
      last = window.localStorage.getItem(LAST_TOKEN_KEY);
    } catch (e) {
      // хранилище недоступно (приватный режим) — чья сессия в cookie, не знаем
    }
    if (last !== cfg.token) {
      ['cw_conversation', 'cw_user_' + cfg.chat.website_token].forEach(function (name) {
        document.cookie = name + '=; Max-Age=0; path=/';
      });
    }
    try {
      window.localStorage.setItem(LAST_TOKEN_KEY, cfg.token);
    } catch (e) {
      // не запомнили (например, хранилище переполнено) — убираем старую запись: иначе в
      // следующий раз чужую сессию примем за сессию той подписки и не почистим
      try {
        window.localStorage.removeItem(LAST_TOKEN_KEY);
      } catch (e2) {
        // хранилище недоступно целиком — чтение тоже упадёт, и сессия забудется
      }
    }
  }

  function loadSdk(baseUrl) {
    return new Promise(function (resolve, reject) {
      if (window.chatwootSDK) { resolve(); return; }
      var script = document.createElement('script');
      script.src = baseUrl + '/packs/js/sdk.js';
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () {
        if (script.remove) { script.remove(); }
        reject(new Error('chatwoot sdk'));
      };
      document.head.appendChild(script);
    });
  }

  function waitReady() {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('chatwoot ready timeout')); }, READY_TIMEOUT_MS);
      window.addEventListener('chatwoot:ready', function () { clearTimeout(timer); resolve(); }, { once: true });
    });
  }

  function fetchIdentity(chat, token) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, IDENTITY_TIMEOUT_MS);
    return fetch(chat.identity_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bot_id: chat.bot_id, token: token }),
      signal: controller.signal
    }).then(function (resp) {
      if (!resp.ok) { throw new Error('identity ' + resp.status); }
      return resp.json();
    }).then(function (identity) {
      clearTimeout(timer);
      return identity;
    }, function (err) {
      clearTimeout(timer);
      throw err;
    });
  }

  // SDK + chatwoot:ready. run() — один раз на страницу (повторный Chatwoot не поддерживает).
  // Сбой не навсегда: сервер чата режет запросы по IP (429), а это бывает временно — следующий
  // клик пробует снова: скрипт не загрузился — грузим заново, виджет запущен, но не ответил —
  // ждём его ещё раз. Identity ниже — повторяемый.
  var sdkStarted = false;

  function ensureSdk(cfg) {
    if (window.$chatwoot && window.$chatwoot.hasLoaded) { return Promise.resolve(); }
    if (!sdkPromise) {
      var ready = waitReady();
      ready.catch(function () {});  // без «Uncaught (in promise)», если SDK не загрузился
      var attempt;
      if (sdkStarted) {
        attempt = ready;
      } else {
        window.chatwootSettings = { hideMessageBubble: true };
        attempt = loadSdk(cfg.chat.base_url).then(function () {
          forgetPreviousChat(cfg);
          sdkStarted = true;
          window.chatwootSDK.run({ websiteToken: cfg.chat.website_token, baseUrl: cfg.chat.base_url });
          return ready;
        });
      }
      sdkPromise = attempt;
      attempt.catch(function () { if (sdkPromise === attempt) { sdkPromise = null; } });
    }
    return sdkPromise;
  }

  function startChat(cfg) {
    return Promise.all([ensureSdk(cfg), fetchIdentity(cfg.chat, cfg.token)]).then(function (results) {
      var identity = results[1];
      window.$chatwoot.setUser(identity.identifier, {
        identifier_hash: identity.identifier_hash,
        name: identity.name || ('ID ' + identity.identifier),
        email: identity.email || undefined
      });
      window.$chatwoot.setCustomAttributes({ source: 'subscription_page' });
    });
  }

  function setStatus(root, text) {
    var status = root.querySelector('[data-support-status]');
    if (!status) { return; }
    status.textContent = text || '';
    status.hidden = !text;
  }

  function init(root) {
    var cfgNode = root.querySelector('script[data-support-config]');
    if (!cfgNode) { return; }
    var cfg = JSON.parse(cfgNode.textContent);
    var toggle = root.querySelector('[data-support-toggle]');
    var list = root.querySelector('[data-support-list]');
    var chatBtn = root.querySelector('[data-support-chat]');
    if (!toggle || !list) { return; }

    // Шторка (мобилка, оба способа): появляется анимацией, уходит переходом (is-closing),
    // скрываем, когда уехала; пока открыта, страница под ней не прокручивается.
    var sheet = list.classList.contains('support-menu__list--sheet');
    var SHEET_CLOSE_MS = 300;
    var closeTimer = null;

    function setOpen(open) {
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!sheet) { list.hidden = !open; return; }
      clearTimeout(closeTimer);
      list.classList.remove('is-closing');
      if (open) {
        list.hidden = false;
        document.body.classList.add('support-sheet-open');
        return;
      }
      if (list.hidden) { return; }
      document.body.classList.remove('support-sheet-open');
      list.classList.add('is-closing');
      closeTimer = setTimeout(function () {
        list.hidden = true;
        list.classList.remove('is-closing');
      }, SHEET_CLOSE_MS);
    }

    // Текущая попытка открыть чат. Пока грузится — спиннер на месте иконки «Написать в чат»
    // (как в вебе; на самой кнопке лоадера нет); ушли из меню, не дождавшись, — чат потом сам
    // не всплывает.
    var waiting = null;

    function setLoading(button, on) {
      if (button !== chatBtn) { return; }
      if (on) { button.classList.add('is-loading'); } else { button.classList.remove('is-loading'); }
      button.setAttribute('aria-busy', on ? 'true' : 'false');
    }

    function cancelWaiting() {
      if (!waiting) { return; }
      waiting.cancelled = true;
      setLoading(waiting.button, false);
      waiting = null;
      // запуск отменён — его поздний chatwoot:error не должен сам открывать меню
      if (activeChat === root) { activeChat = null; }
    }

    function leaveMenu() {
      cancelWaiting();
      setOpen(false);
    }

    document.addEventListener('click', function (event) { if (!root.contains(event.target)) { leaveMenu(); } });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { leaveMenu(); } });
    var tgLink = root.querySelector('a.support-menu__item');
    if (tgLink) { tgLink.addEventListener('click', leaveMenu); }
    // шторка: затемнение — сам список, клик мимо неё закрывает; и крестик
    list.addEventListener('click', function (event) { if (event.target === list) { leaveMenu(); } });
    var closeBtn = root.querySelector('[data-support-close]');
    if (closeBtn) { closeBtn.addEventListener('click', leaveMenu); }
    // шторка — только мобилка: расширили окно до десктопа — закрываем, иначе страница
    // так и осталась бы без прокрутки (сама шторка там скрыта CSS)
    if (sheet && window.matchMedia) {
      var desktop = window.matchMedia('(min-width: 1024px)');
      var onDesktop = function (event) { if (event.matches) { leaveMenu(); } };
      if (desktop.addEventListener) { desktop.addEventListener('change', onDesktop); }
      else if (desktop.addListener) { desktop.addListener(onDesktop); }
    }

    // Только чат (без Telegram) — вилка не нужна: кнопка сразу открывает чат,
    // а список остаётся только под статус загрузки/ошибки.
    var direct = cfg.mode === 'chat';

    function failText() {
      return cfg.tg_url ? TEXT_FAILED_TG : TEXT_FAILED_LATER;
    }

    function failChat() {
      setStatus(root, failText());
      if (direct) { setOpen(true); }
    }

    // Chatwoot отклонил пользователя (например, неверная подпись) — без этого окно
    // оставалось открытым с анонимным пустым чатом
    window.addEventListener('chatwoot:error', function () {
      if (activeChat !== root) { return; }
      if (window.$chatwoot) { window.$chatwoot.toggle('close'); }
      failChat();
      // после успешного запуска список уже закрыт — открываем, иначе ошибку не видно
      setOpen(true);
    });

    function runChat(button) {
      if (waiting) { return; }
      var attempt = { button: button, cancelled: false };
      waiting = attempt;
      activeChat = root;
      // прошлая ошибка уходит, пока пробуем снова
      setStatus(root, '');
      setLoading(button, true);
      startChat(cfg).then(function () {
        if (attempt.cancelled) { return; }
        window.$chatwoot.toggle('open');
        setOpen(false);
      }).catch(function () {
        // ушли из меню — ошибку увидят при следующем открытии, само меню не всплывает
        if (attempt.cancelled) { setStatus(root, failText()); } else { failChat(); }
      }).then(function () {
        if (waiting === attempt) {
          waiting = null;
          setLoading(button, false);
        }
      });
    }

    if (direct) {
      toggle.addEventListener('click', function () { runChat(toggle); });
    } else {
      toggle.addEventListener('click', function () { if (list.hidden) { setOpen(true); } else { leaveMenu(); } });
      if (chatBtn && cfg.chat) {
        chatBtn.addEventListener('click', function () { runChat(chatBtn); });
      }
    }

    // ?support=open — пришли из VPN-приложения. Реагирует только видимая кнопка: на странице
    // их несколько (плавающая и значки в шапках), иначе identity запросили бы дважды.
    if (new URLSearchParams(window.location.search).get('support') === 'open' && toggle.getClientRects().length) {
      if (direct) { runChat(toggle); } else { setOpen(true); }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-support-menu]').forEach(init);
  });
})();
