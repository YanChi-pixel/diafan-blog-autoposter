# diafan-blog-autoposter

[![CI](https://github.com/YanChi-pixel/diafan-blog-autoposter/actions/workflows/ci.yml/badge.svg)](https://github.com/YanChi-pixel/diafan-blog-autoposter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

**Automated blog posting for Diafan.CMS: from a topic in a queue to a published
article in one command.** The whole pipeline — LLM writing, blocking validation,
internal linking, cover, publishing and search-engine recrawl — runs on your
machine and sends **exactly one HTTP request per article** to the site.

Diafan.CMS is a Russian CMS with no publishing API, a database that accepts
connections only from localhost, and hosting that blocks an IP after a handful of
rapid requests. Those constraints shaped the architecture: instead of driving the
admin panel or writing to MySQL from outside, a small token-protected PHP
endpoint lives **inside** the site and saves the article the same way the admin
panel does — cache, image resizing and indexes included.

## What it solves

| Problem | How it is solved here |
| --- | --- |
| No publishing API in Diafan.CMS | `server/publisher.php` bootstraps the CMS core and inserts the article through the CMS itself |
| Database closed to outside connections | All writes happen server-side, inside that endpoint |
| Hosting blocks an IP after 3–5 rapid requests | One POST per article, client-side throttling with exponential backoff, 90 s pause between articles |
| Hosting FTP allows ~1 connection per 30–60 s | Deploy and backups are one connection per run, `MLSD` instead of the broken `LIST` |
| Generated text does not match the site's markup | `verify.py` blocks publication on any deviation from the HTML contract |
| LLM invents numbers | Only facts from `data/facts.json` are passed to the model, and inventing is forbidden by the prompt |
| Endless regeneration loops | The model fixes **only** the reported issues on top of its previous version |

Production numbers: two articles a day, **1–2 minutes per article**, roughly five
minutes for two including the technical pause, and one request to the site per
article instead of the dozens an admin-panel automation would need.

## Features

- ⚙️ **One request per article** — a single POST publishes the article, builds its
  SEF URL, uploads and resizes the cover, and clears the cache.
- 🔒 **Token-protected write endpoint** — `X-Publisher-Token`, POST-only,
  `noindex` header, idempotent by `external_id`, with a one-call `inspect` mode
  that reports the CMS schema instead of guessing it.
- ✅ **Blocking validator** — HTML contract (allowed tags/classes, lead, table,
  list, CTA, FAQ) plus an AI-SEO checklist (numbers in every section, no hedging,
  no promotional clichés, volume).
- 🔗 **Deterministic internal linking** — the model only writes the anchor
  phrases, the linker finds them by word stems and inserts 3–4 links, one per
  `<h2>`, never in the lead, table or FAQ.
- 🖼️ **800×510 covers** — Pexels lookup with a Pillow fallback, or fully manual
  covers attached by slug.
- ♻️ **Resumable queue** — a topic leaves the queue only after a successful
  publication, so a failed run loses nothing.
- 🔁 **Point fixes instead of rewrites** — on validation errors the model receives
  its previous version plus the list of issues and fixes only those.
- 🔎 **Yandex.Webmaster recrawl** — the new URL is submitted right after
  publishing; cached ids make it one request instead of three, and a recrawl
  failure never rolls back a publication.
- 🧪 **31 pipeline tests** that need no site, no network and no API key.

## How it works

```
topic from the queue
      │
      ├─ writer.py     LLM writes the article from prompts/writer.md
      │                (strict JSON; it never inserts links itself)
      ├─ verify.py     check DRAFT: markup contract + AI-SEO checklist
      ├─ linker.py     deterministically weaves 3-4 internal links,
      │                one per different <h2> section
      ├─ verify.py     check FINAL
      ├─ images.py     cover 800×510 (stock photo, or your own via set_cover.py)
      └─ diafan.py     one POST to the site → publisher.php
                       (INSERT news + SEF URL + image upload + cache reset)
                          │
                          └─ recrawl.py → Yandex.Webmaster: recrawl the new URL
```

If the article fails validation, the loop does not regenerate it from scratch:
the model gets its own previous JSON and the list of findings, and must fix only
those, keeping the volume and the rest of the structure. Up to 4 attempts; if the
linker could not find enough anchors, the model is told exactly which phrases to
use.

## Requirements

- **Diafan.CMS 7.0** site with FTP access (the endpoint is deployed into the web
  root and uses the site's own `config.php` for database credentials).
- Python 3.10+ with `requests` and `Pillow`.
- PowerShell 7 or Windows PowerShell 5.1 (on Windows) — or run the Python entry
  points directly; the pipeline itself is cross-platform.
- A DeepSeek API key, or a local model served through an OpenAI-compatible
  endpoint (Ollama).
- Optional: a Pexels API key for automatic covers, and a Yandex.Webmaster OAuth
  token for recrawl.

## Quick start

```bash
git clone https://github.com/YanChi-pixel/diafan-blog-autoposter.git
cd diafan-blog-autoposter
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

1. **Fill in the secrets.** Copy `.env.example` to `.env` and set `SITE_URL`,
   FTP access, `DEEPSEEK_API_KEY`, and a freshly generated `PUBLISHER_TOKEN`:

   ```bash
   python -c "import secrets; print(secrets.token_hex(24))"
   ```

2. **Point `config.json` at your site.** Set `site.base_url`,
   `site.news_site_id` (the id of the site page the news module is attached to)
   and, if you want the local preview to use your site CSS, `site.preview_css`.

3. **Deploy the endpoint and look around** (one FTP connection per command):

   ```bash
   python src/deploy.py publisher     # uploads publisher.php with the token substituted
   python src/deploy.py ls            # what is in the web root
   python src/diafan.py               # GET ?action=inspect → output/inspect.json
   ```

   `inspect` reports the news table schema, image variations, SEF URL samples,
   CMS version and write permissions — everything the publisher needs to know
   about your installation.

4. **Build the site catalogue** (link whitelist + existing articles for duplicate
   detection):

   ```bash
   python src/catalog.py
   ```

5. **Adapt the writer prompt.** `prompts/writer.md` is an example configured for
   a B2B services blog: replace the `РОЛЬ` block with your company and industry.
   The HTML contract, structure and checklist below it are universal.

6. **Prepare the data files** (see `examples/README.md`):

   ```bash
   cp examples/themes.example.txt data/themes.txt     # topic queue
   cp examples/facts.example.json data/facts.json     # only verified numbers
   ```

7. **Dry run, then publish.**

   ```bash
   python src/run_one.py --no-publish      # generate + validate + preview only
   python src/run_one.py --dry-run         # also check the endpoint, without writing
   python src/run_one.py                   # publish the first topic from the queue
   ```

   On Windows the same in one line: `.\publish.ps1 -Count 2` publishes two
   articles and waits 90 seconds between them.

## Credentials and the write endpoint

`.env` (never committed) holds everything secret. `publisher.php` ships with a
`__PUBLISHER_TOKEN__` placeholder: `src/deploy.py` replaces it with your token
during upload, so the secret is never stored in the repository. The endpoint
accepts `?action=inspect`, `publish`, `update`, `set_image`, `delete`,
`clearcache`; anything without a valid token gets `403` and does nothing. To
remove the write path from the site entirely:

```bash
python src/deploy.py unpublish       # takes publisher.php down and keeps a backup
```

## Configuration (`config.json`)

| Key | Meaning |
| --- | --- |
| `site.base_url`, `site.blog_path` | canonical URL of the site and the blog path |
| `site.news_site_id` | id of the site page the news module is attached to (article container) |
| `site.preview_css` | optional URL of the site's compiled CSS for the local preview |
| `site.rate_limit.*` | pause between requests, retries, backoff base — tune to your hosting |
| `llm.provider`, `llm.model`, `llm.temperature`, `llm.max_tokens` | writer model settings |
| `images.provider` | `auto` (stock, fallback to placeholder), `none`, `pexels`, `placeholder` |
| `images.width`, `images.height`, `images.jpeg_quality` | cover geometry (800×510 by default) |
| `content.target_words_min/max` | volume bounds enforced by the validator |
| `content.internal_links_min/target/max` | how many internal links an article must carry |
| `paths.*` | where the queue, catalogue, registry, jobs and backups live |

## Usage

```bash
python src/run_one.py "Topic text"      # publish an article on a given topic
python src/topics.py --count 20         # top up the topic queue (duplicate-safe)
python src/check.py                     # catch up on deferred post-checks
python src/set_cover.py --list          # which articles still have a placeholder cover
python src/set_cover.py --from-dir covers   # attach covers in bulk (filename = slug)
python src/recrawl.py --pending         # resubmit URLs the recrawl missed
python src/recrawl.py --queue           # recrawl state and daily quota in Yandex
python src/verify.py output/article.json    # validate an article by hand
python tests/test_pipeline.py           # 31 pipeline checks
```

```powershell
.\publish.ps1 -Count 2        # two articles in a row, with the pause between them
.\preview.ps1                 # generate and open a preview, site untouched
.\schedule.ps1                # optional: register a twice-a-day task
.\schedule.ps1 -Remove        # remove it again
```

## Hard-won lessons

The full write-up is in `ARCHITECTURE.md` (in Russian, §11). The short version:

1. **An integer in a MySQL `ENUM` column is an index, not a value.** The first
   production publication silently became a draft and answered 404 because
   `act = 1` was read as "the first enum member". The publisher now reads column
   types with `SHOW COLUMNS` and always quotes enum values as strings.
2. **`DB::query()` in Diafan returns `false` on error without telling you why.**
   Inserts and updates go directly through `DB::$backend->query()` inside
   `try/catch` so the SQL error text is visible.
3. **A broken `element_id` in Diafan's internal link format silently becomes a
   link to the homepage.** The linker therefore writes plain absolute URLs —
   those can be checked, and they never degrade quietly.
4. **The CTA block needs no markup.** A single
   `<insert name="show_form" module="feedback" template="ask" site_id="…">` tag
   expands into the finished form with all hidden fields.
5. **Both image variations end up identical.** Diafan resizes `smalla` to 800×800
   and `large` to 1200×1200 but never upscales, so an 800×510 source produces the
   same file in both folders.
6. **Template changes belong in `custom/`, never in the core.** Diafan looks in
   `custom/<module>/views/` first, so an override survives CMS updates.
7. **Full regeneration oscillates, point fixes converge.** A measured run:
   attempt 1 — 2116 words, "no numbers in a section"; attempt 2 — 1348 words, a
   new volume error; attempt 3 — an unwanted "Conclusion" heading. With point
   fixes the same article passed in two attempts at 2284 words.
8. **Soft anchor matching needs a stop-list.** After splitting on hyphens,
   "IT-staff rental" degraded into "rental" + "staff" and the linker attached an
   ordinary phrase to the IT services page. Hyphens are now part of a word, and
   generic-only anchors never match softly.
9. **Windows Task Scheduler fails silently in two ways.** The scheduler runs
   `Windows PowerShell 5.1`, which reads BOM-less `.ps1` files as ANSI and dies
   on Russian strings — so every `.ps1` here is saved with a BOM. And reading
   both `stdout` and `stderr` of a child process through `ReadToEnd()` deadlocks
   the task, so the child writes its own log (`--log`) and PowerShell only reads
   the exit code.
10. **Editing a theme file without a backup took the site down** with HTTP 500:
    in theme files `$this` is `Parser_theme`, not the module controller, so
    `$this->htmleditor()` is a fatal error. Every change is preceded by
    `deploy.py backup`.
11. **PHP in a theme runs before `<insert>` tags are parsed**, so wrapping an
    insert in `<?php if (...): ?>` changes nothing — the tag is replaced
    unconditionally.
12. **The post-check has to be deferrable.** Publishing already spends the
    request budget, so an immediate GET usually hits the flood protection;
    `check.py` catches up later.

## The validator: what blocks a publication

**Markup contract** (taken from the site's own articles): only
`p, h2, h3, ul, li, strong, table, thead, tbody, tr, th, td, div, insert`; only
the classes the theme styles; a comparison table, a list, a CTA block and a FAQ
of 5–8 questions are mandatory; the lead is exactly two paragraphs before the
first `<h2>`, with a number in the first one.

**AI SEO**: 5–9 content sections, a number in each; at least eight numeric facts
per article; forbidden headings ("Introduction", "Conclusion", "Summary");
no hedging ("possibly", "as a rule"), no promotional clichés ("the best",
"unique", "a team of professionals"), no filler phrases.

**Links**: 3–4 internal links, each in its own `<h2>` section, never in the lead,
the table, the FAQ or the CTA; anchors are 2–5 meaningful words (no "here" or
"read more").

The research behind these rules — what is confirmed by primary sources, which 16
popular recommendations are myths, and the mechanical checklist — is in
`docs/ai-seo-research-2026.md`, and the prompt that implements it is
`prompts/writer.md`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `403 forbidden — проверь PUBLISHER_TOKEN в .env` | Token in `.env` differs from the deployed file — redeploy with `python src/deploy.py publisher` |
| `ответ не JSON (HTTP 500)` | PHP error on the site: read the response body, check the PHP version (7.4 here) and that `publisher.php` sits in the web root |
| Requests start timing out after a few calls | Hosting flood protection — the client already pauses and backs off; wait a couple of minutes, keep to one article per run |
| FTP `LIST` fails | The server does not support it; the client uses `MLSD`/`NLST` and one connection per run |
| Publication answers `404` right after publishing | The article was written as a draft — the classic ENUM trap, see lesson 1 |
| `Не найден python.exe` on the scheduler | The task runs without your `PATH`; `ps-common.ps1` looks in the standard install locations |
| Cover still shows the placeholder | `image_provider = pillow_brand` in the registry; attach your own with `set_cover.py` |

## Structure

```
src/            pipeline: run_one, writer, verify, linker, images, topics,
                dupes, slug, catalog, diafan, deploy, ftp_client, recrawl,
                set_cover, check, logsetup, settings
server/         code that lives on the site: publisher.php, show_anons.php
prompts/        writer.md — the article prompt (HTML contract + AI SEO)
docs/           ai-seo-research-2026.md — research, myths, checklist
examples/       site-agnostic examples of the working data files
tests/          test_pipeline.py — 31 checks, no network required
data/           working data (queue, facts, catalogue, registry) — gitignored
jobs/ output/   per-run artefacts, previews and logs — gitignored
```

## Safety

- No secrets in the repository: only `.env.example`. The publisher's token is
  substituted at deploy time.
- The write endpoint refuses everything without the token, answers only to POST
  for write actions, sends `X-Robots-Tag: noindex` and is idempotent, so a
  repeated run cannot create duplicates.
- Publication is never destructive: a failed recrawl or a failed post-check
  leaves the article published and is caught up by a separate command.
  `delete` moves the article to the Diafan trash and removes only its own image
  files.
- Every change to a file on the site is made after a backup
  (`python src/deploy.py backup <path>`), and `data/backups/<date>/` keeps the
  previous version for a one-command rollback.
- Client data of the original installation (domain, credentials, hosting ids,
  article catalogues, run artefacts, database dumps) is **not** part of this
  repository.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

The pipeline publishes content to a live site. Test it on a draft
(`act=0` in the payload) or on a staging copy first, and keep backups of the
`diafan_news`, `diafan_rewrite`, `diafan_images` tables and the
`userfls/news/` folder before the first production run. Automation does not
replace editorial responsibility: the tooling enforces structure and forbids
invented numbers, but the facts you feed it are yours to verify.

---

По-русски: [README.ru.md](README.ru.md). Глубокий технический разбор — в
[ARCHITECTURE.md](ARCHITECTURE.md), методология AI SEO — в
[docs/ai-seo-research-2026.md](docs/ai-seo-research-2026.md).
