# 05 Metrics

This chapter gives, for every metric, its formula and the limit of what it
says. Anyone taking a number out of the dashboard should have read the
matching paragraph.

## The ground rule

**Missing calendar days are gaps, not zeros.**

A day without an entry means "no data", not "zero dollars". It follows that:

- Means and medians run over `daysWithData`, not over `calendarDays`.
- Time series run over all calendar days and carry `null` on missing days.
- The 7-day moving average averages only the values present in the window.

`summary` carries both numbers side by side (`daysWithData`, `calendarDays`,
`missingDays`), so that the size of the gap stays visible in the UI.

## Overview (`metrics.py`)

### `summary`

| Field | Computation |
|---|---|
| `totalCost`, `totalTokens` | sum over the filtered days |
| `daysWithData` | number of days with an entry |
| `calendarDays` | calendar days between the first and the last day |
| `missingDays` | difference between the two |
| `meanCostPerDay` | `totalCost / daysWithData` |
| `medianCostPerDay` | median of the daily costs |
| `minCostDay`, `maxCostDay` | cheapest and most expensive day |
| `costPerMillionTokens` | `totalCost / totalTokens * 1e6` |
| `medianCostPerMillionTokens` | median of the **daily values** of that quantity |
| `contextReloadFactor` | `sum of cacheReadTokens / sum of outputTokens` |

The median of `costPerMillionTokens` is the median of the daily ratios and
therefore something other than the overall ratio above it. Both stand side by
side on purpose: the overall ratio is the billed truth, the median says what
a typical day looked like.

### `$ / 1 Mio. Tokens`

`cost / tokens * 1,000,000`. On the model table additionally as
`$ / 1 Mio. Output-Token` (`costPerMillionOutputTokens`).

**This is not a list price.** It is an empirical usage ratio: how much this
model cost per million output tokens in this period, with this kind of usage.
The value moves with the share of cache reads and with the length of the
context. It is good for comparing days and models with each other, not for
quoting prices.

### Context reload factor

`cacheReadTokens / outputTokens`.

How often the context was read, measured against what came out of it. A high
value means: much context, little output — long sessions in which the same
thing is loaded again and again. The quantity is a ratio indicator with no
absolute meaning; what is interesting is how it develops, not its magnitude.

### 7-day moving average (`rolling_mean`)

A window of 7 **calendar days**, not of 7 data points. Missing days do not
enter as zero, they are simply absent. If the window holds fewer than
`MA_MIN_POINTS` (3) values, the result stays `null`.

The minimum count prevents a single value after a gap from appearing as a
"mean" and making the line jump.

### Pareto

Models in descending order of cost, plus the cumulative percentage line.
Answers the question of how many models make up the bulk of the cost.

### `stackedByModel`

Daily values per model. Only the ten most expensive models get a series of
their own, the rest are collected into one rest bucket, marked `isOther: true`
with an empty `model` — the frontend supplies the translated label
(`ui.models.other`) instead of the backend naming it in German. Without that
limit the legend would be longer than the chart.

### `projection`

Only for the last month, and only if it is incomplete.

```
projectedCost = (cost of the days present / number of those days) * days in the month
```

**Explicitly an extrapolation of the daily mean, not a trend
extrapolation.** The field `isEstimate` is always `true`, `basisCode` carries
the fixed key `ui.projection.basis` instead of a German sentence — the
frontend looks it up in the catalogue — and the user interface visibly flags
the number as an estimate. Anyone who had three expensive days this month and
then goes on holiday gets too high a number. That is the price of keeping the
computation comprehensible.

### Claude versus Codex

Two routes, one number:

| Route | Condition | `source` |
|---|---|---|
| `agents` field of the monthly file | present from 09/2026 on | `"agents"` |
| model prefix `gpt-` | before that, or with an active model filter | `"heuristik"` |

The heuristic is only an approximation: it attributes by model name and gets
it wrong as soon as Codex uses a non-`gpt` model. The field `firstAgentsDate`
names the first day on which the more precise source applies, and the user
interface uses it to name the switchover point in the footnote.

With an active model filter, the heuristic is deliberately used instead:
`filter_days` only recomputes `modelBreakdowns`, `agentBreakdowns` would stay
unfiltered, and the result would contradict the rest of the page.

