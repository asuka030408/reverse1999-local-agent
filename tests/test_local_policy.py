from PIL import Image

from reverse1999_agent.local_policy import decide_locally
from reverse1999_agent.models import Workflow
from reverse1999_agent.vision import OcrItem


def item(text: str, x: int = 100, y: int = 100) -> OcrItem:
    return OcrItem(text=text, confidence=0.99, center_x=x, center_y=y)


def test_story_victory_uses_local_result_action() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("战斗胜利"), item("返回来源", 1732, 1020)],
    )
    assert action is not None
    assert action.action == "tap"
    assert action.state == "result"
    assert action.target == "返回来源"


def test_story_victory_without_exit_text_falls_back_to_model() -> None:
    image = Image.new("RGB", (1920, 1080))
    assert decide_locally(Workflow.STORY, image, [item("战斗胜利")]) is None


def test_level_up_overlay_is_dismissed_for_character_workflow() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("战斗胜利"), item("等级提升")],
    )
    assert action is not None
    assert action.target == "dismiss level up overlay"


def test_character_workflow_does_not_use_story_shortcut() -> None:
    image = Image.new("RGB", (1920, 1080))
    assert decide_locally(Workflow.CHARACTER, image, [item("跳过")]) is None


def test_story_battle_stats_closes_locally() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(Workflow.STORY, image, [item("战斗数据")])
    assert action is not None
    assert action.action == "tap"
    assert action.state == "popup"


def test_ambiguous_text_falls_back_to_model() -> None:
    image = Image.new("RGB", (1920, 1080))
    assert decide_locally(Workflow.STORY, image, [item("确认")]) is None


def test_character_shortage_clicks_missing_material() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("洞悉所见"), item("1/3", 614, 984), item("16/6", 864, 984)],
    )
    assert action is not None
    assert action.action == "tap"
    assert action.x == 614
    assert action.y == 929
    assert action.target == "missing material 1/3"


def test_character_incomplete_resource_read_waits() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("洞悉所见"), item("30/30", 363, 984), item("3/3", 614, 984)],
    )
    assert action is not None
    assert action.action == "wait"


def test_character_complete_resources_allow_insight() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [
            item("洞悉所见"), item("洞悉", 1444, 956), item("30/30", 363, 984),
            item("3/3", 614, 984), item("3/3", 747, 984),
            item("16/6", 864, 984), item("10/6", 987, 984),
        ],
    )
    assert action is not None
    assert action.target == "洞悉"


def test_character_source_prefers_lower_jump_entry() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("来源"), item("跳转", 1480, 538), item("跳转", 1480, 620)],
    )
    assert action is not None
    assert action.x == 1480
    assert action.y == 620


def test_character_resource_stage_starts_action() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("推荐等级：洞悉一1级"), item("开始行动", 1734, 912)],
    )
    assert action is not None
    assert action.target == "开始行动"


def test_character_home_opens_character_entry() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("角色", 1685, 694), item("征集", 1470, 829)],
    )
    assert action is not None
    assert action.target == "角色"


def test_target_character_details_open_insight_tab() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("环状水星"), item("Insight"), item("洞悉", 1571, 212)],
        target_character="环状水星",
    )
    assert action is not None
    assert action.target == "洞悉 tab"


def test_insight_success_screen_closes_locally() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("环状水星"), item("SPIRIT")],
        target_character="环状水星",
    )
    assert action is not None
    assert action.target == "close insight success screen"


def test_target_level_cap_finishes_character_workflow() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.CHARACTER,
        image,
        [item("环状水星等级上限提升至40级")],
        target_character="环状水星",
        target_level=40,
    )
    assert action is not None
    assert action.action == "finish"


def test_battle_enables_auto_once_then_waits() -> None:
    image = Image.new("RGB", (1920, 1080))
    battle_items = [item("轮次:1/2 回合:2/20"), item("敌我情报")]
    first = decide_locally(Workflow.CHARACTER, image, battle_items)
    assert first is not None
    assert first.action == "wait"

    later = decide_locally(
        Workflow.CHARACTER,
        image,
        battle_items,
        battle_click_auto=True,
    )
    assert later is not None
    assert later.action == "tap"
    assert later.x == 1665


