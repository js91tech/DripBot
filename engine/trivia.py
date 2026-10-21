"""
engine/trivia.py — Trivia Game Engine & Question Management
Supports Multiple Choice, True/False, and Open-Ended questions.
Admins can manage custom questions per server, with built-in default questions.
"""

import asyncio
import difflib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("dripsletongue.trivia")

# ── Question Type Constants ──
MULTIPLE_CHOICE = "multiple_choice"
TRUE_FALSE = "true_false"
OPEN_ENDED = "open_ended"

VALID_QUESTION_TYPES = {MULTIPLE_CHOICE, TRUE_FALSE, OPEN_ENDED}

TYPE_LABELS = {
    MULTIPLE_CHOICE: "Multiple Choice",
    TRUE_FALSE: "True or False",
    OPEN_ENDED: "Open-Ended",
}


def normalize_question_type(val: Optional[str]) -> Optional[str]:
    """Normalize various user-provided type aliases into canonical question types."""
    if not val:
        return None
    raw = str(val).strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"mc", "multiple_choice", "multiplechoice", "multiple", "choice"}:
        return MULTIPLE_CHOICE
    if raw in {"tf", "true_false", "truefalse", "true_or_false", "boolean", "bool"}:
        return TRUE_FALSE
    if raw in {"open", "open_ended", "openended", "text", "free", "open_answer"}:
        return OPEN_ENDED
    return None


def clean_text(s: str) -> str:
    """Normalize text for open-ended matching: lowercase, strip punctuation and extra spaces."""
    if not s:
        return ""
    # Lowercase and strip
    text = str(s).strip().lower()
    # Remove leading common articles
    text = re.sub(r"^(the|a|an)\s+", "", text)
    # Remove punctuation characters
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse multiple spaces
    text = " ".join(text.split())
    return text


