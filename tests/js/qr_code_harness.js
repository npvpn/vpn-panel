// Обвязка для tests/test_qr_code_js.py: исполняет настоящий
// app/templates/subscription/scripts/qr-code.js в node:vm с подделкой DOM, qrcode.js и Image
// на поддельных часах (таймаут ожидания логотипа проверяется без реального ожидания).
// Зависимостей нет — только встроенные модули Node.
//
// Вход (argv[2], JSON): { canvas, logo, logoDelay, logoSrc, checkAt: [мс] }
// canvas — есть ли в браузере canvas (иначе qrcode.js рисует таблицей);
// logo: "ok" (загрузился через logoDelay мс) | "fail" (ошибка через logoDelay) | "hang" (не грузится);
// logoSrc — data-logo-src блока (по умолчанию есть; "" — атрибута нет);
// checkAt — моменты, в которые снимаем, что видно в блоке.
// Выход: { qrCalls: [{ into, text, width, height, correctLevel }], logoRequested,
//          snapshots: [{ at, children: [{ kind, width, height, draws }] }] },
// draws — вызовы drawImage на canvas: [источник, ...координаты].
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scenario = JSON.parse(process.argv[2]);
const SCRIPT = path.join(__dirname, '..', '..', 'app', 'templates', 'subscription', 'scripts', 'qr-code.js');

// Поддельные часы: таймеры срабатывают только при advance()
let now = 0;
let timers = [];
function fakeSetTimeout(fn, ms) {
  timers.push({ at: now + (ms || 0), fn });
}
const flush = async () => { for (let i = 0; i < 10; i++) { await Promise.resolve(); } };
async function advanceTo(target) {
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const next = timers[0];
    if (!next || next.at > target) break;
    timers.shift();
    now = next.at;
    next.fn();
    await flush();
  }
  now = target;
  await flush();
}

class FakeCanvas {
  constructor(kind) {
    this.kind = kind;
    this.width = 0;
    this.height = 0;
    this.draws = [];
  }
  getContext(type) {
    if (!scenario.canvas || type !== '2d') return null;
    return { drawImage: (src, ...args) => { this.draws.push([src.kind, ...args]); } };
  }
}

class FakeEl {
  constructor(kind, attrs = {}) {
    this.kind = kind;
    this.attrs = attrs;
    this.children = [];
  }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector(selector) { return this.children.find((c) => c.kind === 'qr-canvas' && selector === 'canvas') || null; }
}

const state = { qrCalls: [], logoRequested: null };

// qrcode.js: с canvas рисует его в переданный элемент, без canvas — таблицу
function QRCode(el, options) {
  state.qrCalls.push({
    into: el === target ? 'target' : 'draft',
    text: options.text,
    width: options.width,
    height: options.height,
    correctLevel: options.correctLevel,
  });
  if (scenario.canvas) {
    const canvas = new FakeCanvas('qr-canvas');
    canvas.width = options.width;
    canvas.height = options.height;
    el.appendChild(canvas);
  } else {
    el.appendChild({ kind: 'table', width: options.width, height: options.height });
  }
}
QRCode.CorrectLevel = { L: 1, M: 0, Q: 3, H: 2 };

class FakeImage {
  constructor() { this.kind = 'logo'; this.src = ''; }
  decode() {
    state.logoRequested = this.src;
    return new Promise((resolve, reject) => {
      if (scenario.logo === 'hang') return;
      fakeSetTimeout(() => (scenario.logo === 'ok' ? resolve() : reject(new Error('EncodingError'))), scenario.logoDelay || 0);
    });
  }
}

const logoSrc = scenario.logoSrc === undefined ? '/statics/subscription/assets/qr-logo.png?v=1' : scenario.logoSrc;
const target = new FakeEl('target', logoSrc ? { 'data-logo-src': logoSrc } : {});

const document = {
  createElement: (tag) => (tag === 'canvas' ? new FakeCanvas('canvas') : new FakeEl(tag)),
};
const window = {};

const context = vm.createContext({
  window, document, QRCode, Image: FakeImage, setTimeout: fakeSetTimeout, Promise, console,
});
vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), context, { filename: SCRIPT });

const snapshot = (at) => ({
  at,
  children: target.children.map((c) => ({ kind: c.kind, width: c.width, height: c.height, draws: c.draws ? c.draws.map((d) => [...d]) : [] })),
});

(async () => {
  window.renderSubscriptionQr(target, 'https://sub.example/sub/TOKEN/');
  const snapshots = [];
  for (const at of scenario.checkAt || [0]) {
    await advanceTo(at);
    snapshots.push(snapshot(at));
  }
  process.stdout.write(JSON.stringify({ ...state, snapshots }));
})();
