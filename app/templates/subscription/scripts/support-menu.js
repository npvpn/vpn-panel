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

  function init(root) {
    var cfgNode = root.querySelector('script[data-support-config]');
    if (!cfgNode) { return; }
    var cfg = JSON.parse(cfgNode.textContent);
    placeAboveFixedBottom(root);
    var replace = function () { placeAboveFixedBottom(root); };
    window.addEventListener('resize', replace);
    window.addEventListener('load', replace);
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(replace); }
    var toggle = root.querySelector('[data-support-toggle]');
    var list = root.querySelector('[data-support-list]');
    var chatBtn = root.querySelector('[data-support-chat]');
    if (!toggle || !list) { return; }

    function setOpen(open) {
      list.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    toggle.addEventListener('click', function () { setOpen(list.hidden); });
    document.addEventListener('click', function (event) { if (!root.contains(event.target)) { setOpen(false); } });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { setOpen(false); } });

    if (chatBtn && cfg.chat) {
      chatBtn.addEventListener('click', function () {
        chatBtn.disabled = true;
        setStatus(root, TEXT_LOADING);
        startChat(cfg).then(function () {
          setStatus(root, '');
          setOpen(false);
        }).catch(function () {
          setStatus(root, cfg.tg_url ? TEXT_FAILED_TG : TEXT_FAILED_LATER);
        }).then(function () { chatBtn.disabled = false; });
      });
    }

    if (new URLSearchParams(window.location.search).get('support') === 'open') { setOpen(true); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-support-menu]').forEach(init);
  });
})();