@dataclass
class TriviaQuestion:
    """Represents a single trivia question."""

    id: Optional[int] = None
    guild_id: int = 0
    question_type: str = MULTIPLE_CHOICE
    question: str = ""
    options: List[str] = field(default_factory=list)
    correct_answer: str = ""
    acceptable_answers: List[str] = field(default_factory=list)
    created_by: int = 0
    created_at: float = 0.0
    is_default: bool = False

    def get_correct_option_index(self) -> Optional[int]:
        """For multiple choice questions, find the 0-based index of the correct option."""
        if self.question_type != MULTIPLE_CHOICE or not self.options:
            return None

        # Check if correct_answer is a letter (A, B, C, D...)
        ans_upper = self.correct_answer.strip().upper()
        if len(ans_upper) == 1 and "A" <= ans_upper <= "Z":
            idx = ord(ans_upper) - ord("A")
            if 0 <= idx < len(self.options):
                return idx

        # Check if correct_answer is a 1-based number string ("1", "2"...)
        if ans_upper.isdigit():
            idx = int(ans_upper) - 1
            if 0 <= idx < len(self.options):
                return idx

        # Check against option texts
        clean_ans = clean_text(self.correct_answer)
        for i, opt in enumerate(self.options):
            if clean_text(opt) == clean_ans:
                return i

        return None

    def get_formatted_choices(self) -> List[Tuple[str, str]]:
        """Return list of (Letter, OptionText) pairs for display."""
        if self.question_type == TRUE_FALSE:
            return [("True", "True"), ("False", "False")]

        letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
        pairs = []
        for i, opt in enumerate(self.options):
            letter = letters[i] if i < len(letters) else str(i + 1)
            pairs.append((letter, opt))
        return pairs

    def check_answer(self, user_input: str) -> bool:
        """
        Evaluate if a user's answer is correct.
        Supports button letters, numbers, full text, T/F, and fuzzy open-ended matching.
        """
        if not user_input:
            return False

        clean_user = clean_text(user_input)
        if not clean_user:
            return False

        if self.question_type == MULTIPLE_CHOICE:
            correct_idx = self.get_correct_option_index()
            if correct_idx is None:
                # Fallback to direct match if no options defined
                return clean_user == clean_text(self.correct_answer)

            # 1. Letter match ("a", "A", "b"...)
            raw_upper = user_input.strip().upper()
            if len(raw_upper) in {1, 2} and raw_upper[0] in "ABCDEFGH":
                user_idx = ord(raw_upper[0]) - ord("A")
                return user_idx == correct_idx

            # 2. Number match ("1", "2"...)
            if raw_upper.isdigit():
                user_idx = int(raw_upper) - 1
                return user_idx == correct_idx

            # 3. Match against the correct option text
            correct_opt = self.options[correct_idx]
            if clean_user == clean_text(correct_opt):
                return True

            # 4. Check if user typed "A) <text>"
            prefix_match = re.match(r"^([a-h])[\)\.\:\-\s]+(.*)$", user_input.strip(), re.IGNORECASE)
            if prefix_match:
                letter = prefix_match.group(1).upper()
                if ord(letter) - ord("A") == correct_idx:
                    return True

            return False

        elif self.question_type == TRUE_FALSE:
            # Expected truthiness
            ans_clean = self.correct_answer.strip().lower()
            expected_bool = ans_clean in {"true", "t", "yes", "y", "1"}

            # User truthiness
            raw_clean = user_input.strip().lower()
            if raw_clean in {"true", "t", "yes", "y", "1"}:
                return expected_bool is True
            elif raw_clean in {"false", "f", "no", "n", "0"}:
                return expected_bool is False
            return False

        elif self.question_type == OPEN_ENDED:
            # Target answers: correct_answer + acceptable_answers
            targets = [self.correct_answer] + list(self.acceptable_answers or [])
            clean_targets = [clean_text(t) for t in targets if t]

            # 1. Exact normalized match
            if clean_user in clean_targets:
                return True

            # 2. Check if clean_user matches any target without article
            for target in clean_targets:
                if clean_user == target:
                    return True

                # If numeric or very short (<4 chars), must be exact match
                if target.isdigit() or len(target) < 4:
                    continue

                # Fuzzy match for minor typos (e.g. "leonardo da vinci" vs "lenardo da vinci")
                sim = difflib.SequenceMatcher(None, clean_user, target).ratio()
                if sim >= 0.88:
                    return True

            return False

        return False

    def get_display_answer(self) -> str:
        """Return a human-readable display of the correct answer."""
        if self.question_type == MULTIPLE_CHOICE:
            idx = self.get_correct_option_index()
            if idx is not None and 0 <= idx < len(self.options):
                letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
                letter = letters[idx] if idx < len(letters) else str(idx + 1)
                return f"**{letter}) {self.options[idx]}**"
            return f"**{self.correct_answer}**"

        elif self.question_type == TRUE_FALSE:
            is_true = self.correct_answer.strip().lower() in {"true", "t", "yes", "1"}
            return "**True**" if is_true else "**False**"

        elif self.question_type == OPEN_ENDED:
            ans = f"**{self.correct_answer}**"
            if self.acceptable_answers:
                extra = ", ".join(f"`{a}`" for a in self.acceptable_answers if clean_text(a) != clean_text(self.correct_answer))
                if extra:
                    ans += f" *(also accepts: {extra})*"
            return ans

        return f"**{self.correct_answer}**"


# ═══════════════════════════════════════════════════════════════
#  Default Question Bank: 5 MC, 5 TF, 5 Open-Ended
# ═══════════════════════════════════════════════════════════════

