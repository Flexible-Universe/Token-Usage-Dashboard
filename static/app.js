/*
 * Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
 * Copyright (C) 2026 Rolf Warnecke
 *
 * Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
 * GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
 * Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
 * LICENSE oder unter <https://www.gnu.org/licenses/>.
 */
/* Token-Usage-Dashboard: Frontend. Spricht ausschliesslich ueber /api/... */
'use strict';

const HAS_CHARTS = typeof window.Chart !== 'undefined';

// The formatters follow the active language and are therefore rebuilt on
// every language change instead of being fixed at load time.
let nf0, nf1, nf2, nf3, nf4, lf;

function buildFormatters(locale) {
  nf0 = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  nf1 = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  nf2 = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  nf3 = new Intl.NumberFormat(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  nf4 = new Intl.NumberFormat(locale, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  lf = new Intl.ListFormat(locale, { style: 'long', type: 'conjunction' });
}

const PALETTE = [
  '#2f6f4f', '#c1663b', '#3f6ea8', '#8a4f7d', '#b3902f',
  '#4f9b8f', '#a4453f', '#6b6f8c', '#7d9440', '#9c5f2a',
  '#526d8a', '#8f6f9f'
];

// The rest bucket has no model name, so colorFor() has nothing to key on.
// A fixed grey also keeps it visually apart from the named models.
const OTHER_COLOR = '#8b8b8b';

const state = {
  data: null,
  metrics: null,
  selectedModels: new Set(),
  modelColors: new Map(),
  period: 'all',
  from: '',
  to: '',
  measure: 'cost',
  lang: 'de',
  locale: 'de-DE',
  loading: false,
  tab: 'overview',
  projects: null,
  sessions: null,
  blocks: null,
  rtk: null
};

const charts = {};

/* ---------- Formatierung ---------- */
function euroLessDollar(value, digits) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  const fmt = digits === 0 ? nf0 : (digits === 3 ? nf3 : nf2);
  return fmt.format(value) + ' $';
}
function num(value, digits) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return (digits === 2 ? nf2 : (digits === 1 ? nf1 : nf0)).format(value);
}
function pct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return nf1.format(value) + ' %';
}
function catalog() {
  return window.I18N[state.lang];
}

// t: looks up a message and fills its placeholders. The placeholder, not
// the call site, says how a value is formatted - params carry raw numbers
// and ISO dates, and only the catalogue knows what the sentence means.
//
// A missing key is shown as <key> and warned about. There is deliberately
// no fallback to German: a missing English text has to be noticeable.
function t(key, params) {
  const strings = catalog().strings;
  if (!Object.prototype.hasOwnProperty.call(strings, key)) {
    console.warn('i18n: unknown key ' + key);
    return '⟨' + key + '⟩';
  }
  const values = params || {};
  return strings[key].replace(/\{([a-zA-Z0-9_]+)(?::([a-z0-9]+))?\}/g,
    (match, name, spec) => {
      if (!Object.prototype.hasOwnProperty.call(values, name)) {
        console.warn('i18n: missing parameter ' + name + ' for ' + key);
        return match;
      }
      return formatParam(values[name], spec, match, key);
    });
}

function formatParam(value, spec, match, key) {
  if (spec === undefined) return String(value);
  if (spec === 'int') return nf0.format(value);
  if (spec === 'cost') return nf2.format(value) + ' $';
  if (spec === 'cost4') return nf4.format(value) + ' $';
  if (spec === 'date') return formatDate(value);
  if (spec === 'list') return lf.format(value.map(String));
  console.warn('i18n: unknown format "' + spec + '" in ' + key);
  return match;
}

// formatDate deliberately builds the moment without a trailing 'Z': a bare
// '2026-09-01' would otherwise be read as UTC and roll back to the previous
// day in western time zones.
function formatDate(iso) {
  if (!iso) return '–';
  return new Date(iso + 'T00:00:00').toLocaleDateString(state.locale,
    { day: '2-digit', month: '2-digit', year: 'numeric' });
}
function formatMonth(month) {
  const [y, m] = month.split('-');
  return catalog().months[Number(m) - 1] + ' ' + y;
}
function measureLabel() {
  return state.measure === 'cost' ? t('ui.measure.cost') : t('ui.measure.tokens');
}
function measureValue(value) {
  if (value === null || value === undefined) return '–';
  return state.measure === 'cost' ? euroLessDollar(value, 2) : num(value, 0);
}

/* ---------- Farben ---------- */
function colorFor(model) {
  if (!state.modelColors.has(model)) {
    state.modelColors.set(model, PALETTE[state.modelColors.size % PALETTE.length]);
  }
  return state.modelColors.get(model);
}
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* ---------- API ---------- */
// apiQuery: baut die Parameter fuer /api/metrics und fuer die drei
// Reiter-Endpunkte. Alle vier nehmen dieselben Parameter, deshalb nur ein
// Helfer. Rueckgabe schliesst das Fragezeichen ein oder ist leer.
function apiQuery(reload) {
  const params = new URLSearchParams();
  if (reload) params.set('reload', '1');
  const range = activeRange();
  if (range.from) params.set('from', range.from);
  if (range.to) params.set('to', range.to);
  const all = state.data ? state.data.models : [];
  if (state.selectedModels.size && state.selectedModels.size !== all.length) {
    params.set('models', [...state.selectedModels].join(','));
  }
  const query = params.toString();
  return query ? '?' + query : '';
}

function activeRange() {
  if (state.period === 'all') return { from: '', to: '' };
  if (state.period === 'custom') return { from: state.from, to: state.to };
  // Echter Monatsletzter. Ein hart gesetzter 31. waere fuer die reine
  // Zeichenkettenfilterung harmlos, aber insights.coverage schlaegt daraus
  // einen Hinweistext und behauptete fuer April dann etwas Falsches.
  const [year, month] = state.period.split('-').map(Number);
  const last = new Date(year, month, 0).getDate();
  return {
    from: `${state.period}-01`,
    to: `${state.period}-${String(last).padStart(2, '0')}`
  };
}

async function getJSON(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const payload = await response.json()
    .catch(() => ({ code: 'ui.error.not_json', params: {} }));
  if (!response.ok) {
    const error = new Error(t(payload.code || 'ui.error.http',
      payload.params || { status: response.status }));
    throw error;
  }
  return payload;
}

