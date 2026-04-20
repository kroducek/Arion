"""Datová vrstva — skóre Door Labyrinth."""

from src.utils.paths import LABYRINTH_SCORES as SCORES_FILE
from src.utils.json_utils import load_json, save_json


def load_scores() -> dict:
    return load_json(SCORES_FILE) or {}


def save_scores(data: dict) -> None:
    save_json(SCORES_FILE, data)


def record_win(uid: str) -> None:
    scores = load_scores()
    scores[uid] = scores.get(uid, 0) + 1
    save_scores(scores)
