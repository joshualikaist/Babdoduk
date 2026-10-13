# Data

Every data file of the site: what it holds, who writes it, the contract it keeps, what checks it
and who reads it. The table is the readable form of `scripts/schema_check.py` `CONTRACTS`; the
contracts themselves are standard JSON Schema files in `schemas/` (data plan phase 3, 2026-10-12).

## Files

| File | What it holds | Written by | Contract (`schemas/`) | Checked by (`validate_content.py`) | Read by | Served |
|---|---|---|---|---|---|---|
| `data/ggongbab/latest.json` | Free-food events now and upcoming | content bot, `refresh_ggongbab.py` (cloud, scheduled every 30 min) | `ggongbab-feed` | `--only ggongbab`: expiry, explicit food or a giveaway, privacy | `ggongbab.html`, home calendar | yes |
| `data/ggongbab/archive/index.json` | Past listings, last 30 days | same | `ggongbab-archive` | same | same | yes |
| `data/ggongbab/news.json` | Campus food news | same, from `inputs/ggongbab/food-news.json` | `ggongbab-news` | same, plus each item's derived id | `ggongbab.html` | yes |
| `data/kaist-menu/YYYY-MM-DD.json` | One day's cafeteria menus; current week only | content bot, `refresh_kaist_menu.py` (scheduled 06:00, 10:30, 16:30) | `kaist-menu-day` | `--only kaist-menu`: dates, counts, coverage | hub (other dates) | yes |
| `data/kaist-menu/latest.json` | Today's menus, a byte-identical copy of today's file | same | `kaist-menu-day` | same | home, magazine `#kaistToday`, hub (today) | yes |
| `data/kaist-menu/week.json` | Which dates of the current week have a file | same | `kaist-menu-week` | same: Monday to Sunday, agrees with the files | hub | yes |
| `data/magazine/YYYY-MM-DD.json` | One edition | content bot, `refresh_magazine.py` (scheduled daily 10:00) | `magazine-edition` | `--only magazine`: lanes, trend evidence, duplicates, no fabricated story | `mukbang.html`, home feature | yes |
| `data/magazine/index.json` | Editions with stories, newest first | same | `magazine-index` | same | same | yes |
| `research/magazine/candidates.jsonl` | Candidate store, one row per line (`docs/MAGAZINE_DISCOVERY.md`, Persistence) | same | `magazine-candidate` | same: unique ids, real URLs, no session fields | the next magazine run | no |
| `research/magazine/health.json`, `source-health.json`, `runs.jsonl` | Run reports | same | `magazine-health`, `magazine-source-health`, `magazine-run` | same | operators | no |
| `data/foods/catalog.json`, `data/foods/packs/*.json` | Food dictionary for the picker (1,314 dishes; the 313 added on 2026-10-13 are dish names from the MFDS 식품영양성분DB representative dishes, each copying the attributes of the closest existing dish and joining its cluster, with protein, popularity, satiety from the MFDS energy per serving and allergens authored on top) | a person (the source since phase 4; the Python generators retired) | `foods-catalog`, `foods-pack` | `--only authored`: counts match, unique dish ids and names, each dish in its cuisine group's pack | `mukbang.html#what` (`js/food-engine.js`) | yes |
| `data/content/labels.json` | Shared labels: free-food types, sources, cafeterias, the picker's cuisines, magazine lanes | a person | `content-labels` | `--only authored`; `sync_site_chrome.py --check` fails when a page's copy differs | the pipeline (`scripts/content_labels.py`); the pages carry a copy written by `scripts/sync_site_chrome.py` | no |
| `data/content/events.json` | News and events: the owner's notices and activities | a person (`docs/EVENT_DETAIL_FIELDS.md`) | `content-events` | `--only authored`: an activity ends on or after its start, a detail carries no markup but `<strong>` | `event.html`, written in by `scripts/sync_site_chrome.py` | no |
| `data/content/worldcup.json` | The menu world cup's dishes (catalog ids), how they were chosen and one credited photo per dish (Wikimedia Commons, free licenses only; files in `images/worldcup/`) | a person | `content-worldcup` | `--only authored`: a pool of distinct catalog dishes at least one game (`size`, a power of two) large, each with an existing photo, at most five of the same dish (`SAME_DISH` in `scripts/page_content.py`) | `worldcup.html` (`js/worldcup.js`) | no |
| `data/content/history.json` | The history timeline and its roadmap | a person | `content-history` | `--only authored`: one milestone per date, its image exists | `history.html`, written in by `scripts/sync_site_chrome.py` | no |
| `i18n/ko.json`, `i18n/en.json` | Every page's Korean and English text, one entry per key, the same keys in both | a person | none (a flat key → text map) | `tests/test_i18n.py`: the same keys, no empty text, each key from one source | every page, written in by `scripts/sync_site_chrome.py` (the families each page shows) | no |
| `data/food-log.json` | The creator's food log | a person | `food-log` | `--only authored`: each day's total | `food.html` | babdoduk-lab only |
| `inputs/ggongbab/manual.json` | Hand-written free-food notices | a person | `ggongbab-manual` | `--only authored`: unique ids | the free-food refresh | no |
| `inputs/ggongbab/food-news.json` | Public campus news items | operator PC, `export_food_news.py --review` (the review file stays in `.local/`) | `ggongbab-news-input` | `--only authored`: each item's derived id | the free-food refresh | no |
| `calendar.ics` | KAIST Portal calendar export | a person | none | none | `lab.html` | babdoduk-lab only |
| `scripts/discovery/sources.json` | Magazine source registry: one entry per source | a person (one source per change) | `magazine-sources` | `--only magazine`, plus `discovery.registry.validate` | the magazine run | no |

