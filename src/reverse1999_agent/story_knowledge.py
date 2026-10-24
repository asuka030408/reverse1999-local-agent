from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Iterable


@dataclass(frozen=True)
class StoryChapter:
    number: int
    title: str
    stages: tuple[str, ...]

    @property
    def final_stage(self) -> str:
        return self.stages[-1] if self.stages else ""


@dataclass(frozen=True)
class StoryKnowledgeBase:
    """Versioned, offline knowledge about the permanent main-story route."""

    chapters: tuple[StoryChapter, ...]
    excluded_entries: tuple[str, ...]
    navigation_notes: tuple[str, ...]
    collection_titles: tuple[str, ...]
    source_url: str
    verified_at: str

    @classmethod
    def load_default(cls) -> "StoryKnowledgeBase":
        resource = files("reverse1999_agent").joinpath("data/story_mainline.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        return cls(
            chapters=tuple(
                StoryChapter(
                    number=int(item["number"]),
                    title=str(item["title"]),
                    stages=tuple(str(stage) for stage in item.get("stages", [])),
                )
                for item in payload["chapters"]
            ),
            excluded_entries=tuple(payload.get("excluded_entries", [])),
            navigation_notes=tuple(payload.get("navigation_notes", [])),
            collection_titles=tuple(
                str(item["title"])
                for item in payload.get("observed_story_collections", [])
                if item.get("title")
            ),
            source_url=str(payload["source_url"]),
            verified_at=str(payload["verified_at"]),
        )

    @property
    def chapter_titles(self) -> tuple[str, ...]:
        return tuple(chapter.title for chapter in self.chapters)

    def match_chapter(self, texts: Iterable[str]) -> StoryChapter | None:
        joined = "\n".join(text.strip() for text in texts if text.strip())
        return next((chapter for chapter in self.chapters if chapter.title in joined), None)

    def match_stage(self, texts: Iterable[str]) -> tuple[StoryChapter, int, str] | None:
        joined = "\n".join(text.strip() for text in texts if text.strip())
        matches: list[tuple[StoryChapter, int, str]] = []
        for chapter in self.chapters:
            for index, stage in enumerate(chapter.stages, start=1):
                if len(stage) >= 2 and stage in joined:
                    matches.append((chapter, index, stage))
        return max(matches, key=lambda item: len(item[2]), default=None)

    def context_hint(self, texts: Iterable[str]) -> str:
        values = tuple(texts)
        excluded = tuple(label for label in self.excluded_entries if label in values)
        stage_match = self.match_stage(values)
        chapter = stage_match[0] if stage_match else self.match_chapter(values)
        notes: list[str] = []
        if chapter is not None:
            notes.append(
                f"离线常驻主线知识库：第{chapter.number}章是{chapter.title!r}，"
                f"这一章常驻路线的最后一关是{chapter.final_stage!r}。"
            )
        if stage_match is not None:
            matched_chapter, index, stage = stage_match
            notes.append(
                f"OCR与常驻主线关卡{matched_chapter.number}-{index:02d} {stage!r}匹配。"
            )
        if excluded:
            notes.append(
                "以下可见入口不属于本次指定的常驻主线路线，禁止打开："
                f"{', '.join(repr(item) for item in excluded)}。"
            )
        chapter_browser_visible = "未解锁" in values or {"故事", "映像", "轶事", "资源"}.issubset(values)
        if chapter_browser_visible and self.navigation_notes:
            notes.append("章节导航规则：" + "".join(self.navigation_notes))
        return " ".join(notes)
