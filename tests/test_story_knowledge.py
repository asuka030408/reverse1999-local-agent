from reverse1999_agent.story_knowledge import StoryKnowledgeBase


def test_default_knowledge_has_ordered_permanent_chapters() -> None:
    knowledge = StoryKnowledgeBase.load_default()
    assert knowledge.chapter_titles[:3] == ("在我们的时代里", "夜色温柔", "故事一无所有")
    assert knowledge.chapter_titles[-2:] == ("孤独之歌", "忧郁的热带")
    assert knowledge.chapters[6].final_stage == "谢幕词"
    assert any("名称正上方" in note for note in knowledge.navigation_notes)


def test_context_identifies_stage_and_rejects_preview_entry() -> None:
    knowledge = StoryKnowledgeBase.load_default()
    hint = knowledge.context_hint(["今夜星光灿烂", "汉赛尔与格蕾特", "预演", "应门者"])
    assert "6-23" in hint
    assert "常驻路线的最后一关" in hint
    assert "禁止打开" in hint
