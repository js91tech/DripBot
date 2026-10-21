"""Trivia engine — pure logic for the Discord trivia mode.

Admins can add their own questions in three formats:
  - multiple_choice: question + 4 options (A-D) + correct answer
  - true_false:      question + True/False answer
  - open:            question + open-ended answer (+ optional alternates)

This module has no discord.py dependency so it is easy to unit test.
The Discord wiring (commands + game loop + persistence) lives in
``cogs/trivia.py`` with storage in ``engine/database.py``.
"""

import difflib
import random
import re

QUESTION_TYPES = ("multiple_choice", "true_false", "open")

MC_LETTERS = ("A", "B", "C", "D")

TRUE_VALUES = {"true", "t", "yes", "y", "1", "correct", "right"}
FALSE_VALUES = {"false", "f", "no", "n", "0", "wrong", "incorrect"}

OPEN_MATCH_THRESHOLD = 0.82


def normalize_text(value):
    """Lowercase, strip punctuation/extra whitespace for fuzzy comparison."""
    if isinstance(value, bool):
        value = "true" if value else "false"
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_mc_answer_index(value, num_options=4):
    """Parse 'A'/'b'/'2' into a 0-based option index. Returns None if unparseable."""
    if value is None:
        return None
    cleaned = str(value).strip().upper().rstrip(").:")
    if cleaned in ("A", "B", "C", "D")[:num_options]:
        return ord(cleaned) - ord("A")
    if cleaned.isdigit():
        index = int(cleaned) - 1
        if 0 <= index < num_options:
            return index
    return None


def parse_true_false(value):
    """Parse many spellings of true/false into a bool. Returns None if unknown."""
    if isinstance(value, bool):
        return value
    cleaned = normalize_text(value)
    if cleaned in TRUE_VALUES:
        return True
    if cleaned in FALSE_VALUES:
        return False
    return None


def validate_mcq(question, options, correct):
    """Validate a multiple-choice payload. Returns a cleaned dict or raises ValueError."""
    question = str(question or "").strip()
    if len(question) < 4:
        raise ValueError("Question must be at least 4 characters long.")
    if len(question) > 500:
        raise ValueError("Question must be 500 characters or fewer.")
    if not isinstance(options, (list, tuple)) or len(options) != 4:
        raise ValueError("Multiple-choice questions need exactly 4 options.")
    cleaned_options = [str(o or "").strip() for o in options]
    if any(len(o) < 1 or len(o) > 200 for o in cleaned_options):
        raise ValueError("Each option must be 1-200 characters.")
    if len({normalize_text(o) for o in cleaned_options}) != 4:
        raise ValueError("All 4 options must be different.")

    index = parse_mc_answer_index(correct, 4)
    if index is None:
        # Maybe they passed the full option text as the answer.
        needle = normalize_text(correct)
        for i, option in enumerate(cleaned_options):
            if normalize_text(option) == needle:
                index = i
                break
    if index is None:
        raise ValueError("Correct answer must be A, B, C, D (or match one option).")
    return {
        "qtype": "multiple_choice",
        "question": question,
        "options": cleaned_options,
        "answer_index": index,
        "answer": cleaned_options[index],
    }


def validate_tf(question, answer):
    """Validate a true/false payload. Returns a cleaned dict or raises ValueError."""
    question = str(question or "").strip()
    if len(question) < 4:
        raise ValueError("Question must be at least 4 characters long.")
    if len(question) > 500:
        raise ValueError("Question must be 500 characters or fewer.")
    parsed = parse_true_false(answer)
    if parsed is None:
        raise ValueError("Answer must be True or False.")
    return {"qtype": "true_false", "question": question, "answer": parsed}


def validate_open(question, answer, alternates=None):
    """Validate an open-ended payload. Returns a cleaned dict or raises ValueError."""
    question = str(question or "").strip()
    answer = str(answer or "").strip()
    if len(question) < 4:
        raise ValueError("Question must be at least 4 characters long.")
    if len(question) > 500:
        raise ValueError("Question must be 500 characters or fewer.")
    if len(answer) < 1:
        raise ValueError("Open-ended questions need an answer.")
    if len(answer) > 200:
        raise ValueError("Answer must be 200 characters or fewer.")
    cleaned_alternates = []
    for alt in alternates or []:
        alt = str(alt or "").strip()
        if alt and alt.lower() != answer.lower() and len(alt) <= 200:
            cleaned_alternates.append(alt)
    return {
        "qtype": "open",
        "question": question,
        "answer": answer,
        "alternates": cleaned_alternates[:5],
    }


