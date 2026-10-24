import json

from reverse1999_agent.story_progress import StoryProgressTracker


def test_tracker_breaks_replay_after_full_stage_flow() -> None:
    tracker = StoryProgressTracker(replay_gap_steps=5)
    target = "latest visible story stage: 湖中仙女"
    assert not tracker.observe_stage_selection(target, 10)
    assert tracker.observe_stage_selection(target, 25)
    assert tracker.seeking_prerequisite
    assert tracker.blocked_stage == "湖中仙女"
    assert "不要再次挑战" in tracker.context_hint()


def test_tracker_allows_immediate_retry_after_missed_click() -> None:
    tracker = StoryProgressTracker(replay_gap_steps=5)
    target = "latest visible story stage: 湖中仙女"
    assert not tracker.observe_stage_selection(target, 10)
    assert not tracker.observe_stage_selection(target, 11)


def test_tracker_restores_recent_replay_from_log(tmp_path) -> None:
    path = tmp_path / "steps.jsonl"
    targets = [
        "latest visible story stage: 湖中仙女",
        "battle progress",
        "latest visible story stage: 湖中仙女",
    ]
    path.write_text(
        "\n".join(json.dumps({"action": {"target": target}}) for target in targets),
        encoding="utf-8",
    )
    tracker = StoryProgressTracker.from_steps_log(path)
    assert tracker.phase == "return_to_chapters"
    assert tracker.blocked_stage == "湖中仙女"


def test_tracker_restores_follow_prerequisite_phase_from_log(tmp_path) -> None:
    path = tmp_path / "steps.jsonl"
    targets = [
        "latest visible story stage: 湖中仙女",
        "latest visible story stage: 湖中仙女",
        "highlighted prerequisite side-story action",
    ]
    path.write_text(
        "\n".join(json.dumps({"action": {"target": target}}) for target in targets),
        encoding="utf-8",
    )
    tracker = StoryProgressTracker.from_steps_log(path)
    assert tracker.phase == "follow_prerequisite"


def test_tracker_advances_prerequisite_phases() -> None:
    tracker = StoryProgressTracker(phase="return_to_chapters", blocked_stage="湖中仙女")
    tracker.note_action_target("return to chapter selection for prerequisites")
    assert tracker.phase == "choose_next_chapter"
    tracker.note_action_target("next chapter candidate: 孤独之歌")
    assert tracker.phase == "follow_prerequisite"
