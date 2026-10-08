/* Tests for the stack total in stacked chart tooltips. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadFrontend } = require('./frontend-harness');

test('stackTotal: sums numbers and skips gaps', () => {
  const { context } = loadFrontend();
  assert.equal(context.stackTotal([1.5, null, 2]), 3.5);
});

test('stackTotal: no number gives null', () => {
  const { context } = loadFrontend();
  assert.equal(context.stackTotal([null, null]), null);
  assert.equal(context.stackTotal([]), null);
});

test('stackTotal: zero is a value, not a gap', () => {
  const { context } = loadFrontend();
  assert.equal(context.stackTotal([0]), 0);
});

test('stackFooter: only null values give no footer', () => {
  const { context } = loadFrontend();
  const items = [{ parsed: { y: null } }, { parsed: { y: null } }];
  assert.equal(context.stackFooter(items), '');
  assert.equal(context.stackFooter([]), '');
});

test('stackFooter: a total of zero still shows a footer', () => {
  const { context } = loadFrontend();
  assert.match(context.stackFooter([{ parsed: { y: 0 } }]), /ui\.chart\.total/);
});
