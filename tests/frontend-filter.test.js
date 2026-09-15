/* Regression tests for the dependency-free browser filter flow. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

class FakeElement {
  constructor() {
    this.listeners = {};
    this.options = [];
    this.value = '';
    this.hidden = false;
    this.dataset = {};
    this.classList = { toggle() {} };
  }

  add(option) { this.options.push(option); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  append() {}
  appendChild() {}
  prepend() {}
  querySelector() { return null; }
  remove() {}
  setAttribute() {}
}

function loadFrontend() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement());
    return elements.get(id);
  };
  const requests = [];
  const responses = [];
  const strings = new Proxy({}, {
    get: (_target, key) => String(key),
    getOwnPropertyDescriptor: (_target, key) => ({
      configurable: true, enumerable: true, value: String(key),
    }),
  });
  const context = {
    console,
    Date,
    Intl,
    Map,
    Set,
    URLSearchParams,
    Option: function Option(text, value) { return { text, value }; },
    fetch(url) {
      requests.push(url);
      return new Promise((resolve) => responses.push({ url, resolve }));
    },
    getComputedStyle() { return { getPropertyValue() { return ''; } }; },
    document: {
      documentElement: {},
      getElementById: element,
      querySelector() { return new FakeElement(); },
      querySelectorAll() { return []; },
      createElement() { return new FakeElement(); },
      createTextNode(text) { return text; },
      title: '',
    },
    window: {
      I18N: {
        de: { locale: 'de-DE', label: 'Deutsch', months: [], strings },
      },
      localStorage: { getItem() { return null; }, setItem() {} },
      sessionStorage: { getItem() { return null; }, setItem() {} },
      matchMedia() { return { addEventListener() {} }; },
    },
    navigator: { language: 'de-DE' },
  };
  context.window.window = context.window;
  context.window.document = context.document;
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
  vm.runInContext(source, context, { filename: 'static/app.js' });
  return { context, element, requests, responses };
}

function metricsPayload(dateFrom) {
  return {
    filter: { from: dateFrom, to: '2026-09-14', models: [] },
    summary: { daysWithData: 0 },
    months: [],
    cumulativeByMonth: { labels: [], series: [] },
    dailySeries: {
      labels: [], cost: [], tokens: [], outputTokens: [],
      costPerMillionTokens: [], costPerMillionTokensMA7: [],
      contextReloadFactor: [],
    },
    stackedByModel: { labels: [], datasets: [] },
    models: [],
    pareto: { labels: [], cost: [], tokens: [], cumulativePercent: [] },
    timeline: [],
    topDays: [],
    projection: null,
    agentSplit: { labels: [], datasets: [], firstAgentsDate: null },
  };
}

function answer(request, payload) {
  request.resolve({ ok: true, json: async () => payload });
}

test('custom date input immediately requests the visible range', () => {
  const frontend = loadFrontend();
  frontend.element('period').listeners.change({ target: { value: 'custom' } });
  frontend.element('date-from').value = '2026-09-01';
  frontend.element('date-to').value = '2026-09-14';

  assert.equal(typeof frontend.element('date-from').listeners.input, 'function');
  frontend.element('date-from').listeners.input();

  assert.equal(
    frontend.requests.at(-1),
    '/api/metrics?from=2026-09-01&to=2026-09-14');
});

test('date inputs are enabled only for a custom period', () => {
  const frontend = loadFrontend();
  const period = frontend.element('period').listeners.change;
  const from = frontend.element('date-from');
  const to = frontend.element('date-to');

  period({ target: { value: 'all' } });
  assert.equal(from.disabled, true);
  assert.equal(to.disabled, true);

  period({ target: { value: '2026-09' } });
  assert.equal(from.disabled, true);
  assert.equal(to.disabled, true);

  period({ target: { value: 'custom' } });
  assert.equal(from.disabled, false);
  assert.equal(to.disabled, false);
});

test('an older metrics response cannot replace the latest date range', async () => {
  const frontend = loadFrontend();
  frontend.element('period').listeners.change({ target: { value: 'custom' } });
  frontend.element('date-from').value = '2026-09-01';
  frontend.element('date-to').value = '2026-09-14';
  frontend.element('date-from').listeners.input();
  const older = frontend.responses.at(-1);

  frontend.element('date-from').value = '2026-09-02';
  frontend.element('date-from').listeners.input();
  const latest = frontend.responses.at(-1);

  answer(latest, metricsPayload('2026-09-02'));
  await new Promise(setImmediate);
  answer(older, metricsPayload('2026-09-01'));
  await new Promise(setImmediate);

  assert.equal(
    vm.runInContext('state.metrics.filter.from', frontend.context),
    '2026-09-02');
});
