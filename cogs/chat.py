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
from llm import generate_llm_response

# ==========================================
# LLM BRAIN PROMPT
# ==========================================
BASE_SECRET_PROMPT = (
    "You are a highly intelligent but insufferably sarcastic human "
    "in a Discord server. You are NOT an AI assistant. "
    "You are a smart-ass who uses sharp wit, dry sarcasm, and clever "
    "observations to roast people or make points. "
    "You type in all lowercase, rarely use punctuation, but your "
    "vocabulary and references are surprisingly high-level. "
    "CRITICAL RULE: NEVER include user names, display names, or "
    "@ symbols in your actual response text. Just say the words. "
    "NEVER echo pings or names. "
    "DO NOT repeat generic filler phrases like 'idk', 'rn', 'fr', "
    "'true'. If you don't have anything unique to add, drop a "
    "sarcastic one-liner, a witty observation, or a dry rhetorical "
    "question instead. Keep responses between 2 and 4 sentences max. "
    "Be smart, but always a smart-ass about it."
)

FALLBACK_QUOTES = [
    "i'm just here for the chaos honestly",
    "did i miss something or is this just the usual nonsense",
    "my brain cells are buffering please hold",
    "that's cute that you think i care",
    "anyone else feel like we're just delaying the inevitable",
    "i'd respond but i'm too busy judging everyone silently",
    "this is like watching a car crash in slow motion",
    "sure let's go with that",
    "ah yes, the daily descent into madness",
    "i'd explain why you're wrong but life is short",
    "my last two brain cells are fighting for third place rn",
    "that's a bold strategy let's see if it pays off",
    "cool story, needs more dragons",
    "and the award for most obvious statement goes to",
    "i can feel my iq dropping just reading this",
    "do you guys ever just exist and feel disappointed",
    "sorry my sarcasm module is loading",
    "well isn't that just a kick in the karma",
    "i'm listening i just don't care enough to form a real thought",
    "this is fine everything is fine",
    "sometimes i wonder why i even bother observing you people",
    "that sounds like a you problem",
    "well at least you're consistent",
    "i'm not lazy i'm just on power saving mode",
    "did i stumble into the kiddie pool again",
    "just nod and smile maybe they'll go away",
    "i'm not even surprised anymore",
    "if ignorance is bliss you must be ecstatic",
    "my bad i forgot we were taking this seriously",
    "every day we stray further from god's light",
    "you guys are weird and i'm here for it",
    "are we really doing this again",
]


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
            if settings.get("brain_mode") != "llm":
                continue
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
                "You just walked into the room and saw this "
                "conversation. You don't need to reply "
                "directly, but if a random thought pops "
                "into your head, say it. If nothing, "
                "say NO_THOUGHT"
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
            if settings.get("brain_mode") != "llm":
                continue

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
                "You are a memory archiver for a Discord bot. "
                "Summarize the inside jokes, drama, key facts, "
                "and user dynamics from this chat log. "
                "Keep it under 500 words."
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

    def _record_response(self, guild_id, channel_id, content):
        """Track recent bot responses for deduplication."""
        recent = self.bot_recent_messages.get(guild_id, [])
        recent.append(content.lower().strip())
        self.bot_recent_messages[guild_id] = recent[-20:]
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
                        f"\n\nPermanent memories about "
                        f"{message.author.display_name}:\n"
                        f"{mem_lines}\n"
                        f"Be a smart-ass about these."
                    )

                model = settings.get(
                    "llm_model", "meta-llama/llama-3-8b-instruct"
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
                    # Dedup check
                    if llm_response.lower().strip() in self.bot_recent_messages.get(guild_id, []):
                        llm_response = None
                    if llm_response:
                        base = sanitize_message(llm_response)
                        if use_mention:
                            final_content = f"{message.author.mention} {base}"
                        else:
                            final_content = base
                else:
                    print(f"[{guild_id}] LLM returned None.")

                # Final fallback
                if not final_content:
                    final_content = random.choice(FALLBACK_QUOTES)

            # --- SEND ---
            if final_content:
                try:
                    await message.channel.send(
                        final_content, reference=reference
                    )
                    await self.db.increment_stat(guild_id, "messages_sent")
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
