# Lethe — static portfolio demo

This is a **static, zero-backend copy** of the real dashboard in `/frontend`, built
so it can be deployed for free (Vercel, GitHub Pages, Netlify, ...) without a live
Postgres database or FastAPI server behind it.

**The real system is `/frontend` + `/src/api` + `/src/db` + `/src/logic`**, backed
by a real database — that is what the project actually is, and what the demo
recordings and the course deliverable are based on. This folder exists only
because keeping a real backend permanently live costs real money (~$13/mo on
Render for a web service with enough RAM for `torch`/`sentence-transformers`,
plus managed Postgres), which isn't worth it just to have a clickable link on a
resume.

## How it works

Every page here is byte-identical to the real `/frontend` pages, except one
`<script>` tag: instead of loading `app.js` (which makes real `fetch()` calls to
a FastAPI backend), each page loads `mock.js`, which exports the exact same
`getJSON`/`postJSON` function signatures but answers them from an in-memory
"database" seeded with realistic data, persisted to `sessionStorage` so it
survives navigating between pages within one visit.

- **Search** returns real-looking canned results instantly.
- **Erasure requests** actually mutate the demo state, document counts drop,
  audit entries get appended, the certificate link works, exactly like the real
  flow, just without a real database underneath.
- **Audit trail** verification and the corrupt-for-demo tamper test work
  identically, since they only operate on the same mock state.
- **Benchmarks** are the **real** numbers from `docs/benchmark_results.csv` at
  the time this was built, not fabricated.

Closing the tab (or opening a new one) resets the demo to its seeded starting
state, since `sessionStorage` is per-tab and doesn't persist beyond the session.

## Deploying to Vercel

1. Push this repo to GitHub (already done).
2. On vercel.com, "Add New Project" → import the `lethe` repo.
3. Set **Root Directory** to `portfolio-demo`.
4. Framework preset: **Other** (it's plain static files, no build step).
5. Deploy. Vercel serves everything as-is.

No environment variables, no database, no build command needed.
