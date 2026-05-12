import asyncio
import aiosqlite
import json
from engine.markov import MarkovChain

DB_PATH = "data/bot.db"
GUILD_ID = 1388136234827649116


async def train():
    if not GUILD_ID:
        print("ERROR: Please open trainer.py and set GUILD_ID to your Discord Server ID!")
        return

    try:
        with open("training_data.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("ERROR: training_data.txt not found! Please create it and add text.")
        return

    print(f"Found {len(lines)} lines of text. Starting training...")

    conn = await aiosqlite.connect(DB_PATH)
    chain = MarkovChain(order=2)

    cursor = await conn.execute("SELECT key, value FROM markov WHERE guild_id = ?", (GUILD_ID,))
    rows = await cursor.fetchall()
    for key, value in rows:
        chain.chain[key] = json.loads(value)

    for line in lines:
        clean_line = line.strip()
        if clean_line:
            chain.learn(clean_line)

    print("Saving learned data to database...")
    for key, values in chain.chain.items():
        await conn.execute(
            "INSERT OR REPLACE INTO markov (guild_id, key, value) VALUES (?, ?, ?)",
            (GUILD_ID, key, json.dumps(values)),
        )

    await conn.commit()
    await conn.close()
    print("Training complete! The bot now has a starter brain.")


if __name__ == "__main__":
    asyncio.run(train())