`python scripts/validate_content.py` checks every family; a bot passes `--only` with the families it
refreshed, so a problem in one cannot block another's publish.

## How a file reaches the site

- **Generated** (`data/magazine`, `data/kaist-menu`, `data/ggongbab`, `research/magazine`): a GitHub
  Actions job runs **main's** code, validates the families it refreshed and publishes them to lab
  and main with `scripts/publish_generated.py`, which copies only those folders. A file whose only
  change is a timestamp is not committed. Never edit these by hand.
- **Authored** (foods, the shared labels, the translations, the food log, `inputs/`, the registry): a
  normal commit through the lab-first lifecycle (`AGENTS.md`).
- **Written into the pages** (`i18n/`, `data/content/`): every page's table is written whole by the
  sync, from the key families the page shows in `i18n/ko.json` and `i18n/en.json`, the labels and
  the entries below, followed by `js/site.js`. A label or an entry is written once. `python
  scripts/sync_site_chrome.py` writes the labels into the translation tables of the pages that
  show them and into the `// @labels:` blocks of `js/eat-slot.js` and `js/ggongbab-public-feed.js`,
  and renders `events.json` and `history.json` (`scripts/page_content.py`) into the `@content`
  blocks of `event.html` and `history.html`: the rows with their Korean text, and both translation
  tables. Order and keys are computed (activities by date, `event.e0` first). The pipeline reads the
  labels through `scripts/content_labels.py`. The browser never fetches the folder, so it is not
  deployed.
- **Served** (`docs/DEPLOYMENT_AND_BRANCHES.md`): `.vercelignore` deploys only the pages, `css/`,
  `js/`, `images/`, `data/` (except `data/content/`) and `manifest.json`; `vercel.json` serves the
  lab experiments on babdoduk-lab alone.

## Changing a format

Readers and writers change in steps, so a page never meets a file it cannot read:

1. **Expand.** Add the field to the schema as optional. Pages ignore what they do not know.
2. **Migrate.** Make the generator write it; make the pages use it when present.
3. **Contract.** Make it required only once no stored file lacks it. To remove a field, the pages
   stop reading it first, then the generator stops writing it, and the schema drops it once no
   file has it. Example: the magazine's `schedule` is no longer read or written; it stays an
   optional field because older editions keep it.

Every generated file says `"schemaVersion": 1`. A change a reader must know about raises it, and the
pages accept both versions until every stored file has moved.

## Checks

- `python scripts/validate_content.py` (all families) or `--only magazine kaist-menu ggongbab authored`.
- `tests/test_schemas.py`: each contract accepts a minimal example and refuses the breaks that
  matter for it (a private field, a wrong vocabulary, a broken id or time); every real file keeps
  its contract.
- `scripts/schema_check.py` is a small subset of JSON Schema, so the bots install nothing; in CI
  the reference implementation (`jsonschema`, `requirements-dev.txt`) checks the same files and
  examples and must agree.
