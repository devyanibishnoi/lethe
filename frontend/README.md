# Lethe — dashboard frontend

One set of static pages, two possible backends:

- **`app.js`** — real `fetch()` calls to the FastAPI backend (`src/api`), backed
  by a real Postgres/pgvector database. This is the actual system.
- **`mock.js`** — the exact same `getJSON`/`postJSON` function signatures,
  answered from an in-memory "database" seeded with realistic data and
  persisted to `sessionStorage` for the tab's session. No backend, no database.
  Exists so this can be deployed somewhere free (Vercel, GitHub Pages, ...)
  without paying to keep a Postgres + FastAPI host running permanently.

`load-backend.js` picks between them on every page load:

1. `?backend=mock` or `?backend=real` in the URL, if present (also remembered
   in `localStorage`, so it sticks across navigation without repeating it on
   every link).
2. Otherwise, the last remembered choice.
3. Otherwise, `localhost`/`127.0.0.1` defaults to `real`; anything else
   (e.g. a Vercel deployment with no backend behind it) defaults to `mock`.

A small badge in the bottom-right corner of every page shows which mode is
active, with a link to switch.

Benchmarks shown in mock mode are the real numbers from
`docs/benchmark_results.csv`, not fabricated.

## Deploying the mock-only version somewhere free

1. Push this repo to GitHub.
2. On vercel.com, "Add New Project" → import the repo.
3. Set **Root Directory** to `frontend`.
4. Framework preset: **Other** (plain static files, no build step).
5. Deploy. No environment variables, no database, no build command needed.
   It'll default to mock mode automatically, since Vercel isn't running the
   FastAPI backend.
