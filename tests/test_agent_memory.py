from pathlib import Path

from reverse1999_agent.agent_memory import AgentMemory
from reverse1999_agent.models import AgentAction, ScreenState, Workflow


def action(target: str, *, kind: str = "tap") -> AgentAction:
    payload = {
        "state": ScreenState.STORY,
        "action": kind,
        "target": target,
        "reason": "test",
        "confidence": 1.0,
    }
    if kind == "tap":
        payload.update(x=10, y=20)
    elif kind == "swipe":
        payload.update(x=10, y=20, x2=30, y2=20)
    return AgentAction(**payload)


def test_story_checkpoint_survives_partial_development(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    memory = AgentMemory()
    memory.observe(
        Workflow.STORY,
        action("latest unlocked chapter: 行于漫漫长路上"),
        visible_collection="故事的根须",
    )
    memory.observe(Workflow.STORY, action("latest visible story stage: 洪水之后"))
    memory.observe(
        Workflow.STORY,
        action("story blocked by defeat", kind="finish"),
    )
    memory.save(path)

    restored = AgentMemory.load(path)
    assert restored.story_start_mode == "resume_checkpoint"
    assert restored.checkpoint.collection == "故事的根须"
    assert restored.checkpoint.subchapter == "行于漫漫长路上"
    assert restored.checkpoint.stage == "洪水之后"


def test_character_finish_keeps_resume_checkpoint() -> None:
    memory = AgentMemory(resume_after_development=True, development_required=True)
    memory.checkpoint.subchapter = "行于漫漫长路上"
    memory.observe(
        Workflow.CHARACTER,
        action("partial development complete", kind="finish"),
    )
    assert not memory.development_required
    assert memory.resume_after_development


def test_starting_saved_stage_consumes_resume_mode() -> None:
    memory = AgentMemory(resume_after_development=True)
    memory.checkpoint.stage = "洪水之后"
    memory.observe(Workflow.STORY, action("开始行动"))
    assert not memory.resume_after_development


def test_normal_story_run_resets_full_scan() -> None:
    memory = AgentMemory(scan_required=False, scan_phase="idle")
    memory.prepare_run(Workflow.STORY)
    assert memory.scan_required
    assert memory.scan_phase == "seek_oldest"


def test_story_scan_changes_direction_at_both_boundaries() -> None:
    memory = AgentMemory(scan_required=True, scan_phase="seek_oldest")
    memory.observe(
        Workflow.STORY,
        action("scan toward oldest story page", kind="swipe"),
        changed=False,
    )
    assert memory.scan_phase == "scan_forward"
    memory.observe(
        Workflow.STORY,
        action("scan forward story page", kind="swipe"),
        changed=False,
    )
    assert memory.scan_phase == "inspect_last"
