# 04 User interface

Three files under `static/`, no build step, no framework: `index.html`
(skeleton), `app.js` (all the logic), `style.css` (styling).

## Page layout

```
Header        data directory, time of last load, "Daten neu laden" (reload)
Tab bar       Uebersicht | Projekte | Sessions | Bloecke | RTK
Status area   result of the plausibility check, message list
Filter bar    period, quantity, models
Tab content   KPI cards, charts, tables
Footer        currency note, gap note
```

All texts run through the two language catalogues under `static/i18n/`
(`de.js`, `en.js`). A pulldown in the header (`#lang-select`) switches
between them; the choice is picked up in this order: `localStorage`
(`dashboard.lang`) first, then `navigator.language`, German otherwise. Once
the pulldown has been used, the stored choice wins on every later visit —
the browser language only counts while nothing is stored yet, otherwise
opening the dashboard in a different browser would silently overwrite a
deliberate choice. Switching needs no network access: the backend ships keys,
not sentences, so data already loaded stays valid and is simply re-rendered
in the other language.

German rendering: numbers with a decimal comma and a thousands point, dates
as TT.MM.JJJJ (`Intl.NumberFormat('de-DE')`). English rendering: decimal
point, thousands comma, dates as the browser's `en` default. Costs stay US
dollars in both languages — no currency conversion, that is the rule, not
the German habit.

## Filters

**Period.** A select field with "Alle Monate" (all months), one entry per
month present, and "Freier Datumsbereich" (custom date range). The two date
fields remain visible but are enabled only for the custom range. Their bounds
are set to the range of data present.

**Quantity.** Switches between cost in US dollars and tokens. It applies to
the charts that carry both quantities.

**Models.** One checkbox per model with a colour dot, plus the shortcuts
"Alle", "Keine", "Nur Claude", "Nur Codex" (all, none, Claude only, Codex
only). The selection goes to the API as `?models=…`.

The filter applies to all tabs at once. The two tabs that do not support a
model filter say so in their note text.

## The five tabs

### Uebersicht (overview)

Eight KPI cards: total cost, total tokens, days with data, median daily cost,
most expensive day, cheapest day, `$ / 1 Mio. Tokens`, context reload factor.
Below them, if the last month is incomplete, the projection marked as an
estimate.

Six charts: cumulative monthly cost, daily values stacked by model, cost per
1 million tokens with a 7-day moving average, Pareto of the model costs,
model timeline, context reload factor. Plus "Claude gegen Codex je Tag"
(Claude versus Codex per day).

Three tables: cost share per model, monthly totals, the 10 most expensive
days.

### Projekte (projects)

Source `projects/`. KPI cards: projects, most expensive project, share of the
largest, total cost. A stacked daily series with the eight largest projects
and a collective rest series with the translated label ("Sonstige" in
German, "Other" in English — the backend marks it `isOther: true` and names
no series itself), plus a table with cost, share, tokens, days and
`$ / 1 Mio.` per project.

The project names are shortened labels, see
[chapter 2](02-data-sources.md).

### Sessions

Source `sessions/`. KPI cards: sessions, median per session, most expensive
session, median duration. Plus the 20 most expensive sessions as a table and
a histogram of the cost distribution.

The histogram sits next to the median because the median alone hides the skew
of the distribution: the classes are left-closed ("5 bis unter 20 $"), and
the labelling says so.

### Bloecke (blocks)

Source `blocks/`. The 5-hour billing windows. KPI cards: blocks, most
expensive block, mean per block, time with usage. Plus a timeline and, if a
block is currently running, its burn rate and projection.

Blocks flagged `isGap` are idle time. They appear in the timeline but count
towards no sum. No model filter.

### RTK

Source `rtk/`. KPI cards: saved tokens, savings rate, commands, runtime. A
bar chart of the saved tokens per day with the savings rate as a line on a
right-hand axis, fixed to a 0 to 100 scale. Below that, monthly totals.

Three note lines explain what is different here compared to the other tabs:
that these are tokens that were never sent, that no model filter applies, and
which period the source actually covers. No monetary value — the reasoning is
in [chapter 5](05-metrics.md).

## Behaviour

**Loading.** On start the page fetches `/api/data`, builds the period and
model filters from it, and then loads the metrics of the active tab.
Switching tabs loads that tab's data and redraws it — even if it was loaded
before, because Chart.js computes wrong sizes when drawing into a hidden
container.

**Active tab.** Remembered in `localStorage` under `dashboard.tab` and
restored on the next visit.

**Reload.** The button appends `reload=1` and forces the `DataStore` to read
everything again. The time of the last load is shown in the header.

**Coverage note.** If the chosen period reaches beyond what a source covers,
a sentence naming the period actually present appears instead of an empty
chart. That separates "no cost" from "no data".

**Without Chart.js.** Chart.js is bundled under `static/vendor/`. If it fails
to load, `chartFallbacks()` replaces every chart box with a note. All KPI
cards and tables stay complete and current — they are built in the frontend
from the API data and do not need Chart.js.

## Drawing rules

**Gaps stay gaps.** Time series run over all calendar days between the first
and the last data point. Missing days carry `null`. Chart.js breaks the line
there instead of pulling it down to zero.

**Colours per model are stable.** `colorFor(model)` assigns every model name
the same slot of the palette, so that a model has the same colour in every
chart.

**Axis colours come from the stylesheet.** `chartBase()` reads `--ink`,
`--muted` and `--line` via `getComputedStyle` instead of duplicating colours.

**Foreign text never goes through `innerHTML`.** Wherever values come from
the data and are freely choosable — model names, project labels, session IDs,
file names, message texts — the nodes are built via `document.createElement`
and `textContent` (`kpiCard`, the table builders, `renderStatus`). The short
form with `innerHTML` is reserved for the KPI cards of the overview, into
which only fixed labels and already formatted numbers and dates are inserted.
