/* Tests for the sessions tab: view state, request query, stale answers. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { loadFrontend, answer } = require('./frontend-harness');

// The vm context has its own prototypes; a JSON round trip makes results
// comparable with strict deep equality.
const plain = (value) => JSON.parse(JSON.stringify(value));

function sessionsPayload(marker) {
  return {
    coverage: { complete: true },
    kpis: {
      sessionCount: 0, medianCost: null, maxCost: null,
      maxSessionProject: '', medianDurationMinutes: null,
    },
    histogram: { bounds: [1], counts: [0, 0], cost: [0, 0] },
    rows: [],
    projects: [],
    page: { number: marker, size: 50, total: 0, pages: 1 },
    sort: { key: 'cost', dir: 'desc' },
    project: '',
  };
}

test('period, models, project and sort reset the page, measure does not', () => {
  const { context } = loadFrontend();
  const view = { project: 'p', sort: 'cost', dir: 'desc', page: 4 };
  ['period', 'models', 'project', 'sort'].forEach((cause) => {
    assert.equal(context.sessionsViewAfter(view, cause).page, 1, cause);
  });
  assert.equal(context.sessionsViewAfter(view, 'measure').page, 4);
  assert.equal(view.page, 4, 'the input view is not modified');
  assert.equal(context.sessionsViewAfter(view, 'period').project, 'p');
});

test('the request query omits default values', () => {
  const { context } = loadFrontend();
  const defaults = { project: '', sort: 'cost', dir: 'desc', page: 1 };
  assert.deepEqual(plain(context.sessionsParams(defaults)), {});
  assert.deepEqual(plain(context.sessionsParams(
    { project: '/a/b', sort: 'start', dir: 'asc', page: 3 })),
  { project: '/a/b', sort: 'start', dir: 'asc', page: '3' });
  assert.deepEqual(plain(context.sessionsParams({ ...defaults, dir: 'asc' })),
    { dir: 'asc' });
});

test('duplicate project labels get the path option text', () => {
  const { context } = loadFrontend();
  const options = plain(context.sessionProjectOptions([
    { project: '/a/app', projectLabel: 'app', sessions: 2 },
    { project: '/b/app', projectLabel: 'app', sessions: 1 },
    { project: '/c/lib', projectLabel: 'lib', sessions: 4 },
  ]));
  assert.deepEqual(options.map((option) => option.value), ['', '/a/app', '/b/app', '/c/lib']);
  assert.equal(options[0].text, 'ui.sessions.filter.all');
  assert.equal(options[1].text, 'ui.sessions.filter.option_path');
  assert.equal(options[2].text, 'ui.sessions.filter.option_path');
  assert.equal(options[3].text, 'ui.sessions.filter.option');
});

test('a selected project without sessions stays a selectable option with count 0', () => {
  const { context } = loadFrontend();
  const options = plain(context.sessionProjectOptions(
    [{ project: '/a/app', projectLabel: 'app', sessions: 2 }], '/gone'));
  assert.deepEqual(options.map((option) => option.value), ['', '/a/app', '/gone']);
  const known = plain(context.sessionProjectOptions(
    [{ project: '/a/app', projectLabel: 'app', sessions: 2 }], '/a/app'));
  assert.equal(known.length, 2);
});

test('an overtaken sessions answer is discarded', async () => {
  const frontend = loadFrontend();
  const { context, requests, responses } = frontend;
  const first = context.loadSessions(false);
  const second = context.loadSessions(false);
  // The page load has already asked for /api/data; only count sessions.
  const asked = responses.filter((r) => r.url.startsWith('/api/sessions'));
  assert.equal(asked.length, 2);
  assert.ok(requests.length >= 2);
  answer(asked[1], sessionsPayload(2));
  await second;
  answer(asked[0], sessionsPayload(1));
  await first;
  const shown = vm.runInContext('state.sessions', context);
  assert.equal(shown.page.number, 2);
});

test('an answer for a view that was reset meanwhile is dropped', async () => {
  const frontend = loadFrontend();
  const { context, responses } = frontend;
  vm.runInContext("state.sessionsView = { project: '', sort: 'cost', dir: 'desc', page: 3 }",
    context);
  const pending = context.loadSessions(false);
  context.resetSessionsPage('period');
  const asked = responses.filter((r) => r.url.startsWith('/api/sessions'));
  answer(asked[0], sessionsPayload(3));
  await pending;
  assert.equal(vm.runInContext('state.sessionsView.page', context), 1);
  assert.equal(vm.runInContext('state.sessions', context), null);
});

test('the error of an overtaken request is swallowed, the newest one still throws', async () => {
  const frontend = loadFrontend();
  const { context, responses } = frontend;
  const first = context.loadSessions(false);
  const second = context.loadSessions(false);
  const asked = responses.filter((r) => r.url.startsWith('/api/sessions'));
  asked[0].resolve({ ok: false, status: 500, json: async () => ({}) });
  await assert.doesNotReject(first);
  asked[1].resolve({ ok: false, status: 500, json: async () => ({}) });
  await assert.rejects(second);
});
