"""Trivia question model, answer checking, and per-guild storage."""

import json
import random
import re
import string
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional

MULTIPLE_CHOICE = "mc"
TRUE_FALSE = "tf"
OPEN_ENDED = "open"
QUESTION_TYPES = (MULTIPLE_CHOICE, TRUE_FALSE, OPEN_ENDED)

TYPE_LABELS = {
    MULTIPLE_CHOICE: "Multiple Choice",
    TRUE_FALSE: "True / False",
    OPEN_ENDED: "Open Ended",
}

MAX_QUESTION_LEN = 300
MAX_ANSWER_LEN = 100
MIN_CHOICES = 2
MAX_CHOICES = 4

_ARTICLES = {"a", "an", "the"}
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


class TriviaError(ValueError):
    """Raised for invalid trivia input; the message is safe to show to users."""


@dataclass
class TriviaQuestion:
    id: int
    guild_id: int
    qtype: str
    question: str
    answer: str
    choices: List[str] = field(default_factory=list)
    alt_answers: List[str] = field(default_factory=list)
    author_id: int = 0

    @property
    def label(self) -> str:
        return TYPE_LABELS.get(self.qtype, self.qtype)


def normalize_answer(text: str) -> str:
    """Lowercase, strip accents/punctuation/articles and collapse whitespace."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().translate(_PUNCT_TABLE)
    words = [w for w in re.split(r"\s+", text.strip()) if w and w not in _ARTICLES]
    return " ".join(words)


def check_open_answer(guess: str, answer: str, alt_answers: Optional[List[str]] = None) -> bool:
    """Case/punctuation-insensitive match with light typo tolerance."""
    guess_n = normalize_answer(guess)
    if not guess_n:
        return False
    for candidate in [answer] + list(alt_answers or []):
        cand_n = normalize_answer(candidate)
        if not cand_n:
            continue
        if guess_n == cand_n:
            return True
        # Typo tolerance only for reasonably long answers so short ones stay exact.
        if len(cand_n) >= 6 and SequenceMatcher(None, guess_n, cand_n).ratio() >= 0.88:
            return True
    return False


def parse_alt_answers(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,;|]", raw)]
    return [p for p in parts if p][:10]


def build_multiple_choice(question: str, correct: str, wrong: List[str]) -> dict:
    question = _clean_question(question)
    correct = _clean_answer(correct)
    wrong_clean = []
    for w in wrong:
        w = (w or "").strip()
        if w:
            wrong_clean.append(_clean_answer(w))
    if len(wrong_clean) < MIN_CHOICES - 1:
        raise TriviaError("Multiple choice needs the correct answer plus at least 1 wrong answer.")
    if len(wrong_clean) > MAX_CHOICES - 1:
        raise TriviaError(f"Multiple choice supports at most {MAX_CHOICES} options total.")
    seen = {normalize_answer(correct)}
    for w in wrong_clean:
        key = normalize_answer(w)
        if key in seen:
            raise TriviaError("All answer options must be different from each other.")
        seen.add(key)
    return {
        "qtype": MULTIPLE_CHOICE,
        "question": question,
        "answer": correct,
        "choices": [correct] + wrong_clean,
        "alt_answers": [],
    }


def build_true_false(question: str, answer: bool) -> dict:
    return {
        "qtype": TRUE_FALSE,
        "question": _clean_question(question),
        "answer": "True" if answer else "False",
        "choices": [],
        "alt_answers": [],
    }


def build_open_ended(question: str, answer: str, alt_answers: Optional[str] = None) -> dict:
    return {
        "qtype": OPEN_ENDED,
        "question": _clean_question(question),
        "answer": _clean_answer(answer),
        "choices": [],
        "alt_answers": parse_alt_answers(alt_answers),
    }


def _clean_question(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise TriviaError("The question can't be empty.")
    if len(text) > MAX_QUESTION_LEN:
        raise TriviaError(f"Questions can be at most {MAX_QUESTION_LEN} characters.")
    return text


def _clean_answer(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise TriviaError("The answer can't be empty.")
    if len(text) > MAX_ANSWER_LEN:
        raise TriviaError(f"Answers can be at most {MAX_ANSWER_LEN} characters.")
    return text


def pick_questions(
    pool: List[TriviaQuestion], counts: dict, rng: Optional[random.Random] = None
) -> List[TriviaQuestion]:
    """Pick up to counts[type] random questions of each type, in MC -> TF -> open order."""
    rng = rng or random
    picked: List[TriviaQuestion] = []
    for qtype in QUESTION_TYPES:
        wanted = max(0, int(counts.get(qtype, 0)))
        of_type = [q for q in pool if q.qtype == qtype]
        rng.shuffle(of_type)
        picked.extend(of_type[:wanted])
    return picked


def _row_to_question(row) -> TriviaQuestion:
    return TriviaQuestion(
        id=row[0],
        guild_id=row[1],
        qtype=row[2],
        question=row[3],
        answer=row[4],
        choices=json.loads(row[5] or "[]"),
        alt_answers=json.loads(row[6] or "[]"),
        author_id=row[7] or 0,
    )


_COLUMNS = "id, guild_id, qtype, question, answer, choices_json, alt_json, author_id"

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS trivia_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        qtype TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        choices_json TEXT NOT NULL DEFAULT '[]',
        alt_json TEXT NOT NULL DEFAULT '[]',
        author_id INTEGER)""",
    """CREATE TABLE IF NOT EXISTS trivia_scores (
        guild_id INTEGER,
        user_id INTEGER,
        points INTEGER DEFAULT 0,
        correct INTEGER DEFAULT 0,
        games INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id))""",
)


