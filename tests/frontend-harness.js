/* Shared test harness for frontend tests. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class FakeElement {
  constructor() {
    this.listeners = {};
    this.options = [];
    this.value = '';
    this.hidden = false;
    this.dataset = {};
    this.style = {};
    this.classList = { toggle() {} };
  }

  focus() {}
  scrollIntoView() {}

  add(option) { this.options.push(option); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  append() {}
  appendChild() {}
  prepend() {}
  querySelector() { return null; }
  remove() {}
  setAttribute() {}
}

function loadFrontend(startHash = '') {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement());
    return elements.get(id);
  };
  const requests = [];
  const responses = [];
  const documentListeners = {};
  const intervals = [];
  const windowListeners = {};
  const location = { hash: startHash, pathname: '/', search: '' };
  const history = {
    pushes: [],
    replaces: [],
    pushState(_state, _title, url) { this.pushes.push(url); follow(url); },
    replaceState(_state, _title, url) { this.replaces.push(url); follow(url); },
  };
  // Mirrors the browser: a written URL becomes the new location.hash.
  function follow(url) {
    const index = String(url).indexOf('#');
    location.hash = index >= 0 ? String(url).slice(index) : '';
  }
  const strings = new Proxy({}, {
    get: (_target, key) => String(key),
    getOwnPropertyDescriptor: (_target, key) => ({
      configurable: true, enumerable: true, value: String(key),
    }),
  });
  const context = {
    console,
    location,
    history,
    Date,
    Intl,
    Map,
    Set,
    URLSearchParams,
    setInterval(callback, ms) { intervals.push({ callback, ms }); return intervals.length; },
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
      addEventListener(name, callback) { documentListeners[name] = callback; },
      visibilityState: 'visible',
      title: '',
    },
    window: {
      I18N: {
        de: { locale: 'de-DE', label: 'Deutsch', months: [], strings },
      },
      localStorage: { getItem() { return null; }, setItem() {} },
      sessionStorage: { getItem() { return null; }, setItem() {} },
      matchMedia() { return { addEventListener() {} }; },
      location,
      history,
      addEventListener(name, callback) { windowListeners[name] = callback; },
    },
    navigator: { language: 'de-DE' },
  };
  context.window.window = context.window;
  context.window.document = context.document;
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
  vm.runInContext(source, context, { filename: 'static/app.js' });
  return {
    context, element, requests, responses, documentListeners, intervals,
    windowListeners, location, history,
  };
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

module.exports = {
  FakeElement,
  loadFrontend,
  metricsPayload,
  answer,
};