async function loadAll(reload) {
  if (state.loading) return;
  state.loading = true;
  const button = document.getElementById('reload');
  button.disabled = true;
  button.textContent = t('ui.app.loading');
  try {
    const data = await getJSON('/api/data' + (reload ? '?reload=1' : ''));
    const isFirst = state.data === null;
    const known = new Set(state.data ? state.data.models : []);
    state.data = data;
    data.models.forEach(colorFor);
    if (isFirst) {
      data.models.forEach((m) => state.selectedModels.add(m));
    } else {
      // Neu hinzugekommene Modelle werden automatisch mitgewaehlt.
      data.models.filter((m) => !known.has(m)).forEach((m) => state.selectedModels.add(m));
      [...state.selectedModels].filter((m) => !data.models.includes(m))
        .forEach((m) => state.selectedModels.delete(m));
    }
    renderDirectory(data);
    renderStatus(data);
    renderFiles(data);
    buildPeriodOptions(data);
    buildModelFilter(data);
    await loadMetrics(reload);
    // Ohne das bleibt der sichtbare Reiter nach "Daten neu laden" stehen,
    // waehrend Statusbereich und Uebersicht sich aktualisieren.
    renderTab(reload);
    document.getElementById('last-load').textContent =
      t('ui.app.laststate', { time: new Date().toLocaleTimeString(state.locale) });
  } catch (error) {
    showFatal(error.message);
  } finally {
    state.loading = false;
    button.disabled = false;
    button.textContent = t('ui.app.reload');
  }
}

async function loadMetrics(reload) {
  state.metrics = await getJSON('/api/metrics' + apiQuery(reload));
  renderMetrics();
}

async function refreshMetrics() {
  try {
    await loadMetrics(false);
  } catch (error) {
    showFatal(error.message);
  }
  renderTab();
}

/* ---------- Reiter ---------- */
const TABS = ['overview', 'projects', 'sessions', 'blocks', 'rtk'];
const TAB_STORAGE_KEY = 'dashboard.tab';

// Der Zugriff auf sessionStorage kann werfen, etwa wenn der Browser
// Speicherung fuer die Seite sperrt. Das darf das Dashboard nicht anhalten,
// deshalb faellt beides still auf den Reiter Uebersicht zurueck.
function storedTab() {
  try {
    const name = window.sessionStorage.getItem(TAB_STORAGE_KEY);
    return TABS.includes(name) ? name : TABS[0];
  } catch (error) {
    return TABS[0];
  }
}

function rememberTab(name) {
  try {
    window.sessionStorage.setItem(TAB_STORAGE_KEY, name);
  } catch (error) {
    // Kein Speicher verfuegbar: die Auswahl gilt dann nur fuer diese Sicht.
  }
}

// applyTab setzt nur Zustand und Sichtbarkeit, ohne zu laden. Der Seitenaufbau
// benutzt das, damit loadAll den Reiter genau einmal laedt.
function applyTab(name) {
  state.tab = name;
  document.querySelectorAll('.tab').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.tab === name);
  });
  TABS.forEach((tab) => {
    document.getElementById(`tab-${tab}`).hidden = tab !== name;
  });
}

function setTab(name) {
  if (!TABS.includes(name)) return;
  applyTab(name);
  rememberTab(name);
  renderTab();
}

function coverageNote(container, coverage) {
  const existing = container.querySelector('.coverage-note');
  if (existing) existing.remove();
  if (!coverage || coverage.complete) return;
  const note = document.createElement('p');
  note.className = 'coverage-note';
  note.textContent = t(coverage.noteCode, coverage.noteParams);
  container.prepend(note);
}

// renderTab: laedt die Daten des aktiven Reiters vom Server (Wechsel des
// Reiters, Filteraenderung, "Daten neu laden") und zeichnet danach.
function renderTab(reload) {
  // Die Uebersicht laedt ueber /api/metrics und braucht hier nichts zu holen.
  // Neu gezeichnet wird sie trotzdem: gebaut wird sie auch, waehrend
  // #tab-overview versteckt ist, und ein Diagramm mit Hoehe null heilt sich so
  // beim Reiterwechsel selbst.
  if (state.tab === 'overview' && state.metrics) { renderCharts(state.metrics); }
  if (state.tab === 'projects') { loadProjects(reload).catch((e) => showFatal(e.message)); }
  if (state.tab === 'sessions') { loadSessions(reload).catch((e) => showFatal(e.message)); }
  if (state.tab === 'blocks') { loadBlocks(reload).catch((e) => showFatal(e.message)); }
  if (state.tab === 'rtk') { loadRtk(reload).catch((e) => showFatal(e.message)); }
}

// redrawActiveTab: zeichnet nur den bereits geladenen Zustand des aktiven
// Reiters neu, OHNE erneut vom Server zu laden. Fuer Aenderungen, die keine
// neuen Daten brauchen (Massstab-Umschalter, Farbschema-Wechsel).
function redrawActiveTab() {
  // The overview draws through renderCharts and would otherwise keep its old
  // axis labels after a language change. Chart.js builds labels when it
  // draws; chart.update() is not enough once the label text comes from the
  // catalogue.
  if (state.tab === 'overview' && state.metrics) { renderCharts(state.metrics); }
  if (state.tab === 'projects' && state.projects) { renderProjects(); }
  if (state.tab === 'sessions' && state.sessions) { renderSessions(); }
  if (state.tab === 'blocks' && state.blocks) { renderBlocks(); }
  if (state.tab === 'rtk' && state.rtk) { renderRtk(); }
}

/* ---------- Projekte ---------- */
// Erzeugt dieselbe Struktur wie der Helfer kpi(), also ein div.kpi mit den
// Kindern div.label, div.value und div.sub, damit das bestehende CSS greift.
// Gesetzt wird ueber textContent: Werte wie der Projektname stammen von der
// Platte des Nutzers und duerfen nicht als Markup ausgelegt werden.
function kpiCard(label, value, sub) {
  const card = document.createElement('div');
  card.className = 'kpi';
  [['label', label], ['value', value], ['sub', sub || '']].forEach(([name, text]) => {
    const part = document.createElement('div');
    part.className = name;
    part.textContent = text;
    card.appendChild(part);
  });
  return card;
}

async function loadProjects(reload) {
  state.projects = await getJSON('/api/projects' + apiQuery(reload));
  renderProjects();
}