class TriviaStore:
    """Async storage on top of an open aiosqlite connection."""

    def __init__(self, conn):
        self.conn = conn

    async def ensure_schema(self):
        for stmt in SCHEMA:
            await self.conn.execute(stmt)
        await self.conn.commit()

    async def add_question(self, guild_id: int, author_id: int, data: dict) -> TriviaQuestion:
        cursor = await self.conn.execute(
            "INSERT INTO trivia_questions "
            "(guild_id, qtype, question, answer, choices_json, alt_json, author_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                data["qtype"],
                data["question"],
                data["answer"],
                json.dumps(data.get("choices", [])),
                json.dumps(data.get("alt_answers", [])),
                author_id,
            ),
        )
        await self.conn.commit()
        return TriviaQuestion(
            id=cursor.lastrowid,
            guild_id=guild_id,
            qtype=data["qtype"],
            question=data["question"],
            answer=data["answer"],
            choices=list(data.get("choices", [])),
            alt_answers=list(data.get("alt_answers", [])),
            author_id=author_id,
        )

    async def list_questions(self, guild_id: int, qtype: Optional[str] = None) -> List[TriviaQuestion]:
        sql = f"SELECT {_COLUMNS} FROM trivia_questions WHERE guild_id = ?"
        params = [guild_id]
        if qtype:
            sql += " AND qtype = ?"
            params.append(qtype)
        sql += " ORDER BY id"
        cursor = await self.conn.execute(sql, params)
        return [_row_to_question(r) for r in await cursor.fetchall()]

    async def get_question(self, guild_id: int, question_id: int) -> Optional[TriviaQuestion]:
        cursor = await self.conn.execute(
            f"SELECT {_COLUMNS} FROM trivia_questions WHERE guild_id = ? AND id = ?",
            (guild_id, question_id),
        )
        row = await cursor.fetchone()
        return _row_to_question(row) if row else None

    async def remove_question(self, guild_id: int, question_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM trivia_questions WHERE guild_id = ? AND id = ?",
            (guild_id, question_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def clear_questions(self, guild_id: int, qtype: Optional[str] = None) -> int:
        if qtype:
            cursor = await self.conn.execute(
                "DELETE FROM trivia_questions WHERE guild_id = ? AND qtype = ?",
                (guild_id, qtype),
            )
        else:
            cursor = await self.conn.execute(
                "DELETE FROM trivia_questions WHERE guild_id = ?", (guild_id,)
            )
        await self.conn.commit()
        return cursor.rowcount

    async def count_by_type(self, guild_id: int) -> dict:
        cursor = await self.conn.execute(
            "SELECT qtype, COUNT(*) FROM trivia_questions WHERE guild_id = ? GROUP BY qtype",
            (guild_id,),
        )
        counts = {t: 0 for t in QUESTION_TYPES}
        for qtype, n in await cursor.fetchall():
            counts[qtype] = n
        return counts

    async def record_game(self, guild_id: int, results: dict):
        """results: {user_id: (points, correct_answers)} for one finished game."""
        for user_id, (points, correct) in results.items():
            await self.conn.execute(
                "INSERT INTO trivia_scores (guild_id, user_id, points, correct, games) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "points = points + excluded.points, "
                "correct = correct + excluded.correct, "
                "games = games + 1",
                (guild_id, user_id, points, correct),
            )
        await self.conn.commit()

    async def leaderboard(self, guild_id: int, limit: int = 10):
        cursor = await self.conn.execute(
            "SELECT user_id, points, correct, games FROM trivia_scores "
            "WHERE guild_id = ? ORDER BY points DESC, correct DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cursor.fetchall()
