/* Tests for sortRows, the sorting of the local tables. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadFrontend } = require('./frontend-harness');

const { sortRows, nextSort } = loadFrontend().context;
// The vm context has its own Array prototype; a JSON round trip makes
// results comparable with strict deep equality.
const plain = (value) => JSON.parse(JSON.stringify(value));
const keys = (rows) => rows.map((row) => row.id);

test('numbers sort numerically, not as text', () => {
  const rows = [{ id: 'a', v: 10 }, { id: 'b', v: 9 }, { id: 'c', v: 100 }];
  assert.deepEqual(keys(sortRows(rows, 'v', 'asc', 'de-DE')), ['b', 'a', 'c']);
  assert.deepEqual(keys(sortRows(rows, 'v', 'desc', 'de-DE')), ['c', 'a', 'b']);
});

test('texts sort by locale with umlauts and numeric digit runs', () => {
  const rows = [
    { id: 'z', v: 'Zebra' }, { id: 'ae', v: 'Aepfel' }, { id: 'ue', v: 'Uebel' },
    { id: 'm10', v: 'model-10' }, { id: 'm9', v: 'model-9' },
  ];
  const asc = keys(sortRows(rows, 'v', 'asc', 'de-DE'));
  assert.ok(asc.indexOf('m9') < asc.indexOf('m10'));
  assert.ok(asc.indexOf('ae') < asc.indexOf('z'));
  // By code point the umlaut would land after Z; the collator files it with A.
  const umlauts = [{ id: 'z', v: 'Zebra' }, { id: 'ae', v: '\u00c4rger' }, { id: 'b', v: 'Berg' }];
  assert.deepEqual(keys(sortRows(umlauts, 'v', 'asc', 'de-DE')), ['ae', 'b', 'z']);
});

test('ISO dates and months sort as text', () => {
  const rows = [{ id: 'b', v: '2026-09-01' }, { id: 'a', v: '2026-08-31' }, { id: 'c', v: '2026-10-01' }];
  assert.deepEqual(keys(sortRows(rows, 'v', 'asc', 'en-US')), ['a', 'b', 'c']);
  const months = [{ id: 'b', v: '2026-10' }, { id: 'a', v: '2026-09' }];
  assert.deepEqual(keys(sortRows(months, 'v', 'desc', 'en-US')), ['b', 'a']);
});

test('booleans put false before true when ascending', () => {
  const rows = [{ id: 't', v: true }, { id: 'f', v: false }];
  assert.deepEqual(keys(sortRows(rows, 'v', 'asc', 'de-DE')), ['f', 't']);
  assert.deepEqual(keys(sortRows(rows, 'v', 'desc', 'de-DE')), ['t', 'f']);
});

test('null and undefined stay at the end in both directions', () => {
  const rows = [{ id: 'n', v: null }, { id: 'a', v: 1 }, { id: 'u' }, { id: 'b', v: 2 }];
  assert.deepEqual(keys(sortRows(rows, 'v', 'asc', 'de-DE')), ['a', 'b', 'n', 'u']);
  assert.deepEqual(keys(sortRows(rows, 'v', 'desc', 'de-DE')), ['b', 'a', 'n', 'u']);
});

test('the sort is stable for equal keys, also when descending', () => {
  const rows = [{ id: '1', v: 5 }, { id: '2', v: 5 }, { id: '3', v: 5 }, { id: '4', v: 1 }];
  assert.deepEqual(keys(sortRows(rows, 'v', 'asc', 'de-DE')), ['4', '1', '2', '3']);
  assert.deepEqual(keys(sortRows(rows, 'v', 'desc', 'de-DE')), ['1', '2', '3', '4']);
});

test('the input array is not modified', () => {
  const rows = [{ id: 'a', v: 3 }, { id: 'b', v: 1 }, { id: 'c', v: 2 }];
  const before = plain(rows);
  const result = sortRows(rows, 'v', 'asc', 'de-DE');
  assert.notEqual(result, rows);
  assert.deepEqual(plain(rows), before);
});

test('nextSort toggles the active column and starts others in their first direction', () => {
  const current = { key: 'cost', dir: 'desc' };
  assert.deepEqual(plain(nextSort(current, 'cost')), { key: 'cost', dir: 'asc' });
  assert.deepEqual(plain(nextSort({ key: 'cost', dir: 'asc' }, 'cost')),
    { key: 'cost', dir: 'desc' });
  assert.deepEqual(plain(nextSort(current, 'start')), { key: 'start', dir: 'desc' });
  assert.deepEqual(plain(nextSort(current, 'project', 'asc')), { key: 'project', dir: 'asc' });
  assert.deepEqual(plain(current), { key: 'cost', dir: 'desc' }, 'the input stays untouched');
});