function renderProjects() {
  const payload = state.projects;
  if (!payload) return;
  const panel = document.getElementById('tab-projects');
  coverageNote(panel, payload.coverage);

  const kpis = document.getElementById('projects-kpis');
  kpis.innerHTML = '';
  kpis.appendChild(kpiCard(t('ui.projects.kpi.count'), num(payload.kpis.projectCount, 0)));
  kpis.appendChild(kpiCard(t('ui.projects.kpi.top'), payload.kpis.topProject || '–',
    euroLessDollar(payload.kpis.topProjectCost, 2)));
  kpis.appendChild(kpiCard(t('ui.projects.kpi.share'),
    pct(payload.kpis.topProjectShare * 100)));
  kpis.appendChild(kpiCard(t('ui.common.kpi.totalcost'),
    euroLessDollar(payload.kpis.totalCost, 2),
    t('ui.common.sub.tokens', { tokens: payload.kpis.totalTokens })));

  const body = document.querySelector('#projects-table tbody');
  body.innerHTML = '';
  payload.table.forEach((row) => {
    const tr = document.createElement('tr');
    const name = document.createElement('td');
    name.textContent = row.projectLabel;
    name.title = row.project;
    tr.appendChild(name);
    [euroLessDollar(row.cost, 2), pct(row.share * 100), num(row.tokens, 0),
      num(row.days, 0), euroLessDollar(row.costPerMillion, 2)].forEach((text) => {
      const td = document.createElement('td');
      td.className = 'num';
      td.textContent = text;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  if (!HAS_CHARTS) { chartFallbacks(); return; }
  const base = chartBase();
  const key = state.measure === 'cost' ? 'cost' : 'tokens';
  mount('chart-projects', {
    type: 'bar',
    data: {
      labels: payload.stacked.labels.map(formatDate),
      datasets: payload.stacked.datasets.map((set, index) => ({
        label: set.isOther ? t('ui.projects.other') : set.label,
        data: set[key],
        backgroundColor: PALETTE[index % PALETTE.length],
        borderWidth: 0
      }))
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${measureValue(c.parsed.y)}` } }
      }),
      scales: Object.assign({}, base.scales, {
        x: Object.assign({}, base.scales.x, { stacked: true }),
        y: Object.assign({}, base.scales.y, {
          stacked: true,
          title: { display: true, text: measureLabel(), color: base.__muted }
        })
      })
    })
  });
}

/* ---------- Sessions ---------- */
function formatMoment(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleString(state.locale,
    { day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit' });
}

function formatDuration(minutes) {
  if (minutes === null || minutes === undefined) return '–';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours
    ? t('ui.duration.hours', { hours, minutes: rest })
    : t('ui.duration.minutes', { minutes: rest });
}

function formatRtkDuration(ms) {
  if (ms === null || ms === undefined) return '–';
  if (ms < 1000) return `${nf0.format(ms)} ms`;
  if (ms < 60000) return `${nf1.format(ms / 1000)} s`;
  return formatDuration(Math.round(ms / 60000));
}

// The class bounds are closed on the left: a value of exactly the upper
// bound belongs to the next class up. The labels say so, and they are
// built here because only the frontend knows the language and its number
// format.
function histogramLabels(bounds) {
  return bounds.map((bound, index) => index === 0
    ? t('ui.sessions.hist.below', { max: bound })
    : t('ui.sessions.hist.between', { min: bounds[index - 1], max: bound })
  ).concat(t('ui.sessions.hist.above', { min: bounds[bounds.length - 1] }));
}

async function loadSessions(reload) {
  state.sessions = await getJSON('/api/sessions' + apiQuery(reload));
  renderSessions();
}

function renderSessions() {
  const payload = state.sessions;
  if (!payload) return;
  const panel = document.getElementById('tab-sessions');
  coverageNote(panel, payload.coverage);

  const kpis = document.getElementById('sessions-kpis');
  kpis.innerHTML = '';
  kpis.appendChild(kpiCard(t('ui.sessions.kpi.count'), num(payload.kpis.sessionCount, 0)));
  kpis.appendChild(kpiCard(t('ui.sessions.kpi.median'),
    euroLessDollar(payload.kpis.medianCost, 2)));
  kpis.appendChild(kpiCard(t('ui.sessions.kpi.top'),
    euroLessDollar(payload.kpis.maxCost, 2),
    payload.kpis.maxSessionProject || ''));
  kpis.appendChild(kpiCard(t('ui.sessions.kpi.duration'),
    formatDuration(payload.kpis.medianDurationMinutes),
    t('ui.sessions.kpi.duration.sub')));

  const body = document.querySelector('#sessions-table tbody');
  body.innerHTML = '';
  payload.top.forEach((row) => {
    const tr = document.createElement('tr');
    const cells = [
      [formatMoment(row.first), '', row.sessionId],
      [formatDuration(row.durationMinutes), 'num', ''],
      [row.projectLabel, '', row.project],
      [row.modelsUsed.join(', '), '', ''],
      [euroLessDollar(row.cost, 2), 'num', ''],
      [num(row.tokens, 0), 'num', '']
    ];
    cells.forEach(([text, cls, title]) => {
      const td = document.createElement('td');
      if (cls) td.className = cls;
      td.textContent = text;
      if (title) td.title = title;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  if (!HAS_CHARTS) { chartFallbacks(); return; }
  const base = chartBase();
  const useCost = state.measure === 'cost';
  mount('chart-sessions', {
    type: 'bar',
    data: {
      labels: histogramLabels(payload.histogram.bounds),
      datasets: [{
        label: useCost ? t('ui.sessions.hist.cost') : t('ui.sessions.hist.count'),
        data: useCost ? payload.histogram.cost : payload.histogram.counts,
        backgroundColor: PALETTE[0],
        borderWidth: 0
      }]
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: {
          callbacks: {
            label: (c) => {
              const count = payload.histogram.counts[c.dataIndex];
              const cost = payload.histogram.cost[c.dataIndex];
              return t('ui.sessions.hist.tooltip', { count, cost });
            }
          }
        }
      }),
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: {
            display: true,
            text: useCost ? t('ui.sessions.hist.axis.cost') : t('ui.sessions.hist.axis.count'),
            color: base.__muted
          }
        })
      })
    })
  });
}

/* ---------- Bloecke ---------- */
async function loadBlocks(reload) {
  state.blocks = await getJSON('/api/blocks' + apiQuery(reload));
  renderBlocks();
}

function renderBlocks() {
  const payload = state.blocks;
  if (!payload) return;
  const panel = document.getElementById('tab-blocks');
  coverageNote(panel, payload.coverage);

  const kpis = document.getElementById('blocks-kpis');
  kpis.innerHTML = '';
  kpis.appendChild(kpiCard(t('ui.blocks.kpi.count'), num(payload.kpis.blockCount, 0),
    t('ui.blocks.kpi.gaps', { count: payload.kpis.gapCount })));
  kpis.appendChild(kpiCard(t('ui.blocks.kpi.top'),
    euroLessDollar(payload.kpis.maxCost, 2),
    payload.kpis.maxBlockStart ? formatMoment(payload.kpis.maxBlockStart) : ''));
  kpis.appendChild(kpiCard(t('ui.blocks.kpi.mean'),
    euroLessDollar(payload.kpis.meanCost, 2)));
  kpis.appendChild(kpiCard(t('ui.blocks.kpi.active'),
    payload.kpis.activeShare === null ? '–' : pct(payload.kpis.activeShare * 100)));

  const active = document.getElementById('blocks-active');
  if (payload.active) {
    const projection = payload.active.projectionCost === null
      ? t('ui.blocks.active.noprojection')
      : t('ui.blocks.active.projection', {
          cost: payload.active.projectionCost,
          minutes: payload.active.projectionRemainingMinutes
        });
    active.hidden = false;
    active.textContent = t('ui.blocks.active.line', {
      start: formatMoment(payload.active.start),
      cost: payload.active.cost,
      burn: payload.active.burnRate,
      projection
    });
  } else {
    active.hidden = true;
    active.textContent = '';
  }

  if (!HAS_CHARTS) { chartFallbacks(); return; }
  const base = chartBase();
  const points = payload.timeline.points;
  const useCost = state.measure === 'cost';
  mount('chart-blocks', {
    type: 'bar',
    data: {
      labels: points.map((p) => formatMoment(p.start)),
      datasets: [
        {
          label: useCost ? t('ui.blocks.chart.cost') : t('ui.blocks.chart.tokens'),
          data: points.map((p) => (useCost ? p.cost : p.tokens)),
          backgroundColor: points.map((p) => (p.isActive ? PALETTE[1] : PALETTE[0])),
          borderWidth: 0,
          yAxisID: 'y'
        },
        {
          label: t('ui.blocks.chart.burn'),
          data: points.map((p) => p.burnRate),
          type: 'line',
          borderColor: PALETTE[2],
          backgroundColor: PALETTE[2],
          borderWidth: 2,
          pointRadius: 0,
          spanGaps: false,
          yAxisID: 'y1'
        }
      ]
    },
    options: Object.assign({}, base, {
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: { display: true, text: measureLabel(), color: base.__muted }
        }),
        y1: {
          position: 'right',
          ticks: { color: base.__muted, callback: (v) => nf0.format(v) + ' $' },
          grid: { drawOnChartArea: false },
          title: { display: true, text: t('ui.blocks.chart.axis.burn'), color: base.__muted }
        }
      })
    })
  });
}

/* ---------- RTK ---------- */
async function loadRtk(reload) {
  state.rtk = await getJSON('/api/rtk' + apiQuery(reload));
  renderRtk();
}

function renderRtk() {
  const payload = state.rtk;
  if (!payload) return;
  const panel = document.getElementById('tab-rtk');
  coverageNote(panel, payload.coverage);

  const kpis = document.getElementById('rtk-kpis');
  kpis.innerHTML = '';
  kpis.appendChild(kpiCard(t('ui.rtk.kpi.saved'), num(payload.kpis.savedTokens, 0)));
  kpis.appendChild(kpiCard(t('ui.rtk.kpi.rate'),
    payload.kpis.savingsRate === null ? '–' : pct(payload.kpis.savingsRate * 100)));
  kpis.appendChild(kpiCard(t('ui.rtk.kpi.commands'), num(payload.kpis.commands, 0),
    t('ui.rtk.kpi.commands.sub', { perCommand: payload.kpis.savedTokensPerCommand })));
  kpis.appendChild(kpiCard(t('ui.rtk.kpi.runtime'), formatRtkDuration(payload.kpis.totalTimeMs),
    t('ui.rtk.kpi.runtime.sub', { ms: payload.kpis.avgTimeMsPerCommand })));

  const body = document.querySelector('#rtk-month-table tbody');
  body.innerHTML = '';
  payload.months.forEach((month) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${formatMonth(month.month)}</td>
      <td class="num">${num(month.commands, 0)}</td>
      <td class="num">${num(month.inputTokens, 0)}</td>
      <td class="num">${num(month.savedTokens, 0)}</td>
      <td class="num">${month.savingsRate === null ? '–' : pct(month.savingsRate * 100)}</td>`;
    body.appendChild(row);
  });

  document.getElementById('rtk-note-kind').textContent = t('ui.rtk.note.kind');
  document.getElementById('rtk-note-filter').textContent = t('ui.rtk.note.filter');
  const cov = payload.coverage;
  document.getElementById('rtk-note-coverage').textContent =
    (cov && cov.from && cov.to)
      ? t('ui.rtk.note.coverage', { from: cov.from, to: cov.to })
      : t('ui.rtk.note.nodata');

  if (!HAS_CHARTS) { chartFallbacks(); return; }
  const base = chartBase();
  const daily = payload.daily;
  mount('chart-rtk', {
    type: 'bar',
    data: {
      labels: daily.labels.map(formatDate),
      datasets: [
        {
          label: t('ui.rtk.chart.saved'),
          data: daily.savedTokens,
          backgroundColor: PALETTE[0],
          borderWidth: 0,
          yAxisID: 'y'
        },
        {
          label: t('ui.rtk.chart.rate'),
          data: daily.savingsRate.map((v) => (v === null ? null : v * 100)),
          type: 'line',
          borderColor: PALETTE[2],
          backgroundColor: PALETTE[2],
          borderWidth: 2,
          pointRadius: 0,
          spanGaps: false,
          yAxisID: 'y1'
        }
      ]
    },
    options: Object.assign({}, base, {
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: { display: true, text: t('ui.rtk.chart.saved'), color: base.__muted }
        }),
        y1: {
          position: 'right', min: 0, max: 100,
          ticks: { color: base.__muted, callback: (v) => nf0.format(v) + ' %' },
          grid: { drawOnChartArea: false },
          title: { display: true, text: t('ui.rtk.chart.rate'), color: base.__muted }
        }
      })
    })
  });
}

/* ---------- Kopf und Status ---------- */
const ISSUE_LEVELS = { error: 'ui.issue.error', warn: 'ui.issue.warn', info: 'ui.issue.info' };

// issueText: one message key is composite. check.weekrun.skipped names one
// or two reasons, and the backend ships both lists, either of which may be
// empty. Building the sentence here is the only place where the frontend
// knows about a specific key; it is the exception the catalogue comments on.
function issueText(issue) {
  if (issue.code !== 'check.weekrun.skipped') {
    return t(issue.code, issue.params);
  }
  const reasons = [];
  if (issue.params.missingSessions.length) {
    reasons.push(t('check.weekrun.skipped.sessions',
      { files: issue.params.missingSessions }));
  }
  if (issue.params.missingBlocks.length) {
    reasons.push(t('check.weekrun.skipped.blocks',
      { files: issue.params.missingBlocks }));
  }
  return t('check.weekrun.skipped', { reasons: reasons.join(t('ui.join.and')) });
}

// applyStaticTexts: fills every marked place in index.html from the
// catalogue. textContent only, never innerHTML - the catalogue is trusted
// but the rule holds for the whole file and an exception here would
// invite one elsewhere.
function applyStaticTexts() {
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.getAttribute('data-i18n'));
  });
  document.querySelectorAll('[data-i18n-title]').forEach((node) => {
    node.setAttribute('title', t(node.getAttribute('data-i18n-title')));
  });
  document.querySelectorAll('[data-i18n-aria]').forEach((node) => {
    node.setAttribute('aria-label', t(node.getAttribute('data-i18n-aria')));
  });
  document.title = t('ui.app.title');
}

