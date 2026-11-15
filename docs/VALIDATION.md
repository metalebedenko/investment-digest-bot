# Validation record

Prepared on 15 November 2026. This record separates offline checks from untested external services.

## Completed checks

- **48 unittest cases passed**, with networking denied by the macOS sandbox and additional mocked HTTP guards. Cases cover offline demo isolation, live failure behaviour, sent-state ordering, data validation, safe errors, Telegram escaping, secret-file handling, panel CSRF/origin guards, PDF escaping and failure preservation.
- The actual `python run_bot.py --demo` command produced a **seven-page PDF** while the OS denied all network access. Every page carries a synthetic-demo marker. No `.env` was created and sent-state remained unchanged.
- Synthetic credential sentinels were absent from PDF text and application logs.
- All seven pages were rendered with Poppler and visually inspected. No clipped text, broken glyphs or overlapping report elements were observed in this sample.
- The original repository's one branch, four commits and 40 unique blobs were inspected. No confirmed credential was found. Personal author-email metadata is excluded from the publication snapshot.
- The three bundled DejaVu 2.37 fonts were replaced by exact official-release files. Their provenance and license are in `fonts/`.
- Eighteen selected Python wheels were verified against official PyPI size/SHA metadata and their RECORD files before isolated installation. The lock contains exact versions and official wheel hashes.

## Independent publication review

An independent reviewer repeated the 48 tests, exercised seven additional probe groups including 59 browser-guard requests, and inspected the full source/history/media boundary. The result is **PASS_WITH_LIMITS**, with no publication blockers. See [the public review](SECURITY-REVIEW.md) for exact scope and limitations. The legacy Windows Task Scheduler helper was removed after its path-quoting issue was identified; the guarded local panel timer remains. This cleanup was submitted for final delta review before publication.

## Not established by these checks

- Real search-provider, paid LLM, Ollama model or Telegram delivery success. These require an explicitly authorized live test with the operator's own settings.
- Correctness, freshness or investment value of generated ideas, assessments and cited links.
- Exactly-once delivery or transactional recovery across Telegram and local state.
- Windows setup-helper execution, Windows secret-file ACLs, or deployment beyond the loopback-only single-user panel.
- A complete vulnerability audit of native third-party libraries. The dependency review established provenance, structure and a bounded text preflight.

The included PDF is synthetic demonstration material, not a live research issue. Demo samples and test counts do not imply production readiness.
