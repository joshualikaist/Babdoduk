# Local ggongbab preview (lab)

Run the existing mailbox session and parser without writing tasks, Supabase, or
`data/ggongbab/latest.json`:

```cmd
python scripts\dooray_web_agent.py --preview-feed --from 2026-09-01 --to 2026-09-19 --max-mails 1000 --read-state read --cdp
```

The verified list/detail contract is reused. Only known read messages are
eligible. The existing prefilter selects candidates, the existing body reader
enriches them, and `RawItem(source_type="dooray")` enters the production
`Pipeline` (sanitizer, rules, real OpenAI extractor, validator, dedup). Storage is
always `MemoryRepository`. The existing exporter and content validator produce
`.local/ggongbab-preview.json`. Unknown/false food and review events are excluded
from the public feed; diagnostic counts retain their outcomes.

The default AI limit is 50 **candidates**, checked before constructing the
extractor. Fallback calls can make the total AI call count larger than the
candidate count. Exceeding the limit requires explicit `--force`. Missing read
state, invalid date windows, and invalid limits fail closed. No mailbox state file
is advanced. Body fetches are restricted to rows marked read by the calibrated
field; that field's discrimination still depends on the live mailbox contract.

Only public-shaped extracted fields are serialized. Raw mail data stays in
memory. The `_preview` object has an explicit numeric-counter allowlist. Privacy
and schema validation run in memory before the atomic write. If individual AI
calls fail, a validated partial feed is saved with `aiErrors` and the command
returns exit 40; this is not a fully successful extraction run.

Serve the lab on loopback (the helper blocks secrets, browser profiles and
directory listings):

```cmd
python scripts\check_ggongbab_ui.py --serve --port 8000
```

- Normal: http://127.0.0.1:8000/lab-ggongbab.html
- Synthetic fixture: http://127.0.0.1:8000/lab-ggongbab.html?fixture=1
- Live preview: http://127.0.0.1:8000/lab-ggongbab.html?preview=1
- Coordinate overlay: add `&debug-layout=1` to either local test mode.

All modes share rendering, filtering, grouping and deadline logic. A public host
rejects preview mode before any `.local` fetch. Diagnostic panels render only
allowlisted numeric counts. No scheduler is registered by these commands.

```cmd
python -m pytest tests/ggongbab
python scripts\check_ggongbab_ui.py --preview
```

The checker starts a temporary loopback server and checks all three viewports,
sticky alignment, long text, CTA boundaries, filter persistence, public food
eligibility, normal-mode requests, remote preview refusal and diagnostic privacy.
Screenshots and measured rectangles go only to `.local/ui-shots/`.

The production HTML and cron schedules are intentionally unchanged. The public
refresh exporter now opts into explicit-food-only filtering; its reusable
serializer retains tri-state support for non-feed consumers. The Windows runner
text includes `--read-state read --cdp`, but is neither run nor registered here.
