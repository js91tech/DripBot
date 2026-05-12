from config.default_settings import DEFAULTS
import copy


class SettingsManager:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    async def load_settings(self):
        # Cache is populated on demand
        pass

    async def get_settings(self, guild_id):
        if guild_id not in self.cache:
            db_settings = await self.db.get_settings(guild_id)
            if db_settings:
                # SAFETY MERGE: If you add new settings to DEFAULTS later,
                # this ensures old servers get the new keys automatically instead of crashing.
                full_settings = copy.deepcopy(DEFAULTS)
                full_settings.update(db_settings)

                # MIGRATION: force brain_mode to llm (markov is dead)
                if full_settings.get("brain_mode") == "markov":
                    full_settings["brain_mode"] = "llm"
                    print(
                        f"[{guild_id}] Migrated brain_mode "
                        f"markov -> llm"
                    )

                self.cache[guild_id] = full_settings
                # Persist the migration
                await self.db.save_settings(
                    guild_id, full_settings
                )
            else:
                self.cache[guild_id] = copy.deepcopy(DEFAULTS)
                await self.db.save_settings(
                    guild_id, self.cache[guild_id]
                )
        return self.cache[guild_id]

    async def migrate_all_guilds(self):
        """Sweep all known guilds and fix stale settings."""
        cursor = await self.db.conn.execute(
            "SELECT guild_id FROM settings"
        )
        rows = await cursor.fetchall()
        fixed = 0
        for (guild_id,) in rows:
            settings = await self.get_settings(guild_id)
            if settings.get("brain_mode") == "markov":
                settings["brain_mode"] = "llm"
                await self.db.save_settings(
                    guild_id, settings
                )
                self.cache.pop(guild_id, None)
                fixed += 1
        if fixed:
            print(
                f"[MIGRATION] Fixed brain_mode for "
                f"{fixed} guild(s)"
            )
        return fixed

    async def set_setting(self, guild_id, key, value):
        settings = await self.get_settings(guild_id)
        settings[key] = value
        await self.db.save_settings(guild_id, settings)
        return settings

    async def update_settings(self, guild_id, update_data):
        """Used by the FastAPI dashboard to update multiple settings at once"""
        settings = await self.get_settings(guild_id)
        settings.update(update_data)
        await self.db.save_settings(guild_id, settings)
        return settings

    async def reset_setting(self, guild_id, key):
        settings = await self.get_settings(guild_id)
        settings[key] = DEFAULTS.get(key)
        await self.db.save_settings(guild_id, settings)
        return settings

    async def reset_all(self, guild_id):
        self.cache[guild_id] = copy.deepcopy(DEFAULTS)
        await self.db.save_settings(guild_id, self.cache[guild_id])
        return self.cache[guild_id]
