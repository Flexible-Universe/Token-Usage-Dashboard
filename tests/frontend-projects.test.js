/* Tests for projectTableRows, the flat row list of the projects table. */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { loadFrontend } = require('./frontend-harness');

const { projectTableRows } = loadFrontend().context;
const plain = (value) => JSON.parse(JSON.stringify(value));

const children = (repo) => [
  { project: repo + '/main', isMain: true, cost: 3 },
  { project: repo + '/wt-a', worktreeLabel: 'wt-a', cost: 2 },
  { project: repo, isRest: true, count: 4, cost: 1 },
];
const table = [
  { project: 'small', cost: 1 },
  { project: 'big', cost: 9, children: children('big') },
  { project: 'mid', cost: 5, children: children('mid') },
];
const flat = (rows) => plain(rows).map((r) => `${r.level}:${r.kind}:${r.row.project}`);

test('collapsed: only repo rows in sort order', () => {
  const rows = projectTableRows(table, { key: 'cost', dir: 'desc' }, new Set(), 'en-US');
  assert.deepEqual(flat(rows), ['0:repo:big', '0:repo:mid', '0:repo:small']);
});

test('expanded repo pulls its children behind it in backend order', () => {
  const rows = projectTableRows(table, { key: 'cost', dir: 'asc' }, new Set(['big']), 'en-US');
  assert.deepEqual(flat(rows), [
    '0:repo:small', '0:repo:mid',
    '0:repo:big', '1:main:big/main', '1:worktree:big/wt-a', '1:rest:big',
  ]);
});

test('repo without children yields no sub rows even when in the set', () => {
  const rows = projectTableRows(table, { key: 'cost', dir: 'asc' }, new Set(['small']), 'en-US');
  assert.deepEqual(flat(rows), ['0:repo:small', '0:repo:mid', '0:repo:big']);
});
