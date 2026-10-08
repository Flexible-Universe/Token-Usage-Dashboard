/* Tests for the view state kept in the URL hash. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { loadFrontend, answer } = require('./frontend-harness');

const MODELS = ['claude-opus-4-1', 'gpt-5'];
const DATA = {
  directory: '/d',
  files: [],
  months: ['2026-08', '2026-09'],
  models: MODELS,
  range: { from: '2026-08-01', to: '2026-09-14' },
  health: {
    filesAccepted: 2, filesFound: 2, daysLoaded: 10, tokenSumOk: 10,
    tokenSumFailed: 0, costSumOk: 10, costSumFailed: 0,
    fileChecks: [], issues: [], exports: [],
  },
};

const tick = () => new Promise(setImmediate);
// The vm context has its own Object prototype; a JSON round trip makes
// results comparable with strict deep equality.
const plain = (value) => JSON.parse(JSON.stringify(value));
const read = (frontend, expression) => vm.runInContext(expression, frontend.context);
const metricsRequests = (frontend) =>
  frontend.requests.filter((url) => url.startsWith('/api/metrics'));

async function boot(hash = '') {
  const frontend = loadFrontend(hash);
  const request = frontend.responses.find((r) => r.url === '/api/data');
  answer(request, DATA);
  await tick();
  await tick();
  return frontend;
}

const VIEW = {
  tab: 'projects', period: '2026-09', from: '', to: '', measure: 'tokens',
  models: ['gpt-5'],
};

test('formatViewHash: all defaults give the empty hash', () => {
  const { context } = loadFrontend();
  const view = {
    tab: 'overview', period: 'all', from: '', to: '', measure: 'cost',
    models: [...MODELS],
  };
  assert.equal(context.formatViewHash(view, MODELS), '');
});

test('format, parse and resolve round trip to the same view', () => {
  const { context } = loadFrontend();
  const hash = context.formatViewHash(VIEW, MODELS);
  assert.equal(hash, '#tab=projects&period=2026-09&measure=tokens&models=gpt-5');
  const resolved = context.resolveView(context.parseViewHash(hash), DATA);
  assert.deepEqual(plain(resolved.view), VIEW);
  assert.deepEqual(plain(resolved.fallbacks), []);
});

test('custom range survives the round trip', () => {
  const { context } = loadFrontend();
  const view = {
    tab: 'overview', period: 'custom', from: '2026-09-01', to: '2026-09-10',
    measure: 'cost', models: [...MODELS],
  };
  const hash = context.formatViewHash(view, MODELS);
  assert.equal(hash, '#period=custom&from=2026-09-01&to=2026-09-10');
  const resolved = context.resolveView(context.parseViewHash(hash), DATA);
  assert.deepEqual(plain(resolved.view), view);
});

test('models= means none, a missing models key means all', () => {
  const { context } = loadFrontend();
  const none = context.resolveView(context.parseViewHash('#models='), DATA);
  assert.deepEqual(plain(none.view.models), []);
  assert.deepEqual(plain(none.fallbacks), []);
  const all = context.resolveView(context.parseViewHash('#tab=rtk'), DATA);
  assert.deepEqual(plain(all.view.models), MODELS);
  const view = Object.assign({}, VIEW, { models: [] });
  assert.match(context.formatViewHash(view, MODELS), /&models=$/);
});

test('resolveView: unknown month falls back to all with a note', () => {
  const { context } = loadFrontend();
  const resolved = context.resolveView(context.parseViewHash('#period=2026-01'), DATA);
  assert.equal(resolved.view.period, 'all');
  assert.equal(resolved.fallbacks.length, 1);
});

test('resolveView: unknown models are dropped, none left means all', () => {
  const { context } = loadFrontend();
  const some = context.resolveView(
    context.parseViewHash('#models=gpt-5,nope'), DATA);
  assert.deepEqual(plain(some.view.models), ['gpt-5']);
  assert.equal(some.fallbacks.length, 1);
  const none = context.resolveView(context.parseViewHash('#models=nope'), DATA);
  assert.deepEqual(plain(none.view.models), MODELS);
  assert.equal(none.fallbacks.length, 1);
});

test('resolveView: invalid custom ranges fall back to all', () => {
  const { context } = loadFrontend();
  const cases = [
    '#period=custom&from=2026-09-10&to=2026-09-01',
    '#period=custom&from=2026-13-01&to=2026-09-01',
    '#period=custom&from=garbage&to=2026-09-01',
    '#period=custom&from=2026-09-01',
  ];
  cases.forEach((hash) => {
    const resolved = context.resolveView(context.parseViewHash(hash), DATA);
    assert.equal(resolved.view.period, 'all', hash);
    assert.equal(resolved.fallbacks.length, 1, hash);
  });
});

test('from and to without period=custom are ignored', () => {
  const { context } = loadFrontend();
  const resolved = context.resolveView(
    context.parseViewHash('#period=2026-09&from=2026-09-01&to=2026-09-05'), DATA);
  assert.equal(resolved.view.period, '2026-09');
  assert.equal(resolved.view.from, '');
  assert.equal(resolved.view.to, '');
});

test('encoded model names survive the round trip', () => {
  const { context } = loadFrontend();
  const models = ['a b&c=d', 'x/y#z'];
  const data = Object.assign({}, DATA, { models });
  const view = Object.assign({}, VIEW, { period: 'all', models: ['x/y#z'] });
  const hash = context.formatViewHash(view, models);
  assert.doesNotMatch(hash.slice(1), /[ #]/);
  const resolved = context.resolveView(context.parseViewHash(hash), data);
  assert.deepEqual(plain(resolved.view.models), ['x/y#z']);
});

test('start with tab and measure applies them without pushState', async () => {
  const frontend = await boot('#tab=projects&measure=tokens');
  assert.equal(read(frontend, 'state.tab'), 'projects');
  assert.equal(read(frontend, 'state.measure'), 'tokens');
  assert.equal(frontend.history.pushes.length, 0);
});

test('start with a custom range sets the fields and the request', async () => {
  const frontend = await boot('#period=custom&from=2026-09-01&to=2026-09-10');
  assert.equal(frontend.element('date-from').value, '2026-09-01');
  assert.equal(frontend.element('date-to').value, '2026-09-10');
  assert.equal(
    metricsRequests(frontend).at(-1), '/api/metrics?from=2026-09-01&to=2026-09-10');
});

test('start with an unknown month falls back and cleans the hash', async () => {
  const frontend = await boot('#period=2026-01&tab=rtk');
  assert.equal(read(frontend, 'state.period'), 'all');
  assert.equal(frontend.history.replaces.length, 1);
  assert.equal(frontend.history.replaces[0], '/#tab=rtk');
  assert.equal(frontend.history.pushes.length, 0);
});

test('a period change pushes exactly one entry', async () => {
  const frontend = await boot();
  frontend.element('period').listeners.change({ target: { value: '2026-09' } });
  assert.deepEqual(frontend.history.pushes, ['/#period=2026-09']);
});

test('date input replaces for a valid range and writes nothing otherwise', async () => {
  const frontend = await boot();
  frontend.element('period').listeners.change({ target: { value: 'custom' } });
  frontend.history.pushes.length = 0;
  frontend.history.replaces.length = 0;

  frontend.element('date-from').value = '2026-09-01';
  frontend.element('date-to').value = '2026-09-10';
  frontend.element('date-from').listeners.input();
  assert.equal(frontend.history.pushes.length, 0);
  assert.equal(frontend.history.replaces.length, 1);

  frontend.element('date-from').value = '2026-09-20';
  frontend.element('date-from').listeners.input();
  assert.equal(frontend.history.pushes.length, 0);
  assert.equal(frontend.history.replaces.length, 1);
});

test('popstate applies the new hash once and never pushes', async () => {
  const frontend = await boot();
  await tick();
  const before = metricsRequests(frontend).length;
  frontend.location.hash = '#tab=sessions&period=2026-09&measure=tokens';
  frontend.windowListeners.popstate();
  assert.equal(read(frontend, 'state.tab'), 'sessions');
  assert.equal(read(frontend, 'state.period'), '2026-09');
  assert.equal(read(frontend, 'state.measure'), 'tokens');
  assert.equal(metricsRequests(frontend).length, before + 1);
  assert.equal(frontend.history.pushes.length, 0);

  frontend.windowListeners.hashchange();
  assert.equal(metricsRequests(frontend).length, before + 1);
});

test('popstate with an unknown model replaces the hash and does not push', async () => {
  const frontend = await boot();
  frontend.location.hash = '#models=gpt-5,nope';
  frontend.windowListeners.popstate();
  assert.deepEqual([...read(frontend, 'state.selectedModels')], ['gpt-5']);
  assert.equal(frontend.history.pushes.length, 0);
  assert.equal(frontend.history.replaces.at(-1), '/#models=gpt-5');
});

test('popstate before /api/data answers does nothing', () => {
  const frontend = loadFrontend();
  frontend.location.hash = '#tab=rtk';
  const before = frontend.requests.length;
  assert.doesNotThrow(() => frontend.windowListeners.popstate());
  assert.equal(frontend.requests.length, before);
});

test('resolveView: undecodable model names count as unusable, not as none', () => {
  const { context } = loadFrontend();
  const resolved = context.resolveView(context.parseViewHash('#models=%ZZ'), DATA);
  assert.deepEqual(plain(resolved.view.models), MODELS);
  assert.ok(resolved.fallbacks.includes('models'));
});

test('resolveView: broken tab, measure, period and dates are reported', () => {
  const { context } = loadFrontend();
  ['#tab=nope', '#measure=nope', '#period=nope', '#period=custom&from=x&to=2026-09-01',
    '#period=custom&from=2026-09-01&to=%ZZ'].forEach((hash) => {
    const resolved = context.resolveView(context.parseViewHash(hash), DATA);
    assert.ok(resolved.fallbacks.length > 0, hash);
  });
  const clean = context.resolveView(context.parseViewHash('#tab=rtk'), DATA);
  assert.deepEqual(plain(clean.fallbacks), []);
});

test('popstate with a broken tab warns and writes the cleaned hash', async () => {
  const frontend = await boot();
  frontend.location.hash = '#tab=nope&measure=tokens';
  frontend.windowListeners.popstate();
  assert.equal(frontend.history.replaces.at(-1), '/#measure=tokens');
  assert.equal(frontend.history.pushes.length, 0);
});

test('formatViewHash orders models by the data order, not by click order', () => {
  const { context } = loadFrontend();
  const all = ['a', 'b', 'c'];
  const view = Object.assign({}, VIEW, { tab: 'overview', period: 'all', measure: 'cost',
    models: ['c', 'a'] });
  assert.equal(context.formatViewHash(view, all), '#models=a,c');
});

test('an invalid range typed into the date fields does not enter the state', async () => {
  const frontend = await boot('#period=custom&from=2026-09-01&to=2026-09-10');
  frontend.element('date-from').value = '2026-09-20';
  frontend.element('date-from').listeners.input();
  assert.equal(read(frontend, 'state.from'), '2026-09-01');
  frontend.element('date-from').value = '';
  frontend.element('date-from').listeners.input();
  assert.equal(read(frontend, 'state.from'), '2026-09-01');
});

test('a hash change of only the tab does not reload metrics', async () => {
  const frontend = await boot();
  await tick();
  const before = metricsRequests(frontend).length;
  frontend.location.hash = '#tab=rtk';
  frontend.windowListeners.popstate();
  assert.equal(read(frontend, 'state.tab'), 'rtk');
  assert.equal(metricsRequests(frontend).length, before);
});

test('a hash change of only the measure does not reload metrics', async () => {
  const frontend = await boot();
  await tick();
  const before = metricsRequests(frontend).length;
  frontend.location.hash = '#measure=tokens';
  frontend.windowListeners.popstate();
  assert.equal(read(frontend, 'state.measure'), 'tokens');
  assert.equal(metricsRequests(frontend).length, before);
});

const SESSIONS_DEFAULTS = { project: '', sort: 'cost', dir: 'desc', page: 1 };

test('sessions keys: default values are left out of the hash', () => {
  const { context } = loadFrontend();
  const view = {
    tab: 'overview', period: 'all', from: '', to: '', measure: 'cost',
    models: [...MODELS],
  };
  assert.equal(context.formatViewHash(view, MODELS, SESSIONS_DEFAULTS), '');
  assert.equal(context.formatViewHash(view, MODELS,
    { ...SESSIONS_DEFAULTS, page: 2 }), '#page=2');
  assert.equal(context.formatViewHash(view, MODELS,
    { ...SESSIONS_DEFAULTS, dir: 'asc' }), '#sort=cost-asc');
});

test('sessions keys round trip, independent of the active tab', () => {
  const { context } = loadFrontend();
  const sessions = { project: '/a b/c', sort: 'duration', dir: 'asc', page: 3 };
  const hash = context.formatViewHash(VIEW, MODELS, sessions);
  assert.equal(hash, '#tab=projects&period=2026-09&measure=tokens&models=gpt-5'
    + '&project=%2Fa%20b%2Fc&sort=duration-asc&page=3');
  const resolved = context.resolveView(context.parseViewHash(hash), DATA);
  assert.deepEqual(plain(resolved.sessions), sessions);
  assert.deepEqual(plain(resolved.fallbacks), []);
});

test('parseViewHash: malformed sessions values fall back and are reported', () => {
  const { context } = loadFrontend();
  ['sort=bogus-asc', 'sort=cost-up', 'sort=cost', 'sort=-asc', 'page=0', 'page=-2',
    'page=abc', 'page=1.5', 'project=%E0%A4%A'].forEach((pair) => {
    const raw = context.parseViewHash('#' + pair);
    const key = pair.split('=')[0];
    assert.deepEqual(plain(raw.sessions), SESSIONS_DEFAULTS, pair);
    assert.deepEqual(plain(raw.invalid), [key], pair);
  });
});

test('parseViewHash: absurd page values are invalid, sane large ones are kept', () => {
  const { context } = loadFrontend();
  ['page=99999999999999999999999', 'page=9007199254740993', 'page=1e23'].forEach((pair) => {
    const raw = context.parseViewHash('#' + pair);
    assert.equal(raw.sessions.page, 1, pair);
    assert.deepEqual(plain(raw.invalid), ['page'], pair);
  });
  const big = context.parseViewHash('#page=100000');
  assert.equal(big.sessions.page, 100000);
  assert.deepEqual(plain(big.invalid), []);
});

test('checkSessionsView: an unknown project stays selected without a reload', () => {
  const { context } = loadFrontend();
  const requested = { project: '/gone', sort: 'tokens', dir: 'asc', page: 1 };
  const response = { projects: [{ project: '/there' }], page: { number: 1 } };
  const result = context.checkSessionsView(requested, response);
  assert.deepEqual(plain(result.view), requested);
  assert.deepEqual(plain(result.reported), []);
});

test('checkSessionsView: a clamped page is adopted and reported without reload', () => {
  const { context } = loadFrontend();
  const requested = { project: '/there', sort: 'cost', dir: 'desc', page: 9 };
  const response = { projects: [{ project: '/there' }], page: { number: 3 } };
  assert.deepEqual(plain(context.checkSessionsView(requested, response)), {
    view: { project: '/there', sort: 'cost', dir: 'desc', page: 3 },
    reported: ['page'],
  });
  const same = context.checkSessionsView(requested,
    { projects: [{ project: '/there' }], page: { number: 9 } });
  assert.deepEqual(plain(same.reported), []);
});

test('start with sessions keys applies them', async () => {
  const frontend = await boot('#tab=sessions&sort=start-asc&page=0');
  assert.deepEqual(plain(read(frontend, 'state.sessionsView')),
    { project: '', sort: 'start', dir: 'asc', page: 1 });
  assert.equal(frontend.history.replaces.at(-1), '/#tab=sessions&sort=start-asc');
});

test('popstate with changed sessions values reloads sessions once, without push', async () => {
  const frontend = await boot('#tab=sessions');
  const sessionsRequests = () =>
    frontend.requests.filter((url) => url.startsWith('/api/sessions'));
  const before = sessionsRequests().length;
  frontend.location.hash = '#tab=sessions&page=2';
  frontend.windowListeners.popstate();
  assert.equal(read(frontend, 'state.sessionsView.page'), 2);
  assert.equal(sessionsRequests().length, before + 1);
  assert.equal(frontend.history.pushes.length, 0);
  frontend.location.hash = '#tab=sessions&page=2&measure=tokens';
  frontend.windowListeners.popstate();
  assert.equal(sessionsRequests().length, before + 1);
});