DEFAULT_QUESTIONS: List[TriviaQuestion] = [
    # ── 5 Multiple Choice ──
    TriviaQuestion(
        id=-1,
        guild_id=0,
        question_type=MULTIPLE_CHOICE,
        question="Which planet in our solar system is known as the Red Planet?",
        options=["Mars", "Venus", "Jupiter", "Mercury"],
        correct_answer="Mars",
        is_default=True,
    ),
    TriviaQuestion(
        id=-2,
        guild_id=0,
        question_type=MULTIPLE_CHOICE,
        question="What is the powerhouse of the cell?",
        options=["Mitochondria", "Nucleus", "Ribosome", "Chloroplast"],
        correct_answer="Mitochondria",
        is_default=True,
    ),
    TriviaQuestion(
        id=-3,
        guild_id=0,
        question_type=MULTIPLE_CHOICE,
        question="Which programming language was created by Guido van Rossum?",
        options=["Python", "JavaScript", "Rust", "Go"],
        correct_answer="Python",
        is_default=True,
    ),
    TriviaQuestion(
        id=-4,
        guild_id=0,
        question_type=MULTIPLE_CHOICE,
        question="How many elements are currently in the periodic table?",
        options=["118", "108", "120", "92"],
        correct_answer="118",
        is_default=True,
    ),
    TriviaQuestion(
        id=-5,
        guild_id=0,
        question_type=MULTIPLE_CHOICE,
        question="Which ocean is the largest on Earth?",
        options=["Pacific Ocean", "Atlantic Ocean", "Indian Ocean", "Arctic Ocean"],
        correct_answer="Pacific Ocean",
        is_default=True,
    ),

    # ── 5 True or False ──
    TriviaQuestion(
        id=-6,
        guild_id=0,
        question_type=TRUE_FALSE,
        question="Lightning never strikes the same place twice.",
        options=["True", "False"],
        correct_answer="False",
        is_default=True,
    ),
    TriviaQuestion(
        id=-7,
        guild_id=0,
        question_type=TRUE_FALSE,
        question="Sound travels faster in water than in air.",
        options=["True", "False"],
        correct_answer="True",
        is_default=True,
    ),
    TriviaQuestion(
        id=-8,
        guild_id=0,
        question_type=TRUE_FALSE,
        question="Sharks are classified as mammals.",
        options=["True", "False"],
        correct_answer="False",
        is_default=True,
    ),
    TriviaQuestion(
        id=-9,
        guild_id=0,
        question_type=TRUE_FALSE,
        question="A day on Venus is longer than a year on Venus.",
        options=["True", "False"],
        correct_answer="True",
        is_default=True,
    ),
    TriviaQuestion(
        id=-10,
        guild_id=0,
        question_type=TRUE_FALSE,
        question="The Great Wall of China is visible from space with the naked eye.",
        options=["True", "False"],
        correct_answer="False",
        is_default=True,
    ),

    # ── 5 Open-Ended ──
    TriviaQuestion(
        id=-11,
        guild_id=0,
        question_type=OPEN_ENDED,
        question="What is the chemical symbol for gold?",
        correct_answer="Au",
        acceptable_answers=["Au", "gold"],
        is_default=True,
    ),
    TriviaQuestion(
        id=-12,
        guild_id=0,
        question_type=OPEN_ENDED,
        question="Who painted the Mona Lisa?",
        correct_answer="Leonardo da Vinci",
        acceptable_answers=["Leonardo da Vinci", "da Vinci", "Leonardo"],
        is_default=True,
    ),
    TriviaQuestion(
        id=-13,
        guild_id=0,
        question_type=OPEN_ENDED,
        question="What is the hardest natural substance on Earth?",
        correct_answer="Diamond",
        acceptable_answers=["Diamond", "Diamonds"],
        is_default=True,
    ),
    TriviaQuestion(
        id=-14,
        guild_id=0,
        question_type=OPEN_ENDED,
        question="Which gas do plants absorb from the atmosphere during photosynthesis?",
        correct_answer="Carbon dioxide",
        acceptable_answers=["Carbon dioxide", "CO2", "Carbon Dioxide", "carbon-dioxide"],
        is_default=True,
    ),
    TriviaQuestion(
        id=-15,
        guild_id=0,
        question_type=OPEN_ENDED,
        question="In what year did the Apollo 11 mission land humans on the Moon?",
        correct_answer="1969",
        acceptable_answers=["1969", "'69"],
        is_default=True,
    ),
]


