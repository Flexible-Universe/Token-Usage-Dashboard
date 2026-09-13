# Security

## Reporting a vulnerability

Reports go through GitHub Private Vulnerability Reporting: in the "Security"
tab of the repository, choose "Report a vulnerability".

Please do **not** open a public issue. An issue is readable by everyone
before a fix is available.

## What this application does not provide

The dashboard is a local tool for a single person on their own machine. It
has:

- **no authentication** — whoever reaches the port sees everything,
- **no authorization** — there are no roles and no permissions,
- **no encryption** — the server speaks HTTP, not HTTPS.

That is why the server binds to `127.0.0.1` and does not belong on
`0.0.0.0`. Changing the bind address opens the data to the whole network.

The data it reads is not harmless: it contains project paths and costs, and
therefore allows conclusions about its owner's work.
