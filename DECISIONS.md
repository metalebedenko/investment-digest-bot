# Decisions

## 15 November 2026 — Public portfolio preparation

The owner requested history/secret review, cleanup and portfolio documentation, with publication only if the result passes review. Own code uses MIT by the owner's explicit choice. An independent final security review is required before any candidate is sent to GitHub.

The demonstration path is offline and labelled synthetic. Live failures never fall back to fixture ideas. Actual provider integrations remain a separate, explicitly authorized test.

The bundled fonts are replaced with exact official DejaVu 2.37 files and their notices because the prior files' provenance was not established. Dependencies are pinned for repeatability.

The legacy Windows Task Scheduler helper was removed after independent review found shell path expansion risks. The guarded in-process panel timer remains; no elevated task registration helper is shipped. Windows setup execution and ACLs were not validated.
