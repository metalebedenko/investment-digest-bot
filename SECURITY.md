# Security boundaries

This is a local research prototype, not a public multi-user web service. Keep the control panel bound to `127.0.0.1:8787`; do not expose it through a reverse proxy or public tunnel. Its browser request and CSRF checks do not replace authentication or an OS account boundary.

- `.env` contains credentials and stays outside Git. The application restricts new secret-file permissions on POSIX, rejects symlinks, and displays only set/unset status.
- Keys are looked up at use time. Clearing a key suppresses its old fallback value.
- Error paths report safe error categories rather than raw provider responses, URLs, exception messages or tracebacks.
- All browser mutations require a CSRF token and a valid local origin/host. A GET does not start a digest or scheduler.
- `--demo` does not contact search, models or Telegram and does not read saved live credentials/settings.
- Text from a model or source is treated as plain data in PDF and Telegram markup.
- Live model endpoints require HTTPS, except HTTP on loopback for local services. Credentials do not belong in an endpoint URL.

Reports and logs can contain information from a live run. Treat `reports/`, `logs/`, `state/`, any backups and `.env*` as local material. The committed `docs/demo-digest.pdf` is generated only from synthetic fixtures.

The preparation review covers the submitted source snapshot and the recorded tests. It is not a guarantee against all vulnerabilities, a financial validation, or a full audit of native third-party libraries. No real provider keys were used during validation. See `docs/VALIDATION.md` for the independent review result and its scope.

If a real credential is accidentally committed, revoke or rotate it at its issuer before relying on history cleanup. Deleting a file or rewriting refs does not prove deletion from all GitHub caches, clones or backups. Never put the credential itself in an issue or an error report.
