const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
const document = {};
const clipboard = [];
const close = {};
let state;
let onTimeout;

const context = vm.createContext({
  document,
  window: { location: { origin: 'https://panel.example.test' } },
  navigator: { clipboard: { writeText: async (text) => clipboard.push(text) } },
  initialDevices: [],
  fetch: async () => ({ headers: new Map() }),
  setTimeout(callback) {
    onTimeout = callback;
    return 1;
  },
  clearTimeout() {
    onTimeout = undefined;
  },
  Alpine: { data: (_, factory) => { state = factory(); } },
});
document.addEventListener = (event, callback) => {
  assert.equal(event, 'alpine:init');
  callback();
};
vm.runInContext(scenario.controller, context);
state.$refs = { [scenario.closeRef]: close };
context.state = state;

const evaluateBinding = (expression) => vm.runInContext(`with (state) { (${expression}) }`, context);

async function verify() {
  assert.equal(evaluateBinding(scenario.inertBinding), '');

  // Run the real handlers wired to the QR and platform buttons in the rendered page.
  for (const [index, copyHandler] of scenario.copyHandlers.entries()) {
    const trigger = {
      focus(options) {
        assert.equal(options.preventScroll, true);
        document.activeElement = trigger;
      },
    };
    document.activeElement = trigger;
    await evaluateBinding(copyHandler);
    assert.equal(clipboard.length, index + 1);
    assert.equal(clipboard.at(-1), scenario.expectedUrl);
    assert.equal(state.toast, 'Ключ скопирован');
    assert.equal(state.toastKind, 'success');
    assert.equal(evaluateBinding(scenario.inertBinding), null);

    document.activeElement = close;
    if (index === 0) {
      evaluateBinding(scenario.closeHandler);
    } else {
      onTimeout();
    }
    assert.equal(document.activeElement, trigger);
    assert.equal(evaluateBinding(scenario.inertBinding), '');
    assert.equal(onTimeout, undefined);
  }

  await evaluateBinding(scenario.copyHandlers[0]);
  const otherControl = {};
  document.activeElement = otherControl;
  onTimeout();
  assert.equal(document.activeElement, otherControl);
}

verify().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
