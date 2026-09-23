"""Generic text tools available to any agent."""

from __future__ import annotations

import re


def word_count(text: str) -> dict:
    """Counts words, sentences and characters in a piece of text.

    Args:
        text: The text to analyse.

    Returns:
        A dict with the 'words', 'sentences' and 'characters' counts.
    """
    words = re.findall(r"\b\w+\b", text)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    return {"words": len(words), "sentences": len(sentences), "characters": len(text)}


def readability(text: str) -> dict:
    """Estimates how easy a text is to read using average sentence and word length.

    Args:
        text: The text to score.

    Returns:
        A dict with the 'score' (0-100, higher is easier) and a 'level' label.
    """
    words = re.findall(r"\b\w+\b", text)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not words or not sentences:
        return {"error": "text must contain at least one sentence"}

    words_per_sentence = len(words) / len(sentences)
    chars_per_word = sum(len(w) for w in words) / len(words)
    score = max(0.0, min(100.0, 110.0 - (words_per_sentence * 1.5) - (chars_per_word * 6.0)))

    if score >= 70:
        level = "easy"
    elif score >= 45:
        level = "standard"
    else:
        level = "difficult"
    return {"score": round(score, 1), "level": level}