const LANG_STORAGE_KEY = 'dashboard.lang';

// localStorage rather than sessionStorage: the chosen tab deliberately
// lasts one session, the language has to survive a fresh visit.
// Access can throw when the browser blocks storage for the page; the
// dashboard must not stop there, so both sides fall through quietly.
function storedLang() {
  try {
    const code = window.localStorage.getItem(LANG_STORAGE_KEY);
    return window.I18N[code] ? code : null;
  } catch (error) {
    return null;
  }
}

function rememberLang(code) {
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, code);
  } catch (error) {
    /* storage blocked - the choice simply does not survive the visit */
  }
}

// The browser language counts only while nothing is stored. Once the
// pulldown has been used, localStorage alone decides - otherwise changing
// browsers would overwrite a deliberate choice.
function initialLang() {
  const stored = storedLang();
  if (stored) return stored;
  const base = (navigator.language || '').split('-')[0];
  return window.I18N[base] ? base : 'de';
}

function buildLangSelect() {
  const select = document.getElementById('lang-select');
  select.innerHTML = '';
  Object.keys(window.I18N).forEach((code) => {
    select.add(new Option(window.I18N[code].label, code));
  });
  select.value = state.lang;
  select.addEventListener('change', () => setLanguage(select.value));
}

// setLanguage: no network access. The backend ships keys, so the data
// already loaded stays valid.
function setLanguage(code) {
  if (!window.I18N[code]) return;
  state.lang = code;
  state.locale = window.I18N[code].locale;
  rememberLang(code);
  // Without this a screen reader would read English text with German
  // pronunciation.
  document.documentElement.lang = code;
  buildFormatters(state.locale);
  applyStaticTexts();
  if (state.data) { buildPeriodOptions(state.data); renderStatus(state.data); renderFiles(state.data); }
  if (state.metrics) { renderMetrics(); }
  redrawActiveTab();
}

