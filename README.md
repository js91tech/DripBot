# DripBot

Discord bot (Markov / LLM) lives at the repository root.

## CommercePulse

The dropshipping research app was moved to its own repository:

**https://github.com/js91tech/CommercePulse**

```bash
git clone https://github.com/js91tech/CommercePulse.git
cd CommercePulse
cp .env.example .env
npm install
npm run db:setup
npm run dev
```

Host it on Vercel (root directory = repo root) and use Neon for Postgres when you leave local SQLite. See that repo’s README for details.
