import aiosqlite
import json
import os
import asyncio
import time


class Database:
    def __init__(self):
        self.db_path = "data/bot.db"
        self.conn = None
        self.queue = asyncio.Queue()
        self._worker_task = None

    async def init(self):
        os.makedirs("data", exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS markov (
                                    guild_id INTEGER,
                                    key TEXT,
                                    value TEXT,
                                    PRIMARY KEY (guild_id, key))"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                                    guild_id INTEGER PRIMARY KEY,
                                    settings_json TEXT)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS stats (
                                    guild_id INTEGER PRIMARY KEY,
                                    messages_learned INTEGER DEFAULT 0,
                                    messages_sent INTEGER DEFAULT 0)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                                    guild_id INTEGER,
                                    user_id INTEGER,
                                    note TEXT)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS consolidated_memories (
                                    guild_id INTEGER PRIMARY KEY,
                                    summary_json TEXT)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    user_id INTEGER,
                                    channel_id INTEGER,
                                    message TEXT,
                                    trigger_time REAL)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trivia_questions (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    guild_id INTEGER,
                                    question_type TEXT,
                                    question TEXT,
                                    options_json TEXT,
                                    correct_answer TEXT,
                                    acceptable_answers_json TEXT,
                                    created_by INTEGER DEFAULT 0,
                                    created_at REAL DEFAULT 0)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trivia_scores (
                                    guild_id INTEGER,
                                    user_id INTEGER,
                                    points INTEGER DEFAULT 0,
                                    games_played INTEGER DEFAULT 0,
                                    correct_answers INTEGER DEFAULT 0,
                                    PRIMARY KEY (guild_id, user_id))"""
        )
        await self.conn.commit()
        self._worker_task = asyncio.create_task(self._write_worker())

    async def _write_worker(self):
        while True:
            sql, params = await self.queue.get()
            try:
                await self.conn.execute(sql, params)
                await self.conn.commit()
            except Exception as e:
                print(f"DB Write Error: {e}")
            self.queue.task_done()

    async def get_markov(self, guild_id):
        cursor = await self.conn.execute(
            "SELECT key, value FROM markov WHERE guild_id = ?", (guild_id,)
        )
        rows = await cursor.fetchall()
        chain = {}
        for key, value in rows:
            chain[key] = json.loads(value)
        return chain

    async def save_full_chain(self, guild_id, db_dict):
        await self.queue.put(("DELETE FROM markov WHERE guild_id = ?", (guild_id,)))
        for json_key, values in db_dict.items():
            sql = "INSERT OR REPLACE INTO markov (guild_id, key, value) VALUES (?, ?, ?)"
            params = (guild_id, json_key, json.dumps(values))
            await self.queue.put((sql, params))

    async def get_settings(self, guild_id):
        cursor = await self.conn.execute(
            "SELECT settings_json FROM settings WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def save_settings(self, guild_id, settings_dict):
        sql = "INSERT OR REPLACE INTO settings (guild_id, settings_json) VALUES (?, ?)"
        params = (guild_id, json.dumps(settings_dict))
        await self.queue.put((sql, params))

    VALID_STAT_COLUMNS = {"messages_learned", "messages_sent"}

    async def increment_stat(self, guild_id, column, amount=1):
        if column not in self.VALID_STAT_COLUMNS:
            raise ValueError(f"Invalid stat column: {column}")
        sql = (
            f"INSERT INTO stats (guild_id, {column}) VALUES (?, ?) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {column} = {column} + ?"
        )
        params = (guild_id, amount, amount)
        await self.queue.put((sql, params))

    async def get_stats(self, guild_id):
        cursor = await self.conn.execute(
            "SELECT messages_learned, messages_sent FROM stats WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        return (
            {"messages_learned": row[0], "messages_sent": row[1]}
            if row
            else {"messages_learned": 0, "messages_sent": 0}
        )

    async def delete_guild_data(self, guild_id):
        await self.queue.put(("DELETE FROM markov WHERE guild_id = ?", (guild_id,)))
        await self.queue.put(("DELETE FROM settings WHERE guild_id = ?", (guild_id,)))
        await self.queue.put(("DELETE FROM stats WHERE guild_id = ?", (guild_id,)))
        await self.queue.put(("DELETE FROM memories WHERE guild_id = ?", (guild_id,)))
        await self.queue.put(
            ("DELETE FROM consolidated_memories WHERE guild_id = ?", (guild_id,))
        )
        await self.queue.put(("DELETE FROM trivia_questions WHERE guild_id = ?", (guild_id,)))
        await self.queue.put(("DELETE FROM trivia_scores WHERE guild_id = ?", (guild_id,)))

    async def add_memory(self, guild_id, user_id, note, limit: int = 12):
        """Store a short per-user memory, skipping near-duplicates and capping count."""
        note = (note or "").strip()
        if not note:
            return False
        existing = await self.get_memories(guild_id, user_id)
        note_l = note.lower()
        for prev in existing:
            prev_l = (prev or "").lower()
            if note_l == prev_l or note_l in prev_l or prev_l in note_l:
                return False
        sql = "INSERT INTO memories (guild_id, user_id, note) VALUES (?, ?, ?)"
        await self.queue.put((sql, (guild_id, user_id, note[:240])))
        if len(existing) + 1 > limit:
            # Drop oldest extras (table has no id/timestamp; delete then reinsert newest)
            keep = (existing + [note[:240]])[-limit:]
            await self.queue.put(
                ("DELETE FROM memories WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            )
            for item in keep:
                await self.queue.put(
                    (
                        "INSERT INTO memories (guild_id, user_id, note) VALUES (?, ?, ?)",
                        (guild_id, user_id, item),
                    )
                )
        return True

    async def get_memories(self, guild_id, user_id):
        cursor = await self.conn.execute(
            "SELECT note FROM memories WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def forget_memories(self, guild_id, user_id):
        await self.queue.put(
            ("DELETE FROM memories WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        )

    async def get_consolidated_memory(self, guild_id):
        cursor = await self.conn.execute(
            "SELECT summary_json FROM consolidated_memories WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def save_consolidated_memory(self, guild_id, summary):
        sql = "INSERT OR REPLACE INTO consolidated_memories (guild_id, summary_json) VALUES (?, ?)"
        params = (guild_id, json.dumps(summary))
        await self.queue.put((sql, params))

    async def add_reminder(self, user_id, channel_id, message, trigger_time):
        sql = "INSERT INTO reminders (user_id, channel_id, message, trigger_time) VALUES (?, ?, ?, ?)"
        params = (user_id, channel_id, message, trigger_time)
        await self.queue.put((sql, params))

    async def get_pending_reminders(self, current_time):
        cursor = await self.conn.execute(
            "SELECT id, user_id, channel_id, message, trigger_time FROM reminders WHERE trigger_time <= ?",
            (current_time,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "user_id": row[1],
                "channel_id": row[2],
                "message": row[3],
                "trigger_time": row[4],
            }
            for row in rows
        ]

    async def delete_reminder(self, reminder_id):
        await self.queue.put(("DELETE FROM reminders WHERE id = ?", (reminder_id,)))

    async def flush(self):
        """Wait for any queued writes to complete."""
        await self.queue.join()

    # ═══════════════════════════════════════════════════════════════
    #  Trivia Operations
    # ═══════════════════════════════════════════════════════════════

    async def add_trivia_question(
        self,
        guild_id: int,
        question_type: str,
        question: str,
        options: list = None,
        correct_answer: str = "",
        acceptable_answers: list = None,
        created_by: int = 0,
    ) -> int:
        """Add a custom trivia question for a guild and return its generated ID."""
        options_json = json.dumps(options or [])
        acceptable_json = json.dumps(acceptable_answers or [])
        now = time.time()
        cursor = await self.conn.execute(
            """INSERT INTO trivia_questions 
               (guild_id, question_type, question, options_json, correct_answer, acceptable_answers_json, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                guild_id,
                question_type,
                question,
                options_json,
                correct_answer,
                acceptable_json,
                created_by,
                now,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_trivia_questions(self, guild_id: int, question_type: str = None) -> list:
        """Retrieve all custom trivia questions for a guild, optionally filtered by type."""
        if question_type:
            cursor = await self.conn.execute(
                """SELECT id, guild_id, question_type, question, options_json, correct_answer, acceptable_answers_json, created_by, created_at
                   FROM trivia_questions WHERE guild_id = ? AND question_type = ? ORDER BY id ASC""",
                (guild_id, question_type),
            )
        else:
            cursor = await self.conn.execute(
                """SELECT id, guild_id, question_type, question, options_json, correct_answer, acceptable_answers_json, created_by, created_at
                   FROM trivia_questions WHERE guild_id = ? ORDER BY id ASC""",
                (guild_id,),
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "guild_id": row[1],
                "question_type": row[2],
                "question": row[3],
                "options": json.loads(row[4]) if row[4] else [],
                "correct_answer": row[5],
                "acceptable_answers": json.loads(row[6]) if row[6] else [],
                "created_by": row[7],
                "created_at": row[8],
            })
        return results

    async def get_trivia_question_by_id(self, guild_id: int, question_id: int) -> dict:
        """Retrieve a single trivia question by guild ID and question ID."""
        cursor = await self.conn.execute(
            """SELECT id, guild_id, question_type, question, options_json, correct_answer, acceptable_answers_json, created_by, created_at
               FROM trivia_questions WHERE guild_id = ? AND id = ?""",
            (guild_id, question_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "guild_id": row[1],
            "question_type": row[2],
            "question": row[3],
            "options": json.loads(row[4]) if row[4] else [],
            "correct_answer": row[5],
            "acceptable_answers": json.loads(row[6]) if row[6] else [],
            "created_by": row[7],
            "created_at": row[8],
        }

    async def delete_trivia_question(self, guild_id: int, question_id: int) -> bool:
        """Delete a single trivia question by ID."""
        cursor = await self.conn.execute(
            "DELETE FROM trivia_questions WHERE guild_id = ? AND id = ?",
            (guild_id, question_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def clear_trivia_questions(self, guild_id: int) -> int:
        """Delete all custom trivia questions for a guild."""
        cursor = await self.conn.execute(
            "DELETE FROM trivia_questions WHERE guild_id = ?",
            (guild_id,),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def update_trivia_score(
        self,
        guild_id: int,
        user_id: int,
        points: int = 10,
        correct_answers: int = 1,
        games_played: int = 0,
    ):
        """Update trivia leaderboard stats for a user."""
        await self.conn.execute(
            """INSERT INTO trivia_scores (guild_id, user_id, points, games_played, correct_answers)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   points = points + ?,
                   games_played = games_played + ?,
                   correct_answers = correct_answers + ?""",
            (
                guild_id,
                user_id,
                points,
                games_played,
                correct_answers,
                points,
                games_played,
                correct_answers,
            ),
        )
        await self.conn.commit()

    async def record_trivia_games_played(self, guild_id: int, user_ids: list):
        """Increment games_played for participants."""
        for user_id in user_ids:
            await self.conn.execute(
                """INSERT INTO trivia_scores (guild_id, user_id, points, games_played, correct_answers)
                   VALUES (?, ?, 0, 1, 0)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET
                       games_played = games_played + 1""",
                (guild_id, user_id),
            )
        await self.conn.commit()

    async def get_trivia_leaderboard(self, guild_id: int, limit: int = 10) -> list:
        """Get top trivia scores for a guild."""
        cursor = await self.conn.execute(
            """SELECT user_id, points, games_played, correct_answers
               FROM trivia_scores
               WHERE guild_id = ?
               ORDER BY points DESC, correct_answers DESC
               LIMIT ?""",
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "points": row[1],
                "games_played": row[2],
                "correct_answers": row[3],
            }
            for row in rows
        ]

    async def reset_trivia_scores(self, guild_id: int):
        """Reset the trivia leaderboard for a guild."""
        cursor = await self.conn.execute(
            "DELETE FROM trivia_scores WHERE guild_id = ?",
            (guild_id,),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def close(self):
        if self._worker_task:
            self._worker_task.cancel()
        if self.conn:
            await self.conn.close()
