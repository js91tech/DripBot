# CommercePulse

Automated market research, supply–demand scoring, and warehouse-aware supplier matching for **digital** and **physical** dropshipping businesses.

The app runs on a laptop with **no API keys**. Optional OpenAI, Anthropic, and SerpAPI keys enrich summaries and shopping listings when present.

## What it does

1. **Hybrid catalog** — Digital products (instant file + license keys) and physical dropship SKUs (weight, shipping, inventory).
2. **Research engine** — Keyword in, viability score (0–100), recommended prices, and consumer personas out.
3. **Demand vs supply** — Search volume, social momentum, ad activity, competitor density, saturation rating, and a **Buy / Watch / Pass** verdict.
4. **Supplier directory** — Filter US / UK / EU local warehouses (2–5 day ship) vs China / global nodes, with MOQ and return policy.
5. **Product builder** — One form that exports Shopify or WooCommerce CSV.

Live marketplace scraping of Amazon / TikTok / Etsy is intentionally **not** implemented. Those surfaces block unauthorized scraping. CommercePulse uses a deterministic scoring model, public Google News RSS, and optional SerpAPI instead.

## Stack

- Next.js 15 (App Router, Server Actions)
- Tailwind CSS + shadcn/ui
- Prisma ORM (SQLite locally, PostgreSQL-ready)
- OpenAI GPT-4o / Anthropic Claude for optional narrative summaries
- Cheerio for public RSS; SerpAPI when `SERPAPI_KEY` is set

## Local setup

```bash
cp .env.example .env
npm install
npm run db:setup
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

`npm run db:setup` generates the Prisma client, creates `prisma/dev.db`, and seeds products, suppliers, and sample research reports.

### Optional keys (`.env`)

```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
SERPAPI_KEY=
```

If they are empty, mock fallbacks still produce full reports.

## Project layout

```
app/
  page.tsx                 Dashboard + research bar
  research/                Report list + detail
  demand/                  Demand vs supply analyzer
  suppliers/               Filterable warehouse directory
  catalog/                 Digital / physical catalog
  builder/                 CSV export builder
  api/research|suppliers|demand|products|export
lib/
  scoring.ts               Viability model
  research-engine.ts       Orchestrates mock + live + LLM
  supplier-engine.ts       Local vs overseas matching
  csv-export.ts            Shopify / WooCommerce
prisma/schema.prisma       Product, Supplier, MarketTrend, ResearchReport
```

## Hosting

Suggested path:

1. **GitHub** for source.
2. **Vercel** for the web app (hobby plan is enough for a demo).
3. **Neon Postgres** when you outgrow SQLite.

### Vercel + Neon (recommended)

1. Create a project at [neon.tech](https://neon.tech) and copy the pooled `DATABASE_URL`.
2. In `prisma/schema.prisma`, change the datasource to:

```prisma
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}
```

3. Import this repository in Vercel (root directory = repo root).
4. Set env vars: `DATABASE_URL`, optional `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `SERPAPI_KEY`.
5. Build command: `npx prisma generate && npx prisma db push && npm run build`.
6. After the first deploy, run `npx prisma db seed` against Neon (or hit `/api/research` to generate reports).

SQLite (`file:./dev.db`) is for local demo only. Serverless hosts cannot keep a writable SQLite file.

### Other hosts

- **Railway / Render / Fly.io** — Next.js app + a Postgres addon. Use `npm run start` after `npm run build`.
- **Docker** — `docker compose up db` for Postgres, then point `DATABASE_URL` at `postgresql://commercepulse:commercepulse@localhost:5432/commercepulse`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/research` | Run + persist a research report |
| `GET` | `/api/research` | List reports |
| `GET` | `/api/demand?query=` | Demand / supply snapshot |
| `GET` | `/api/suppliers?region=LOCAL&q=` | Supplier search |
| `POST` | `/api/products` | Create catalog SKU |
| `POST` | `/api/products/:id/license` | Issue a digital license key |
| `POST` | `/api/export` | Shopify or WooCommerce CSV |
| `GET` | `/api/health` | Database + key status |

## Scripts

```bash
npm run dev          # Next.js on :3000
npm run db:setup     # generate + push + seed
npm run lint
npm run build
```
