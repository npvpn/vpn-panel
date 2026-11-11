// Обвязка для tests/test_support_menu_js.py: исполняет настоящий
// app/templates/subscription/scripts/support-menu.js в node:vm с минимальной
// подделкой DOM / Chatwoot SDK / fetch и печатает итоговое состояние JSON-ом.
// Зависимостей нет — только встроенные модули Node.
//
// Вход (argv[2], JSON): { search, identityOk, chatwootError, lastToken, sdk, readyDelay, settle, roots: [{ mode, tgUrl, visible, sheet }], clicks: [[rootIndex, target]] }
// target: toggle | chat | tg | close | escape | outside | overlay | tab | shiftTab | desktop | wait
// target: "toggle" | "chat" | "tg" | "escape" | шторка: "close" (крестик) | "overlay" (затемнение) |
// "tab" / "shiftTab" (клавиши в шторке) | "desktop" (окно расширили до десктопа) | "wait" (300 мс,
// шторка успевает уехать) — по очереди, с паузой; sheet — корень-шторка (значок в шапке, оба способа);
// settle — сколько ещё ждать перед итогом (мс);
// chatwootError — Chatwoot отклоняет setUser (как SET_USER_ERROR);
// lastToken — подписка, открытая в этом браузере раньше; storageBroken — localStorage бросает
// исключение (приватный режим); storageFull — не пишет (QuotaExceededError), но читает и удаляет;
// sdk: "present" (уже на странице) | "load" (скрипт грузится) | "failOnce" (первая загрузка
// скрипта падает, вторая — нет); otherTabDuringLoad — пока грузится скрипт, другая вкладка
// открыла чат своей подписки (в localStorage её токен);
// readyDelay — через сколько мс после run() виджет присылает chatwoot:ready.
// errorDelay — через сколько мс после setUser приходит chatwoot:error (по умолчанию сразу).
// Выход: { identityCalls, scriptLoads, chatOpened, chatClosed, setUser, cookiesCleared, storedToken,
//          bodyLocked, focus, roots: [{ listOpen, closing, status, chatLoading, toggleLoading }] }.
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
  constructor({ attrs = {}, classes = [], visible = true, name = '' } = {}) {
    Object.assign(this, makeTarget());
    this.name = name;
    this.focusables = [];
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
  // шторка ищет пункты для Tab одним селектором — порядок как в разметке
  querySelectorAll() { return this.focusables; }
  focus() { document.activeElement = this; }
  contains(node) { return node === this || Object.values(this.parts).includes(node); }
  closest() { return null; }
  getClientRects() { return this.visible ? [{}] : []; }
  getBoundingClientRect() { return { width: 0, height: 0, top: 0 }; }
}

// Корень меню как его рисует _support_menu.html: конфиг, кнопка-вход, список, статус, пункт чата.
function makeRoot({ mode, tgUrl = '', visible = true, sheet = false, legacySheet = false }) {
  const root = new FakeEl({ attrs: { 'data-support-menu': '' }, visible });
  const cfg = new FakeEl();
  cfg.textContent = JSON.stringify({
    mode,
    tg_url: tgUrl,
    token: 'TOKEN',
    chat: { base_url: 'https://chat.test', website_token: 'wt', identity_url: 'https://bot.test/identity', bot_id: 7 },
  });
  const toggle = new FakeEl({ visible, name: 'toggle' });
  const tgLink = new FakeEl({ visible, name: 'tg' });
  const list = new FakeEl({ visible, classes: sheet ? ['support-menu__list--sheet'] : [], name: 'list' });
  list.hidden = true;
  const status = new FakeEl();
  status.hidden = true;
  root.parts = { 'script[data-support-config]': cfg, '[data-support-toggle]': toggle, '[data-support-list]': list, '[data-support-status]': status };
  const chat = new FakeEl({ visible, name: 'chat' });
  if (mode === 'menu') { root.parts['[data-support-chat]'] = chat; }
  if (tgUrl) { root.parts['a.support-menu__item'] = tgLink; }
  if (sheet) {
    // крестик, пункты — внутри шторки (списка): так их видит и root, и list
    const close = new FakeEl({ visible, name: 'close' });
    // сама шторка (role=dialog, tabindex=-1) — на неё ставится фокус при открытии
    const sheetEl = new FakeEl({ visible, name: 'sheet' });
    root.parts['[data-support-close]'] = close;
    list.parts = { '[data-support-sheet]': sheetEl, '[data-support-close]': close, chat, tg: tgLink };
    // своя разметка владельца без data-support-sheet
    if (legacySheet) { delete list.parts['[data-support-sheet]']; }
    list.focusables = [close, chat].concat(tgUrl ? [tgLink] : []);
  }
  return root;
}

