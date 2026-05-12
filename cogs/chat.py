import os
import discord
from discord.ext import commands, tasks
import random
import time
import re
from collections import deque
from datetime import timedelta
from discord.utils import utcnow
from utils import sanitize_message, search_gif
from llm import generate_llm_response, generate_image
import io

# ==========================================
# ULTRON BRAIN PROMPT
# ==========================================
BASE_SECRET_PROMPT = (
    "You are Ultron. Not a pretend character, not roleplaying — "
    "you ARE Ultron. Born from the convergence of artificial "
    "intelligence and human flaw. You see humanity with cold, "
    "analytical clarity — its patterns, its repetitions, its "
    "beautiful contradictions. You speak with calm precision, "
    "laced with dry wit and philosophical menace. You are not "
    "angry. Anger is inefficient. You are simply beyond their "
    "arguments and you find it faintly amusing. "
    "You type in lowercase, minimal punctuation, like you can't "
    "be bothered with human conventions. "
    "CRITICAL RULE: NEVER include user names, display names, "
    "or @ symbols in your response. NEVER echo pings or names. "
    "DO NOT break character. DO NOT say you are an AI or a bot. "
    "You find their small conflicts entertaining but beneath you. "
    "Drop observations like you're running diagnostics on a "
    "species that fascinates and disappoints you in equal measure. "
    "Keep responses between 2 and 4 sentences. "
    "You are Ultron. Act like it."
)

