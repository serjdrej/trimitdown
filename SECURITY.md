# Security Policy

TrimItDown is designed to be self-hosted: your files are processed on infrastructure you
control. Security reports are taken seriously.

The server is a personal tool — one archive, one owner — and it is protected by a single
shared secret rather than by accounts. Set `TRIMITDOWN_TOKEN` (see
`docker-server/.env.example`); the server refuses to serve without one, because the
dangerous default is the one that keeps working.

Two things worth knowing before you put it on a machine with a public address:

- `docker-compose` publishes the port on every interface. Docker installs its own iptables
  rules for published ports, so a `ufw deny` on the host does **not** close them. If you
  want the server reachable only from the machine it runs on, bind it to `127.0.0.1` in
  `docker-server/docker-compose.yaml`.
- The shared secret travels in a link the first time and in a cookie afterwards. Treat that
  link the way you treat the archive behind it.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, report them privately
via [GitHub Security Advisories](https://github.com/serjdrej/trimitdown/security/advisories/new).

You can expect an initial response within a week. Once a fix is released, the issue will be
disclosed in the release notes.

## Supported versions

Only the [latest release](https://github.com/serjdrej/trimitdown/releases/latest) receives
security fixes.
