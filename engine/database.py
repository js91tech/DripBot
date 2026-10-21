import aiosqlite
import json
import os
import asyncio


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
                                    qtype TEXT,
                                    question TEXT,
                                    options_json TEXT,
                                    answer TEXT,
                                    answer_index INTEGER,
                                    alternates_json TEXT,
                                    created_by INTEGER,
                                    created_at REAL)"""
        )
        await self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trivia_scores (
                                    guild_id INTEGER,
                                    user_id INTEGER,
                                    points INTEGER DEFAULT 0,
                                    wins INTEGER DEFAULT 0,
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

    # ── Trivia ──

    async def add_trivia_question(self, guild_id, qtype, question, options,
                                  answer, answer_index=None, alternates=None,
                                  created_by=0):
        import time as _time

        cursor = await self.conn.execute(
            """INSERT INTO trivia_questions
               (guild_id, qtype, question, options_json, answer, answer_index,
                alternates_json, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                guild_id,
                qtype,
                question,
                json.dumps(options or []),
                str(answer),
                answer_index,
                json.dumps(alternates or []),
                created_by,
                _time.time(),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid

    def _trivia_row_to_dict(self, row):
        qid, guild_id, qtype, question, options_json, answer, answer_index, alternates_json, created_by = row
        try:
            options = json.loads(options_json or "[]")
        except (TypeError, ValueError):
            options = []
        try:
            alternates = json.loads(alternates_json or "[]")
        except (TypeError, ValueError):
            alternates = []
        parsed_answer = answer
        if qtype == "true_false":
            parsed_answer = str(answer).strip().lower() in ("1", "true", "t", "yes", "y")
        return {
            "id": qid,
            "guild_id": guild_id,
            "qtype": qtype,
            "question": question,
            "options": options,
            "answer": parsed_answer if qtype == "true_false" else answer,
            "answer_index": answer_index,
            "alternates": alternates,
            "created_by": created_by,
        }

    async def get_trivia_questions(self, guild_id, qtype=None):
        if qtype:
            cursor = await self.conn.execute(
                "SELECT id, guild_id, qtype, question, options_json, answer,"
                " answer_index, alternates_json, created_by"
                " FROM trivia_questions WHERE guild_id = ? AND qtype = ? ORDER BY id",
                (guild_id, qtype),
            )
        else:
            cursor = await self.conn.execute(
                "SELECT id, guild_id, qtype, question, options_json, answer,"
                " answer_index, alternates_json, created_by"
                " FROM trivia_questions WHERE guild_id = ? ORDER BY id",
                (guild_id,),
            )
        rows = await cursor.fetchall()
        return [self._trivia_row_to_dict(row) for row in rows]

    async def count_trivia_questions(self, guild_id):
        cursor = await self.conn.execute(
            "SELECT qtype, COUNT(*) FROM trivia_questions WHERE guild_id = ? GROUP BY qtype",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        counts = {"multiple_choice": 0, "true_false": 0, "open": 0, "total": 0}
        for qtype, count in rows:
            counts[qtype] = count
            counts["total"] += count
        return counts

    async def delete_trivia_question(self, guild_id, question_id):
        cursor = await self.conn.execute(
            "DELETE FROM trivia_questions WHERE guild_id = ? AND id = ?",
            (guild_id, question_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def clear_trivia_questions(self, guild_id, qtype=None):
        if qtype:
            cursor = await self.conn.execute(
                "DELETE FROM trivia_questions WHERE guild_id = ? AND qtype = ?",
                (guild_id, qtype),
            )
        else:
            cursor = await self.conn.execute(
                "DELETE FROM trivia_questions WHERE guild_id = ?",
                (guild_id,),
            )
        await self.conn.commit()
        return cursor.rowcount

    async def add_trivia_points(self, guild_id, user_id, points=1):
        sql = (
            "INSERT INTO trivia_scores (guild_id, user_id, points, wins) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET points = points + ?"
        )
        await self.conn.execute(sql, (guild_id, user_id, points, points))
        await self.conn.commit()

    async def add_trivia_win(self, guild_id, user_id):
        sql = (
            "INSERT INTO trivia_scores (guild_id, user_id, points, wins) VALUES (?, ?, 0, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET wins = wins + 1"
        )
        await self.conn.execute(sql, (guild_id, user_id))
        await self.conn.commit()

    async def get_trivia_leaderboard(self, guild_id, limit=10):
        cursor = await self.conn.execute(
            "SELECT user_id, points, wins FROM trivia_scores"
            " WHERE guild_id = ? ORDER BY points DESC, wins DESC LIMIT ?",
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
        return [{"user_id": row[0], "points": row[1], "wins": row[2]} for row in rows]

    async def get_trivia_score(self, guild_id, user_id):
        cursor = await self.conn.execute(
            "SELECT points, wins FROM trivia_scores WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        if row:
            return {"points": row[0], "wins": row[1]}
        return {"points": 0, "wins": 0}

    async def close(self):
        if self._worker_task:
            self._worker_task.cancel()
        if self.conn:
            await self.conn.close()