# ═══════════════════════════════════════════════════════════════
#  Trivia Game Session
# ═══════════════════════════════════════════════════════════════

class TriviaSession:
    """Manages an active trivia game session in a channel."""

    def __init__(
        self,
        guild_id: int,
        channel_id: int,
        questions: List[TriviaQuestion],
        timeout_seconds: int = 30,
        points_per_question: int = 10,
        started_by: int = 0,
    ):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.questions = questions
        self.timeout_seconds = timeout_seconds
        self.points_per_question = points_per_question
        self.started_by = started_by

        self.current_index = 0
        self.scores: Dict[int, int] = {}
        self.user_names: Dict[int, str] = {}
        self.correct_counts: Dict[int, int] = {}

        self.is_active = True
        self.question_answered = False
        self.winner_id: Optional[int] = None
        self.winner_name: Optional[str] = None
        self.points_awarded: int = 0

        self.answer_event = asyncio.Event()
        self.question_start_time: float = 0.0
        self.active_message_id: Optional[int] = None
        self.current_view = None
        self.game_task: Optional[asyncio.Task] = None

    @property
    def current_question(self) -> Optional[TriviaQuestion]:
        if 0 <= self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None

    @property
    def total_questions(self) -> int:
        return len(self.questions)

    def is_finished(self) -> bool:
        return not self.is_active or self.current_index >= len(self.questions)

    def record_correct_answer(self, user_id: int, user_name: str) -> int:
        """Mark the current question as answered correctly by a user."""
        if self.question_answered:
            return 0

        self.question_answered = True
        self.winner_id = user_id
        self.winner_name = user_name

        # Calculate score (base points + small speed bonus if answered within first 20% of time)
        elapsed = time.time() - self.question_start_time
        speed_bonus = 0
        if elapsed <= (self.timeout_seconds * 0.25):
            speed_bonus = 5
        elif elapsed <= (self.timeout_seconds * 0.50):
            speed_bonus = 2

        points = self.points_per_question + speed_bonus
        self.points_awarded = points

        self.scores[user_id] = self.scores.get(user_id, 0) + points
        self.correct_counts[user_id] = self.correct_counts.get(user_id, 0) + 1
        self.user_names[user_id] = user_name

        self.answer_event.set()
        return points

    def record_timeout(self):
        """Mark the current question as timed out."""
        if self.question_answered:
            return
        self.question_answered = True
        self.winner_id = None
        self.winner_name = None
        self.points_awarded = 0
        self.answer_event.set()

    def advance_to_next_question(self) -> Optional[TriviaQuestion]:
        """Move to the next question in the session."""
        self.current_index += 1
        self.question_answered = False
        self.winner_id = None
        self.winner_name = None
        self.points_awarded = 0
        self.answer_event.clear()
        self.question_start_time = time.time()
        return self.current_question

    def stop(self):
        """Halt the session."""
        self.is_active = False
        self.answer_event.set()

    def get_standings(self) -> List[Tuple[int, str, int, int]]:
        """Return standings as a list of (user_id, display_name, score, correct_count) descending."""
        standings = [
            (uid, self.user_names.get(uid, f"User {uid}"), score, self.correct_counts.get(uid, 0))
            for uid, score in self.scores.items()
        ]
        standings.sort(key=lambda x: (x[2], x[3]), reverse=True)
        return standings


# ═══════════════════════════════════════════════════════════════
#  Trivia Manager
# ═══════════════════════════════════════════════════════════════