def check_mc_answer(question, response):
    """True when a response answers a multiple-choice question correctly."""
    options = question.get("options") or []
    answer_index = question.get("answer_index")
    if answer_index is None:
        # Legacy rows store only the answer text.
        needle = normalize_text(question.get("answer"))
        return normalize_text(response) == needle and bool(needle)
    index = parse_mc_answer_index(response, len(options))
    if index is not None:
        return index == answer_index
    # Full-text answer: "paris" should match option B "Paris".
    needle = normalize_text(response)
    if not needle:
        return False
    for i, option in enumerate(options):
        if normalize_text(option) == needle and i == answer_index:
            return True
    return False


def check_tf_answer(question, response):
    """True when a response answers a true/false question correctly."""
    expected = question.get("answer")
    if isinstance(expected, str):
        expected = parse_true_false(expected)
    if not isinstance(expected, bool):
        return False
    given = parse_true_false(response)
    return given is not None and given == expected


def check_open_answer(question, response, threshold=OPEN_MATCH_THRESHOLD):
    """Fuzzy True when an open-ended response matches the answer or an alternate."""
    needle = normalize_text(response)
    if not needle:
        return False
    candidates = [question.get("answer", "")] + list(question.get("alternates") or [])
    for candidate in candidates:
        target = normalize_text(candidate)
        if not target:
            continue
        if needle == target:
            return True
        # Containment with a length guard so "par" does not match "paris france".
        if len(needle) >= 3 and len(target) >= 3:
            if needle == target:
                return True
            ratio = difflib.SequenceMatcher(None, needle, target).ratio()
            if ratio >= threshold:
                return True
    return False


def check_answer(question, response):
    """Dispatch to the right checker based on ``qtype``."""
    qtype = (question or {}).get("qtype")
    if qtype == "multiple_choice":
        return check_mc_answer(question, response)
    if qtype == "true_false":
        return check_tf_answer(question, response)
    if qtype == "open":
        return check_open_answer(question, response)
    return False


def format_correct_answer(question):
    """Human-readable correct answer for reveal messages/embeds."""
    qtype = (question or {}).get("qtype")
    if qtype == "multiple_choice":
        options = question.get("options") or []
        index = question.get("answer_index", -1)
        letter = MC_LETTERS[index] if 0 <= index < len(MC_LETTERS) else "?"
        return f"{letter}) {question.get('answer', '')}"
    if qtype == "true_false":
        answer = question.get("answer")
        if isinstance(answer, str):
            answer = parse_true_false(answer)
        return "True" if answer else "False"
    return str(question.get("answer", ""))


def pick_game_questions(questions, count=10, rng=None):
    """Pick up to ``count`` random questions, shuffled. Never mutates the input."""
    pool = list(questions or [])
    rng = rng or random
    rng.shuffle(pool)
    return pool[: max(0, int(count or 0))]


SEED_QUESTIONS = [
    # 5 multiple choice
    {
        "qtype": "multiple_choice",
        "question": "What is the capital of France?",
        "options": ["London", "Paris", "Rome", "Madrid"],
        "answer": "Paris",
    },
    {
        "qtype": "multiple_choice",
        "question": "Which planet is known as the Red Planet?",
        "options": ["Venus", "Jupiter", "Mars", "Saturn"],
        "answer": "Mars",
    },
    {
        "qtype": "multiple_choice",
        "question": "How many days are in a leap year?",
        "options": ["365", "364", "366", "367"],
        "answer": "366",
    },
    {
        "qtype": "multiple_choice",
        "question": "Which animal is the largest mammal on Earth?",
        "options": ["African Elephant", "Blue Whale", "Giraffe", "Polar Bear"],
        "answer": "Blue Whale",
    },
    {
        "qtype": "multiple_choice",
        "question": "What does HTTP stand for in a URL?",
        "options": [
            "HyperText Transfer Protocol",
            "High Throughput Transfer Process",
            "HyperText Transmission Program",
            "Home Tool Transfer Protocol",
        ],
        "answer": "HyperText Transfer Protocol",
    },
    # 5 true/false
    {"qtype": "true_false", "question": "The Sun rises in the east.", "answer": True},
    {"qtype": "true_false", "question": "Water boils at 90 degrees Celsius at sea level.", "answer": False},
    {"qtype": "true_false", "question": "Octopuses have three hearts.", "answer": True},
    {"qtype": "true_false", "question": "The Great Wall of China is visible from the Moon with the naked eye.", "answer": False},
    {"qtype": "true_false", "question": "Light travels faster than sound.", "answer": True},
    # 5 open ended
    {"qtype": "open", "question": "What is the largest ocean on Earth?", "answer": "Pacific Ocean", "alternates": ["Pacific"]},
    {"qtype": "open", "question": "How many continents are there?", "answer": "7", "alternates": ["seven"]},
    {"qtype": "open", "question": "What gas do plants absorb from the air?", "answer": "carbon dioxide", "alternates": ["CO2"]},
    {"qtype": "open", "question": "What is the hardest natural substance on Earth?", "answer": "diamond"},
    {"qtype": "open", "question": "Which instrument has 88 keys?", "answer": "piano"},
]
