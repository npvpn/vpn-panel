// Обвязка для tests/test_support_menu_js.py: исполняет настоящий
// app/templates/subscription/scripts/support-menu.js в node:vm с минимальной
// подделкой DOM / Chatwoot SDK / fetch и печатает итоговое состояние JSON-ом.
// Зависимостей нет — только встроенные модули Node.
//
// Вход (argv[2], JSON): { search, identityOk, roots: [{ mode, tgUrl, visible }], clicks: [[rootIndex, target]] }
// target: "toggle" | "chat". Выход: { identityCalls, chatOpened, setUser, roots: [{ listOpen, status }] }.
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
  const list = new FakeEl({ visible });
  list.hidden = true;
  const status = new FakeEl();
  status.hidden = true;
  root.parts = { 'script[data-support-config]': cfg, '[data-support-toggle]': toggle, '[data-support-list]': list, '[data-support-status]': status };
  if (mode === 'menu') { root.parts['[data-support-chat]'] = new FakeEl({ visible }); }
  return root;
}

const roots = scenario.roots.map(makeRoot);
const state = { identityCalls: 0, chatOpened: false, setUser: null };

const document = Object.assign(makeTarget(), {
  head: { appendChild() {} },
  createElement: () => ({}),
  querySelectorAll: (selector) => (selector === '[data-support-menu]' ? roots : []),
});

const window = Object.assign(makeTarget(), {
  location: { search: scenario.search || '' },
  innerHeight: 800,
  matchMedia: () => ({ matches: true }),
  getComputedStyle: () => ({ position: 'static', fontSize: '16px' }),
  // SDK уже на странице: run() поднимает виджет и шлёт chatwoot:ready, как настоящий.
  chatwootSDK: {
    run() {
      window.$chatwoot = {
        setUser(identifier, attrs) { state.setUser = { identifier, ...attrs }; },
        setCustomAttributes() {},
        toggle(action) { if (action === 'open') { state.chatOpened = true; } },
      };
      setTimeout(() => window.dispatch('chatwoot:ready'), 0);
    },
  },
});

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

document.dispatch('DOMContentLoaded');
for (const [index, target] of scenario.clicks || []) {
  const root = roots[index];
  const el = target === 'chat' ? root.parts['[data-support-chat]'] : root.parts['[data-support-toggle]'];
  el.dispatch('click', { target: el });
}

// Дать отработать промисам (SDK → ready → identity → setUser → toggle).
setTimeout(() => {
  process.stdout.write(JSON.stringify({
    ...state,
    roots: roots.map((r) => ({
      listOpen: !r.parts['[data-support-list]'].hidden,
      status: r.parts['[data-support-status]'].hidden ? '' : r.parts['[data-support-status]'].textContent,
    })),
  }));
}, 50);