def test_manual_only_battle_repeatedly_clicks_rightmost_skill_card() -> None:
    image = Image.new("RGB", (1920, 1080))
    battle_items = [item("轮次:1/1 回合:1/20"), item("敌我情报")]

    for slot, expected_x in enumerate((1816, 1816, 1816, 1816)):
        action = decide_locally(
            Workflow.STORY,
            image,
            battle_items,
            battle_manual=True,
            manual_card_slot=slot,
        )
        assert action is not None
        assert action.action == "tap"
        assert action.x == expected_x
        assert action.y == 907
        assert action.target == f"manual battle skill {slot + 1}/4"

    resolution = decide_locally(
        Workflow.STORY,
        image,
        battle_items,
        battle_manual=True,
        manual_card_slot=4,
    )
    assert resolution is not None
    assert resolution.action == "wait"
    assert resolution.target == "manual battle turn resolution"


def test_stalled_battle_without_cards_advances_dialogue_overlay() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("轮次:1/1 回合:4/20"), item("敌我情报")],
        battle_force_dialogue=True,
    )
    assert action is not None
    assert action.action == "tap"
    assert action.target == "advance stalled in-battle dialogue"
    assert (action.x, action.y) == (960, 194)


def test_story_selects_rightmost_unlocked_chapter() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("故事"), item("映像"), item("轶事"), item("资源"),
            item("夜色温柔", 91, 799), item("故事一无所有", 430, 799),
            item("老虎的金黄", 770, 800), item("洞穴的囚徒", 1110, 800),
        ],
    )
    assert action is not None
    assert action.target.endswith("洞穴的囚徒")
    assert action.y == 541


def test_story_selects_icon_above_last_unlocked_subchapter_before_lock() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("故事"), item("映像"), item("轶事"), item("资源"),
            item("行于漫漫长路上", 780, 798), item("未解锁", 1123, 527),
            item("未选择的路", 1611, 848),
        ],
    )
    assert action is not None
    assert action.target == "latest unlocked chapter: 行于漫漫长路上"
    assert action.x == 780
    assert action.y == 539
    assert "名称上方" in action.reason


def test_story_resume_prefers_saved_subchapter() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("故事"), item("映像"), item("轶事"), item("资源"),
            item("行于漫漫长路上", 780, 798), item("未选择的路", 1611, 848),
        ],
        resume_story_subchapter="行于漫漫长路上",
    )
    assert action is not None
    assert action.target == "resume story subchapter: 行于漫漫长路上"
    assert (action.x, action.y) == (780, 539)


def test_story_full_scan_first_swipes_toward_oldest_page() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("故事"), item("映像"), item("轶事"), item("资源")],
        story_scan_phase="seek_oldest",
    )
    assert action is not None
    assert action.action == "swipe"
    assert action.target == "scan toward oldest story page"
    assert action.x2 > action.x


def test_story_scan_moves_forward_until_unlocked_boundary_is_found() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("故事"), item("映像"), item("轶事"), item("资源")],
        story_scan_phase="scan_forward",
    )
    assert action is not None
    assert action.action == "swipe"
    assert action.target == "scan forward story page"
    assert action.x2 < action.x


def test_story_prerequisite_mode_selects_rightmost_locked_chapter_candidate() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("故事"), item("映像"), item("轶事"), item("资源"),
            item("洞穴的囚徒", 1110, 800), item("孤独之歌", 1710, 800),
        ],
        story_prerequisite_phase="choose_next_chapter",
    )
    assert action is not None
    assert action.x == 1710
    assert action.target == "next chapter candidate: 孤独之歌"


def test_story_prerequisite_mode_ignores_preview_and_uses_permanent_chapter() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("故事"), item("映像"), item("轶事"), item("资源"),
            item("孤独之歌", 1110, 799), item("预演", 1471, 333),
            item("特别篇", 1591, 463), item("应门者", 1360, 799), item("船喻", 1636, 796),
        ],
        story_prerequisite_phase="choose_next_chapter",
        known_story_chapters=("今夜星光灿烂", "孤独之歌", "忧郁的热带"),
        excluded_story_entries=("预演", "特别篇", "应门者", "船喻"),
    )
    assert action is not None
    assert action.target == "next permanent chapter: 孤独之歌"
    assert action.x == 1110


def test_story_immediately_leaves_summon_screen_even_during_prerequisite_mode() -> None:
    image = Image.new("RGB", (1920, 1080), "#d96a20")
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("银行兑换", 130, 980), item("征集一次", 1130, 980), item("征集十次", 1580, 980)],
        story_prerequisite_phase="follow_prerequisite",
    )
    assert action is not None
    assert action.target == "退出征集界面"
    assert action.action == "back"


def test_story_does_not_mistake_home_summon_entry_for_summon_detail() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("SUMMON", 1530, 800), item("征集", 1530, 825)],
    )
    assert action is None


