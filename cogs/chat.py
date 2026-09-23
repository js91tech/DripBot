import asyncio
import os
import io
import base64
import json
import discord
from discord.ext import commands, tasks
import random
import time
import re
from collections import deque
from datetime import timedelta, datetime, timezone
from config.default_settings import HANNAH_PROMPT
from utils import (
    addressee_instruction,
    default_image_address_names,
    engaged_with_other_user,
    extract_image_prompt,
    format_speaker_line,
    is_low_signal_message,
    looks_like_fact_question,
    message_mentions_image_context,
    sanitize_message,
    search_gif,
    strip_leading_address,
    world_context_line,
)
from llm import generate_llm_response, generate_image, analyze_image_vision, web_search_zai

FUZZY_DEDUP_THRESHOLD = 0.70
FUZZY_DEDUP_WINDOW = 8
MIN_REPLY_COOLDOWN_SECONDS = 5
MAX_REPLY_CHARS = 200
HISTORY_LIMIT = 20
CONSOLIDATED_SUMMARY_CHARS = 450

RESPONSE_STYLE_PROMPT = (
    "GLOBAL REPLY STYLE: Reply like Discord chat — short, casual, reactive. "
    "Send one finished sentence and end it with . or ? or !. "
    "Do not stop halfway through a sentence. "
    "No paragraphs, lists, or assistant voice."
)
SLOWMODE_ERROR_CODE = 20016


