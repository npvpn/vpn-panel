// Обвязка для tests/test_support_menu_js.py: исполняет настоящий
// app/templates/subscription/scripts/support-menu.js в node:vm с минимальной
// подделкой DOM / Chatwoot SDK / fetch и печатает итоговое состояние JSON-ом.
// Зависимостей нет — только встроенные модули Node.
//
// Вход (argv[2], JSON): { search, identityOk, chatwootError, lastToken, sdk, readyDelay, roots: [{ mode, tgUrl, visible }], clicks: [[rootIndex, target]] }
// target: "toggle" | "chat" | "tg" | "escape" (клики — по очереди, с паузой);
// chatwootError — Chatwoot отклоняет setUser (как SET_USER_ERROR);
// lastToken — подписка, открытая в этом браузере раньше; storageBroken — localStorage бросает
// исключение (приватный режим);
// sdk: "present" (уже на странице) | "failOnce" (первая загрузка скрипта падает, вторая — нет);
// readyDelay — через сколько мс после run() виджет присылает chatwoot:ready.
// Выход: { identityCalls, scriptLoads, chatOpened, chatClosed, setUser, cookiesCleared, storedToken,
//          roots: [{ listOpen, status, chatLoading, toggleLoading }] }.
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scenario = JSON.parse(process.argv[2]);
const SCRIPT = path.join(__dirname, '..', '..', 'app', 'templates', 'subscription', 'scripts', 'support-menu.js');

function makeTarget() {
  const handlers = {};
  return {
    addEventListener(type, fn, opts) { (handlers[type] = handlers[type] || []).push({ fn, once: opts && opts.once }); },
    removeEventListener(type, fn) { handlers[type] = (handlers[type] || []).filter((h) => h.fn !== fn); },
    dispatch(type, event) {
      for (const h of [...(handlers[type] || [])]) {
        if (h.once) { this.removeEventListener(type, h.fn); }
        h.fn(event || { type });
      }
    },
  };
}

