/* Tests for the footer version line. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadFrontend } = require('./frontend-harness');

test('versionView: a release shows the plain version', () => {
  const { context } = loadFrontend();
  const view = context.versionView({ version: '1.2.0', release: true, commit: null });
  assert.equal(view.key, 'ui.foot.version');
  assert.deepEqual({ ...view.params }, { version: '1.2.0' });
  assert.equal(view.commit, null);
});

test('versionView: a clone with a commit carries the short hash', () => {
  const { context } = loadFrontend();
  const view = context.versionView({ version: '1.2.0', release: false, commit: 'abc1234' });
  assert.equal(view.key, 'ui.foot.version.dev');
  assert.deepEqual({ ...view.params }, { version: '1.2.0' });
  assert.equal(view.commit, 'abc1234');
});

test('versionView: a clone without a commit has its own key', () => {
  const { context } = loadFrontend();
  const view = context.versionView({ version: '1.2.0', release: false, commit: null });
  assert.equal(view.key, 'ui.foot.version.devNoCommit');
  assert.equal(view.commit, null);
});

test('versionView: a null version is unknown', () => {
  const { context } = loadFrontend();
  const view = context.versionView({ version: null, release: false, commit: 'abc1234' });
  assert.equal(view.key, 'ui.foot.version.unknown');
  assert.equal(view.commit, null);
});

test('versionView: a missing app object gives no view', () => {
  const { context } = loadFrontend();
  assert.equal(context.versionView(undefined), null);
});

test('renderVersion: a missing app object leaves the line empty', () => {
  const { context, element } = loadFrontend();
  element('app-version').textContent = 'stale';
  context.renderVersion({});
  assert.equal(element('app-version').textContent, '');
});
