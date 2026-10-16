// NPVPN-2224: «Помощь» на странице подписки — Chatwoot-чат с identity от бота или Telegram.
(function () {
  'use strict';

  var READY_TIMEOUT_MS = 15000;
  var IDENTITY_TIMEOUT_MS = 15000;
  var TEXT_LOADING = 'Загружаем чат…';
  var TEXT_FAILED_TG = 'Чат недоступен, напишите в Telegram';
  var TEXT_FAILED_LATER = 'Чат недоступен, попробуйте позже';
  var sdkPromise = null;

  function loadSdk(baseUrl) {
    return new Promise(function (resolve, reject) {
      if (window.chatwootSDK) { resolve(); return; }
      var script = document.createElement('script');
      script.src = baseUrl + '/packs/js/sdk.js';
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () { reject(new Error('chatwoot sdk')); };
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

  // SDK + chatwoot:ready — один раз на страницу (повторный run() Chatwoot не поддерживает),
  // сбой загрузки SDK запоминается до перезагрузки. Identity ниже — повторяемый.
  function ensureSdk(cfg) {
    if (!sdkPromise) {
      window.chatwootSettings = { hideMessageBubble: true };
      var ready = waitReady();
      ready.catch(function () {});  // без «Uncaught (in promise)», если SDK не загрузился
      sdkPromise = loadSdk(cfg.chat.base_url).then(function () {
        window.chatwootSDK.run({ websiteToken: cfg.chat.website_token, baseUrl: cfg.chat.base_url });
        return ready;
      });
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
      window.$chatwoot.toggle('open');
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

    document.addEventListener('click', function (event) { if (!root.contains(event.target)) { setOpen(false); } });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { setOpen(false); } });

    // Только чат (без Telegram) — вилка не нужна: «Помощь» сразу открывает чат,
    // а список остаётся только под статус загрузки/ошибки.
    var direct = cfg.mode === 'chat';

    function runChat(button) {
      if (button.disabled) { return; }
      button.disabled = true;
      setStatus(root, TEXT_LOADING);
      if (direct) { setOpen(true); }
      startChat(cfg).then(function () {
        setStatus(root, '');
        setOpen(false);
      }).catch(function () {
        setStatus(root, cfg.tg_url ? TEXT_FAILED_TG : TEXT_FAILED_LATER);
        if (direct) { setOpen(true); }
      }).then(function () { button.disabled = false; });
    }

    if (direct) {
      toggle.addEventListener('click', function () { runChat(toggle); });
    } else {
      toggle.addEventListener('click', function () { setOpen(list.hidden); });
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
