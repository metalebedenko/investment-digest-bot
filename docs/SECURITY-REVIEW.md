# Independent publication security review

Reviewed on 15 November 2026. **PASS_WITH_LIMITS**: no publication-blocking issue was found in the final 50-file source and artifact package. The reviewer did not implement the application changes.

The initial full review covered a 50-file candidate identified by manifest SHA256 `3030a6640a09afe6b84560643b5ab9fe170018be3b0618dd7e7b4bff433988cb`. A subsequent bounded delta review checked removal of the legacy Windows scheduler helper, its remaining setup/documentation references, publication status wording and this public review. The final package still contains 50 files: the helper was removed and this document was added. All 17 Python modules, four test files, PDF/PNG assets, fonts and dependency inputs retain their initially reviewed hashes. Exact final file hashes were recorded separately before publication; this finding does not extend to future changes or an operational deployment.

The reviewer independently reran all **48 offline regression tests**, added seven probe groups including **59 local-panel request checks**, and exercised the actual demo CLI with network access denied. The demo generated seven pages without opening live credentials or state, and synthetic secret markers were absent from its PDF and logs. Those results remain applicable because the tested Python source, tests and runtime inputs did not change in the delta.

The review covered secret storage and stale-value handling, browser Host/Origin/CSRF guards, error and UI disclosure, PDF/HTML injection, network/provider boundaries and publication exclusions. All published PDF pages and PDF/PNG metadata were inspected; no confirmed credential, private owner contact or machine-specific path was found. The PDF contained no active actions or attachments. The bundled fonts matched the documented release archive; the selected dependency wheels and lock hashes matched the captured official release metadata.

All available original history objects were examined: four commits and 40 blobs. No confirmed credential was found. Original personal commit-email metadata is excluded by the clean-history publication strategy; this does not establish deletion from previous clones or remote caches.

The earlier **LOW** finding in the optional Windows Task Scheduler helper is **closed by removal**. The final package does not contain that helper, and setup instructions no longer invoke it. The guarded timer within the local panel remains unchanged. This resolution removes the identified shell path expansion surface; it is not a claim of Windows runtime acceptance. The remaining Windows setup helper and Windows secret-file ACLs were not validated. The verified runtime was CPython 3.12 on macOS, and the panel remains a loopback-only, single-user prototype.

Live search, paid model calls, Ollama and real Telegram delivery were not exercised. The review does not establish investment accuracy, provider privacy, exactly-once delivery, safe public hosting, a complete native dependency/CVE audit or the absence of every possible encoded secret. Runtime reports, logs, state and credentials remain local and excluded from publication.

No real provider key was used. This review is evidence for the stated portfolio-publication boundary, not a production security certification.
