# DripBot

Discord bot (Markov / LLM) lives at the repository root.

## CommercePulse

The Next.js market-research app currently also lives in [`commercepulse/`](./commercepulse) on this branch.

A **root-level split** (ready to become `js91tech/CommercePulse`) is on branch [`cursor/commercepulse-standalone-4004`](https://github.com/js91tech/DripBot/tree/cursor/commercepulse-standalone-4004).

This environment cannot create a new GitHub repository (GitHub App tokens are limited to DripBot). To finish the split, create an empty public repo named **CommercePulse**, then:

```bash
git clone --branch cursor/commercepulse-standalone-4004 --single-branch https://github.com/js91tech/DripBot.git CommercePulse
cd CommercePulse
git checkout -B main
git remote set-url origin https://github.com/js91tech/CommercePulse.git
git push -u origin main
```

Create the empty repo here: https://github.com/new?name=CommercePulse

Until that push lands, run the nested copy:

```bash
cd commercepulse
npm install
npm run db:setup
npm run dev
```
