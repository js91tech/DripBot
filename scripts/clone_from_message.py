#!/usr/bin/env python3
"""Clone a Discord user from a message id into people/<profile>.

Usage:
  DISCORD_TOKEN=... python scripts/clone_from_message.py --message-id 1552791353153421444 --profile panda
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord

from people_clone import DEFAULT_GUILD_ID, DEFAULT_SOURCE_MESSAGE_ID, clone_user_from_message


async def main():
    parser = argparse.ArgumentParser(description="Clone a Discord user into a people profile")
    parser.add_argument("--message-id", default=str(DEFAULT_SOURCE_MESSAGE_ID))
    parser.add_argument("--profile", default="panda")
    parser.add_argument("--guild-id", default=str(DEFAULT_GUILD_ID))
    args = parser.parse_args()

    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_TOKEN is not set. Cannot look up the message author.")
        return 2

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = discord.Client(intents=intents)

    result_holder = {}

    @bot.event
    async def on_ready():
        try:
            result_holder["result"] = await clone_user_from_message(
                bot,
                args.message_id,
                profile_id=args.profile,
                preferred_guild_id=args.guild_id,
            )
        finally:
            await bot.close()

    await bot.start(token)
    result = result_holder.get("result") or {"ok": False, "error": "Bot closed before clone finished"}
    print(json.dumps(result, indent=2, ensure_ascii=False)[:8000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
