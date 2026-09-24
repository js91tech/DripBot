"""Clone a Discord user into a people/ profile the same way Hannah was cloned."""

import json
import os
import aiohttp

from people import (
    PEOPLE_DIR,
    analyze_message_style,
    appearance_from_member,
    build_clone_personality_prompt,
    decode_snowflake,
    upsert_profile,
)

DEFAULT_SOURCE_MESSAGE_ID = 1552791353153421444
DEFAULT_GUILD_ID = 1388136234827649116


async def find_message_in_guilds(bot, message_id, preferred_guild_id=None):
    """Search visible text channels for a message id. Prefer the known guild."""
    message_id = int(message_id)
    guilds = list(bot.guilds)
    if preferred_guild_id:
        preferred = bot.get_guild(int(preferred_guild_id))
        if preferred is not None:
            guilds = [preferred] + [g for g in guilds if g.id != preferred.id]

    for guild in guilds:
        for channel in getattr(guild, "text_channels", []):
            me = guild.me
            if me is None:
                continue
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.read_message_history):
                continue
            try:
                message = await channel.fetch_message(message_id)
            except Exception:
                continue
            if message is not None:
                return message
    return None


async def collect_user_messages(guild, user_id, per_channel=80, max_messages=120):
    texts = []
    for channel in getattr(guild, "text_channels", []):
        me = guild.me
        if me is None:
            continue
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.read_message_history):
            continue
        try:
            async for msg in channel.history(limit=per_channel):
                if msg.author.id != user_id:
                    continue
                if (msg.content or "").startswith("/"):
                    continue
                text = (msg.content or "").strip()
                if text:
                    texts.append(text)
                if len(texts) >= max_messages:
                    return texts
        except Exception:
            continue
    return texts


async def download_avatar(member, dest_path):
    url = None
    avatar = getattr(member, "display_avatar", None) or getattr(member, "avatar", None)
    if avatar is not None:
        url = str(getattr(avatar, "url", "") or "")
    if not url:
        return None
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def write_report(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


async def clone_user_from_message(
    bot,
    message_id,
    profile_id="panda",
    preferred_guild_id=DEFAULT_GUILD_ID,
):
    snowflake = decode_snowflake(message_id)
    message = await find_message_in_guilds(bot, message_id, preferred_guild_id)
    if message is None:
        return {
            "ok": False,
            "error": (
                f"Could not find message {message_id} in any guild this bot can read. "
                "Need DISCORD_TOKEN, Message Content Intent, and access to that channel."
            ),
            "snowflake": snowflake,
        }

    author = message.author
    guild = message.guild
    texts = []
    if guild is not None:
        texts = await collect_user_messages(guild, author.id)
    if message.content and message.content.strip():
        if message.content.strip() not in texts:
            texts.insert(0, message.content.strip())

    style = analyze_message_style(texts)
    image_name = f"{profile_id}.jpg"
    image_path = os.path.join(PEOPLE_DIR, image_name)
    saved_image = await download_avatar(author, image_path)

    display = getattr(author, "display_name", None) or author.name
    appearance = appearance_from_member(author)
    extra_notes = [
        f"Cloned from Discord message {message_id}.",
        f"Discord user id {author.id} ({author.name}).",
        style.get("summary") or "",
    ]
    prompt = build_clone_personality_prompt(profile_id.title(), style, extra_notes)

    profile = {
        "name": profile_id.title() if profile_id.lower() == profile_id else profile_id,
        "aliases": [profile_id.lower(), display.lower()] if display else [profile_id.lower()],
        "image": image_name if saved_image else "",
        "notes": [
            f"This is {profile_id.title()}. They are a real person in this Discord community, cloned the same way Hannah was.",
            f"Source message id {message_id} from {getattr(author, 'name', 'unknown')} ({author.id}).",
            "A reference photo is on file. If someone asks for a picture, drawing, photo, or generated image of them, generate one that looks like them.",
        ],
        "appearance": appearance,
        "source": {
            "message_id": str(message_id),
            "user_id": str(author.id),
            "username": author.name,
            "display_name": display,
            "guild_id": str(guild.id) if guild else None,
            "channel_id": str(message.channel.id),
            "message_sent_at": snowflake["sent_at"],
            "style": {
                "sample_count": style["sample_count"],
                "avg_chars": style["avg_chars"],
                "median_chars": style["median_chars"],
                "lowercase_ratio": style["lowercase_ratio"],
                "emoji_ratio": style["emoji_ratio"],
                "slang": style["slang"],
                "common_starters": style["common_starters"],
            },
            "method": "hannah-people-dataset",
        },
        "personality_prompt": prompt,
    }
    # Keep the requested profile name as the display name (panda, not their Discord nick).
    profile["name"] = profile_id.title()
    upsert_profile(profile_id, profile)

    report = {
        "ok": True,
        "profile_id": profile_id,
        "snowflake": snowflake,
        "author": {
            "id": str(author.id),
            "username": author.name,
            "display_name": display,
            "bot": bool(getattr(author, "bot", False)),
        },
        "source_message": {
            "id": str(message.id),
            "channel_id": str(message.channel.id),
            "guild_id": str(guild.id) if guild else None,
            "content": (message.content or "")[:500],
            "has_attachments": bool(message.attachments),
        },
        "style": style,
        "image_path": saved_image,
        "personality_prompt": prompt,
    }
    write_report(os.path.join(PEOPLE_DIR, f"{profile_id}_report.json"), report)
    return report