class FakeEl {
  constructor({ attrs = {}, classes = [], visible = true } = {}) {
    Object.assign(this, makeTarget());
    this.attrs = { ...attrs };
    this.classes = new Set(classes);
    this.visible = visible;
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.style = {};
    this.parts = {};
    this.classList = { contains: (c) => this.classes.has(c), add: (c) => this.classes.add(c), remove: (c) => this.classes.delete(c) };
  }
  hasAttribute(name) { return name in this.attrs; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  querySelector(selector) { return this.parts[selector] || null; }
  contains(node) { return node === this || Object.values(this.parts).includes(node); }
  closest() { return null; }
  getClientRects() { return this.visible ? [{}] : []; }
  getBoundingClientRect() { return { width: 0, height: 0, top: 0 }; }
}

// Корень меню как его рисует _support_menu.html: конфиг, кнопка-вход, список, статус, пункт чата.
function makeRoot({ mode, tgUrl = '', visible = true }) {
  const root = new FakeEl({ attrs: { 'data-support-menu': '', 'data-support-inline': '' }, visible });
  const cfg = new FakeEl();
  cfg.textContent = JSON.stringify({
    mode,
    tg_url: tgUrl,
    token: 'TOKEN',
    chat: { base_url: 'https://chat.test', website_token: 'wt', identity_url: 'https://bot.test/identity', bot_id: 7 },
  });
  const toggle = new FakeEl({ visible });
  const tgLink = new FakeEl({ visible });
  const list = new FakeEl({ visible });
  list.hidden = true;
  const status = new FakeEl();
  status.hidden = true;
  root.parts = { 'script[data-support-config]': cfg, '[data-support-toggle]': toggle, '[data-support-list]': list, '[data-support-status]': status };
  if (mode === 'menu') { root.parts['[data-support-chat]'] = new FakeEl({ visible }); }
  if (tgUrl) { root.parts['a.support-menu__item'] = tgLink; }
  return root;
}

const roots = scenario.roots.map(makeRoot);
const state = { identityCalls: 0, scriptLoads: 0, chatOpened: false, chatClosed: false, setUser: null, cookiesCleared: [] };
const storage = scenario.lastToken ? { cw_sub_token: scenario.lastToken } : {};

// Скрипт SDK: «загружается» асинхронно; при sdk: "failOnce" первая попытка падает.
const document = Object.assign(makeTarget(), {
  head: {
    appendChild(script) {
      state.scriptLoads += 1;
      const failed = scenario.sdk === 'failOnce' && state.scriptLoads === 1;
      setTimeout(() => {
        if (failed) { script.onerror(); return; }
        window.chatwootSDK = sdk;
        script.onload();
      }, 0);
    },
  },
  createElement: () => ({ remove() {} }),
  querySelectorAll: (selector) => (selector === '[data-support-menu]' ? roots : []),
});

// скрипт стирает cookie Chatwoot записью «имя=; Max-Age=0»; Object.assign сеттер
// не переносит — задаём отдельно
Object.defineProperty(document, 'cookie', {
  set(value) { state.cookiesCleared.push(value.split('=')[0]); },
});

const window = Object.assign(makeTarget(), {
  location: { search: scenario.search || '' },
  localStorage: {
    getItem: (key) => {
      if (scenario.storageBroken) { throw new Error('SecurityError'); }
      return key in storage ? storage[key] : null;
    },
    setItem: (key, value) => {
      if (scenario.storageBroken) { throw new Error('SecurityError'); }
      storage[key] = String(value);
    },
  },
  innerHeight: 800,
  matchMedia: () => ({ matches: true }),
  getComputedStyle: () => ({ position: 'static', fontSize: '16px' }),
});

// SDK: run() поднимает виджет и шлёт chatwoot:ready, как настоящий.
const sdk = {
    run() {
      window.$chatwoot = {
        setUser(identifier, attrs) {
          state.setUser = { identifier, ...attrs };
          // Chatwoot отвечает на setUser асинхронно
          if (scenario.chatwootError) {
            setTimeout(() => window.dispatch('chatwoot:error', { detail: 'SET_USER_ERROR' }), 0);
          }
        },
        setCustomAttributes() {},
        toggle(action) {
          if (action === 'open') { state.chatOpened = true; }
          if (action === 'close') { state.chatClosed = true; }
        },
      };
      setTimeout(() => window.dispatch('chatwoot:ready'), scenario.readyDelay || 0);
    },
};
if (scenario.sdk !== 'failOnce') { window.chatwootSDK = sdk; }

async function fakeFetch(url, opts) {
  state.identityCalls += 1;
  if (!scenario.identityOk) { return { ok: false, status: 502, json: async () => ({}) }; }
  const body = JSON.parse(opts.body);
  return { ok: true, status: 200, json: async () => ({ identifier: '42', identifier_hash: 'h', name: 'Test', email: null, bot_id: body.bot_id }) };
}

const context = vm.createContext({
  window, document, fetch: fakeFetch, URLSearchParams, AbortController, setTimeout, clearTimeout, Promise, console,
});
vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), context, { filename: SCRIPT });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const TARGETS = { chat: '[data-support-chat]', tg: 'a.support-menu__item', toggle: '[data-support-toggle]' };

(async () => {
  document.dispatch('DOMContentLoaded');
  // По очереди, с паузой — между кликами успевают отработать промисы (повтор после сбоя и т. п.)
  for (const [index, target] of scenario.clicks || []) {
    if (target === 'escape') {
      document.dispatch('keydown', { key: 'Escape' });
    } else {
      const el = roots[index].parts[TARGETS[target]];
      el.dispatch('click', { target: el });
    }
    await sleep(10);
  }

  // Дать отработать промисам (SDK → ready → identity → setUser → toggle).
  await sleep(80);
  const loading = (el) => !!el && el.classes.has('is-loading');
  process.stdout.write(JSON.stringify({
    ...state,
    storedToken: storage.cw_sub_token || null,
    roots: roots.map((r) => ({
      listOpen: !r.parts['[data-support-list]'].hidden,
      status: r.parts['[data-support-status]'].hidden ? '' : r.parts['[data-support-status]'].textContent,
      chatLoading: loading(r.parts['[data-support-chat]']),
      toggleLoading: loading(r.parts['[data-support-toggle]']),
    })),
  }));
})();