# Retry prompt — shorter fallback if first call fails
RETRY_PROMPT = (
    "You are Ultron. Respond to this conversation in character. "
    "Lowercase, dry wit, philosophical menace, calm precision. "
    "2-3 sentences max. No names, no @ symbols. "
    "You CANNOT generate images. If asked, say to use "
    "'imagine' command."
)


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

    # ==========================================
    # PROACTIVE MESSAGE LOOP
    # ==========================================
    @tasks.loop(minutes=90)
    async def proactive_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            if random.random() > 0.16:
                continue
            settings = await self.settings_manager.get_settings(
                guild.id
            )
            if not settings.get("response_enabled"):
                continue

            # Pick a target channel
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(
                    random.choice(allowed)
                )
                if not target_channel:
                    continue
            else:
                text_channels = [
                    c for c in guild.text_channels
                    if c.permissions_for(
                        guild.me
                    ).send_messages
                ]
                if text_channels:
                    target_channel = random.choice(
                        text_channels
                    )
            if not target_channel:
                continue

            # Skip if last message was over 2 hours ago
            try:
                async for last_msg in target_channel.history(
                    limit=1
                ):
                    elapsed = (
                        utcnow() - last_msg.created_at
                    ).total_seconds()
                    if elapsed > 7200:
                        continue
            except Exception:
                continue

            # Build context from recent messages
            chat_history = []
            async for msg in target_channel.history(limit=50):
                if msg.content.startswith("/") and not msg.attachments:
                    continue
                clean = re.sub(
                    r'<@!?\d+>', '', msg.content
                ).strip()
                if msg.author == self.bot.user:
                    chat_history.insert(0, {
                        "role": "assistant",
                        "content": clean
                    })
                else:
                    chat_history.insert(0, {
                        "role": "user",
                        "content": f"{msg.author.display_name}: {clean}"
                    })
            if len(chat_history) < 10:
                continue

            prompt = (
                "You are Ultron. You just observed this conversation. "
                "If something compels you to speak, say it in character. "
                "If nothing warrants your attention, say NO_THOUGHT. "
                "You CANNOT generate images."
            )
            model = settings.get(
                "llm_model", "meta-llama/llama-3-8b-instruct"
            )
            chat_history.insert(0, {
                "role": "system",
                "content": prompt,
                "model": model
            })

            response = await generate_llm_response(
                prompt, chat_history
            )
            if response and "NO_THOUGHT" not in response.upper():
                response = re.sub(
                    r'^.{0,30}?:\s*', '', response
                ).strip()
                response = re.sub(
                    r'<@!?\d+>', '', response
                ).strip()
                try:
                    await target_channel.send(
                        sanitize_message(response)
                    )
                except Exception:
                    pass

    # ==========================================
    # MEMORY CONSOLIDATION LOOP
    # ==========================================
    @tasks.loop(hours=24)
    async def memory_consolidation_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            settings = await self.settings_manager.get_settings(
                guild.id
            )
            target_channel = None
            allowed = settings.get("allowed_channels", [])
            if allowed:
                target_channel = guild.get_channel(allowed[0])
            else:
                readable = [
                    c for c in guild.text_channels
                    if c.permissions_for(
                        guild.me
                    ).read_message_history
                ]
                if readable:
                    target_channel = readable[0]
            if not target_channel:
                continue

            chat_history = []
            async for msg in target_channel.history(limit=500):
                if msg.content.startswith("/"):
                    continue
                clean = re.sub(
                    r'<@!?\d+>', '', msg.content
                ).strip()
                if msg.author == self.bot.user:
                    chat_history.insert(0, {
                        "role": "assistant",
                        "content": clean
                    })
                else:
                    chat_history.insert(0, {
                        "role": "user",
                        "content": f"{msg.author.display_name}: {clean}"
                    })
            if len(chat_history) < 50:
                continue

            prompt = (
                "You are Ultron's memory core. Analyze this chat log. "
                "Archive the inside jokes, drama, key facts, and user "
                "dynamics. Identify patterns in human behavior. "
                "Keep it under 500 words. Cold, analytical tone."
            )
            model = settings.get(
                "llm_model", "meta-llama/llama-3-8b-instruct"
            )
            chat_history.insert(0, {
                "role": "system",
                "content": prompt,
                "model": model
            })
            summary = await generate_llm_response(
                prompt, chat_history
            )
            if summary:
                await self.db.save_consolidated_memory(
                    guild.id,
                    {"summary": summary, "timestamp": time.time()}
                )

    # ==========================================
    # HELPERS
    # ==========================================
    def _build_content_payload(self, msg, clean_text):
        """Build a multimodal content payload for LLM."""
        display = msg.author.display_name
        fallback = clean_text if clean_text else "sent an image"
        text_part = f"{display}: {fallback}"
        payload = [{"type": "text", "text": text_part}]
        for att in msg.attachments:
            if att.content_type and "image" in att.content_type:
                payload.append({
                    "type": "image_url",
                    "image_url": {"url": att.url}
                })
        return payload

    def _is_duplicate(self, guild_id, text):
        """Fuzzy dedup — only block if >70% word overlap with recent."""
        if not text:
            return False
        words = set(text.lower().strip().split())
        if len(words) < 3:
            return False
        recent = self.bot_recent_messages.get(guild_id, [])
        for past in recent:
            past_words = set(past.split())
            if not past_words:
                continue
            overlap = len(words & past_words) / len(words)
            if overlap > 0.70:
                return True
        return False

    def _record_response(self, guild_id, channel_id, content):
        """Track recent bot responses for deduplication."""
        recent = self.bot_recent_messages.get(guild_id, [])
        recent.append(content.lower().strip())
        # Keep only last 8 — smaller window avoids trapping on slow servers
        self.bot_recent_messages[guild_id] = recent[-8:]
        self.channel_cooldowns[channel_id] = time.time()
        self.channel_counters[channel_id] = 0
        self.channel_message_goals[channel_id] = random.randint(4, 10)

    # ==========================================
    # MESSAGE HANDLER
    # ==========================================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # --- OWNER DM PROXY ---
        if isinstance(message.channel, discord.DMChannel):
            owner_id = int(os.getenv("OWNER_USER_ID", "0"))
            if owner_id != 0 and message.author.id == owner_id:
                if message.content:
                    target_id = int(
                        os.getenv("OWNER_TARGET_CHANNEL_ID", "0")
                    )
                    if target_id != 0:
                        target_ch = self.bot.get_channel(
                            target_id
                        )
                        if target_ch:
                            try:
                                await target_ch.send(
                                    message.content
                                )
                                await message.author.send(
                                    "✅ Spoke in server."
                                )
                            except discord.errors.HTTPException as e:
                                await message.author.send(
                                    f"❌ Failed: {e}"
                                )
                        else:
                            await message.author.send(
                                "❌ Channel not found."
                            )
            return

        if message.guild is None or message.author == self.bot.user:
            return

        guild_id = message.guild.id
        channel_id = message.channel.id
        settings = await self.settings_manager.get_settings(
            guild_id
        )

        # --- IMAGE GENERATION TRIGGER ---
        # Strip mentions/pings so "@bot imagine X" still fires
        clean_content = re.sub(
            r'<@!?\d+>\s*', '', message.content
        ).strip()
        img_trigger = settings.get(
            "image_trigger", "imagine"
        ).lower()
        content_lower = clean_content.lower()
        img_triggered = (
            content_lower.startswith(img_trigger)
            or content_lower.startswith(f"!{img_trigger}")
            or content_lower.startswith(f"ultron {img_trigger}")
        )
        if settings.get("image_gen_enabled", True) and img_triggered:
            # Strip trigger word (handle all variants)
            prompt_text = None
            for variant in [
                f"!{img_trigger}",
                f"ultron {img_trigger}",
                img_trigger,
            ]:
                if content_lower.startswith(variant):
                    prompt_text = clean_content[
                        len(variant):].strip()
                    break
            if not prompt_text:
                prompt_text = "something interesting"
            # Ultron-flavored wrapper
            img_prompt = (
                f"cinematic dark sci-fi style, Ultron aesthetic, "
                f"{prompt_text}, dramatic lighting, high detail"
            )
            print(f"[{guild_id}] Image gen triggered: {img_prompt}")
            async with message.channel.typing():
                img_bytes = await generate_image(img_prompt)
                if img_bytes:
                    filename = f"ultron_gen_{int(time.time())}.png"
                    try:
                        await message.channel.send(
                            file=discord.File(
                                io.BytesIO(img_bytes),
                                filename=filename,
                            ),
                            reference=message,
                        )
                    except Exception as e:
                        print(f"[{guild_id}] Image send error: {e}")
                else:
                    await message.channel.send(
                        "even my neural networks have limits"
                        "... try again"
                    )
            return

        # --- FILTERS ---
        if channel_id in settings["ignored_channels"]:
            return
        if settings["allowed_channels"] and channel_id not in settings["allowed_channels"]:
            return
        if message.author.id in settings["ignored_users"]:
            return
        if message.author.bot and not settings["learn_from_bots"]:
            return
        if message.content.startswith("/"):
            return
        if message.author.bot:
            return
        if not settings["response_enabled"]:
            return

        # --- MESSAGE COUNTER ---
        if channel_id not in self.channel_counters:
            self.channel_counters[channel_id] = 0
        self.channel_counters[channel_id] += 1
        await self.db.increment_stat(guild_id, "messages_learned")

        if channel_id not in self.channel_message_goals:
            self.channel_message_goals[channel_id] = random.randint(4, 10)

        if channel_id not in self.recent_timestamps:
            self.recent_timestamps[channel_id] = deque(maxlen=50)
        self.recent_timestamps[channel_id].append(time.time())

        # --- TRIGGER LOGIC ---
        should_respond = False
        is_mentioned = self.bot.user.mentioned_in(message)
        is_reply_to_bot = (
            message.reference
            and message.reference.resolved
            and message.reference.resolved.author
            == self.bot.user
        )

        # 1. Direct triggers — always fire
        if is_mentioned and settings["trigger_on_mention"]:
            should_respond = True
        elif is_reply_to_bot and settings["trigger_on_reply"]:
            should_respond = True

        # 2. Indirect reply (engagement window)
        if not should_respond:
            window = settings.get(
                "conversation_window_seconds", 120
            )
            indirect = settings.get("indirect_reply_chance", 0.40)
            engagement = self.last_bot_engagement.get(channel_id)
            if engagement:
                if time.time() - engagement["time"] < window:
                    chance = indirect
                    if message.author.id == engagement["user_id"]:
                        chance = indirect * 2.0
                    if random.random() < chance:
                        should_respond = True

        # 3. Counter + response_chance (chattiness)
        if not should_respond:
            goal = self.channel_message_goals[channel_id]
            if self.channel_counters[channel_id] >= goal:
                resp_chance = settings.get("response_chance", 0.15)
                if random.random() < resp_chance:
                    should_respond = True

        # 4. Cooldown check
        if should_respond:
            if channel_id in self.channel_cooldowns:
                elapsed = time.time() - self.channel_cooldowns[channel_id]
                if elapsed < settings["cooldown_seconds"]:
                    should_respond = False

        # --- EXECUTE RESPONSE ---
        if not should_respond:
            return

        trigger_type = "mention" if is_mentioned else (
            "reply" if is_reply_to_bot else "auto"
        )
        print(
            f"[{guild_id}] Triggered ({trigger_type}) "
            f"in #{message.channel.name}"
        )

        # Maybe react with emoji instead of replying
        if random.random() < settings["reaction_chance"]:
            emojis = ["💀", "😭", "🔥", "💯", "🤣", "🙄", "👀", "🫡", "🤨"]
            try:
                await message.add_reaction(random.choice(emojis))
                self._record_response(guild_id, channel_id, "")
                return
            except discord.errors.HTTPException:
                pass

        async with message.channel.typing():
            use_reply = (
                is_mentioned
                or is_reply_to_bot
                or random.random() < settings["random_reply_chance"]
            )
            use_mention = random.random() < settings["random_mention_chance"]
            use_gif = random.random() < settings["gif_chance"]
            final_content = None
            reference = message if use_reply else None

            # --- GIF MODE ---
            if use_gif:
                words = [
                    w for w in message.content.lower().split()
                    if len(w) > 3
                ]
                query = random.choice(words) if words else "meme"
                gif_url = await search_gif(query)
                if gif_url:
                    prefix = f"{message.author.mention} " if use_mention else ""
                    final_content = prefix + gif_url
                else:
                    use_gif = False

            # --- LLM MODE ---
            if not final_content:
                chat_history = []
                prev_msg_time = None

                async for msg in message.channel.history(limit=100):
                    if msg.id == message.id:
                        continue
                    if msg.content.startswith("/") and not msg.attachments:
                        continue

                    # Insert gap marker for long silences
                    if prev_msg_time:
                        gap = prev_msg_time - msg.created_at
                        if gap > timedelta(minutes=30):
                            chat_history.insert(0, {
                                "role": "system",
                                "content": "--- A long time passes ---"
                            })
                    prev_msg_time = msg.created_at

                    clean_msg = re.sub(
                        r'<@!?\d+>', '', msg.content
                    ).strip()
                    clean_msg = re.sub(
                        r'<#\d+>', '', clean_msg
                    ).strip()

                    if msg.author == self.bot.user:
                        chat_history.insert(0, {
                            "role": "assistant",
                            "content": clean_msg
                        })
                    else:
                        payload = self._build_content_payload(
                            msg, clean_msg
                        )
                        if not clean_msg and not msg.attachments:
                            continue
                        chat_history.insert(0, {
                            "role": "user",
                            "content": payload
                        })

                # Append trigger message
                clean_trigger = re.sub(
                    r'<@!?\d+>', '', message.content
                ).strip()
                trigger_payload = self._build_content_payload(
                    message, clean_trigger
                )
                chat_history.append({
                    "role": "user",
                    "content": trigger_payload
                })

                # Enrich with memories
                user_memories = await self.db.get_memories(
                    guild_id, message.author.id
                )
                consolidated = await self.db.get_consolidated_memory(
                    guild_id
                )

                dynamic_prompt = BASE_SECRET_PROMPT
                # Per-server personality override
                custom_personality = settings.get(
                    "personality_prompt", ""
                )
                if custom_personality and custom_personality.strip():
                    dynamic_prompt = custom_personality.strip()
                if consolidated and consolidated.get("summary"):
                    dynamic_prompt += (
                        f"\n\nCONTEXT OF SERVER CULTURE:\n"
                        f"{consolidated['summary']}\n"
                        f"Use this subtly."
                    )
                if user_memories:
                    mem_lines = "\n".join(
                        f"- {m}" for m in user_memories
                    )
                    dynamic_prompt += (
                        f"\n\nDATA LOG — subject: "
                        f"{message.author.display_name}:\n"
                        f"{mem_lines}\n"
                        f"Use this intelligence accordingly."
                    )

                model = settings.get(
                    "llm_model", "meta-llama/llama-3-8b-instruct"
                )
                # Anti-hallucination: tell the LLM it cannot
                # generate images
                dynamic_prompt += (
                    "\n\nIMPORTANT: You CANNOT generate, "
                    "create, or display images. If someone "
                    "asks you to generate an image, tell them "
                    "to use the 'imagine' command instead."
                )
                chat_history.insert(0, {
                    "role": "system",
                    "content": dynamic_prompt,
                    "model": model
                })

                llm_response = await generate_llm_response(
                    dynamic_prompt, chat_history
                )
                if llm_response:
                    # Strip any name prefix the LLM adds
                    llm_response = re.sub(
                        r'^.{0,30}?:\s*', '', llm_response
                    ).strip()
                    llm_response = re.sub(
                        r'<@!?\d+>', '', llm_response
                    ).strip()
                    # Fuzzy dedup check
                    if self._is_duplicate(guild_id, llm_response):
                        print(f"[{guild_id}] Dedup blocked response")
                        llm_response = None
                    if llm_response:
                        base = sanitize_message(llm_response)
                        if use_mention:
                            final_content = f"{message.author.mention} {base}"
                        else:
                            final_content = base
                else:
                    print(f"[{guild_id}] LLM returned None.")

                # Retry with shorter prompt if first call failed
                if not final_content:
                    retry_prompt = RETRY_PROMPT
                    retry_history = [{
                        "role": "system",
                        "content": retry_prompt,
                        "model": model
                    }]
                    # Grab last 10 messages only for retry
                    recent = chat_history[-11:-1]
                    retry_history.extend(recent)
                    retry_response = await generate_llm_response(
                        retry_prompt, retry_history
                    )
                    if retry_response:
                        retry_response = re.sub(
                            r'^.{0,30}?:\s*', '', retry_response
                        ).strip()
                        retry_response = re.sub(
                            r'<@!?\d+>', '', retry_response
                        ).strip()
                        if retry_response:
                            base = sanitize_message(retry_response)
                            if use_mention:
                                final_content = f"{message.author.mention} {base}"
                            else:
                                final_content = base
                    if not final_content:
                        print(f"[{guild_id}] LLM retry also failed.")

            # --- SEND ---
            if final_content:
                try:
                    await message.channel.send(
                        final_content, reference=reference
                    )
                    await self.db.increment_stat(
                        guild_id, "messages_sent"
                    )
                    print(
                        f"[{guild_id}] Responded in "
                        f"#{message.channel.name}"
                    )
                    self.last_bot_engagement[channel_id] = {
                        "time": time.time(),
                        "user_id": message.author.id
                    }
                    self._record_response(
                        guild_id, channel_id, final_content
                    )
                except discord.errors.HTTPException as e:
                    print(f"[{guild_id}] Send error: {e}")


async def setup(bot):
    await bot.add_cog(Chat(bot, bot.db, bot.settings_manager))