function renderDirectory(data) {
  document.getElementById('data-directory').textContent = data.directory;
}

function showFatal(message) {
  const box = document.getElementById('status');
  box.className = 'status error';
  document.getElementById('status-line').textContent = t('ui.error.prefix') + message;
  document.getElementById('issue-list').hidden = true;
}

function renderStatus(data) {
  const health = data.health;
  const box = document.getElementById('status');
  const line = document.getElementById('status-line');
  const list = document.getElementById('issue-list');

  // Stufe "info" benennt einen uebersprungenen Pruefschritt und ist kein
  // Befund. Sie faerbt den Statusbereich weder rot noch gelb.
  const errors = health.issues.filter((i) => i.level === 'error');
  const warnings = health.issues.filter((i) => i.level === 'warn');
  box.className = 'status ' + (errors.length ? 'error' : (warnings.length ? 'warn' : 'ok'));

  line.textContent = t('ui.status.summary', {
    accepted: health.filesAccepted,
    found: health.filesFound,
    days: health.daysLoaded,
    tokenOk: health.tokenSumOk,
    tokenFailed: health.tokenSumFailed,
    costOk: health.costSumOk,
    costFailed: health.costSumFailed,
    fileOk: health.fileChecks.filter((f) => f.ok).length,
    fileCount: health.fileChecks.length
  });

  list.innerHTML = '';
  const shown = health.issues.slice(0, 60);
  shown.forEach((issue) => {
    const item = document.createElement('li');
    item.className = 'issue-' + (ISSUE_LEVELS[issue.level] ? issue.level : 'warn');
    const level = t(ISSUE_LEVELS[issue.level] || 'ui.issue.warn');
    item.textContent = '[' + level + '] ' + issue.key + ': ' + issueText(issue);
    list.appendChild(item);
  });
  if (health.issues.length > shown.length) {
    const item = document.createElement('li');
    item.textContent = t('ui.status.more',
      { count: health.issues.length - shown.length });
    list.appendChild(item);
  }
  list.hidden = health.issues.length === 0;
}

function renderFiles(data) {
  const body = document.querySelector('#file-table tbody');
  body.innerHTML = '';
  data.files.forEach((file) => {
    const row = document.createElement('tr');

    const nameTd = document.createElement('td');
    const code = document.createElement('code');
    code.textContent = file.name;
    nameTd.appendChild(code);
    row.appendChild(nameTd);

    const statusTd = document.createElement('td');
    if (file.accepted) {
      statusTd.textContent = t('ui.files.accepted');
    } else {
      const strong = document.createElement('strong');
      strong.textContent = t('ui.files.rejected');
      statusTd.appendChild(strong);
    }
    row.appendChild(statusTd);

    const schemaTd = document.createElement('td');
    schemaTd.textContent = file.schemas.length
      ? file.schemas.map((s) => (s === 'period'
          ? t('ui.files.schema.period') : t('ui.files.schema.date'))).join(', ')
      : '–';
    row.appendChild(schemaTd);

    [nf0.format(file.days),
      file.hasTotals ? nf0.format(file.totals.totalTokens) : '–',
      file.hasTotals ? euroLessDollar(file.totals.totalCost, 2) : '–'
    ].forEach((text) => {
      const td = document.createElement('td');
      td.className = 'num';
      td.textContent = text;
      row.appendChild(td);
    });

    body.appendChild(row);
  });
}

