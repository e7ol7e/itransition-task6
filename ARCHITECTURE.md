# Nominal architecture

## Ownership

| Layer | Owns | Files |
| --- | --- | --- |
| PostgreSQL | Every generated value, deterministic streams, locale dictionaries, distributions | `sql/001_library.sql` |
| SQL boundary | Bounded read-only procedure calls, exports, pool lifecycle | `services.py` |
| FastHTML routes | Request validation, page/fragment selection, canonical URLs, response policy | `app.py` |
| FastHTML components | HTML for pages, forms, table, dossiers, pagination, docs and benchmark | `views.py` |
| HTMX | Requests, replacement, shared synchronization and loading indicators | `static/vendor/htmx-4.0.0.min.js` |
| Browser preferences | Early theme application, local persistence, theme switch | `static/js/theme.js` |
| Browser interactions | Native dialog, clipboard, random seed input, request feedback | `static/js/browser.js` |
| Canvas | Globe projection, drag gestures, animation/resize cleanup | `static/js/globe.js` |
| Presentation | Both themes, responsive layouts, typography, reduced-motion styling | `static/style.css` |

Python owns authoritative data and HTML. HTMX transports fragments. JavaScript adapts browser APIs; it does not
fetch contact data, assemble contact HTML, implement pagination state, or calculate
synthetic attributes. The random-seed button uses browser crypto only to choose a
new input seed; PostgreSQL still generates the complete contact.

## A generation request

1. The generator form submits locale, seed, size and zero-based page 0 to `/fragment`.
2. The route validates parameter types; the SQL boundary checks all limits.
3. A read-only connection calls `nominal.batch` with bound SQL parameters.
4. Python renders the new `#results` component and returns `HX-Replace-Url` pointing
   to the equivalent full page. Table, pagination, exports and globe data identify
   the same batch.
5. HTMX replaces `#results`. All generator and pagination requests share
   `hx-sync="#generator:replace"`, so a newer request supersedes older work.
6. The globe adapter tears down the old canvas observer/animation and mounts the
   new canvas. It projects SQL coordinates; it never invents geolocation data.

Pagination links carry authoritative batch parameters rendered by Python. The
one-based jump control is converted server-side to the zero-based batch index.
Without JavaScript, ordinary form actions and anchor URLs render complete pages.

## A contact dossier

The person's link requests `/contact` with that batch's parameters and contact
index. Python re-reads the deterministic batch, renders the dossier, and HTMX
inserts it into `#detail-content`. A browser adapter opens the native dialog after
the swap. Without HTMX, the same URL serves a standalone dossier page. Clipboard
copy reads a JSON data element rendered by Python.

## HTMX 4 details

Pinned versions verified on 2026-10-29: FastHTML **0.14.15**, HTMX **4.0.0**.
FastHTML's automatic HTMX/Surreal scripts are disabled. We serve precisely one
local HTMX copy and configure `metaCharacter="-"`.
Events use `htmx-after-swap`, `htmx-error` and `htmx-finally-request`; the request
context is `event.detail.ctx`. The finalization event also runs for failed/aborted
requests, so loading state clears reliably. Intentional request replacement is
not presented as a network failure.

HTMX 4 swaps error responses by default. Our HTTP exception handler retargets
errors to `#error`, preserving the last valid batch. Network failures also show
feedback. `allowEval` and executable fragment scripts are disabled. No custom
JavaScript lives inside Python strings or HTML event attributes.

All executable assets use content-hashed query versions. HTML uses
`Cache-Control: no-store, no-transform`, preventing stale pages and Cloudflare email
rewriting. FastHTML escapes content/attributes. Inert JSON escapes `<`, `>` and `&`
to prevent closing a script element via a malicious seed. Trusted checked-in
Markdown is the only raw document HTML.

## Themes and accessibility

Charcoal/coral is the default; paper/coral is available through the header switch.
The preference is applied before CSS to avoid a theme flash and saved in local
storage when available. CSS variables also color the globe. Native links, forms,
dialog dismissal, visible focus, a skip link and reduced-motion support are used.
On narrow screens, secondary table columns move into the complete contact dossier.

## Verification

- `test_library.py`: real PostgreSQL integration and distribution tests.
- `test_web.py`: FastHTML validation, error preservation, state/URL agreement,
  injection escaping, local versioned assets and document routes.
- `verify_browser.py`: real Chrome checks against `TASK6_URL` (defaults to the
  public service); tests both themes, pagination, the millionth contact, dossiers,
  arbitrary seeds, failures, exports and responsive layouts.

The SQL benchmark measures complete generation and checksumming in PostgreSQL,
excluding HTTP and rendering.
