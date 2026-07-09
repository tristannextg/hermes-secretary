from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LeetCodeExercise:
    title: str
    difficulty: str
    topic: str
    url: str
    target_minutes: int
    reflection_prompt: str


def pick_leetcode(config_path: Path, state_path: Path, allowed_difficulties: tuple[str, ...]) -> LeetCodeExercise:
    exercises = _load_exercises(config_path)
    if allowed_difficulties:
        allowed = {item.lower() for item in allowed_difficulties}
        filtered = [item for item in exercises if str(item.get("difficulty", "")).lower() in allowed]
        exercises = filtered or exercises
    index = _next_index(state_path, len(exercises))
    item = exercises[index]
    return LeetCodeExercise(
        title=str(item.get("title", "Two Sum")),
        difficulty=str(item.get("difficulty", "Easy")),
        topic=str(item.get("topic", item.get("topics", "arrays"))),
        url=str(item.get("url", item.get("link", "https://leetcode.com/problemset/"))),
        target_minutes=int(item.get("target_minutes", 25)),
        reflection_prompt=str(item.get("reflection_prompt", "What invariant made the solution simpler?")),
    )


def _load_exercises(path: Path) -> list[dict]:
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list) and loaded:
            return loaded
        if isinstance(loaded, dict) and isinstance(loaded.get("exercises"), list) and loaded["exercises"]:
            return loaded["exercises"]
    return [{"title": "Two Sum", "difficulty": "Easy", "topic": "arrays", "url": "https://leetcode.com/problems/two-sum/"}]


def _next_index(state_path: Path, count: int) -> int:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    current = -1
    if state_path.exists():
        try:
            current = int(json.loads(state_path.read_text(encoding="utf-8")).get("last_index", -1))
        except (ValueError, json.JSONDecodeError, AttributeError):
            current = -1
    next_index = (current + 1) % max(count, 1)
    state_path.write_text(json.dumps({"last_index": next_index}, indent=2), encoding="utf-8")
    return next_index
