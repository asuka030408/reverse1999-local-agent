from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


STAGE_TARGET_PREFIX = "latest visible story stage:"


@dataclass
class StoryProgressTracker:
    """Detect completed-stage replays and switch to prerequisite discovery."""

    replay_gap_steps: int = 5
    last_selected_step: dict[str, int] = field(default_factory=dict)
    phase: str = "normal"
    blocked_stage: str = ""

    @property
    def seeking_prerequisite(self) -> bool:
        return self.phase != "normal"

    @classmethod
    def from_steps_log(cls, path: Path, tail_limit: int = 200) -> "StoryProgressTracker":
        tracker = cls()
        if not path.exists():
            return tracker
        lines = path.read_text(encoding="utf-8").splitlines()[-tail_limit:]
        stages: list[str] = []
        targets: list[str] = []
        for line in lines:
            try:
                target = str(json.loads(line)["action"]["target"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            targets.append(target)
            if target.startswith(STAGE_TARGET_PREFIX):
                stages.append(target.removeprefix(STAGE_TARGET_PREFIX).strip())
        if stages and stages.count(stages[-1]) >= 2:
            tracker.blocked_stage = stages[-1]
            if any(
                target.startswith(
                    (
                        "next chapter candidate:",
                        "next permanent chapter:",
                        "next chapter preview card",
                        "open required side story location",
                        "highlighted prerequisite side-story action",
                        "locked prerequisite stage node:",
                    )
                )
                for target in targets
            ):
                tracker.phase = "follow_prerequisite"
            else:
                tracker.phase = "return_to_chapters"
        return tracker

    def observe_stage_selection(self, target: str, step: int) -> bool:
        if not target.startswith(STAGE_TARGET_PREFIX):
            return False
        stage = target.removeprefix(STAGE_TARGET_PREFIX).strip()
        previous = self.last_selected_step.get(stage)
        self.last_selected_step[stage] = step
        if previous is None or step - previous < self.replay_gap_steps:
            return False
        self.phase = "choose_next_chapter"
        self.blocked_stage = stage
        return True

    def note_action_target(self, target: str) -> None:
        if target == "return to chapter selection for prerequisites":
            self.phase = "choose_next_chapter"
        elif target.startswith(("next chapter candidate:", "next permanent chapter:")):
            self.phase = "follow_prerequisite"

    def context_hint(self) -> str:
        if not self.seeking_prerequisite:
            return ""
        phase_instruction = {
            "return_to_chapters": (
                "使用画面中游戏自身的章节导航按钮打开章节选择页。不要使用安卓系统返回键，"
                "因为它可能重新打开旧关卡。"
            ),
            "choose_next_chapter": (
                "依据离线常驻主线知识选择下一章，即使它仍处于锁定状态。若仍在旧地图，"
                "使用游戏自身的章节导航按钮，不要使用安卓系统返回键。"
            ),
            "follow_prerequisite": (
                "按照锁定章节显示的前置要求前往指定地图，并选择高亮的必需支线。"
            ),
        }.get(self.phase, "")
        return (
            f"已启用重复关卡阻断：不要再次挑战已经完成的关卡{self.blocked_stage!r}。"
            f"{phase_instruction}持续处理前置要求，直到下一章正式解锁。"
        )