/* ---------- Bedienelemente ---------- */
function buildPeriodOptions(data) {
  const select = document.getElementById('period');
  const previous = state.period;
  select.innerHTML = '';
  const all = new Option(t('ui.filter.period.all'), 'all');
  select.add(all);
  data.months.forEach((month) => select.add(new Option(formatMonth(month), month)));
  select.add(new Option(t('ui.filter.period.custom'), 'custom'));
  select.value = [...select.options].some((o) => o.value === previous) ? previous : 'all';
  state.period = select.value;
  toggleRangeInputs();

  const from = document.getElementById('date-from');
  const to = document.getElementById('date-to');
  if (data.range.from) {
    from.min = data.range.from; from.max = data.range.to;
    to.min = data.range.from; to.max = data.range.to;
    if (!state.from) { state.from = data.range.from; from.value = data.range.from; }
    if (!state.to) { state.to = data.range.to; to.value = data.range.to; }
  }
}

function toggleRangeInputs() {
  const visible = state.period === 'custom';
  document.getElementById('range-control').hidden = !visible;
  document.getElementById('range-control-to').hidden = !visible;
}

function buildModelFilter(data) {
  const box = document.getElementById('model-filter');
  box.innerHTML = '';
  data.models.forEach((model) => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = model;
    input.checked = state.selectedModels.has(model);
    input.addEventListener('change', () => {
      if (input.checked) state.selectedModels.add(model);
      else state.selectedModels.delete(model);
      refreshMetrics();
    });
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = colorFor(model);
    label.append(input, swatch, document.createTextNode(model));
    box.appendChild(label);
  });
}

function setModels(filterFn) {
  state.selectedModels = new Set(state.data.models.filter(filterFn));
  buildModelFilter(state.data);
  refreshMetrics();
}

/* ---------- Kennzahlen ---------- */
function renderMetrics() {
  const m = state.metrics;
  renderKpis(m);
  renderProjection(m);
  renderModelTable(m);
  renderMonthTable(m);
  renderTopDays(m);
  renderAgents(m);
  renderCharts(m);
}

function kpi(label, value, sub) {
  return `<div class="kpi"><div class="label">${label}</div>
    <div class="value">${value}</div>
    <div class="sub">${sub || ''}</div></div>`;
}

function renderKpis(m) {
  const s = m.summary;
  const box = document.getElementById('kpis');
  if (!s.daysWithData) {
    box.innerHTML = '<div class="kpi"><div class="label">' + t('ui.overview.kpi.nodata') +
      '</div><div class="value">–</div><div class="sub">' +
      t('ui.overview.kpi.nodata.sub') + '</div></div>';
    return;
  }
  box.innerHTML = [
    kpi(t('ui.common.kpi.totalcost'), euroLessDollar(s.totalCost, 2),
      t('ui.overview.kpi.range', { first: s.firstDay, last: s.lastDay })),
    kpi(t('ui.overview.kpi.tokens'), num(s.totalTokens, 0),
      t('ui.overview.kpi.tokens.sub', { output: s.outputTokens })),
    kpi(t('ui.common.days_with_data'), num(s.daysWithData, 0),
      t('ui.overview.kpi.missing', { missing: s.missingDays, calendar: s.calendarDays })),
    kpi(t('ui.overview.kpi.median'), euroLessDollar(s.medianCostPerDay, 2),
      t('ui.overview.kpi.median.sub', { mean: s.meanCostPerDay })),
    kpi(t('ui.overview.kpi.maxday'), euroLessDollar(s.maxCostDay.value, 2),
      t('ui.overview.kpi.maxday.sub', { date: s.maxCostDay.date, tokens: s.maxCostDay.totalTokens })),
    kpi(t('ui.overview.kpi.minday'), euroLessDollar(s.minCostDay.value, 2), formatDate(s.minCostDay.date)),
    kpi(t('ui.common.cpm'), euroLessDollar(s.costPerMillionTokens, 3),
      s.minCostPerMillionTokens
        ? t('ui.overview.kpi.cpm.sub', {
            min: s.minCostPerMillionTokens.value, minDate: s.minCostPerMillionTokens.date,
            max: s.maxCostPerMillionTokens.value, maxDate: s.maxCostPerMillionTokens.date
          })
        : ''),
    kpi(t('ui.overview.kpi.reload'), num(s.contextReloadFactor, 1),
      t('ui.overview.kpi.reload.sub'))
  ].join('');
}

function renderProjection(m) {
  const box = document.getElementById('projection');
  const p = m.projection;
  if (!p) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = '';
  const lead = document.createElement('strong');
  lead.textContent = t('ui.overview.projection.lead');
  box.appendChild(lead);
  const rest = document.createElement('span');
  rest.textContent = ' ' + t('ui.overview.projection.body', {
    month: formatMonth(p.month),
    daysWithData: p.daysWithData,
    daysInMonth: p.daysInMonth,
    actualCost: p.actualCost,
    meanCostPerDay: p.meanCostPerDay
  });
  box.appendChild(rest);
  const value = document.createElement('strong');
  value.textContent = ' ' + euroLessDollar(p.projectedCost, 2);
  box.appendChild(value);
  const tail = document.createElement('span');
  tail.textContent = t('ui.overview.projection.tail');
  box.appendChild(tail);
}

function renderModelTable(m) {
  const body = document.querySelector('#model-table tbody');
  body.innerHTML = '';
  m.models.forEach((entry) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><span class="swatch" style="background:${colorFor(entry.model)}"></span> ${entry.model}</td>
      <td><span class="tag">${entry.agent}</span></td>
      <td class="num">${euroLessDollar(entry.cost, 2)}</td>
      <td class="num">${pct(entry.costShare)}</td>
      <td class="num">${num(entry.totalTokens, 0)}</td>
      <td class="num">${num(entry.outputTokens, 0)}</td>
      <td class="num">${euroLessDollar(entry.costPerMillionOutputTokens, 2)}</td>
      <td class="num">${euroLessDollar(entry.costPerMillionTokens, 3)}</td>
      <td class="num">${num(entry.contextReloadFactor, 1)}</td>
      <td class="num">${num(entry.days, 0)}</td>
      <td>${formatDate(entry.firstDay)}</td>
      <td>${formatDate(entry.lastDay)}</td>`;
    body.appendChild(row);
  });
}

function renderMonthTable(m) {
  const body = document.querySelector('#month-table tbody');
  body.innerHTML = '';
  m.months.forEach((month) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${formatMonth(month.month)}</td>
      <td class="num">${num(month.days, 0)}</td>
      <td class="num">${num(month.totalTokens, 0)}</td>
      <td class="num">${euroLessDollar(month.totalCost, 2)}</td>
      <td class="num">${euroLessDollar(month.costPerMillionTokens, 3)}</td>`;
    body.appendChild(row);
  });
  if (m.months.length > 1) {
    const row = document.createElement('tr');
    row.innerHTML = `<td><strong>${t('ui.common.sum')}</strong></td>
      <td class="num"><strong>${num(m.summary.daysWithData, 0)}</strong></td>
      <td class="num"><strong>${num(m.summary.totalTokens, 0)}</strong></td>
      <td class="num"><strong>${euroLessDollar(m.summary.totalCost, 2)}</strong></td>
      <td class="num"><strong>${euroLessDollar(m.summary.costPerMillionTokens, 3)}</strong></td>`;
    body.appendChild(row);
  }
}