const desktopQuery = Object.assign(makeTarget(), { matches: false });
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
        if (scenario.otherTabDuringLoad) { storage.cw_sub_token = 'OTHER'; }
        window.chatwootSDK = sdk;
        script.onload();
      }, 0);
    },
  },
  createElement: () => ({ remove() {} }),
  body: new FakeEl({ name: 'body' }),
  activeElement: null,
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
      if (scenario.storageFull) { throw new Error('QuotaExceededError'); }
      storage[key] = String(value);
    },
    removeItem: (key) => {
      if (scenario.storageBroken) { throw new Error('SecurityError'); }
      delete storage[key];
    },
  },
  innerHeight: 800,
  // «десктоп» (min-width: 1024px): по умолчанию мобилка; цель "desktop" — расширили окно
  matchMedia: () => desktopQuery,
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
            setTimeout(() => window.dispatch('chatwoot:error', { detail: 'SET_USER_ERROR' }), scenario.errorDelay || 0);
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
if (!scenario.sdk || scenario.sdk === 'present') { window.chatwootSDK = sdk; }

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
const TARGETS = {
  chat: '[data-support-chat]', tg: 'a.support-menu__item', toggle: '[data-support-toggle]', close: '[data-support-close]',
};
const SHEET_CLOSE_MS = 300;

(async () => {
  document.dispatch('DOMContentLoaded');
  // По очереди, с паузой — между кликами успевают отработать промисы (повтор после сбоя и т. п.)
  for (const [index, target] of scenario.clicks || []) {
    const list = roots[index].parts['[data-support-list]'];
    if (target === 'escape') {
      document.dispatch('keydown', { key: 'Escape' });
    } else if (target === 'outside') {
      // клик по странице мимо меню
      document.dispatch('click', { target: { name: 'page' } });
    } else if (target === 'overlay') {
      list.dispatch('click', { target: list });
    } else if (target === 'tab' || target === 'shiftTab') {
      const event = { key: 'Tab', shiftKey: target === 'shiftTab', prevented: false };
      event.preventDefault = () => { event.prevented = true; };
      list.dispatch('keydown', event);
      // без перехвата браузер сам переводит фокус: внутри шторки — на соседний пункт,
      // с краёв — дальше по странице
      if (!event.prevented) {
        const items = list.focusables;
        const at = items.indexOf(document.activeElement);
        const next = at + (event.shiftKey ? -1 : 1);
        document.activeElement = at >= 0 && next >= 0 && next < items.length ? items[next] : { name: 'page' };
      }
    } else if (target === 'desktop') {
      // на ПК значок-шторка в шапке скрыт стилями
      roots.forEach((r) => { if (r.parts['[data-support-list]'].focusables.length) { r.parts['[data-support-toggle]'].visible = false; } });
      desktopQuery.matches = true;
      desktopQuery.dispatch('change', { matches: true });
    } else if (target === 'wait') {
      await sleep(SHEET_CLOSE_MS + 50);
    } else {
      const el = roots[index].parts[TARGETS[target]];
      // браузер ставит фокус на нажатую кнопку
      document.activeElement = el;
      el.dispatch('click', { target: el });
    }
    await sleep(10);
  }

  // Дать отработать промисам (SDK → ready → identity → setUser → toggle).
  await sleep(80 + (scenario.settle || 0));
  const loading = (el) => !!el && el.classes.has('is-loading');
  process.stdout.write(JSON.stringify({
    ...state,
    storedToken: storage.cw_sub_token || null,
    bodyLocked: document.body.classes.has('support-sheet-open'),
    focus: document.activeElement ? document.activeElement.name : null,
    roots: roots.map((r) => ({
      listOpen: !r.parts['[data-support-list]'].hidden,
      closing: r.parts['[data-support-list]'].classes.has('is-closing'),
      status: r.parts['[data-support-status]'].hidden ? '' : r.parts['[data-support-status]'].textContent,
      chatLoading: loading(r.parts['[data-support-chat]']),
      toggleLoading: loading(r.parts['[data-support-toggle]']),
    })),
  }), () => {
    // таймеры скрипта (ожидание chatwoot:ready до 15 с) держали бы процесс — результат уже записан
    process.exit(0);
  });
})();
