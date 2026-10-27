// NPVPN-2224: «Помощь» на странице подписки — Chatwoot-чат с identity от бота или Telegram.
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
  // владелец получит обратно по identity
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
      // не запомнили — в следующий раз сессия чата снова забудется, чат всё равно работает
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
        forgetPreviousChat(cfg);
        window.chatwootSettings = { hideMessageBubble: true };
        attempt = loadSdk(cfg.chat.base_url).then(function () {
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

  // На мобильных поднимаем меню над фиксированными элементами снизу (высота .hint зависит от текста).
  function placeAboveFixedBottom(root) {
    var top = null;
    var mobile = window.matchMedia('(max-width: 1023px)').matches;
    if (mobile) {
      document.querySelectorAll('.floating-nav, .button-wrapper_revoke').forEach(function (el) {
        var rect = el.getBoundingClientRect();
        if (!rect.width || !rect.height || window.getComputedStyle(el).position !== 'fixed') { return; }
        if (top === null || rect.top < top) { top = rect.top; }
      });
    }
    if (top !== null) { root.style.bottom = (window.innerHeight - top + 12) + 'px'; }
    else { root.style.bottom = mobile ? '24px' : ''; }
  }

  // Кнопка в шапке стоит в одной строке с заголовком. Не влезает — сначала уменьшаем
  // «Помощь» (до HELP_MIN_PX), потом заголовок (до TITLE_MIN_PX, на 1–3px от исходного);
  // не влезает и так (экраны уже 360px) — разрешаем заголовку перенос. Заголовок nowrap,
  // поэтому нехватка места видна как переполнение строки.
  var HELP_MIN_PX = 12;
  var TITLE_MIN_PX = 21;

  function fitHeaderTitle(root) {
    var row = root.closest('.page-header__top');
    var title = row && row.querySelector('.page-title');
    var chip = root.querySelector('.support-menu__chip');
    if (!title || !chip) { return; }
    title.style.fontSize = '';
    chip.style.fontSize = '';
    title.classList.remove('page-title--wrap');
    if (!root.getClientRects().length) { return; }  // кнопка скрыта — подгонять не к чему
    var overflows = function () { return row.scrollWidth > row.clientWidth; };
    var help = parseFloat(window.getComputedStyle(chip).fontSize);
    while (overflows() && help > HELP_MIN_PX) { help -= 1; chip.style.fontSize = help + 'px'; }
    var size = parseFloat(window.getComputedStyle(title).fontSize);
    while (overflows() && size > TITLE_MIN_PX) { size -= 1; title.style.fontSize = size + 'px'; }
    if (overflows()) { title.classList.add('page-title--wrap'); }
  }

  function init(root) {
    var cfgNode = root.querySelector('script[data-support-config]');
    if (!cfgNode) { return; }
    var cfg = JSON.parse(cfgNode.textContent);
    // Пункт нижнего меню стоит внутри .floating-nav — поднимать нужно только плавающую кнопку.
    if (!root.hasAttribute('data-support-inline')) {
      placeAboveFixedBottom(root);
      var replace = function () { placeAboveFixedBottom(root); };
      window.addEventListener('resize', replace);
      window.addEventListener('load', replace);
      if (document.fonts && document.fonts.ready) { document.fonts.ready.then(replace); }
    }
    if (root.classList.contains('support-menu--header')) {
      var refit = function () { fitHeaderTitle(root); };
      refit();
      window.addEventListener('resize', refit);
      window.addEventListener('load', refit);
      // ширина заголовка зависит от шрифта — пересчитываем, когда он догрузится
      if (document.fonts && document.fonts.ready) { document.fonts.ready.then(refit); }
    }
    var toggle = root.querySelector('[data-support-toggle]');
    var list = root.querySelector('[data-support-list]');
    var chatBtn = root.querySelector('[data-support-chat]');
    if (!toggle || !list) { return; }

    function setOpen(open) {
      list.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    // Текущая попытка открыть чат. Пока грузится — спиннер на месте иконки «Чат на сайте»
    // (как в вебе; на «Помощь» лоадера нет); ушли из меню, не дождавшись, — чат потом сам
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
    }

    function leaveMenu() {
      cancelWaiting();
      setOpen(false);
    }

    document.addEventListener('click', function (event) { if (!root.contains(event.target)) { leaveMenu(); } });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { leaveMenu(); } });
    var tgLink = root.querySelector('a.support-menu__item');
    if (tgLink) { tgLink.addEventListener('click', leaveMenu); }

    // Только чат (без Telegram) — вилка не нужна: «Помощь» сразу открывает чат,
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
    // их две (плавающая и пункт нижнего меню), иначе identity запросили бы дважды.
    if (new URLSearchParams(window.location.search).get('support') === 'open' && toggle.getClientRects().length) {
      if (direct) { runChat(toggle); } else { setOpen(true); }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-support-menu]').forEach(init);
  });
})();
