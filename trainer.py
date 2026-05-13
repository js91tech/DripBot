import asyncio
import aiosqlite
import json
import os
import sys
from engine.markov import MarkovChain

DB_PATH = "data/bot.db"


def _resolve_guild_id():
    raw = os.environ.get("GUILD_ID") or (sys.argv[1] if len(sys.argv) > 1 else "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


GUILD_ID = _resolve_guild_id()


async def train():
    if not GUILD_ID:
        print("ERROR: Set GUILD_ID in the environment or pass it as the first argument.")
        return

    try:
        with open("training_data.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("ERROR: training_data.txt not found! Please create it and add text.")
        return

    print(f"Found {len(lines)} lines of text. Starting training...")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS markov (
                                guild_id INTEGER,
                                key TEXT,
                                value TEXT,
                                PRIMARY KEY (guild_id, key))"""
    )
    chain = MarkovChain(order=2)

    # Load existing data from DB so we don't overwrite what the bot already knows
    cursor = await conn.execute("SELECT key, value FROM markov WHERE guild_id = ?", (GUILD_ID,))
    rows = await cursor.fetchall()
    for key, value in rows:
        chain.chain[key] = json.loads(value)

    # Learn the new lines
    for line in lines:
        clean_line = line.strip()
        if clean_line:  # Skip empty lines
            chain.learn(clean_line)

    # Save the newly updated chain back to the DB
    print("Saving learned data to database...")
    for key, values in chain.chain.items():
        await conn.execute("INSERT OR REPLACE INTO markov (guild_id, key, value) VALUES (?, ?, ?)",
                           (GUILD_ID, key, json.dumps(values)))

    await conn.commit()
    await conn.close()
    print("Training complete! The bot now has a starter brain.")

if __name__ == "__main__":
    asyncio.run(train())
