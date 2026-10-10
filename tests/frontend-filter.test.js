/* Regression tests for the dependency-free browser filter flow. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { FakeElement, loadFrontend, metricsPayload, answer } = require('./frontend-harness');

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

function localToday() {
  const now = new Date();
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((part) => String(part).padStart(2, '0')).join('-');
}

test('date inputs follow the selected period', () => {
  const frontend = loadFrontend();
  const period = frontend.element('period').listeners.change;
  const from = frontend.element('date-from');
  const to = frontend.element('date-to');

  period({ target: { value: '2026-02' } });
  assert.equal(from.value, '2026-02-01');
  assert.equal(to.value, '2026-02-28');

  period({ target: { value: 'all' } });
  assert.equal(from.value, '2026-05-01');
  assert.equal(to.value, localToday());

  period({ target: { value: '2026-09' } });
  period({ target: { value: 'custom' } });
  assert.equal(from.value, '2026-05-01');
  assert.equal(to.value, localToday());
  assert.equal(
    frontend.requests.at(-1),
    `/api/metrics?from=2026-05-01&to=${localToday()}`);
});

test('a rebuilt period list keeps a custom range', () => {
  const frontend = loadFrontend();
  frontend.element('period').listeners.change({ target: { value: 'custom' } });
  frontend.element('period').value = 'custom';
  frontend.element('date-from').value = '2026-09-03';
  frontend.element('date-to').value = '2026-09-10';
  frontend.element('date-from').listeners.input();

  vm.runInContext(`buildPeriodOptions({
    months: ['2026-09'], range: { from: '2026-08-01', to: '2026-09-30' } })`,
    frontend.context);

  assert.equal(frontend.element('date-from').value, '2026-09-03');
  assert.equal(frontend.element('date-to').value, '2026-09-10');
});

function summarize(exportsList) {
  return vm.runInContext(
    `summarizeExports(${JSON.stringify(exportsList)})`, loadFrontend().context);
}

const job = (name, state, ageHours, cause = null) =>
  ({ job: name, state, ageHours, cause });

test('summarizeExports: no or empty list hides the element', () => {
  assert.equal(summarize([]), null);
  assert.equal(summarize(null), null);
});

test('summarizeExports: all ok, and ok mixed with unknown, is ok', () => {
  assert.equal(summarize([job('daily', 'ok', 3), job('weekly', 'ok', 9)]).state, 'ok');
  assert.equal(summarize([job('daily', 'ok', 3), job('monthly', 'unknown', null)]).state, 'ok');
});

test('summarizeExports: only unknown is unknown', () => {
  assert.equal(summarize([job('daily', 'unknown', null), job('weekly', 'unknown', null)]).state, 'unknown');
});

test('summarizeExports: warn beats ok, error beats warn', () => {
  const warn = summarize([job('daily', 'ok', 3), job('weekly', 'warn', 199, 'overdue')]);
  assert.equal(warn.state, 'warn');
  assert.equal(warn.job.job, 'weekly');
  const error = summarize([job('daily', 'warn', 90, 'last_failed'), job('weekly', 'error', 50, 'gap_risk')]);
  assert.equal(error.state, 'error');
  assert.equal(error.job.job, 'weekly');
});

test('summarizeExports: the higher cause rank wins, even against a greater age', () => {
  const ladder = ['gap_risk', 'never_succeeded', 'last_failed', 'success_unrecorded',
    'future_timestamp', 'overdue'];
  for (let i = 0; i < ladder.length - 1; i += 1) {
    const high = job('weekly', i === 0 ? 'error' : 'warn', 1, ladder[i]);
    const low = job('daily', 'warn', 500, ladder[i + 1]);
    assert.equal(summarize([low, high]).job.job, 'weekly', ladder[i] + ' over ' + ladder[i + 1]);
  }
});

test('summarizeExports: success_unrecorded outranks overdue despite a smaller age', () => {
  const result = summarize([job('daily', 'warn', 300, 'overdue'),
    job('weekly', 'warn', null, 'success_unrecorded')]);
  assert.equal(result.job.job, 'weekly');
});

test('summarizeExports: equal cause goes to the greatest age, then job order', () => {
  const aged = summarize([job('daily', 'warn', 40, 'overdue'), job('weekly', 'warn', 199, 'overdue'),
    job('rtk', 'warn', 50, 'overdue')]);
  assert.equal(aged.job.job, 'weekly');
  const missing = summarize([job('rtk', 'warn', null, 'never_succeeded'),
    job('monthly', 'warn', null, 'never_succeeded'), job('weekly', 'warn', null, 'never_succeeded')]);
  assert.equal(missing.job.job, 'weekly');
});

test('summarizeExports: a negative age counts as missing', () => {
  const result = summarize([job('daily', 'warn', -5, 'future_timestamp'),
    job('weekly', 'warn', 40, 'future_timestamp')]);
  assert.equal(result.job.job, 'weekly');
  const tie = summarize([job('weekly', 'warn', -5, 'future_timestamp'),
    job('daily', 'warn', null, 'future_timestamp')]);
  assert.equal(tie.job.job, 'daily');
});

function headerText(entry) {
  const frontend = loadFrontend();
  const context = frontend.context;
  context.window.I18N.de.strings = {
    'ui.export.stale': 'stale {job} {age}',
    'ui.export.stale_noage': 'noage {job}',
    'ui.export.failed': 'failed {job}',
    'ui.export.job_line': '{job}: {when}',
    'ui.export.never': 'never',
    'ui.export.aria': '{summary}. {jobs}'
  };
  vm.runInContext(
    `renderExportState({ exports: ${JSON.stringify([entry])} })`, context);
  return context.document.getElementById('export-state').textContent;
}

function withConsoleErrors(fn) {
  const calls = [];
  const original = console.error;
  console.error = (...args) => calls.push(args);
  try { fn(); } finally { console.error = original; }
  return calls;
}

test('header text per cause', () => {
  assert.equal(headerText(job('daily', 'warn', 2, 'last_failed')), '! failed daily');
  assert.equal(headerText(job('daily', 'warn', null, 'never_succeeded')), '! failed daily');
  assert.equal(headerText(job('daily', 'warn', -3, 'future_timestamp')), '! noage daily');
  assert.equal(headerText(job('daily', 'warn', null, 'success_unrecorded')), '! noage daily');
  assert.equal(headerText(job('daily', 'warn', 40, 'success_unrecorded')), '! noage daily');
  assert.equal(headerText(job('weekly', 'error', 400, 'gap_risk')), '! stale weekly vor 16 Tagen');
  assert.equal(headerText(job('weekly', 'warn', 200, 'overdue')), '! stale weekly vor 8 Tagen');
  assert.equal(headerText(job('daily', 'warn', 30, 'overdue')), '! stale daily vor 30 Stunden');
});

test('header text for an unexpected cause is age-free and logged once', () => {
  [['mystery', 'warn'], [null, 'warn'], ['mystery', 'error']].forEach(([cause, level]) => {
    let text;
    const calls = withConsoleErrors(() => {
      text = headerText(job('daily', level, 12, cause));
    });
    assert.equal(text, '! noage daily');
    assert.equal(calls.length, 1);
    assert.match(JSON.stringify(calls[0]), /daily/);
    assert.match(JSON.stringify(calls[0]), new RegExp(String(cause)));
  });
});

test('known causes never log to the console', () => {
  const calls = withConsoleErrors(() => {
    headerText(job('daily', 'warn', 40, 'overdue'));
    headerText(job('daily', 'warn', -1, 'future_timestamp'));
    headerText(job('daily', 'warn', null, 'success_unrecorded'));
  });
  assert.equal(calls.length, 0);
});

test('visibilitychange fetches /api/health once while a request is running', () => {
  const frontend = loadFrontend();
  vm.runInContext("state.data = { health: { issues: [], exports: [] } }", frontend.context);
  const before = frontend.requests.length;
  const listener = frontend.documentListeners.visibilitychange;
  assert.equal(typeof listener, 'function');
  listener();
  listener();
  const health = frontend.requests.slice(before).filter((u) => u === '/api/health');
  assert.equal(health.length, 1);
});

test('visibilitychange does nothing while the page is hidden', () => {
  const frontend = loadFrontend();
  vm.runInContext("state.data = { health: { issues: [], exports: [] } }", frontend.context);
  frontend.context.document.visibilityState = 'hidden';
  const before = frontend.requests.length;
  frontend.documentListeners.visibilitychange();
  assert.equal(frontend.requests.length, before);
});

test('stale health response is dropped after a newer loadAll started', async () => {
  const frontend = loadFrontend();
  vm.runInContext("state.data = { health: { issues: [], exports: [], tag: 'old' } }", frontend.context);
  frontend.documentListeners.visibilitychange();
  const stale = frontend.responses.find((r) => r.url === '/api/health');
  vm.runInContext("state.loading = false", frontend.context);
  frontend.context.loadAll(true);
  vm.runInContext("state.data.health = { issues: [], exports: [], tag: 'fresh' }", frontend.context);
  answer(stale, { issues: [], exports: [], tag: 'stale' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(vm.runInContext('state.data.health.tag', frontend.context), 'fresh');
});

test('health is refreshed every 15 minutes, only while visible', () => {
  const frontend = loadFrontend();
  vm.runInContext("state.data = { health: { issues: [], exports: [] } }", frontend.context);
  assert.equal(frontend.intervals.length, 1);
  assert.equal(frontend.intervals[0].ms, 15 * 60 * 1000);
  const count = () => frontend.requests.filter((u) => u === '/api/health').length;
  frontend.context.document.visibilityState = 'hidden';
  frontend.intervals[0].callback();
  assert.equal(count(), 0);
  frontend.context.document.visibilityState = 'visible';
  frontend.intervals[0].callback();
  assert.equal(count(), 1);
});

test('export failure texts come from the catalogue without a special case', () => {
  const frontend = loadFrontend();
  frontend.context.window.I18N.de.strings = {
    'check.export.last_failed': 'files={files:list}',
    'check.export.last_failed_no_targets': 'none {exitCode:int}',
    'check.export.last_failed_after_targets': 'after {exitCode:int}',
  };
  const text = (code, params) => vm.runInContext(
    `issueText(${JSON.stringify({ code, params })})`, frontend.context);
  const base = { job: 'daily', lastAttempt: 'x', exitCode: 1 };
  assert.equal(text('check.export.last_failed', Object.assign({ files: ['2026-10.json'] }, base)),
    'files=2026-10.json');
  assert.equal(text('check.export.last_failed_no_targets', base), 'none 1');
  assert.equal(text('check.export.last_failed_after_targets', base), 'after 1');
  assert.doesNotMatch(fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8'),
    /ui\.export\.no_targets/);
});

test('gapRiskCommand: POSIX path with spaces, interpreter from the backend', () => {
  const context = loadFrontend().context;
  context.dir = '/Users/x/Library/Application Support/Claude-Code-Usage';
  context.runtime = { python: '/opt/homebrew/bin/python3', windows: false };
  assert.equal(
    vm.runInContext('gapRiskCommand(dir, 33, runtime)', context),
    "'/opt/homebrew/bin/python3' " +
    "'/Users/x/Library/Application Support/Claude-Code-Usage/bin/ccusage-export.py' " +
    "weekly --data-dir '/Users/x/Library/Application Support/Claude-Code-Usage' " +
    '--lookback-days 33');
});

test('gapRiskCommand: POSIX single quote is closed, escaped and reopened', () => {
  const context = loadFrontend().context;
  context.dir = "/a$b`c\"d\\e'f";
  context.runtime = { python: 'python3', windows: false };
  const quoted = "'/a$b`c\"d\\e'\\''f";
  assert.equal(
    vm.runInContext('gapRiskCommand(dir, 5, runtime)', context),
    "'python3' " + quoted + "/bin/ccusage-export.py' weekly --data-dir " + quoted +
    "' --lookback-days 5");
});

test('gapRiskCommand: Windows uses PowerShell call syntax and backslashes', () => {
  const context = loadFrontend().context;
  context.dir = "C:\\Users\\O'Neil\\AppData\\Local\\Claude-Code-Usage";
  context.runtime = { python: 'C:\\Program Files\\Python313\\python.exe', windows: true };
  assert.equal(
    vm.runInContext('gapRiskCommand(dir, 20, runtime)', context),
    "& 'C:\\Program Files\\Python313\\python.exe' " +
    "'C:\\Users\\O''Neil\\AppData\\Local\\Claude-Code-Usage\\bin\\ccusage-export.py' " +
    "weekly --data-dir 'C:\\Users\\O''Neil\\AppData\\Local\\Claude-Code-Usage' " +
    '--lookback-days 20');
});

test('gapRiskCommand: PowerShell typographic single quotes are doubled', () => {
  const context = loadFrontend().context;
  context.dir = 'C:\\D\u2019x';
  context.runtime = { python: 'py', windows: true };
  assert.match(vm.runInContext('gapRiskCommand(dir, 1, runtime)', context),
    /--data-dir 'C:\\D\u2019\u2019x'/);
});

test('gapRiskCommand: without runtime falls back to python3 on POSIX', () => {
  const context = loadFrontend().context;
  context.dir = '/d';
  assert.equal(vm.runInContext('gapRiskCommand(dir, 3)', context),
    "'python3' '/d/bin/ccusage-export.py' weekly --data-dir '/d' --lookback-days 3");
});
