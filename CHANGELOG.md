# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-28

Initial public release: the posting pipeline extracted from a production
Diafan.CMS blog, cleaned of site-specific data and prepared for reuse.

### Added

- `server/publisher.php` — the single write endpoint for Diafan.CMS: bootstraps
  the CMS core, inserts the article, builds the SEF URL, uploads the cover
  through the CMS image pipeline and clears the cache. Token-protected,
  POST-only, idempotent by `external_id`, with `inspect` diagnostics.
- `server/show_anons.php` — template-tag override that keeps the blog section
  intro out of article pages.
- `src/` — the pipeline: `run_one.py` (orchestrator), `writer.py` (LLM call with
  a strict JSON contract), `verify.py` (blocking markup + AI-SEO validator),
  `linker.py` (deterministic internal linking), `images.py` (800×510 covers),
  `topics.py` (topic queue with duplicate detection), `dupes.py`, `slug.py`,
  `catalog.py`, `diafan.py` (publisher client with backoff), `deploy.py` +
  `ftp_client.py` (FTP deploy and backups), `recrawl.py` (Yandex.Webmaster
  recrawl), `set_cover.py`, `check.py` (deferred post-checks), `logsetup.py`,
  `settings.py`.
- `prompts/writer.md` — the writer prompt: HTML contract, structure rules and
  the AI-SEO checklist that the validator enforces.
- `docs/ai-seo-research-2026.md` — the research behind the prompt and the
  validator: what is confirmed by primary sources, 16 widespread myths, and a
  mechanical article checklist.
- `tests/test_pipeline.py` — 31 pipeline checks (no network, no site needed).
- PowerShell entry points: `publish.ps1`, `preview.ps1`, `schedule.ps1`,
  `test_schedule.ps1`, `ps-common.ps1`.
- `examples/` — site-agnostic examples of the topic queue, the fact base and the
  writer output contract.
- CI: ruff (`E4,E7,E9,F,I,FURB,DTZ`), byte-compile, smoke import and the test
  suite on Python 3.10 and 3.12.

### Changed (compared with the private working copy)

- Client domain replaced by `SITE_URL` / `your-site.example.com`; the host used
  by the link checks now comes from configuration instead of being hardcoded.
- Blog section id moved from a constant in `run_one.py` to
  `config.site.news_site_id`.
- Site CSS in the local preview is now optional (`config.site.preview_css`).
- Brand names, credentials, hostings ids, site catalogues, article artefacts and
  database dumps removed; `.env.example` added.
- The news template override is **not** shipped: it is a copy of a Diafan core
  template. The change is documented in `server/README.md` instead.

[1.0.0]: https://github.com/YanChi-pixel/diafan-blog-autoposter/releases/tag/v1.0.0
