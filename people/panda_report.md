# Panda clone report

Source Discord message id: `1552791353153421444`

## Snowflake

| Field | Value |
| --- | --- |
| Message id | `1552791353153421444` |
| Discord timestamp | 2026-09-24 21:18:28.060 UTC |
| Worker | 1 |
| Process | 0 |
| Increment | 132 |
| Known guild | `1388136234827649116` |

This is a Discord message snowflake from a few minutes before the clone request. It is not a Twitter/X id and not a Slack timestamp.

## What “clone like Hannah” means here

Hannah was cloned as a **people dataset** entry, not only as a chat persona:

1. `people/profiles.json` — name, aliases, appearance, notes
2. `people/<id>.jpg` — reference photo used for likeness
3. Chat + `/imagine` detect `draw <name>` / `picture of <name>`
4. Image gen gets the reference photo so the result matches their face
5. NSFW / nude requests for a real person are refused
6. A Hannah-shaped voice prompt is built from **observed messages** when we can read them

Panda is wired the same way under the profile id `panda`.

## Live lookup

This environment does not have `DISCORD_TOKEN`, so the bot API cannot resolve that message to an author, avatar, or message history.

Without the token we cannot truthfully fill:

- Discord user id / username / nickname
- avatar / attached reference photo
- observed texting rhythm, slang, or topics

Inventing those would not be a clone.

To finish the live clone (author, avatar as `people/panda.jpg`, style report, voice prompt):

```bash
export DISCORD_TOKEN=...
python scripts/clone_from_message.py --message-id 1552791353153421444 --profile panda
```

Or in Discord (manage-guild):

`/botsettings clone message_id:1552791353153421444 name:panda`

The command searches the bot’s guilds for that message, writes the photo + style report, and refreshes the Panda personality from their recent chat.

## How to ask for Panda after deploy

- `draw panda`
- `generate a picture of Panda as a barista`
- `/imagine person:Panda prompt:casual portrait`
