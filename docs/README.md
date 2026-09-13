# Token Usage Dashboard — documentation

This documentation is organized by area. If you only want to start the
dashboard, read chapter 7. If you want to understand why a number looks the
way it does, read chapters 5 and 6.

| Chapter | Contents |
|---|---|
| [01 Overview](01-overview.md) | What the dashboard does, what it is built from, which principles apply |
| [02 Data sources and export](02-data-sources.md) | Where the data comes from, which files exist, how the export chain runs |
| [03 Backend](03-backend.md) | The five Python modules, the HTTP server, the API |
| [04 User interface](04-interface.md) | Tabs, filters, charts, behaviour without a network |
| [05 Metrics](05-metrics.md) | Every metric, its formula and its limits |
| [06 Checks](06-checks.md) | Plausibility checks, status area, message levels |
| [07 Installation](07-installation.md) | Setup on a fresh machine, step by step |
| [08 Development](08-development.md) | Tests, conventions, how changes are made |

The user interface itself is in German; this documentation is not.

## The three sentences that explain everything else

1. **The dashboard only reads files.** It never calls `ccusage` or `rtk`
   itself. Filling the data directory is a separate export chain
   (chapter 2).
2. **Missing days are gaps, not zeros.** Means run over days with data only,
   and time series carry `null` on missing days.
3. **Broken data is reported, never silently skipped.** Every rejected file
   and every sum that does not add up shows in the status area of the user
   interface.