## Projects (`insights.project_insights`)

Cost, share, tokens, number of days and `$ / 1 Mio.` per project. The stacked
daily series carries the `TOP_PROJECTS` (8) largest projects and collects the
rest into one rest bucket, marked `isOther: true` with an empty `label` —
the frontend supplies the translated collective name (`ui.projects.other`).
A project actually named "Sonstige" no longer risks silently merging with the
rest bucket: the bucket has no displayable name at all, it is keyed by a
sentinel that cannot occur in the data.

The project names are shortened labels. The full key sits next to them in the
field `project`.

## Sessions (`insights.session_insights`)

Count, median and maximum of the costs, median duration, the `TOP_SESSIONS`
(20) most expensive sessions.

**The histogram.** Class bounds `0.10 / 1 / 5 / 20 / 50 $`, left-closed: a
value of exactly 50 falls into the top class, not the one below. The result
carries `bounds` (the class limits, as numbers) instead of ready-worded
`labels` — the frontend builds each class label from three catalogue keys
(`ui.sessions.hist.below`, `.between`, `.above`) in the active language and
number format. The histogram sits next to the median because the median
alone hides the skew of the distribution — a few very expensive sessions
carry the bulk of the cost and disappear behind an unremarkable median.

The duration is `lastActivity - firstActivity` in whole minutes, never
negative. It measures the span, not the compute time: a pause in the middle
of the session counts.

## Blocks (`insights.block_insights`)

The 5-hour billing windows.

| Field | Computation |
|---|---|
| `blockCount` | blocks without `isGap` |
| `gapCount` | blocks with `isGap` |
| `maxCost`, `meanCost` | over blocks without `isGap` |
| `activeShare` | minutes in real blocks divided by total minutes |

**`isGap` does not count.** A gap is idle time between two windows. It
appears in the timeline so that the gap stays visible, but it enters no sum
and no mean.

If a block is currently running (`isActive`), the tab shows its burn rate
(`costPerHour`, `tokensPerMinute`) and the projection that `ccusage`
supplies. Both come from the source and are not recomputed.

No model filter: the source only reports `models[]` per block, without a cost
split.

## RTK (`insights.rtk_insights`)

| Field | Computation |
|---|---|
| `savedTokens` | sum of `saved_tokens` |
| `savingsRate` | **sum of `saved_tokens` / sum of `input_tokens`** |
| `commands` | sum of `commands` |
| `savedTokensPerCommand` | `savedTokens / commands` |
| `totalTimeMs`, `avgTimeMsPerCommand` | sum and quotient |

**The savings rate is computed exactly once from the sums**, not as the mean
of the daily rates. `savings_pct` from the source is a ratio; averaged over
rows it gives something different from the sums, and the value would jump
with every filter setting. The same rule holds for the savings rate per month
in `months`: sum per month divided by sum per month.

**No monetary value.** RTK mostly saves input tokens. The only price the
dashboard knows is an empirical `$ / 1 Mio. Output-Token` per model,
explicitly not a list price. Multiplying one by the other would produce a
number that looks serious and has no basis.

**Not offsettable against the other sources.** The rtk figures are the
proxy's estimates of tokens that were never sent. The other tabs measure
consumed tokens and billed cost. The two quantities complement each other but
are not the same currency — adding or subtracting between them is
meaningless.

This source reaches further back than `projects/`, `blocks/` and
`sessions/`. The actual period is named on the note card in the tab.

## Coverage (`insights.coverage`)

Every evaluation of the extra sources returns a `coverage` block that
compares the requested period with the one present. Instead of a
ready-worded sentence it carries `noteCode` (empty when complete) and
`noteParams` (raw, ISO-8601 dates where applicable), which the frontend
turns into a sentence in the active language:

| Case | `complete` | `noteCode` |
|---|---|---|
| no data at all | `false` | `range.no_data` |
| period lies entirely elsewhere | `false` | `range.empty` |
| period reaches beyond | `false` | `range.partial` |
| period fully covered | `true` | `""` (empty) |

The purpose: to make "no cost in this period" distinguishable from "this
source does not exist for this period yet". Without the note, an empty chart
would be ambiguous.