class TriviaManager:
    """Coordinates trivia games, question banks, and persistent storage."""

    def __init__(self, db):
        self.db = db
        self.active_sessions: Dict[int, TriviaSession] = {}  # channel_id -> TriviaSession

    def is_channel_in_trivia(self, channel_id: int) -> bool:
        """Check if an active trivia session is running in the given channel."""
        session = self.active_sessions.get(channel_id)
        return bool(session and session.is_active)

    def get_session(self, channel_id: int) -> Optional[TriviaSession]:
        """Get the active session in a channel."""
        return self.active_sessions.get(channel_id)

    def stop_session(self, channel_id: int) -> Optional[TriviaSession]:
        """Stop and remove an active session in a channel."""
        session = self.active_sessions.pop(channel_id, None)
        if session:
            session.stop()
            if session.game_task and not session.game_task.done():
                session.game_task.cancel()
        return session

    async def add_question(
        self,
        guild_id: int,
        question_type: str,
        question: str,
        options: Optional[List[str]] = None,
        correct_answer: str = "",
        acceptable_answers: Optional[List[str]] = None,
        created_by: int = 0,
    ) -> TriviaQuestion:
        """Add a custom question to the guild's question bank."""
        canonical_type = normalize_question_type(question_type)
        if not canonical_type:
            raise ValueError(f"Invalid question type: {question_type}. Must be multiple_choice, true_false, or open_ended.")

        question_text = str(question).strip()
        if not question_text:
            raise ValueError("Question prompt cannot be empty.")

        clean_options = [str(opt).strip() for opt in (options or []) if str(opt).strip()]
        clean_acceptable = [str(ans).strip() for ans in (acceptable_answers or []) if str(ans).strip()]
        ans_text = str(correct_answer).strip()

        if canonical_type == MULTIPLE_CHOICE:
            if len(clean_options) < 2:
                raise ValueError("Multiple choice questions require at least 2 options.")
            if not ans_text:
                raise ValueError("Correct answer is required for multiple choice questions.")

            # Validate that the answer matches an option or a valid letter (A, B, C...)
            valid_letters = [chr(ord("A") + i) for i in range(len(clean_options))]
            ans_upper = ans_text.upper()
            if ans_upper in valid_letters:
                # Answer was given as a letter (e.g. 'A')
                pass
            elif any(clean_text(opt) == clean_text(ans_text) for opt in clean_options):
                # Answer was given as the option text
                pass
            elif ans_upper.isdigit() and 1 <= int(ans_upper) <= len(clean_options):
                # Answer was given as a 1-based index (e.g. '1')
                idx = int(ans_upper) - 1
                ans_text = valid_letters[idx]
            else:
                raise ValueError(
                    f"Answer '{correct_answer}' does not match any of the provided options: {', '.join(clean_options)}"
                )

        elif canonical_type == TRUE_FALSE:
            clean_options = ["True", "False"]
            lower_ans = ans_text.lower()
            if lower_ans in {"true", "t", "yes", "1"}:
                ans_text = "True"
            elif lower_ans in {"false", "f", "no", "0"}:
                ans_text = "False"
            else:
                raise ValueError("True/False questions must have a correct answer of 'True' or 'False'.")

        elif canonical_type == OPEN_ENDED:
            if not ans_text:
                raise ValueError("Correct answer cannot be empty for open-ended questions.")
            clean_options = []
            if ans_text not in clean_acceptable:
                clean_acceptable.insert(0, ans_text)

        new_id = await self.db.add_trivia_question(
            guild_id=guild_id,
            question_type=canonical_type,
            question=question_text,
            options=clean_options,
            correct_answer=ans_text,
            acceptable_answers=clean_acceptable,
            created_by=created_by,
        )

        return TriviaQuestion(
            id=new_id,
            guild_id=guild_id,
            question_type=canonical_type,
            question=question_text,
            options=clean_options,
            correct_answer=ans_text,
            acceptable_answers=clean_acceptable,
            created_by=created_by,
            created_at=time.time(),
            is_default=False,
        )

    async def get_questions(
        self,
        guild_id: int,
        question_type: Optional[str] = None,
        include_defaults: bool = False,
    ) -> List[TriviaQuestion]:
        """Fetch custom questions for a guild, optionally including built-in defaults."""
        canonical_type = normalize_question_type(question_type) if question_type else None
        db_rows = await self.db.get_trivia_questions(guild_id, canonical_type)

        questions = [
            TriviaQuestion(
                id=row["id"],
                guild_id=row["guild_id"],
                question_type=row["question_type"],
                question=row["question"],
                options=row["options"],
                correct_answer=row["correct_answer"],
                acceptable_answers=row["acceptable_answers"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                is_default=False,
            )
            for row in db_rows
        ]

        if include_defaults:
            for dq in DEFAULT_QUESTIONS:
                if not canonical_type or dq.question_type == canonical_type:
                    questions.append(dq)

        return questions

    async def get_question_by_id(self, guild_id: int, question_id: int) -> Optional[TriviaQuestion]:
        """Fetch a specific question by ID."""
        # Check defaults first if negative ID
        if question_id < 0:
            for dq in DEFAULT_QUESTIONS:
                if dq.id == question_id:
                    return dq

        row = await self.db.get_trivia_question_by_id(guild_id, question_id)
        if not row:
            return None

        return TriviaQuestion(
            id=row["id"],
            guild_id=row["guild_id"],
            question_type=row["question_type"],
            question=row["question"],
            options=row["options"],
            correct_answer=row["correct_answer"],
            acceptable_answers=row["acceptable_answers"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            is_default=False,
        )

    async def delete_question(self, guild_id: int, question_id: int) -> bool:
        """Delete a custom question by ID."""
        if question_id < 0:
            raise ValueError("Cannot delete built-in default questions.")
        return await self.db.delete_trivia_question(guild_id, question_id)

    async def clear_questions(self, guild_id: int) -> int:
        """Clear all custom questions for a guild."""
        return await self.db.clear_trivia_questions(guild_id)

    async def get_question_pool(
        self,
        guild_id: int,
        question_type: Optional[str] = None,
        include_defaults: bool = True,
    ) -> List[TriviaQuestion]:
        """Get the full pool of available questions for a guild."""
        custom_questions = await self.get_questions(guild_id, question_type, include_defaults=False)
        pool = list(custom_questions)

        if include_defaults or not pool:
            canonical_type = normalize_question_type(question_type) if question_type else None
            for dq in DEFAULT_QUESTIONS:
                if not canonical_type or dq.question_type == canonical_type:
                    pool.append(dq)

        return pool

    async def start_session(
        self,
        guild_id: int,
        channel_id: int,
        rounds: int = 10,
        question_type: Optional[str] = None,
        timeout: int = 30,
        points: int = 10,
        include_defaults: bool = True,
        started_by: int = 0,
    ) -> TriviaSession:
        """Create and register a new trivia session in a channel."""
        if self.is_channel_in_trivia(channel_id):
            raise ValueError("A trivia session is already in progress in this channel. Use `!trivia stop` to end it.")

        pool = await self.get_question_pool(guild_id, question_type, include_defaults=include_defaults)
        if not pool:
            raise ValueError("No trivia questions available! Admins can add questions or enable default questions.")

        # Shuffle and sample questions for the session
        rounds = max(1, min(rounds, 50))
        shuffled = list(pool)
        random.shuffle(shuffled)
        selected_questions = shuffled[:rounds]

        session = TriviaSession(
            guild_id=guild_id,
            channel_id=channel_id,
            questions=selected_questions,
            timeout_seconds=timeout,
            points_per_question=points,
            started_by=started_by,
        )

        self.active_sessions[channel_id] = session
        return session

    async def save_session_results(self, session: TriviaSession):
        """Persist session scores to the database leaderboard."""
        if not session.scores and not session.user_names:
            return

        all_players = set(session.user_names.keys())
        for user_id, points in session.scores.items():
            correct = session.correct_counts.get(user_id, 0)
            await self.db.update_trivia_score(
                guild_id=session.guild_id,
                user_id=user_id,
                points=points,
                correct_answers=correct,
                games_played=1,
            )
            all_players.discard(user_id)

        # Participants who played but scored 0
        if all_players:
            await self.db.record_trivia_games_played(session.guild_id, list(all_players))

    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[dict]:
        """Fetch the trivia leaderboard for a guild."""
        return await self.db.get_trivia_leaderboard(guild_id, limit)
