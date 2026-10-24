from __future__ import annotations

import re

from PIL import Image

from .models import AgentAction, ScreenState, Workflow
from .vision import OcrItem, deficient_ratios, orange_action_center


SAFE_STORY_BUTTONS = (
    "跳过",
    "继续",
    "下一步",
    "领取",
    "开始行动",
    "进入战斗",
)


def _find_text(items: list[OcrItem], labels: tuple[str, ...]) -> OcrItem | None:
    candidates = [
        item
        for item in items
        if item.confidence >= 0.75 and any(label == item.text.strip() for label in labels)
    ]
    return max(candidates, key=lambda item: item.confidence, default=None)


def _ratio_slot_count(items: list[OcrItem], height: int) -> int:
    xs = sorted(
        item.center_x
        for item in items
        if item.center_y >= height * 0.84 and "/" in item.text
    )
    clusters: list[int] = []
    for x in xs:
        if not clusters or x - clusters[-1] >= 35:
            clusters.append(x)
    return len(clusters)


def _chapter_icon_y(title_y: int, height: int) -> int:
    """Chapter labels are captions; the interactive card/icon is directly above them."""
    return max(round(height * 0.22), title_y - round(height * 0.24))


def decide_locally(
    workflow: Workflow,
    image: Image.Image,
    ocr_items: list[OcrItem],
    *,
    battle_click_auto: bool = False,
    battle_manual: bool = False,
    manual_card_slot: int = 0,
    battle_force_dialogue: bool = False,
    story_prerequisite_phase: str = "normal",
    blocked_story_stage: str = "",
    known_story_chapters: tuple[str, ...] = (),
    excluded_story_entries: tuple[str, ...] = (),
    resume_story_subchapter: str = "",
    resume_story_stage: str = "",
    story_scan_phase: str = "idle",
    target_character: str = "",
    target_level: int | None = None,
) -> AgentAction | None:
    """Return only highly conservative actions; ambiguous screens go to the model."""
    texts = {item.text.strip() for item in ocr_items if item.confidence >= 0.75}

    has_single_summon = any("征集一次" in text for text in texts)
    has_ten_summon = any("征集十次" in text for text in texts)
    summon_screen = any("银行兑换" in text for text in texts) or (
        has_single_summon and has_ten_summon
    )
    if summon_screen:
        return AgentAction(
            state=ScreenState.POPUP,
            action="back",
            target="退出征集界面",
            reason="识别到征集详情界面，立即返回，不执行任何征集操作",
            confidence=0.99,
        )

    portray_screen = "塑造详情" in texts or (
        "塑造" in texts and "材料不足" in texts
    )
    if portray_screen:
        return AgentAction(
            state=ScreenState.CHARACTER,
            action="back",
            target="leave portray screen",
            reason="塑造材料只能通过重复征集角色获得，不属于可刷取养成资源，立即返回",
            confidence=0.99,
        )

    if workflow is Workflow.STORY:
        home_marker_count = sum(label in texts for label in ("邮件", "任务", "仓库", "银行"))
        has_story_entry = "入场" in texts or "ENTER" in texts
        if home_marker_count >= 2 and has_story_entry:
            return AgentAction(
                state=ScreenState.HOME,
                action="tap",
                x=round(image.width * 0.89),
                y=round(image.height * 0.47),
                target="主界面右侧入场",
                reason="已识别主界面；按照用户指定路径点击右侧“入场”进入剧情，不打开任务或顶部活动图标",
                confidence=0.99,
            )

    if target_character and target_level:
        completion_text = f"{target_character}等级上限提升至{target_level}级"
        if any(completion_text in text for text in texts):
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="finish",
                target="character development complete",
                reason=f"已确认{completion_text}",
                confidence=0.99,
            )

    battle_visible = "敌我情报" in texts or any(
        "轮次" in text and "回合" in text for text in texts
    )
    if battle_visible:
        if battle_force_dialogue:
            return AgentAction(
                state=ScreenState.BATTLE,
                action="tap",
                x=round(image.width * 0.50),
                y=round(image.height * 0.18),
                target="advance stalled in-battle dialogue",
                reason="同一回合长期未变化且底部没有技能卡，点击战斗剧情提示区域继续",
                confidence=0.96,
            )
        if battle_manual:
            if manual_card_slot < 4:
                width, height = image.size
                # Selected cards disappear and the remaining hand stacks toward the right.
                # Therefore every pick uses the same rightmost slot; moving left would risk
                # clicking an empty position when only a few cards remain.
                slot = max(0, min(manual_card_slot, 3))
                return AgentAction(
                    state=ScreenState.BATTLE,
                    action="tap",
                    x=round(width * 0.946),
                    y=round(height * 0.84),
                    target=f"manual battle skill {slot + 1}/4",
                    reason="自动战斗未能推进；卡片会向右补位，因此连续点击最右侧技能卡，避免点到空位",
                    confidence=0.98,
                )
            return AgentAction(
                state=ScreenState.BATTLE,
                action="wait",
                wait_seconds=6,
                target="manual battle turn resolution",
                reason="已选择四张技能牌，等待本回合结算和下一回合发牌",
                confidence=0.98,
            )
        if battle_click_auto:
            width, height = image.size
            return AgentAction(
                state=ScreenState.BATTLE,
                action="tap",
                x=round(width * 0.867),
                y=round(height * 0.058),
                target="enable auto battle",
                reason="检测到战斗界面，点击右上角第三个自动战斗按钮",
                confidence=0.97,
            )
        return AgentAction(
            state=ScreenState.BATTLE,
            action="wait",
            wait_seconds=10,
            target="battle progress",
            reason="观察回合是否自动推进；只有连续停滞才点击自动按钮",
            confidence=0.95,
        )

    if workflow is Workflow.STORY:
        story_orange_evidence = any(
            marker in text
            for text in texts
            for marker in (
                "小径", "前置", "解锁下一剧情", "完成后解锁", "开始行动", "剧情"
            )
        )
        orange_center = orange_action_center(image) if story_orange_evidence else None
        if orange_center is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=orange_center[0],
                y=orange_center[1],
                target="visible orange story action button",
                reason="OpenCV检测到独立的大型橙色按钮，点击其实际矩形中心而不是让视觉模型猜坐标",
                confidence=0.98,
            )

    if workflow is Workflow.STORY:
        start_action = _find_text(ocr_items, ("开始行动",))
        if (
            start_action is not None
            and (
                story_prerequisite_phase in {"return_to_chapters", "choose_next_chapter"}
                or (
                    story_prerequisite_phase == "follow_prerequisite"
                    and blocked_story_stage
                    and any(
                        item.text.strip() == blocked_story_stage
                        and item.center_y < image.height * 0.5
                        for item in ocr_items
                    )
                )
            )
            and any(re.fullmatch(r"\d{2}\s*/?", text) for text in texts)
        ):
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=round(image.width * 0.035),
                y=round(image.height * 0.063),
                target="open chapter selection with in-game arrow",
                reason="重复关卡详情页已打开，点击左上角游戏内三角箭头返回章节列表",
                confidence=0.98,
            )
        if start_action is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=start_action.center_x,
                y=start_action.center_y,
                target="开始行动",
                reason="剧情关卡或编队页面已就绪，优先开始行动",
                confidence=start_action.confidence,
            )

    if workflow is Workflow.STORY and {"故事", "映像", "轶事", "资源"}.issubset(texts):
        resume_chapter = next(
            (
                item
                for item in ocr_items
                if resume_story_subchapter
                and item.text.strip() == resume_story_subchapter
            ),
            None,
        )
        if resume_chapter is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=resume_chapter.center_x,
                y=_chapter_icon_y(resume_chapter.center_y, image.height),
                target=f"resume story subchapter: {resume_chapter.text}",
                reason="培养结束后按持久化检查点返回原小章节，点击标题上方的卡片图标",
                confidence=resume_chapter.confidence,
            )
        if story_scan_phase == "seek_oldest":
            return AgentAction(
                state=ScreenState.STORY,
                action="swipe",
                x=round(image.width * 0.27),
                y=round(image.height * 0.52),
                x2=round(image.width * 0.78),
                y2=round(image.height * 0.52),
                duration_ms=700,
                target="scan toward oldest story page",
                reason="正常启动时先向前翻到最早的故事页；滑动不再改变画面后再顺序检查",
                confidence=0.99,
            )
        visible_locked_cards = [
            item
            for item in ocr_items
            if item.confidence >= 0.75
            and any(marker in item.text.strip() for marker in ("未解锁", "尚未解锁", "LOCKED"))
            and image.height * 0.25 <= item.center_y <= image.height * 0.72
        ]
        if story_scan_phase == "scan_forward" and not visible_locked_cards:
            return AgentAction(
                state=ScreenState.STORY,
                action="swipe",
                x=round(image.width * 0.78),
                y=round(image.height * 0.52),
                x2=round(image.width * 0.27),
                y2=round(image.height * 0.52),
                duration_ms=700,
                target="scan forward story page",
                reason="当前页没有“未解锁”，继续向后逐页检查",
                confidence=0.99,
            )
        chapter_order = {title: index for index, title in enumerate(known_story_chapters)}
        known_candidates = [
            item for item in ocr_items if item.text.strip() in chapter_order
        ]
        if known_candidates and story_scan_phase == "idle":
            chapter = max(known_candidates, key=lambda item: chapter_order[item.text.strip()])
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=chapter.center_x,
                y=_chapter_icon_y(chapter.center_y, image.height),
                target=(
                    f"next permanent chapter: {chapter.text}"
                    if story_prerequisite_phase != "normal"
                    else f"latest permanent chapter: {chapter.text}"
                ),
                reason="依据离线常驻主线知识库选择序号最大的已显示章节，忽略预演、特别篇和活动入口",
                confidence=chapter.confidence,
            )
        chapter_titles = [
            item
            for item in ocr_items
            if image.height * 0.72 <= item.center_y <= image.height * 0.82
            and item.center_x < image.width * 0.96
            and re.search(r"[\u4e00-\u9fff]", item.text)
            and item.text.strip() not in {"故事", "映像", "轶事", "资源"}
            and item.text.strip() not in excluded_story_entries
        ]
        if chapter_titles:
            locked_cards = visible_locked_cards
            if locked_cards:
                first_locked_x = min(item.center_x for item in locked_cards)
                unlocked_before_lock = [
                    item for item in chapter_titles if item.center_x < first_locked_x - image.width * 0.04
                ]
                chapter = (
                    max(unlocked_before_lock, key=lambda item: item.center_x)
                    if unlocked_before_lock
                    else min(chapter_titles, key=lambda item: item.center_x)
                )
                selection_reason = (
                    "检测到后续小章节未解锁，选择第一个锁定卡片之前最后一个可用小章节；"
                    "点击章节名称上方的卡片图标，而不是文字"
                )
            else:
                chapter = max(chapter_titles, key=lambda item: item.center_x)
                selection_reason = (
                    "当前画面未发现锁定标记，选择最右侧可见小章节；"
                    "点击章节名称上方的卡片图标，而不是文字"
                )
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=chapter.center_x,
                y=_chapter_icon_y(chapter.center_y, image.height),
                target=(
                    f"next chapter candidate: {chapter.text}"
                    if story_prerequisite_phase != "normal"
                    else f"latest unlocked chapter: {chapter.text}"
                ),
                reason=selection_reason,
                confidence=chapter.confidence,
            )

    story_map_visible = workflow is Workflow.STORY and any(
        re.search(r"\d{2}\s*/", text) or re.fullmatch(r"0\d\d?", text)
        for text in texts
    )
    if story_map_visible and story_scan_phase != "idle":
        return AgentAction(
            state=ScreenState.STORY,
            action="tap",
            x=round(image.width * 0.035),
            y=round(image.height * 0.063),
            target="return to story browser for full scan",
            reason="正常启动要求逐页检查，先用游戏内返回按钮离开当前地图并打开章节浏览页",
            confidence=0.98,
        )
    if story_map_visible and story_prerequisite_phase in {
        "return_to_chapters",
        "choose_next_chapter",
    }:
        # The Android back action can reopen the currently selected stage on some maps.
        # Let the vision planner locate the map's real chapter-selection control instead.
        return None

    if story_map_visible and story_prerequisite_phase in {"normal", "follow_prerequisite"}:
        resume_stage = next(
            (
                item
                for item in ocr_items
                if resume_story_stage and item.text.strip() == resume_story_stage
            ),
            None,
        )
        if resume_stage is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=resume_stage.center_x,
                y=resume_stage.center_y,
                target=f"resume story stage: {resume_stage.text}",
                reason="培养结束后按持久化检查点返回上次受阻的具体关卡",
                confidence=resume_stage.confidence,
            )
        if story_prerequisite_phase == "follow_prerequisite":
            stage_codes = [
                item
                for item in ocr_items
                if item.confidence >= 0.7
                and item.center_x >= image.width * 0.45
                and image.height * 0.7 <= item.center_y <= image.height * 0.9
                and re.search(r"0[7-9]", item.text.strip())
            ]
            if stage_codes:
                code = max(stage_codes, key=lambda item: item.center_x)
                return AgentAction(
                    state=ScreenState.STORY,
                    action="tap",
                    x=min(image.width - 1, code.center_x + round(image.width * 0.037)),
                    y=min(image.height - 1, code.center_y + round(image.height * 0.028)),
                    target=f"locked prerequisite stage node: {code.text}",
                    reason="放大OCR读取到最右侧章节编号，点击编号右下方的锁定节点查看下一条前置要求",
                    confidence=code.confidence,
                )
        stage_titles = [
            item
            for item in ocr_items
            if image.height * 0.78 <= item.center_y <= image.height * 0.9
            and item.center_x < image.width * 0.8
            and re.search(r"[\u4e00-\u9fff]{2,}", item.text)
            and item.text.strip() != blocked_story_stage
        ]
        if stage_titles:
            stage = max(stage_titles, key=lambda item: item.center_x)
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=stage.center_x,
                y=stage.center_y,
                target=(
                    f"prerequisite stage candidate: {stage.text}"
                    if story_prerequisite_phase == "follow_prerequisite"
                    else f"latest visible story stage: {stage.text}"
                ),
                reason=(
                    "下一章前置流程中点击地图最右侧的锁定或高亮节点以查看要求"
                    if story_prerequisite_phase == "follow_prerequisite"
                    else "关卡地图中点击最右侧可见的中文关卡节点继续进度"
                ),
                confidence=stage.confidence,
            )

    if workflow is Workflow.STORY and story_prerequisite_phase != "normal":
        requirement = next(
            (
                item
                for item in ocr_items
                if item.confidence >= 0.75 and re.fullmatch(r"0\s*/\s*1", item.text.strip())
            ),
            None,
        )
        if requirement is not None:
            return AgentAction(
                state=ScreenState.POPUP,
                action="tap",
                x=min(image.width - 1, requirement.center_x + round(image.width * 0.042)),
                y=requirement.center_y,
                target="open required side story location",
                reason="下一章锁定提示显示未完成小径0/1，点击右侧箭头定位前置支线",
                confidence=requirement.confidence,
            )

        prerequisite_evidence = story_map_visible or any(
            marker in text
            for text in texts
            for marker in ("小径", "前置", "解锁下一剧情", "完成后解锁")
        )
        orange_center = orange_action_center(image) if prerequisite_evidence else None
        if orange_center is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=orange_center[0],
                y=orange_center[1],
                target="highlighted prerequisite side-story action",
                reason="OpenCV检测到前置小径弹层中的大型橙色行动按钮，点击其几何中心",
                confidence=0.98,
            )

    if "战斗失败" in texts or "挑战失败" in texts:
        if workflow is Workflow.STORY:
            return AgentAction(
                state=ScreenState.RESULT,
                action="finish",
                target="story blocked by defeat",
                reason="检测到战斗失败，需要切换到人物养成工作流",
                confidence=0.99,
            )

    if "战斗胜利" in texts and "等级提升" in texts:
        width, height = image.size
        return AgentAction(
            state=ScreenState.RESULT,
            action="tap",
            x=round(width * 0.5),
            y=round(height * 0.83),
            target="dismiss level up overlay",
            reason="战斗胜利后出现等级提升遮罩，点击空白区域继续结算",
            confidence=0.96,
        )

    if "战斗胜利" in texts:
        exit_button = _find_text(ocr_items, ("返回来源", "继续", "确认"))
        if exit_button is not None:
            return AgentAction(
                state=ScreenState.RESULT,
                action="tap",
                x=exit_button.center_x,
                y=exit_button.center_y,
                target=exit_button.text,
                reason="本地 OCR 检测到战斗胜利，点击明确的结果页退出按钮",
                confidence=exit_button.confidence,
            )

    if workflow is Workflow.STORY and "战斗数据" in texts:
        width, height = image.size
        return AgentAction(
            state=ScreenState.POPUP,
            action="tap",
            x=round(width * 0.933),
            y=round(height * 0.129),
            target="battle stats close button",
            reason="本地 OCR 检测到战斗数据页，关闭统计页以继续剧情",
            confidence=0.97,
        )

    if workflow is Workflow.STORY:
        button = _find_text(ocr_items, SAFE_STORY_BUTTONS)
        if button is not None:
            return AgentAction(
                state=ScreenState.STORY,
                action="tap",
                x=button.center_x,
                y=button.center_y,
                target=button.text,
                reason="高置信度本地 OCR 命中安全剧情按钮",
                confidence=button.confidence,
            )

    if workflow is Workflow.CHARACTER and "洞悉所见" in texts:
        shortages = deficient_ratios(ocr_items)
        if shortages:
            item, available, required = shortages[0]
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="tap",
                x=item.center_x,
                y=max(0, item.center_y - 55),
                target=f"missing material {available}/{required}",
                reason="局部 OCR 检测到洞悉材料不足，点击缺少的材料图标查看来源",
                confidence=item.confidence,
            )
        if _ratio_slot_count(ocr_items, image.height) < 5:
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="wait",
                wait_seconds=1,
                target="retry insight resource reading",
                reason="洞悉页资源比例未完整识别，等待下一帧重新读取，禁止盲目升级",
                confidence=0.99,
            )
        upgrade = _find_text(ocr_items, ("洞悉",))
        if upgrade is not None:
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="tap",
                x=upgrade.center_x,
                y=upgrade.center_y,
                target="洞悉",
                reason="已完整读取全部资源比例且未发现缺口，执行洞悉",
                confidence=upgrade.confidence,
            )

    if workflow is Workflow.CHARACTER and "来源" in texts:
        jumps = [
            item
            for item in ocr_items
            if item.confidence >= 0.75 and item.text.strip() == "跳转"
        ]
        if jumps:
            selected = max(jumps, key=lambda item: item.center_y)
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="tap",
                x=selected.center_x,
                y=selected.center_y,
                target="highest listed material source",
                reason="材料来源列表已打开，选择列表中靠下的较高阶来源",
                confidence=selected.confidence,
            )

    if workflow is Workflow.CHARACTER:
        if target_character and target_character in texts and "SPIRIT" in texts:
            width, height = image.size
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="tap",
                x=round(width * 0.932),
                y=round(height * 0.836),
                target="close insight success screen",
                reason="洞悉成功展示页已完成，点击右下角关闭按钮返回角色界面",
                confidence=0.96,
            )

        insight_tab = _find_text(ocr_items, ("洞悉",))
        if target_character and target_character in texts and "Insight" in texts and insight_tab is not None:
            return AgentAction(
                state=ScreenState.CHARACTER,
                action="tap",
                x=insight_tab.center_x,
                y=insight_tab.center_y,
                target="洞悉 tab",
                reason=f"已确认当前角色为{target_character}，打开洞悉页面",
                confidence=insight_tab.confidence,
            )

        character_entry = _find_text(ocr_items, ("角色",))
        if character_entry is not None and "征集" in texts:
            return AgentAction(
                state=ScreenState.HOME,
                action="tap",
                x=character_entry.center_x,
                y=character_entry.center_y,
                target="角色",
                reason="主界面已识别，进入角色养成界面",
                confidence=character_entry.confidence,
            )

        start = _find_text(ocr_items, ("开始行动",))
        if start is not None:
            return AgentAction(
                state=ScreenState.RESOURCE_STAGE,
                action="tap",
                x=start.center_x,
                y=start.center_y,
                target="开始行动",
                reason="已进入缺失材料来源副本，消耗体力开始行动",
                confidence=start.confidence,
            )

    return None
