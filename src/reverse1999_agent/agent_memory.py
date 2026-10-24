from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import AgentAction, Workflow


@dataclass
class StoryCheckpoint:
    collection: str = ""
    subchapter: str = ""
    stage: str = ""
    updated_at: str = ""


@dataclass
class AgentMemory:
    """Small persistent state used to resume story after partial development."""

    version: int = 1
    scan_required: bool = True
    resume_after_development: bool = False
    development_required: bool = False
    partial_development_steps: int = 0
    current_team: list[str] = field(default_factory=list)
    scan_phase: str = "seek_oldest"
    checkpoint: StoryCheckpoint = field(default_factory=StoryCheckpoint)

    @classmethod
    def load(cls, path: Path) -> "AgentMemory":
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["checkpoint"] = StoryCheckpoint(**payload.get("checkpoint", {}))
            return cls(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @property
    def story_start_mode(self) -> str:
        if self.resume_after_development and (
            self.checkpoint.subchapter or self.checkpoint.stage
        ):
            return "resume_checkpoint"
        return "full_scan"

    def context_hint(self, workflow: Workflow) -> str:
        if workflow is Workflow.CHARACTER:
            if self.development_required:
                return (
                    "本次培养由主线战败触发。允许只完成一部分安全、有效的提升；"
                    "材料或体力不足时保存成果并结束培养，之后返回剧情检查点。"
                )
            return "允许部分培养：不要求一次满级，只执行当前资源允许的有效提升。"
        if self.story_start_mode == "resume_checkpoint":
            return (
                "培养后恢复模式：不要重新扫描全部章节。优先返回已保存的剧情检查点："
                f"大章节={self.checkpoint.collection or '未知'}，"
                f"小章节={self.checkpoint.subchapter or '未知'}，"
                f"关卡={self.checkpoint.stage or '未知'}。"
            )
        return (
            "正常启动扫描模式：不得把游戏默认打开的故事集合当成最新进度。"
            "先翻到最早一页，再从前往后逐页检查；页面没有“未解锁”就继续下一页，"
            "遇到第一个“未解锁”时选择它前一个已解锁小章节并保存检查点。"
        )

    def prepare_run(self, workflow: Workflow) -> None:
        if workflow is Workflow.STORY and self.story_start_mode != "resume_checkpoint":
            self.scan_required = True
            self.scan_phase = "seek_oldest"

    def observe(
        self,
        workflow: Workflow,
        action: AgentAction,
        *,
        visible_collection: str = "",
        changed: bool = True,
    ) -> None:
        if visible_collection:
            self.checkpoint.collection = visible_collection

        target = action.target.strip()
        if workflow is Workflow.STORY:
            if target == "scan toward oldest story page" and not changed:
                self.scan_phase = "scan_forward"
            elif target == "scan forward story page" and not changed:
                self.scan_phase = "inspect_last"
            for prefix in (
                "latest unlocked chapter:",
                "next chapter candidate:",
                "latest permanent chapter:",
                "next permanent chapter:",
                "resume story subchapter:",
            ):
                if changed and target.startswith(prefix):
                    self.checkpoint.subchapter = target.removeprefix(prefix).strip()
                    self.checkpoint.stage = ""
                    self.scan_required = False
                    self.scan_phase = "idle"
                    self._touch()
                    break
            for prefix in (
                "latest visible story stage:",
                "prerequisite stage candidate:",
                "resume story stage:",
            ):
                if changed and target.startswith(prefix):
                    self.checkpoint.stage = target.removeprefix(prefix).strip()
                    self._touch()
                    break
            if target == "story blocked by defeat":
                self.development_required = True
                self.resume_after_development = True
                self.scan_required = False
                self._touch()
            elif target == "开始行动" and self.resume_after_development:
                # The saved stage has been reached. Continue normally from this point.
                self.resume_after_development = False
                self._touch()
        else:
            if target in {"洞悉", "close insight success screen", "dismiss level up overlay"}:
                self.partial_development_steps += 1
            if action.action == "finish":
                self.development_required = False
                self.resume_after_development = bool(
                    self.checkpoint.subchapter or self.checkpoint.stage
                )
                self._touch()

    def _touch(self) -> None:
        self.checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
