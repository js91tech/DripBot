"""Clone a Discord user into a people/ profile the same way Hannah was cloned."""

import json
import os
import aiohttp

from people import (
    CLONE_LOOKBACK,
    FAVORITE_EMOJI_LIMIT,
    FAVORITE_STICKER_LIMIT,
    PEOPLE_DIR,
    analyze_message_style,
    appearance_from_member,
    build_clone_personality_prompt,
    decode_snowflake,
    extract_emojis_from_text,
    rank_favorites,
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


def _sticker_record(sticker):
    return {
        "id": str(getattr(sticker, "id", "") or ""),
        "name": str(getattr(sticker, "name", "") or ""),
        "format": str(getattr(getattr(sticker, "format", None), "name", "") or getattr(sticker, "format", "") or ""),
    }


async def collect_user_messages(
    guild,
    user_id,
    lookback=CLONE_LOOKBACK,
    preferred_channel=None,
):
    """Read the last `lookback` messages in each readable channel and keep this user's."""
    from collections import Counter

    texts = []
    emoji_counter = Counter()
    sticker_counter = Counter()
    sticker_meta = {}
    channels = []
    if preferred_channel is not None:
        channels.append(preferred_channel)
    for channel in getattr(guild, "text_channels", []):
        if preferred_channel is not None and channel.id == getattr(preferred_channel, "id", None):
            continue
        channels.append(channel)

    for channel in channels:
        me = getattr(guild, "me", None)
        if me is None:
            continue
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.read_message_history):
            continue
        try:
            async for msg in channel.history(limit=lookback):
                if msg.author.id != user_id:
                    continue
                if (msg.content or "").startswith("/"):
                    continue
                text = (msg.content or "").strip()
                if text:
                    texts.append(text)
                    emoji_counter.update(extract_emojis_from_text(text))
                for sticker in getattr(msg, "stickers", None) or []:
                    record = _sticker_record(sticker)
                    if not record["id"]:
                        continue
                    sticker_counter[record["id"]] += 1
                    sticker_meta[record["id"]] = record
        except Exception:
            continue

    favorites = {
        "emojis": rank_favorites(emoji_counter, FAVORITE_EMOJI_LIMIT),
        "stickers": [
            {**sticker_meta[sid], "count": sticker_counter[sid]}
            for sid in rank_favorites(sticker_counter, FAVORITE_STICKER_LIMIT)
            if sid in sticker_meta
        ],
    }
    return texts, favorites


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
    favorites = {"emojis": [], "stickers": []}
    if guild is not None:
        texts, favorites = await collect_user_messages(
            guild,
            author.id,
            lookback=CLONE_LOOKBACK,
            preferred_channel=message.channel,
        )
    if message.content and message.content.strip():
        if message.content.strip() not in texts:
            texts.insert(0, message.content.strip())
        from collections import Counter
        extras = Counter(extract_emojis_from_text(message.content))
        if extras:
            merged = Counter({e: 1 for e in favorites.get("emojis") or []})
            merged.update(extras)
            favorites["emojis"] = rank_favorites(merged, FAVORITE_EMOJI_LIMIT)
    for sticker in getattr(message, "stickers", None) or []:
        record = _sticker_record(sticker)
        if record["id"] and record["id"] not in {s.get("id") for s in favorites.get("stickers") or []}:
            favorites.setdefault("stickers", []).insert(0, {**record, "count": 1})
            favorites["stickers"] = favorites["stickers"][:FAVORITE_STICKER_LIMIT]

    style = analyze_message_style(
        texts,
        emoji_counts=favorites.get("emojis") or [],
        sticker_counts={s["id"]: s for s in favorites.get("stickers") or [] if s.get("id")},
    )
    style["favorite_emojis"] = favorites.get("emojis") or style.get("favorite_emojis") or []
    style["favorite_stickers"] = favorites.get("stickers") or style.get("favorite_stickers") or []
    image_name = f"{profile_id}.jpg"
    image_path = os.path.join(PEOPLE_DIR, image_name)
    saved_image = await download_avatar(author, image_path)

    display = getattr(author, "display_name", None) or author.name
    appearance = appearance_from_member(author)
    extra_notes = [
        f"Cloned from Discord message {message_id}.",
        f"Discord user id {author.id} ({author.name}).",
        f"Looked at the last {CLONE_LOOKBACK} messages per channel.",
        style.get("summary") or "",
    ]
    if style.get("favorite_emojis"):
        extra_notes.append("Favorite emojis: " + " ".join(style["favorite_emojis"]))
    if style.get("favorite_stickers"):
        names = [s.get("name") or s.get("id") for s in style["favorite_stickers"]]
        extra_notes.append("Favorite stickers: " + ", ".join(n for n in names if n))
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
            "lookback": CLONE_LOOKBACK,
            "style": {
                "sample_count": style["sample_count"],
                "avg_chars": style["avg_chars"],
                "median_chars": style["median_chars"],
                "lowercase_ratio": style["lowercase_ratio"],
                "emoji_ratio": style["emoji_ratio"],
                "slang": style["slang"],
                "common_starters": style["common_starters"],
                "favorite_emojis": style.get("favorite_emojis") or [],
                "favorite_stickers": style.get("favorite_stickers") or [],
            },
            "method": "hannah-people-dataset",
        },
        "favorite_emojis": style.get("favorite_emojis") or [],
        "favorite_stickers": style.get("favorite_stickers") or [],
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
        "favorite_emojis": style.get("favorite_emojis") or [],
        "favorite_stickers": style.get("favorite_stickers") or [],
        "image_path": saved_image,
        "personality_prompt": prompt,
    }
    write_report(os.path.join(PEOPLE_DIR, f"{profile_id}_report.json"), report)
    return report
