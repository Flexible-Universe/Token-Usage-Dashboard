/* Tests for the collapsible status line. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadFrontend } = require('./frontend-harness');

function health(issues) {
  return {
    filesAccepted: 5, filesFound: 5, daysLoaded: 40,
    tokenSumOk: 40, tokenSumFailed: 0, costSumOk: 40, costSumFailed: 0,
    fileChecks: [{ ok: true }], issues, exports: [],
  };
}

const issue = (level, code) => ({ level, code, key: 'k', params: {} });

test('statusView: no issues gives the short line', () => {
  const { context } = loadFrontend();
  const view = context.statusView(health([]));
  assert.equal(view.level, 'ok');
  assert.equal(view.key, 'ui.status.ok_short');
  assert.deepEqual({ ...view.params }, { accepted: 5, days: 40 });
  assert.equal(view.infoCount, 0);
});

test('statusView: info only keeps ok and shows the note count', () => {
  const { context } = loadFrontend();
  const view = context.statusView(health([
    issue('info', 'check.weekrun.skipped'), issue('info', 'check.export.never_logged')]));
  assert.equal(view.level, 'ok');
  assert.equal(view.key, 'ui.status.ok_short_info');
  assert.equal(view.params.notes, 2);
  assert.equal(view.infoCount, 2);
});

test('statusView: a single status_missing counts as a note', () => {
  const { context } = loadFrontend();
  const view = context.statusView(health([issue('info', 'check.export.status_missing')]));
  assert.equal(view.key, 'ui.status.ok_short_info');
  assert.equal(view.params.notes, 1);
});

test('statusView: warn with info shows the full summary', () => {
  const { context } = loadFrontend();
  const view = context.statusView(health([
    issue('warn', 'x'), issue('info', 'check.export.status_missing')]));
  assert.equal(view.level, 'warn');
  assert.equal(view.key, 'ui.status.summary');
  assert.equal(view.params.found, 5);
  assert.equal(view.infoCount, 1);
});

test('statusView: error beats warn', () => {
  const { context } = loadFrontend();
  const view = context.statusView(health([issue('warn', 'x'), issue('error', 'y')]));
  assert.equal(view.level, 'error');
  assert.equal(view.key, 'ui.status.summary');
});

test('renderStatus changes the open state only on a level change', () => {
  const { context, element } = loadFrontend();
  const details = element('status-details');
  const render = (issues) => context.renderStatus({ directory: '/d', health: health(issues) });

  render([]);
  assert.equal(details.open, false);
  assert.equal(element('status-detail-line').hidden, false);
  assert.equal(element('status-detail-line').textContent, 'ui.status.summary');

  details.open = true;
  render([]);
  assert.equal(details.open, true);

  render([issue('warn', 'x')]);
  assert.equal(details.open, true);
  assert.equal(element('status-detail-line').hidden, true);
  assert.equal(element('status-detail-line').textContent, '');

  render([issue('error', 'y')]);
  assert.equal(details.open, true);

  render([]);
  assert.equal(details.open, false);
});

test('showFatal hides the details and renderStatus shows them again', () => {
  const { context, element } = loadFrontend();
  context.showFatal('boom');
  assert.equal(element('status-details').hidden, true);
  context.renderStatus({ directory: '/d', health: health([]) });
  assert.equal(element('status-details').hidden, false);
});

test('clicking the export state opens the details', () => {
  const { element } = loadFrontend();
  element('status-details').open = false;
  element('export-state').listeners.click();
  assert.equal(element('status-details').open, true);
});

test('export badge does nothing while a fatal error hides the details', () => {
  const frontend = loadFrontend();
  const details = frontend.element('status-details');
  let scrolled = 0;
  frontend.element('status').scrollIntoView = () => { scrolled += 1; };
  frontend.context.showFatal('boom');
  assert.equal(details.hidden, true);
  frontend.element('export-state').listeners.click();
  assert.equal(details.open, undefined);
  assert.equal(scrolled, 0);
  details.hidden = false;
  frontend.element('export-state').listeners.click();
  assert.equal(details.open, true);
  assert.equal(scrolled, 1);
});