def test_story_uses_right_side_enter_from_home() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("邮件", 118, 322), item("任务", 118, 446),
            item("仓库", 118, 576), item("银行", 118, 730),
            item("ENTER", 1590, 482), item("入场", 1708, 506),
        ],
    )
    assert action is not None
    assert action.target == "主界面右侧入场"
    assert action.x == 1709
    assert action.y == 508


def test_story_does_not_treat_arbitrary_orange_screen_as_prerequisite() -> None:
    image = Image.new("RGB", (1920, 1080), "#d96a20")
    action = decide_locally(
        Workflow.STORY,
        image,
        [],
        story_prerequisite_phase="follow_prerequisite",
    )
    assert action is None


def test_story_clicks_geometric_center_of_orange_action_button_with_story_evidence() -> None:
    image = Image.new("RGB", (1920, 1080), "black")
    pixels = image.load()
    for y in range(500, 601):
        for x in range(1110, 1361):
            pixels[x, y] = (198, 86, 32)
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("完成后解锁下一剧情", 900, 300)],
    )
    assert action is not None
    assert action.target == "visible orange story action button"
    assert abs(action.x - 1235) <= 2
    assert abs(action.y - 550) <= 2


def test_story_does_not_click_orange_character_portray_button() -> None:
    image = Image.new("RGB", (1920, 1080), "black")
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("塑造详情", 1200, 200), item("材料不足", 1650, 180)],
    )
    assert action is not None
    assert action.action == "back"
    assert action.target == "leave portray screen"


def test_story_map_selects_rightmost_visible_stage() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("04/", 656, 848), item("箱底", 70, 897), item("出航日", 626, 897)],
    )
    assert action is not None
    assert action.x == 626
    assert action.target.endswith("出航日")


def test_story_prerequisite_mode_leaves_highlighted_map_to_vision_model() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("04/", 656, 848), item("箱底", 70, 897), item("出航日", 626, 897)],
        story_prerequisite_phase="follow_prerequisite",
    )
    assert action is not None
    assert action.target == "prerequisite stage candidate: 出航日"


def test_story_prerequisite_mode_uses_enlarged_locked_stage_number() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("06", 620, 850), item("湖中仙女", 655, 896),
            item("077", 1193, 850),
        ],
        story_prerequisite_phase="follow_prerequisite",
        blocked_story_stage="湖中仙女",
    )
    assert action is not None
    assert action.target == "locked prerequisite stage node: 077"
    assert (action.x, action.y) == (1264, 880)


def test_story_prerequisite_never_restarts_blocked_stage_detail() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("06"), item("湖中仙女", 1500, 220), item("开始行动", 1734, 912)],
        story_prerequisite_phase="follow_prerequisite",
        blocked_story_stage="湖中仙女",
    )
    assert action is not None
    assert action.target == "open chapter selection with in-game arrow"


def test_story_prerequisite_starts_new_stage_when_old_title_is_only_in_map_background() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [
            item("07"), item("厢情愿", 1500, 220),
            item("湖中仙女", 655, 896), item("开始行动", 1734, 912),
        ],
        story_prerequisite_phase="follow_prerequisite",
        blocked_story_stage="湖中仙女",
    )
    assert action is not None
    assert action.target == "开始行动"


def test_story_prerequisite_never_uses_blocked_stage_title_as_fallback() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("06/", 620, 850), item("湖中仙女", 655, 896)],
        story_prerequisite_phase="follow_prerequisite",
        blocked_story_stage="湖中仙女",
    )
    assert action is None


def test_story_prerequisite_mode_lets_model_find_real_chapter_navigation() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("04/", 656, 848), item("湖中仙女", 654, 897)],
        story_prerequisite_phase="return_to_chapters",
    )
    assert action is None


def test_story_prerequisite_mode_leaves_repeated_stage_using_ui_arrow() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("06"), item("开始行动", 1734, 912)],
        story_prerequisite_phase="return_to_chapters",
    )
    assert action is not None
    assert action.target == "open chapter selection with in-game arrow"
    assert (action.x, action.y) == (67, 68)


def test_story_prerequisite_requirement_opens_side_story_location() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("远处，似乎有事或物在等待着你"), item("0/1", 1475, 434)],
        story_prerequisite_phase="follow_prerequisite",
    )
    assert action is not None
    assert action.target == "open required side story location"
    assert (action.x, action.y) == (1556, 434)


def test_story_start_action_has_priority_over_visible_map_node() -> None:
    image = Image.new("RGB", (1920, 1080))
    action = decide_locally(
        Workflow.STORY,
        image,
        [item("04/", 656, 848), item("出航日", 626, 897), item("开始行动", 1734, 912)],
    )
    assert action is not None
    assert action.target == "开始行动"