function renderTopDays(m) {
  const body = document.querySelector('#topdays-table tbody');
  body.innerHTML = '';
  m.topDays.forEach((day) => {
    const breakdown = day.models.map((entry) =>
      `<span class="tag"><span class="swatch" style="background:${colorFor(entry.model)}"></span> ${entry.model}: ${euroLessDollar(entry.cost, 2)} / ${num(entry.totalTokens, 0)} Tokens</span>`
    ).join(' ');
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${formatDate(day.date)}</td>
      <td class="num">${euroLessDollar(day.totalCost, 2)}</td>
      <td class="num">${num(day.totalTokens, 0)}</td>
      <td class="num">${euroLessDollar(day.costPerMillionTokens, 3)}</td>
      <td class="breakdown">${breakdown}</td>`;
    body.appendChild(row);
  });
}

/* ---------- Diagramme ---------- */
function chartBase() {
  const ink = cssVar('--ink');
  const muted = cssVar('--muted');
  const line = cssVar('--line');
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: ink, boxWidth: 12, font: { size: 11 } } },
      tooltip: { callbacks: {} }
    },
    scales: {
      x: { ticks: { color: muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 14 },
           grid: { color: line } },
      y: { ticks: { color: muted }, grid: { color: line } }
    },
    __ink: ink, __muted: muted, __line: line
  };
}

function mount(id, config) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
  const canvas = document.getElementById(id);
  if (!canvas) return;
  if (!HAS_CHARTS) return;
  charts[id] = new window.Chart(canvas.getContext('2d'), config);
}

function chartFallbacks() {
  document.querySelectorAll('.canvas-box').forEach((box) => {
    if (box.querySelector('.chart-fallback')) return;
    box.innerHTML = '<div class="chart-fallback">' + t('ui.chart.fallback') + '</div>';
  });
}

function renderCharts(m) {
  if (!HAS_CHARTS) { chartFallbacks(); return; }
  renderCumulative(m);
  renderStacked(m);
  renderCpm(m);
  renderPareto(m);
  renderTimeline(m);
  renderReload(m);
}

function renderCumulative(m) {
  const base = chartBase();
  const datasets = m.cumulativeByMonth.series.map((series, index) => ({
    label: formatMonth(series.month),
    data: series.data,
    borderColor: PALETTE[index % PALETTE.length],
    backgroundColor: PALETTE[index % PALETTE.length],
    borderWidth: 2, pointRadius: 0, tension: 0.15, spanGaps: false
  }));
  mount('chart-cumulative', {
    type: 'line',
    data: { labels: m.cumulativeByMonth.labels.map((d) => t('ui.overview.cumulative.day', { day: d })), datasets },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${euroLessDollar(c.parsed.y, 2)}` } }
      }),
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: { display: true, text: t('ui.overview.cumulative.axis'), color: base.__muted },
          ticks: { color: base.__muted, callback: (v) => nf0.format(v) + ' $' }
        })
      })
    })
  });
}

function renderStacked(m) {
  const base = chartBase();
  const key = state.measure;
  const datasets = m.stackedByModel.datasets.map((set) => ({
    label: set.isOther ? t('ui.models.other') : set.model,
    data: set[key],
    backgroundColor: set.isOther ? OTHER_COLOR : colorFor(set.model),
    borderWidth: 0
  }));
  mount('chart-stacked', {
    type: 'bar',
    data: { labels: m.stackedByModel.labels.map(formatDate), datasets },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: {
          callbacks: {
            label: (c) => c.parsed.y === null ? null : `${c.dataset.label}: ${measureValue(c.parsed.y)}`
          }
        }
      }),
      scales: {
        x: Object.assign({}, base.scales.x, { stacked: true }),
        y: Object.assign({}, base.scales.y, {
          stacked: true,
          title: { display: true, text: measureLabel(), color: base.__muted },
          ticks: {
            color: base.__muted,
            callback: (v) => key === 'cost' ? nf0.format(v) + ' $' : nf0.format(v)
          }
        })
      }
    })
  });
}