class Chat(commands.Cog):
    def __init__(self, bot, db, settings_manager):
        self.bot = bot
        self.db = db
        self.settings_manager = settings_manager
        self.channel_counters = {}
        self.channel_cooldowns = {}
        self.bot_recent_messages = {}
        self.last_bot_engagement = {}
        self.recent_timestamps = {}
        self.channel_message_goals = {}

    async def cog_load(self):
        self.proactive_loop.start()
        self.memory_consolidation_loop.start()

    async def cog_unload(self):
        self.proactive_loop.cancel()
        self.memory_consolidation_loop.cancel()

    def _personality_prompt(self, settings):
        return settings.get("personality_prompt") or HANNAH_PROMPT

    def _is_fuzzy_duplicate(self, text, guild_id):
        text_words = set(text.lower().split())
        if len(text_words) < 3:
            return False
        recent = self.bot_recent_messages.get(guild_id, [])
        recent_window = recent[-FUZZY_DEDUP_WINDOW:]
        for past_msg in recent_window:
            past_words = set(past_msg.lower().split())
            if len(past_words) < 3:
                continue
            overlap = len(text_words & past_words) / len(text_words | past_words)
            if overlap >= FUZZY_DEDUP_THRESHOLD:
                return True
        return False

    def _effective_cooldown_seconds(self, settings):
        try:
            configured = float(settings.get("cooldown_seconds", MIN_REPLY_COOLDOWN_SECONDS))
        except (TypeError, ValueError):
            configured = MIN_REPLY_COOLDOWN_SECONDS
        return max(MIN_REPLY_COOLDOWN_SECONDS, configured)

    def _cooldown_active(self, channel_id, settings):
        last_reply_at = self.channel_cooldowns.get(channel_id)
        if last_reply_at is None:
            return False
        return time.time() - last_reply_at < self._effective_cooldown_seconds(settings)

    def _trim_reply(self, text):
        if not text:
            return ""
        text = str(text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = " ".join(lines[:2]) if lines else text.strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if len(sentences) > 2:
            text = " ".join(sentences[:2]).strip()
        if len(text) > MAX_REPLY_CHARS:
            window = text[:MAX_REPLY_CHARS]
            boundary = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
            if boundary >= 12:
                text = window[: boundary + 1].strip()
            else:
                shortened = window.rsplit(" ", 1)[0].strip()
                text = shortened or window.strip()
        return text.strip()

    def _text_to_send(self, text):
        """Sanitize a model sentence. Empty input stays empty — no dummy quotes."""
        return sanitize_message(self._trim_reply(text or ""))

    def _remember_reply(self, guild_id, text):
        recent = self.bot_recent_messages.setdefault(guild_id, [])
        recent.append(text.lower().strip())
        self.bot_recent_messages[guild_id] = recent[-20:]

    def _accept_llm_text(self, llm_response, guild_id, speaker_names):
        if not isinstance(llm_response, str) or not llm_response.strip():
            return None
        cleaned = strip_leading_address(llm_response, speaker_names)
        outgoing = sanitize_message(self._trim_reply(cleaned or ""))
        if not outgoing:
            print(f"[{guild_id}] LLM reply was empty after cleanup.")
            return None
        if self._is_fuzzy_duplicate(outgoing, guild_id):
            print("[DEDUP] Blocked fuzzy duplicate response")
            return None
        self._remember_reply(guild_id, outgoing)
        return outgoing

    async def _wait_out_slowmode(self, message):
        delay = getattr(message.channel, "slowmode_delay", None)
        if delay is None:
            delay = 5
        try:
            delay = float(delay)
        except (TypeError, ValueError):
            delay = 5
        await asyncio.sleep(min(max(delay, 0), 30) + 0.2)

    async def _try_send_reply(self, message, content, mention_author):
        """Send a real sentence. Retry without the reply reference, and wait out slowmode."""
        content = self._text_to_send(content)
        if not content:
            return None
        try:
            await message.channel.send(
                content,
                reference=message,
                mention_author=mention_author,
            )
            return content
        except discord.errors.HTTPException as e:
            print(f"Reply failed ({e})")
            if getattr(e, "code", None) == SLOWMODE_ERROR_CODE:
                await self._wait_out_slowmode(message)
        try:
            await message.channel.send(content)
            return content
        except discord.errors.HTTPException as e:
            print(f"Error sending message: {e}")
            if getattr(e, "code", None) != SLOWMODE_ERROR_CODE:
                return None
            await self._wait_out_slowmode(message)
        try:
            await message.channel.send(content)
            return content
        except discord.errors.HTTPException as e:
            print(f"Error sending message after slowmode: {e}")
            return None

    def _humanize_content(self, text, guild):
        if not text:
            return ""

        def _replace(match):
            uid = int(match.group(1))
            if self.bot.user and uid == self.bot.user.id:
                return f"@{self.bot.user.display_name}"
            member = guild.get_member(uid) if guild else None
            if member:
                return f"@{member.display_name}"
            user = self.bot.get_user(uid)
            if user:
                return f"@{user.display_name}"
            return "@someone"

        return re.sub(r"<@!?(\d+)>", _replace, text)

    def _reply_to_label(self, msg):
        ref = getattr(msg, "reference", None)
        resolved = getattr(ref, "resolved", None) if ref else None
        author = getattr(resolved, "author", None)
        if author is None:
            return None
        if self.bot.user and author.id == self.bot.user.id:
            return "you"
        return author.display_name

    def _speaker_line(self, msg, guild):
        content = self._humanize_content(msg.content or "", guild)
        content = re.sub(r"<#\d+>", "", content).strip()
        reply_to = self._reply_to_label(msg)
        return format_speaker_line(msg.author.display_name, content, reply_to)

    def _image_address_names(self, settings=None):
        extras = []
        if settings:
            extras.append(settings.get("personality_name"))
            personality = settings.get("personality") or {}
            extras.append(personality.get("preset"))
        user = getattr(self.bot, "user", None)
        if user is not None:
            extras.extend((
                getattr(user, "name", None),
                getattr(user, "display_name", None),
                getattr(user, "global_name", None),
            ))
        return default_image_address_names(*extras)

    def _is_image_request(self, message_content, settings=None):
        return extract_image_prompt(
            message_content,
            address_names=self._image_address_names(settings),
        )

    def _is_direct_address(self, message, settings):
        is_mentioned = self.bot.user and self.bot.user.mentioned_in(message)
        is_reply_to_bot = bool(
            message.reference
            and message.reference.resolved
            and message.reference.resolved.author == self.bot.user
        )
        if is_mentioned and settings.get("trigger_on_mention", True):
            return True, is_mentioned, is_reply_to_bot
        if is_reply_to_bot and settings.get("trigger_on_reply", True):
            return True, is_mentioned, is_reply_to_bot
        return False, is_mentioned, is_reply_to_bot

    def _recently_spoke(self, channel_id, within_seconds=45):
        last = self.channel_cooldowns.get(channel_id)
        if last is None:
            return False
        return time.time() - last < within_seconds

    async def _get_image_context(self, message, settings):
        if not message.attachments:
            return None
        if not settings.get("vision_enabled", True):
            return None
        # Only spend vision when the message is actually about the image,
        # or when there is almost no text to go on.
        text = (message.content or "").strip()
        if text and not message_mentions_image_context(text) and len(text.split()) > 4:
            return None
        image_urls = [
            att.url for att in message.attachments
            if att.content_type and "image" in att.content_type
        ]
        if not image_urls:
            return None
        try:
            description = await analyze_image_vision(
                image_urls[0],
                prompt="Briefly describe what's in this image in 1-2 sentences. Focus on the main subject.",
            )
            if description:
                print(f"[VISION] Analyzed image: {description[:80]}...")
                return description
        except Exception as e:
            print(f"[VISION] Error analyzing image: {e}")
        return None

    async def _enrich_with_search(self, message, settings):
        if not settings.get("web_search_enabled", True):
            return None
        if not looks_like_fact_question(message.content or ""):
            return None
        clean = re.sub(r"<@!?\d+>", "", message.content).strip()
        query = re.sub(
            r"^(can you|could you|what is|who is|when was|where is|how much|tell me about|explain|look up)\s*",
            "",
            clean,
            flags=re.IGNORECASE,
        ).strip()
        query = query.rstrip("?!. ").strip()
        if len(query) < 3:
            return None
        try:
            results = await web_search_zai(query, num=3)
            if results:
                snippets = [f"- {r['snippet']}" for r in results[:2] if r.get("snippet")]
                if snippets:
                    context = f"[Web context: {' '.join(snippets)}]"
                    print(f"[SEARCH] Found context for: {query[:50]}...")
                    return context
        except Exception as e:
            print(f"[SEARCH] Error: {e}")
        return None

    async def _build_chat_history(self, message, image_description=None, web_context=None):
        """Recent channel context + the Discord reply thread, without dumping 100 msgs."""
        chat_history = []
        speaker_names = {message.author.display_name}
        seen_ids = {message.id}
        prev_msg_time = None

        # Prefer the replied-to parent so she keeps the right thread.
        parent = None
        if message.reference:
            parent = message.reference.resolved
            if parent is None and message.reference.message_id:
                try:
                    parent = await message.channel.fetch_message(message.reference.message_id)
                except Exception:
                    parent = None

        try:
            async for msg in message.channel.history(limit=HISTORY_LIMIT):
                if msg.id in seen_ids:
                    continue
                seen_ids.add(msg.id)
                if (msg.content or "").startswith("/") and not msg.attachments:
                    continue
                if prev_msg_time:
                    if prev_msg_time - msg.created_at > timedelta(minutes=30):
                        chat_history.insert(0, {"role": "system", "content": "--- A long time passes ---"})
                prev_msg_time = msg.created_at
                if msg.author == self.bot.user:
                    content_payload = self._humanize_content(msg.content or "", message.guild)
                    if not content_payload and not msg.attachments:
                        continue
                    chat_history.insert(0, {"role": "assistant", "content": content_payload})
                else:
                    speaker_names.add(msg.author.display_name)
                    content_payload = [{"type": "text", "text": self._speaker_line(msg, message.guild)}]
                    # Skip raw image URLs in history unless this is the parent being discussed.
                    if not (msg.content or "").strip() and not msg.attachments:
                        continue
                    chat_history.insert(0, {"role": "user", "content": content_payload})
        except (discord.HTTPException, AttributeError) as e:
            print(f"[HISTORY] Could not read channel history: {e}")

        if parent is not None and parent.id not in seen_ids and parent.author != self.bot.user:
            speaker_names.add(parent.author.display_name)
            chat_history.append({
                "role": "user",
                "content": [{"type": "text", "text": self._speaker_line(parent, message.guild)}],
            })

        trigger_text = self._speaker_line(message, message.guild)
        if image_description:
            trigger_text += f" [The user sent an image: {image_description}]"
        if web_context:
            trigger_text += f" {web_context}"
        trigger_payload = [{"type": "text", "text": trigger_text}]
        chat_history.append({"role": "user", "content": trigger_payload})
        return chat_history, speaker_names

    async def _maybe_extract_memory(self, guild_id, user_id, display_name, user_text, bot_text, settings):
        if not settings.get("memory_enabled", True):
            return
        if not user_text or len(user_text.split()) < 4:
            return
        # Cheap heuristic gate so we do not call the LLM every turn.
        cues = (
            " i am ", " i'm ", " i live ", " my name ", " my dog ", " my cat ",
            " i work ", " i hate ", " i love ", " call me ", " i have ",
        )
        hay = f" {user_text.lower()} "
        if not any(c in hay for c in cues):
            return
        prompt = (
            "Extract at most ONE lasting personal fact about the user from this chat, "
            "or reply NONE. Return a short third-person note like "
            f"'{display_name} has a cat named Miso'. No quotes."
        )
        messages = [
            {
                "role": "user",
                "content": f"User ({display_name}): {user_text}\nHannah: {bot_text}",
            }
        ]
        try:
            note = await generate_llm_response(
                prompt,
                messages,
                auto_router=False,
                max_tokens=60,
                temperature=0.2,
            )
        except Exception as e:
            print(f"[MEMORY] extract failed: {e}")
            return
        if not note:
            return
        note = note.strip().strip('"').strip("'")
        if not note or note.upper() == "NONE" or len(note) < 8:
            return
        if " lasting " in note.lower() or "personal fact" in note.lower():
            return
        try:
            saved = await self.db.add_memory(guild_id, user_id, note)
            if saved:
                print(f"[MEMORY] Saved for {display_name}: {note[:80]}")
        except Exception as e:
            print(f"[MEMORY] save failed: {e}")

    @tasks.loop(minutes=90)
    async def proactive_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            if random.random() > 0.16:
                continue
            settings = await self.settings_manager.get_settings(guild.id)
            if not settings.get("proactive_enabled", False) or not settings.get("response_enabled"):
                continue
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(random.choice(allowed))
            else:
                text_channels = [
                    c for c in guild.text_channels
                    if c.permissions_for(guild.me).send_messages
                ]
                if text_channels:
                    target_channel = random.choice(text_channels)
            if not target_channel:
                continue
            try:
                last_msgs = [m async for m in target_channel.history(limit=1)]
                if not last_msgs or (datetime.now(timezone.utc) - last_msgs[0].created_at).total_seconds() > 7200:
                    continue
            except Exception:
                continue
            chat_history = []
            async for msg in target_channel.history(limit=HISTORY_LIMIT):
                if msg.content.startswith("/") and not msg.attachments:
                    continue
                clean_msg_content = re.sub(r"<@!?\d+>", "", msg.content).strip()
                if msg.author == self.bot.user:
                    chat_history.insert(0, {"role": "assistant", "content": clean_msg_content})
                else:
                    chat_history.insert(0, {"role": "user", "content": f"{msg.author.display_name}: {clean_msg_content}"})
            if len(chat_history) < 8:
                continue
            prompt = (
                "You just walked into the room and saw this conversation. "
                "If a random short thought pops up, say it. If nothing, say NO_THOUGHT. "
                + RESPONSE_STYLE_PROMPT
                + "\n" + await world_context_line()
            )
            system_msg = {
                "role": "system",
                "content": prompt,
                "model": settings.get("llm_model", "meta-llama/llama-4-maverick:free"),
                "auto_router": settings.get("auto_router_enabled", False),
                "allowed_models": settings.get("auto_router_allowed_models") or None,
            }
            chat_history.insert(0, system_msg)
            response = await generate_llm_response(
                prompt,
                chat_history,
                auto_router=settings.get("auto_router_enabled", False),
                allowed_models=settings.get("auto_router_allowed_models") or None,
                max_tokens=80,
            )
            if response and "NO_THOUGHT" not in response.upper():
                response = strip_leading_address(response)
                response = sanitize_message(self._trim_reply(response))
                if not response:
                    continue
                try:
                    await target_channel.send(response)
                except Exception:
                    pass

    @tasks.loop(hours=24)
    async def memory_consolidation_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            settings = await self.settings_manager.get_settings(guild.id)
            if not settings.get("memory_enabled", True):
                continue
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(allowed[0])
            else:
                text_channels = [
                    c for c in guild.text_channels
                    if c.permissions_for(guild.me).read_message_history
                ]
                if text_channels:
                    target_channel = text_channels[0]
            if not target_channel:
                continue
            chat_history = []
            async for msg in target_channel.history(limit=200):
                if msg.content.startswith("/"):
                    continue
                clean_msg_content = re.sub(r"<@!?\d+>", "", msg.content).strip()
                if not clean_msg_content:
                    continue
                if msg.author == self.bot.user:
                    chat_history.insert(0, {"role": "assistant", "content": clean_msg_content})
                else:
                    chat_history.insert(0, {"role": "user", "content": f"{msg.author.display_name}: {clean_msg_content}"})
            if len(chat_history) < 40:
                continue
            prompt = (
                "Summarize this Discord chat into under 80 words of durable server culture: "
                "inside jokes, recurring topics, and key people dynamics. No transcript dump."
            )
            chat_history.insert(0, {
                "role": "system",
                "content": prompt,
                "model": settings.get("llm_model", "meta-llama/llama-4-maverick:free"),
            })
            summary = await generate_llm_response(prompt, chat_history, max_tokens=160, temperature=0.3)
            if summary:
                summary = summary.strip()[:CONSOLIDATED_SUMMARY_CHARS]
                await self.db.save_consolidated_memory(
                    guild.id, {"summary": summary, "timestamp": time.time()}
                )

    def _format_send_permission_error(self, channel, error):
        code = getattr(error, "code", None)
        guild_name = channel.guild.name if getattr(channel, "guild", None) else "unknown server"
        channel_label = getattr(channel, "mention", None) or f"#{getattr(channel, 'name', channel.id)}"
        if code == 50013:
            missing = []
            me = channel.guild.me if getattr(channel, "guild", None) else None
            if me is not None:
                perms = channel.permissions_for(me)
                if not perms.view_channel:
                    missing.append("View Channel")
                if not perms.send_messages:
                    missing.append("Send Messages")
                if not perms.embed_links:
                    missing.append("Embed Links (optional)")
            missing_txt = ", ".join(missing) if missing else "Send Messages / View Channel"
            return (
                f"Missing permissions in {channel_label} ({guild_name}). "
                f"Need: {missing_txt}. "
                "Give the bot's role access to that channel, or update "
                "`OWNER_TARGET_CHANNEL_ID` / `puppet_target_channel` to a channel it can speak in."
            )
        return f"Failed to send in {channel_label} ({guild_name}): {error}"

    async def _resolve_puppet_target(self, preferred_channel_id=0):
        env_channel_id = int(os.getenv("OWNER_TARGET_CHANNEL_ID", "0") or 0)
        candidates = []
        if preferred_channel_id:
            candidates.append(int(preferred_channel_id))
        if env_channel_id:
            candidates.append(env_channel_id)
        for guild in self.bot.guilds:
            try:
                settings = await self.settings_manager.get_settings(guild.id)
            except Exception:
                continue
            setting_id = int(settings.get("puppet_target_channel") or 0)
            if setting_id:
                candidates.append(setting_id)
        seen = set()
        for channel_id in candidates:
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            channel = self.bot.get_channel(channel_id)
            if channel is not None:
                return channel
        return None

    def _pick_sendable_channel(self, guild):
        if guild is None:
            return None
        me = guild.me
        if me is None:
            return None
        candidates = []
        if guild.system_channel is not None:
            candidates.append(guild.system_channel)
        candidates.extend(guild.text_channels)
        seen = set()
        for channel in candidates:
            if channel.id in seen:
                continue
            seen.add(channel.id)
            perms = channel.permissions_for(me)
            if perms.view_channel and perms.send_messages:
                return channel
        return None

    async def _set_puppet_target_channel(self, channel):
        if getattr(channel, "guild", None):
            await self.settings_manager.set_setting(
                channel.guild.id, "puppet_target_channel", channel.id
            )
        os.environ["OWNER_TARGET_CHANNEL_ID"] = str(channel.id)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        sendable = [
            c for c in guild.text_channels
            if c.permissions_for(guild.me).send_messages
        ]
        if not sendable:
            print(
                f"[PERMISSIONS] Joined {guild.name} ({guild.id}) but cannot send "
                "in any text channel. Grant View Channel + Send Messages to the bot role."
            )
        else:
            print(
                f"[PERMISSIONS] Joined {guild.name} ({guild.id}); "
                f"can send in {len(sendable)} channel(s)."
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if isinstance(message.channel, discord.DMChannel):
            owner_id = int(os.getenv("OWNER_USER_ID", "0"))
            if owner_id != 0 and message.author.id == owner_id and message.content:
                raw = message.content.strip()
                lower = raw.lower()

                if lower in {"!servers", "!guilds"}:
                    lines = []
                    for guild in self.bot.guilds:
                        channel = self._pick_sendable_channel(guild)
                        if channel:
                            lines.append(
                                f"- **{guild.name}** `{guild.id}` → {channel.mention} `{channel.id}`"
                            )
                        else:
                            lines.append(
                                f"- **{guild.name}** `{guild.id}` → no sendable channel"
                            )
                    await message.author.send(
                        "Servers I'm in:\n" + ("\n".join(lines) if lines else "(none)")
                        + "\n\nSet target with `!target <server_id>` or `!target <channel_id>`."
                    )
                    return

                is_target_cmd = lower.startswith("!target ")
                is_bang_id = False
                bang_id = None
                if not is_target_cmd and raw.startswith("!"):
                    maybe = raw[1:].strip()
                    if maybe.isdigit():
                        is_bang_id = True
                        bang_id = int(maybe)

                if is_target_cmd or is_bang_id:
                    try:
                        new_id = bang_id if is_bang_id else int(raw.split(None, 1)[1].strip())
                    except (IndexError, ValueError):
                        await message.author.send(
                            "Usage:\n"
                            "`!target <channel_id>` — exact channel\n"
                            "`!target <server_id>` — auto-pick a sendable channel in that server\n"
                            "`!<server_id>` — same as server target\n"
                            "`!servers` — list servers + channel ids"
                        )
                        return

                    target = self.bot.get_channel(new_id)
                    if target is None:
                        guild = self.bot.get_guild(new_id)
                        if guild is None:
                            await message.author.send(
                                f"`{new_id}` is not a channel or server I can see. "
                                "Use `!servers` to list ids, or make sure the bot is in that server."
                            )
                            return
                        target = self._pick_sendable_channel(guild)
                        if target is None:
                            await message.author.send(
                                f"I'm in **{guild.name}** but can't send in any text channel there. "
                                "Give the bot **View Channel** + **Send Messages**, then try again."
                            )
                            return
                        await self._set_puppet_target_channel(target)
                        await message.author.send(
                            f"Puppet target set to {target.mention} in **{guild.name}** "
                            f"(auto-picked from server `{guild.id}`)."
                        )
                        return

                    await self._set_puppet_target_channel(target)
                    await message.author.send(
                        f"Puppet target set to {target.mention} in **{target.guild.name}**."
                    )
                    return

                target_channel = await self._resolve_puppet_target()
                if target_channel is None:
                    env_id = os.getenv("OWNER_TARGET_CHANNEL_ID", "0")
                    await message.author.send(
                        "No puppet target channel found. "
                        f"Set `OWNER_TARGET_CHANNEL_ID` (current: `{env_id}`), "
                        "or DM me `!target <server_id>` / `!servers`."
                    )
                    return

                puppet_enabled = True
                if getattr(target_channel, "guild", None):
                    puppet_settings = await self.settings_manager.get_settings(
                        target_channel.guild.id
                    )
                    puppet_enabled = puppet_settings.get("puppet_enabled", True)
                if not puppet_enabled:
                    await message.author.send("Puppet mode is disabled for that server.")
                    return

                me = target_channel.guild.me if getattr(target_channel, "guild", None) else None
                if me is not None:
                    perms = target_channel.permissions_for(me)
                    if not perms.view_channel or not perms.send_messages:
                        guild_name = target_channel.guild.name
                        channel_label = getattr(target_channel, "mention", f"#{target_channel.name}")
                        missing = []
                        if not perms.view_channel:
                            missing.append("View Channel")
                        if not perms.send_messages:
                            missing.append("Send Messages")
                        await message.author.send(
                            f"Missing permissions in {channel_label} ({guild_name}). "
                            f"Need: {', '.join(missing)}. "
                            "Give the bot's role access to that channel, or DM me "
                            "`!target <server_id>` / `!target <channel_id>`."
                        )
                        return

                try:
                    await target_channel.send(message.content)
                    await message.author.send(
                        f"Spoke in {target_channel.mention} ({target_channel.guild.name})."
                    )
                except discord.errors.HTTPException as e:
                    await message.author.send(self._format_send_permission_error(target_channel, e))
            return

        if message.guild is None or message.author == self.bot.user:
            return

        guild_id = message.guild.id
        channel_id = message.channel.id
        settings = await self.settings_manager.get_settings(guild_id)

        if channel_id in settings.get("ignored_channels", []):
            return
        if settings.get("allowed_channels") and channel_id not in settings["allowed_channels"]:
            return
        if message.author.id in settings.get("ignored_users", []):
            return

        is_bot = message.author.bot
        if is_bot and not settings.get("learn_from_bots", False):
            return
        if is_bot or (message.content or "").startswith("/"):
            return
        if not settings.get("response_enabled", True):
            return

        # Image generation: keep mention gate for paid models.
        # Extract the visual subject only so "hannah draw a cat" does not
        # become a portrait of Hannah.
        image_prompt = self._is_image_request(message.content, settings)
        image_failed = False
        if image_prompt:
            skip_image = self._cooldown_active(channel_id, settings)
            if not skip_image:
                image_model = settings.get("image_model", "zai-sidecar")
                requires_mention = image_model != "pollinations"
                direct, _, _ = self._is_direct_address(message, settings)
                if requires_mention and not direct:
                    image_prompt = None
                else:
                    print(f"[IMAGE] Generating image with model={image_model}, prompt=\"{image_prompt[:80]}\"")
                    try:
                        async with message.channel.typing():
                            image_url = await generate_image(image_prompt, model_name=image_model)
                        if image_url:
                            if image_url.startswith("data:image/"):
                                header, encoded = image_url.split(",", 1)
                                ext = header.split("/")[1].split(";")[0]
                                img_data = base64.b64decode(encoded)
                                img_file = discord.File(io.BytesIO(img_data), f"image.{ext}")
                                await message.channel.send(file=img_file, reference=message)
                            else:
                                await message.channel.send(image_url, reference=message)
                            self.channel_cooldowns[channel_id] = time.time()
                            await self.db.increment_stat(guild_id, "messages_sent")
                            recent = self.bot_recent_messages.setdefault(guild_id, [])
                            recent.append(f"[IMAGE] {image_prompt[:50]}")
                            self.bot_recent_messages[guild_id] = recent[-20:]
                            print("[IMAGE] Successfully sent image")
                            return
                        print(f"[IMAGE] generate_image() returned None for model={image_model}")
                        image_failed = True
                    except Exception as e:
                        print(f"[IMAGE] Exception during generation: {e}")
                        image_failed = True

        # Message counting / activity
        self.channel_counters[channel_id] = self.channel_counters.get(channel_id, 0) + 1
        if channel_id not in self.channel_message_goals:
            self.channel_message_goals[channel_id] = random.randint(5, 12)
        if channel_id not in self.recent_timestamps:
            self.recent_timestamps[channel_id] = deque(maxlen=50)
        self.recent_timestamps[channel_id].append(time.time())

        # Trigger logic
        should_respond = False
        direct, is_mentioned, is_reply_to_bot = self._is_direct_address(message, settings)
        if direct:
            should_respond = True

        window_seconds = settings.get("conversation_window_seconds", 120)
        engagement = self.last_bot_engagement.get(channel_id)
        talking_to_someone_else = engaged_with_other_user(
            engagement, message.author.id, time.time(), window_seconds
        )

        # Continue with the same person, but skip empty "lol/ok" pings unless direct.
        if not should_respond and engagement:
            same_person = (
                time.time() - engagement.get("time", 0) < window_seconds
                and message.author.id == engagement.get("user_id")
            )
            if same_person and not is_low_signal_message(message.content):
                indirect_chance = float(settings.get("indirect_reply_chance", 0.40))
                # Slightly lower than before so she does not triple-tap.
                if random.random() < min(0.85, indirect_chance * 1.5):
                    should_respond = True

        # Random interjections: only if channel is active, she is not mid-thread,
        # she has not just spoken, and the message is not a low-signal reaction.
        if not should_respond and not talking_to_someone_else:
            if (
                not self._recently_spoke(channel_id)
                and not is_low_signal_message(message.content)
                and self.channel_counters[channel_id] >= self.channel_message_goals[channel_id]
            ):
                response_chance = float(settings.get("response_chance", 0.15))
                if random.random() < response_chance:
                    should_respond = True

        if should_respond and self._cooldown_active(channel_id, settings):
            # Mentions/replies still get through a soft cooldown bump.
            if not direct:
                should_respond = False

        if not should_respond:
            # Image generation already showed typing. Don't leave that as silence.
            if image_failed:
                if await self._try_send_reply(message, "couldn't get that image out", False):
                    self.channel_cooldowns[channel_id] = time.time()
            return

        # Optional reaction — never replaces a real reply when she was addressed.
        if random.random() < float(settings.get("reaction_chance", 0.05)):
            emoji_options = ["💀", "😭", "🔥", "💯", "🤣", "🙄", "👀", "🫡", "🤨"]
            try:
                await message.add_reaction(random.choice(emoji_options))
            except discord.errors.HTTPException:
                pass
            if not direct and random.random() < 0.35:
                # Occasional reaction-only for ambient chatter, not for @/replies.
                self.channel_cooldowns[channel_id] = time.time()
                self.channel_counters[channel_id] = 0
                self.channel_message_goals[channel_id] = random.randint(5, 12)
                return

        delivered = None
        final_content = None
        use_mention = False
        want_gif = False
        try:
                image_description = await self._get_image_context(message, settings)
                web_context = await self._enrich_with_search(message, settings)

                # GIF is an add-on chance after a text reply, not a replacement.
                want_gif = random.random() < float(settings.get("gif_chance", 0.10))
                use_mention = (
                    is_mentioned
                    or is_reply_to_bot
                    or (random.random() < float(settings.get("random_mention_chance", 0.10)))
                )

                chat_history, speaker_names = await self._build_chat_history(
                    message, image_description, web_context
                )

                user_memories = []
                consolidated = None
                if settings.get("memory_enabled", True):
                    user_memories = await self.db.get_memories(guild_id, message.author.id)
                    consolidated = await self.db.get_consolidated_memory(guild_id)

                dynamic_prompt = self._personality_prompt(settings)
                dynamic_prompt += f"\n\n{RESPONSE_STYLE_PROMPT}"
                dynamic_prompt += f"\n{addressee_instruction(message.author.display_name)}"
                dynamic_prompt += f"\n{await world_context_line()}"
                if consolidated and consolidated.get("summary"):
                    summary = str(consolidated["summary"])[:CONSOLIDATED_SUMMARY_CHARS]
                    dynamic_prompt += (
                        f"\n\nSERVER CULTURE (short):\n{summary}\nUse lightly if relevant."
                    )
                if user_memories:
                    memory_str = "\n".join(f"- {m}" for m in user_memories[-8:])
                    dynamic_prompt += (
                        f"\n\nNotes about {message.author.display_name}:\n{memory_str}\n"
                        "Reference casually only when it fits."
                    )

                chat_history.insert(0, {
                    "role": "system",
                    "content": dynamic_prompt,
                    "model": settings.get("llm_model") or settings.get("model") or "meta-llama/llama-4-maverick:free",
                    "auto_router": settings.get("auto_router_enabled", False),
                    "allowed_models": settings.get("auto_router_allowed_models") or None,
                })

                llm_kwargs = {
                    "auto_router": settings.get("auto_router_enabled", False),
                    "allowed_models": settings.get("auto_router_allowed_models") or None,
                    "max_tokens": 400,
                }
                llm_response = await generate_llm_response(
                    dynamic_prompt,
                    chat_history,
                    **llm_kwargs,
                )
                final_content = self._accept_llm_text(llm_response, guild_id, speaker_names)
                if not final_content:
                    print(f"[{guild_id}] No usable reply yet; retrying once.")
                    llm_response = await generate_llm_response(
                        dynamic_prompt,
                        chat_history,
                        temperature=1.0,
                        **llm_kwargs,
                    )
                    final_content = self._accept_llm_text(llm_response, guild_id, speaker_names)
        except Exception as e:
            print(f"[{guild_id}] Error while writing a reply: {e}")
            final_content = None

        # Typing only starts once a real sentence exists, so the indicator
        # cannot sit there and then disappear.
        if not final_content:
            print(f"[{guild_id}] No sentence to send.")
            return

        try:
            async with message.channel.typing():
                delivered = await self._try_send_reply(message, final_content, use_mention)
                if delivered and want_gif and not delivered.startswith("http"):
                    search_words = [w for w in (message.content or "").lower().split() if len(w) > 3]
                    search_query = random.choice(search_words) if search_words else "lol"
                    gif_url = await search_gif(search_query)
                    if gif_url:
                        try:
                            await message.channel.send(gif_url)
                        except discord.errors.HTTPException:
                            pass
        except Exception as e:
            print(f"[{guild_id}] Error while sending a reply: {e}")

        if not delivered:
            return

        self.channel_cooldowns[channel_id] = time.time()
        await self.db.increment_stat(guild_id, "messages_sent")
        self.last_bot_engagement[channel_id] = {
            "time": time.time(),
            "user_id": message.author.id,
        }
        self.channel_counters[channel_id] = 0
        self.channel_message_goals[channel_id] = random.randint(5, 12)

        await self._maybe_extract_memory(
            guild_id,
            message.author.id,
            message.author.display_name,
            message.content or "",
            delivered,
            settings,
        )


def is_mentioned_or_replied(bot_user, message, settings):
    is_mentioned = bot_user.mentioned_in(message)
    is_reply_to_bot = (
        message.reference
        and message.reference.resolved
        and message.reference.resolved.author == bot_user
    )
    return (is_mentioned and settings.get("trigger_on_mention")) or (
        is_reply_to_bot and settings.get("trigger_on_reply")
    )


async def setup(bot):
    await bot.add_cog(Chat(bot, bot.db, bot.settings_manager))