function renderCpm(m) {
  const base = chartBase();
  mount('chart-cpm', {
    type: 'line',
    data: {
      labels: m.dailySeries.labels.map(formatDate),
      datasets: [
        {
          label: t('ui.overview.cpm.daily'),
          data: m.dailySeries.costPerMillionTokens,
          borderColor: PALETTE[2], backgroundColor: PALETTE[2],
          borderWidth: 1.4, pointRadius: 0, spanGaps: false, tension: 0.1
        },
        {
          label: t('ui.overview.cpm.ma7'),
          data: m.dailySeries.costPerMillionTokensMA7,
          borderColor: PALETTE[1], backgroundColor: PALETTE[1],
          borderWidth: 2.4, pointRadius: 0, spanGaps: false, tension: 0.2
        }
      ]
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${euroLessDollar(c.parsed.y, 3)}` } }
      }),
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: { display: true, text: t('ui.overview.cpm.axis'), color: base.__muted },
          ticks: { color: base.__muted, callback: (v) => nf2.format(v) + ' $' }
        })
      })
    })
  });
}

function renderPareto(m) {
  const base = chartBase();
  const key = state.measure;
  const values = key === 'cost' ? m.pareto.cost : m.pareto.tokens;
  mount('chart-pareto', {
    type: 'bar',
    data: {
      labels: m.pareto.labels,
      datasets: [
        {
          type: 'bar', label: measureLabel(), data: values, yAxisID: 'y',
          backgroundColor: m.pareto.labels.map(colorFor), borderWidth: 0, order: 2
        },
        {
          type: 'line', label: t('ui.overview.pareto.cum'),
          data: m.pareto.cumulativePercent, yAxisID: 'y1',
          borderColor: base.__ink, backgroundColor: base.__ink,
          borderWidth: 2, pointRadius: 3, order: 1
        }
      ]
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: {
          callbacks: {
            label: (c) => c.dataset.yAxisID === 'y1'
              ? t('ui.overview.pareto.tooltip', { value: pct(c.parsed.y) })
              : `${measureLabel()}: ${measureValue(c.parsed.y)}`
          }
        }
      }),
      scales: {
        x: { ticks: { color: base.__muted, maxRotation: 60, minRotation: 45, font: { size: 10 } },
             grid: { color: base.__line } },
        y: {
          position: 'left', ticks: { color: base.__muted,
            callback: (v) => key === 'cost' ? nf0.format(v) + ' $' : nf0.format(v) },
          grid: { color: base.__line }
        },
        y1: {
          position: 'right', min: 0, max: 100,
          ticks: { color: base.__muted, callback: (v) => nf0.format(v) + ' %' },
          grid: { drawOnChartArea: false }
        }
      }
    })
  });
}

function renderTimeline(m) {
  const base = chartBase();
  const entries = m.timeline;
  if (!entries.length) { mount('chart-timeline', { type: 'bar', data: { labels: [], datasets: [] } }); return; }
  const origin = new Date(m.summary.firstDay + 'T00:00:00Z').getTime();
  const dayMs = 86400000;
  const toIndex = (iso) => Math.round((new Date(iso + 'T00:00:00Z').getTime() - origin) / dayMs);
  const fromIndex = (index) => {
    const date = new Date(origin + index * dayMs);
    return formatDate(date.toISOString().slice(0, 10));
  };
  mount('chart-timeline', {
    type: 'bar',
    data: {
      labels: entries.map((e) => e.model),
      datasets: [{
        label: t('ui.overview.timeline.span'),
        data: entries.map((e) => [toIndex(e.firstDay), toIndex(e.lastDay) + 1]),
        backgroundColor: entries.map((e) => colorFor(e.model)),
        borderWidth: 0, borderSkipped: false
      }]
    },
    options: Object.assign({}, base, {
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => {
              const e = entries[c.dataIndex];
              return t('ui.overview.timeline.tooltip',
                { first: e.firstDay, last: e.lastDay, days: e.days });
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          ticks: { color: base.__muted, maxTicksLimit: 8, callback: (v) => fromIndex(v) },
          grid: { color: base.__line }
        },
        y: { ticks: { color: base.__muted, font: { size: 11 } }, grid: { display: false } }
      }
    })
  });
}

function renderReload(m) {
  const base = chartBase();
  mount('chart-reload', {
    type: 'line',
    data: {
      labels: m.dailySeries.labels.map(formatDate),
      datasets: [{
        label: t('ui.overview.reload.series'),
        data: m.dailySeries.contextReloadFactor,
        borderColor: PALETTE[5], backgroundColor: PALETTE[5],
        borderWidth: 1.8, pointRadius: 0, spanGaps: false, tension: 0.15
      }]
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: { callbacks: { label: (c) => t('ui.overview.reload.axis') + ' ' + num(c.parsed.y, 1) } }
      }),
      scales: Object.assign({}, base.scales, {
        y: Object.assign({}, base.scales.y, {
          title: { display: true, text: t('ui.overview.reload.axis'), color: base.__muted },
          ticks: { color: base.__muted, callback: (v) => nf0.format(v) }
        })
      })
    })
  });
}

function renderAgents(m) {
  const split = m.agentSplit;
  const note = document.getElementById('agents-note');
  if (split.firstAgentsDate) {
    note.textContent = t('ui.overview.agents.note.from', { date: split.firstAgentsDate });
  } else {
    note.textContent = t('ui.overview.agents.note.derived');
  }

  if (!HAS_CHARTS) return;
  const base = chartBase();
  const key = state.measure === 'cost' ? 'cost' : 'tokens';
  mount('chart-agents', {
    type: 'bar',
    data: {
      labels: split.labels.map(formatDate),
      datasets: split.datasets.map((set, index) => ({
        label: set.label === 'claude' ? t('ui.agent.claude')
          : (set.label === 'codex' ? t('ui.agent.codex') : set.label),
        data: set[key],
        backgroundColor: PALETTE[index % PALETTE.length],
        borderWidth: 0
      }))
    },
    options: Object.assign({}, base, {
      plugins: Object.assign({}, base.plugins, {
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${measureValue(c.parsed.y)}` } }
      }),
      scales: Object.assign({}, base.scales, {
        x: Object.assign({}, base.scales.x, { stacked: true }),
        y: Object.assign({}, base.scales.y, {
          stacked: true,
          title: { display: true, text: measureLabel(), color: base.__muted }
        })
      })
    })
  });
}

/* ---------- Ereignisse ---------- */
document.getElementById('reload').addEventListener('click', () => loadAll(true));
document.getElementById('period').addEventListener('change', (event) => {
  state.period = event.target.value;
  toggleRangeInputs();
  refreshMetrics();
});
document.getElementById('date-from').addEventListener('change', (event) => {
  state.from = event.target.value; refreshMetrics();
});
document.getElementById('date-to').addEventListener('change', (event) => {
  state.to = event.target.value; refreshMetrics();
});
document.getElementById('measure').addEventListener('change', (event) => {
  state.measure = event.target.value;
  if (state.metrics) renderCharts(state.metrics);
  redrawActiveTab();
});
document.getElementById('models-all').addEventListener('click', () => setModels(() => true));
document.getElementById('models-none').addEventListener('click', () => setModels(() => false));
document.getElementById('models-claude').addEventListener('click',
  () => setModels((m) => !m.startsWith('gpt-')));
document.getElementById('models-codex').addEventListener('click',
  () => setModels((m) => m.startsWith('gpt-')));
document.querySelectorAll('.tab').forEach((button) => {
  button.addEventListener('click', () => setTab(button.dataset.tab));
});

if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (state.metrics) renderCharts(state.metrics);
    redrawActiveTab();
  });
}

if (!HAS_CHARTS) chartFallbacks();
state.lang = initialLang();
state.locale = window.I18N[state.lang].locale;
document.documentElement.lang = state.lang;
buildFormatters(state.locale);
applyStaticTexts();
buildLangSelect();
applyTab(storedTab());
loadAll(false);
