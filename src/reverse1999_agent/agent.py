from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from pathlib import Path

from .adb import AdbClient
from .agent_memory import AgentMemory
from .config import Settings
from .local_policy import decide_locally
from .models import AgentAction, ScreenState, StepRecord, Workflow
from .planner import VisionPlanner
from .policy import DEFAULT_POLICY
from .story_progress import StoryProgressTracker
from .story_knowledge import StoryKnowledgeBase
from .vision import OcrReader, format_ocr, orange_action_center, screen_change_ratio
from .workflows import workflow_prompt


LOG = logging.getLogger("reverse1999_agent")


class SafetyViolation(RuntimeError):
    pass


class GameAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adb = AdbClient(settings.adb_path, settings.adb_serial)
        self.planner: VisionPlanner | None = None
        self.history: deque[str] = deque(maxlen=6)
        self.failed_tap_points: deque[tuple[int, int]] = deque(maxlen=10)
        self.no_effect_tap_count = 0
        self.ocr = OcrReader(settings.enable_ocr)
        self.battle_marker: str | None = None
        self.battle_stall_count = 0
        self.battle_auto_attempted = False
        self.battle_auto_attempt_marker: str | None = None
        self.battle_auto_wait_count = 0
        self.battle_auto_confirmed = False
        self.battle_manual = False
        self.battle_absent_count = 0
        self.battle_auto_started_at: float | None = None
        self.last_battle_timeout_recovery_at: float | None = None
        self.manual_card_count = 0
        self.manual_resolution_waits = 0
        self.watchdog_image = None
        self.watchdog_battle_marker: str | None = None
        self.watchdog_started_at = time.monotonic()
        self.prevent_immediate_stage_replay = False
        # Restore prerequisite progress so restarting in the middle of a required side story
        # does not route the same screen through an unrelated normal-story policy.
        self.story_progress = StoryProgressTracker.from_steps_log(Path("logs/steps.jsonl"))
        self.story_knowledge = StoryKnowledgeBase.load_default()
        self.memory_path = Path("work/agent_state.json")
        self.memory = AgentMemory.load(self.memory_path)

    def _get_planner(self) -> VisionPlanner:
        if self.planner is None:
            self.planner = VisionPlanner(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                model=self.settings.model,
            )
        return self.planner

    @staticmethod
    def _has_forbidden_intent(text: str, forbidden: tuple[str, ...]) -> bool:
        lowered = text.lower()
        negations = (
            "不涉及", "不使用", "不进行", "不会", "无需", "禁止", "避免", "不可",
            "未使用", "没有", "not ", "no ", "without ", "avoid ", "never ",
        )
        for word in forbidden:
            start = lowered.find(word)
            while start >= 0:
                prefix = lowered[max(0, start - 12):start]
                if not any(marker in prefix for marker in negations):
                    return True
                start = lowered.find(word, start + len(word))
        return False

    @staticmethod
    def _validate(action: AgentAction, width: int, height: int) -> None:
        if action.action in {"tap", "swipe"}:
            points = [(action.x, action.y)]
            if action.action == "swipe":
                points.append((action.x2, action.y2))
            for x, y in points:
                if x is None or y is None or not (0 <= x < width and 0 <= y < height):
                    raise SafetyViolation(f"coordinate outside screenshot: {(x, y)} vs {width}x{height}")

        forbidden = (
            "purchase", "payment", "recharge", "gacha", "summon", "paid",
            "充值", "购买", "支付", "抽卡", "召唤", "礼包", "账号", "删除",
        )
        description = f"{action.target} {action.reason}"
        # “支付/消耗 N 点体力” describes an ordinary stamina cost, not money.
        safety_description = re.sub(
            r"支付\s*\d+\s*点?(?:体力|活性|消耗)",
            "消耗体力",
            description,
        )
        if (
            GameAgent._has_forbidden_intent(safety_description, forbidden)
            and action.action not in {"back", "wait", "finish"}
        ):
            raise SafetyViolation(f"forbidden target detected: {action.target}")

        if action.resource_type == "currency":
            raise SafetyViolation("currency may not be used to restore stamina")
        if action.resource_type == "stamina_item":
            if action.stamina_items_total_before is None:
                raise SafetyViolation(
                    "total stamina item count across all item types must be observed before use"
                )
            if not DEFAULT_POLICY.can_consume_stamina_items(
                action.stamina_items_total_before,
                action.consume_quantity,
            ):
                raise SafetyViolation(
                    "stamina item action would leave fewer than two items in total"
                )

    def _execute(self, action: AgentAction) -> None:
        if self.settings.dry_run:
            LOG.info("DRY RUN: would execute %s", action.model_dump_json())
            return
        if action.action == "tap":
            self.adb.tap(action.x or 0, action.y or 0)
        elif action.action == "swipe":
            self.adb.swipe(
                action.x or 0,
                action.y or 0,
                action.x2 or 0,
                action.y2 or 0,
                action.duration_ms,
            )
        elif action.action == "back":
            self.adb.back()
        elif action.action == "wait":
            time.sleep(action.wait_seconds)

    def run(
        self,
        workflow: Workflow,
        *,
        max_steps: int | None = None,
        character: str = "",
        target_level: int | None = None,
    ) -> AgentAction | None:
        self.settings.ensure_dirs()
        self.adb.connect()
        if self.adb.device_state() != "device":
            raise RuntimeError(f"MuMu device is not ready: {self.adb.device_state()}")

        prompt = workflow_prompt(workflow, character, target_level)
        self.memory.prepare_run(workflow)
        self.memory.save(self.memory_path)
        limit = max_steps or self.settings.max_steps
        recovering_to_character_home = (
            workflow is Workflow.CHARACTER and self.memory.development_required
        )

        for step in range(1, limit + 1):
            before = self.adb.screenshot()
            context = "\n".join(self.history)
            memory_hint = self.memory.context_hint(workflow)
            context = f"{context}\n{memory_hint}".strip()
            if recovering_to_character_home:
                context = (
                    f"{context}\n战败后的养成导航恢复仍未完成：当前若仍是原主线、"
                    "关卡详情或编队画面，必须返回，绝不能点击其中的“开始行动”。"
                    "先回到主界面并点击“角色”；只有进入角色养成界面后，才可把"
                    "后续来源关卡当作材料副本。"
                ).strip()
            progress_hint = self.story_progress.context_hint()
            if progress_hint:
                context = f"{context}\n{progress_hint}".strip()
            ocr_items = self.ocr.read(before)
            width, height = before.size
            resource_region = (round(width * 0.14), round(height * 0.79), round(width * 0.58), height)
            ocr_items.extend(self.ocr.read_region(before, resource_region, scale=2))
            if workflow is Workflow.STORY:
                story_node_region = (
                    round(width * 0.47),
                    round(height * 0.60),
                    round(width * 0.84),
                    round(height * 0.96),
                )
                ocr_items.extend(self.ocr.read_region(before, story_node_region, scale=3))
            ocr_text = format_ocr(ocr_items)
            lineup_capture_due = (
                workflow is Workflow.STORY
                and any(
                    item.text.strip() == "开始行动"
                    and item.confidence >= 0.75
                    and item.center_y >= height * 0.88
                    for item in ocr_items
                )
            )
            if lineup_capture_due:
                context = (
                    f"{context}\n当前疑似最终编队确认页。执行下一步的同时，必须读取画面中"
                    "实际上阵的全部角色姓名并写入team_members；不要写候选角色或助战角色。"
                ).strip()
            force_planner_recovery = self.no_effect_tap_count >= 3
            if force_planner_recovery:
                failed_points = ", ".join(
                    f"({x},{y})" for x, y in self.failed_tap_points
                )
                orange_candidate = orange_action_center(before)
                recovery_hint = (
                    f"故障恢复：最近连续{self.no_effect_tap_count}次点击没有产生有效画面变化。"
                    f"已失败坐标：{failed_points or '未知'}。不要重复猜测这些位置；"
                    "重新识别真正的控件边界和中心。"
                )
                if orange_candidate is not None:
                    recovery_hint += (
                        f" OpenCV检测到大型橙色矩形中心为{orange_candidate}，"
                        "若它与目标按钮一致，应优先点击这个精确中心。"
                    )
                context = f"{context}\n{recovery_hint}".strip()
            if workflow is Workflow.STORY:
                knowledge_hint = self.story_knowledge.context_hint(
                    item.text for item in ocr_items if item.confidence >= 0.65
                )
                if knowledge_hint:
                    context = f"{context}\n{knowledge_hint}".strip()
            # The top-left counter is commonly returned by OCR as two adjacent boxes
            # ("轮次:1/1" and "回合:1/20"), not one combined string.
            round_marker = next(
                (item.text.strip() for item in ocr_items if "轮次" in item.text),
                "",
            )
            turn_marker = next(
                (item.text.strip() for item in ocr_items if "回合" in item.text),
                "",
            )
            round_numbers = re.search(r"(\d+)\s*/\s*(\d+)", round_marker)
            turn_numbers = re.search(r"(\d+)\s*/\s*(\d+)", turn_marker)
            current_battle_marker = (
                f"round:{round_numbers.group(1)}/{round_numbers.group(2)}|"
                f"turn:{turn_numbers.group(1)}/{turn_numbers.group(2)}"
                if round_numbers and turn_numbers
                else None
            )
            battle_visible = current_battle_marker is not None or any(
                item.text.strip() == "敌我情报" for item in ocr_items
            )
            has_visible_skill_card = any(
                item.center_y >= height * 0.80
                and any(
                    label in item.text.lower()
                    for label in ("attack", "buff", "debuff", "channel", "counter")
                )
                for item in ocr_items
            )
            if not battle_visible:
                self.battle_absent_count += 1
                if self.battle_absent_count >= 3:
                    self.battle_marker = None
                    self.battle_stall_count = 0
                    self.battle_auto_attempted = False
                    self.battle_auto_attempt_marker = None
                    self.battle_auto_wait_count = 0
                    self.battle_auto_confirmed = False
                    self.battle_manual = False
                    self.battle_auto_started_at = None
                    self.last_battle_timeout_recovery_at = None
                    self.manual_card_count = 0
                    self.manual_resolution_waits = 0
            elif current_battle_marker is None:
                # A toast or attack effect can temporarily cover the counter. Missing OCR is
                # unknown state, not evidence that the turn advanced.
                self.battle_absent_count = 0
                pass
            elif self.battle_marker is None:
                self.battle_absent_count = 0
                self.battle_marker = current_battle_marker
            elif current_battle_marker == self.battle_marker:
                self.battle_absent_count = 0
                self.battle_stall_count += 1
            else:
                self.battle_absent_count = 0
                self.battle_marker = current_battle_marker
                self.battle_stall_count = 0
                # While filling a manual turn, OCR fluctuations must not restart at card one.
                # A new turn may reset the queue only after all four cards were submitted.
                if (
                    not self.battle_manual
                    or (self.manual_card_count >= 4 and self.manual_resolution_waits >= 1)
                ):
                    self.manual_card_count = 0
                    self.manual_resolution_waits = 0
                if self.battle_auto_attempted and not self.battle_manual:
                    self.battle_auto_confirmed = True

            if (
                battle_visible
                and self.battle_auto_attempted
                and not self.battle_auto_confirmed
                and not self.battle_manual
            ):
                if (
                    self.battle_auto_attempt_marker is None
                    or current_battle_marker == self.battle_auto_attempt_marker
                ):
                    self.battle_auto_wait_count += 1
                    if self.battle_auto_wait_count >= 2:
                        self.battle_manual = True
                        self.battle_auto_started_at = None
                        self.manual_card_count = 0
                        LOG.warning(
                            "auto battle did not advance; switching to card-strip-only manual fallback"
                        )
            now = time.monotonic()
            battle_auto_timeout_due = bool(
                battle_visible
                and self.battle_auto_started_at is not None
                and now - self.battle_auto_started_at >= 300
                and (
                    self.last_battle_timeout_recovery_at is None
                    or now - self.last_battle_timeout_recovery_at >= 60
                )
            )
            global_watchdog_recovery_due = False
            if self.watchdog_image is None:
                self.watchdog_image = before.copy()
                self.watchdog_battle_marker = current_battle_marker
                self.watchdog_started_at = now
            elif now - self.watchdog_started_at >= 300:
                watchdog_ratio = screen_change_ratio(self.watchdog_image, before)
                same_battle_round = bool(
                    current_battle_marker
                    and current_battle_marker == self.watchdog_battle_marker
                )
                global_watchdog_recovery_due = watchdog_ratio < 0.08 or same_battle_round
                if global_watchdog_recovery_due:
                    context = (
                        f"{context}\n全局进度看门狗：五分钟前截图与当前截图的变化率为"
                        f"{watchdog_ratio:.3f}，同一战斗回合={same_battle_round}。"
                        "疑似长时间无实质进展；请重新分析当前画面并选择安全恢复动作，"
                        "不要仅因背景动画而继续等待。"
                    ).strip()
                self.watchdog_image = before.copy()
                self.watchdog_battle_marker = current_battle_marker
                self.watchdog_started_at = now

            if battle_auto_timeout_due:
                elapsed = round(now - (self.battle_auto_started_at or now))
                context = (
                    f"{context}\n自动战斗超时保险：本次自动战斗已持续约{elapsed}秒，"
                    "超过五分钟上限。必须重新判断是否卡在对白、结算、手动出牌或自动按钮状态；"
                    "不要继续无条件等待。"
                ).strip()

            action = decide_locally(
                workflow,
                before,
                ocr_items,
                battle_click_auto=(
                    battle_visible
                    and not self.battle_auto_attempted
                    and self.battle_stall_count >= 2
                ),
                battle_manual=self.battle_manual,
                manual_card_slot=self.manual_card_count,
                battle_force_dialogue=(
                    battle_visible
                    and (self.battle_auto_confirmed or self.battle_manual)
                    and self.battle_stall_count >= 4
                    and not has_visible_skill_card
                ),
                story_prerequisite_phase=self.story_progress.phase,
                blocked_story_stage=self.story_progress.blocked_stage,
                known_story_chapters=self.story_knowledge.chapter_titles,
                excluded_story_entries=self.story_knowledge.excluded_entries,
                resume_story_subchapter=(
                    self.memory.checkpoint.subchapter
                    if self.memory.story_start_mode == "resume_checkpoint"
                    else ""
                ),
                resume_story_stage=(
                    self.memory.checkpoint.stage
                    if self.memory.story_start_mode == "resume_checkpoint"
                    else ""
                ),
                story_scan_phase=(
                    self.memory.scan_phase
                    if workflow is Workflow.STORY and self.memory.scan_required
                    else "idle"
                ),
                target_character=character,
                target_level=target_level,
            )
            if (
                force_planner_recovery
                or battle_auto_timeout_due
                or global_watchdog_recovery_due
                or lineup_capture_due
            ):
                action = None
            if action is None:
                action = self._get_planner().decide(before, prompt, context, ocr_text)
            else:
                LOG.info("step=%d used local policy", step)

            if (
                workflow is Workflow.STORY
                and self.story_progress.observe_stage_selection(action.target, step)
            ):
                action = AgentAction(
                    state=ScreenState.STORY,
                    action="back",
                    target="return to chapter selection after repeated completed stage",
                    reason=(
                        f"检测到关卡{self.story_progress.blocked_stage}在完整流程后再次出现；"
                        "停止重打并返回章节选择页寻找下一章的前置支线"
                    ),
                    confidence=0.99,
                )
            if (
                workflow is Workflow.STORY
                and self.prevent_immediate_stage_replay
                and action.target == "开始行动"
            ):
                action = AgentAction(
                    state=ScreenState.STORY,
                    action="back",
                    target="leave completed stage detail before selecting next stage",
                    reason="刚完成战斗后仍停留在同一关详情页，返回地图，禁止立即重打同一关",
                    confidence=0.99,
                )
            if (
                recovering_to_character_home
                and "开始行动" in action.target
            ):
                action = AgentAction(
                    state=ScreenState.CHARACTER,
                    action="back",
                    target="leave defeated story stage before development",
                    reason="人物养成刚由主线战败触发；先退出原主线，禁止将其误判为材料副本重打",
                    confidence=0.99,
                )
            if recovering_to_character_home and action.target == "角色":
                recovering_to_character_home = False
            if action.target.startswith(
                (
                    "latest visible story stage:",
                    "prerequisite stage candidate:",
                    "resume story stage:",
                )
            ):
                self.prevent_immediate_stage_replay = False
            self.story_progress.note_action_target(action.target)
            if workflow is Workflow.STORY and action.team_members:
                observed_team = list(
                    dict.fromkeys(
                        name.strip() for name in action.team_members if name.strip()
                    )
                )
                if observed_team:
                    self.memory.current_team = observed_team
                    self.memory.save(self.memory_path)
                    LOG.info("saved current battle team: %s", "、".join(observed_team))
            if (
                workflow is Workflow.CHARACTER
                and action.selected_character
                and self.memory.current_team
                and not DEFAULT_POLICY.character_is_allowed(
                    action.selected_character,
                    set(self.memory.current_team),
                )
            ):
                LOG.warning(
                    "blocked development of non-team character: %s; saved team=%s",
                    action.selected_character,
                    self.memory.current_team,
                )
                action = AgentAction(
                    state=ScreenState.CHARACTER,
                    action="back",
                    target="reject non-team character selection",
                    reason="候选角色不在战前保存的当前队伍名单中，返回重新选择",
                    confidence=0.99,
                )
            try:
                self._validate(action, *before.size)
            except SafetyViolation as exc:
                LOG.warning(
                    "blocked unsafe action without terminating agent: %s; action=%s",
                    exc,
                    action.model_dump_json(),
                )
                action = AgentAction(
                    state=action.state,
                    action="wait",
                    wait_seconds=2,
                    target="safety rejection recovery",
                    reason="安全校验拒绝了上一步候选动作；保持运行并在下一帧重新判断",
                    confidence=0.99,
                )

            visible_collection = next(
                (
                    title
                    for title in self.story_knowledge.collection_titles
                    if any(title in item.text for item in ocr_items)
                ),
                "",
            )

            record = StepRecord(
                step=step,
                workflow=workflow,
                screenshot_size=before.size,
                action=action,
            )
            LOG.info("step=%d decision=%s", step, action.model_dump_json())

            if action.action == "finish":
                self.memory.observe(
                    workflow,
                    action,
                    visible_collection=visible_collection,
                )
                self.memory.save(self.memory_path)
                LOG.info("workflow finished: %s", action.reason)
                return action

            if (
                workflow is Workflow.STORY
                and action.state is ScreenState.RESULT
                and action.action == "tap"
            ):
                self.prevent_immediate_stage_replay = True

            self._execute(action)
            if self.settings.dry_run:
                return

            if action.target == "enable auto battle":
                self.battle_auto_attempted = True
                self.battle_auto_attempt_marker = current_battle_marker
                self.battle_auto_wait_count = 0
                self.battle_auto_started_at = time.monotonic()

            if battle_auto_timeout_due:
                self.last_battle_timeout_recovery_at = time.monotonic()

            if action.target.startswith("manual battle skill"):
                self.manual_card_count += 1
                self.manual_resolution_waits = 0
            elif action.target == "manual battle turn resolution":
                self.manual_resolution_waits += 1
                if self.manual_resolution_waits >= 2:
                    # A missed card or a special turn can leave the queue incomplete. Retry the
                    # same bounded card strip instead of becoming permanently stuck.
                    self.manual_card_count = 0
                    self.manual_resolution_waits = 0

            time.sleep(self.settings.step_delay_seconds)
            after = self.adb.screenshot()
            if action.target == "enable auto battle":
                auto_feedback = self.ocr.read(after)
                if any("无法使用" in item.text for item in auto_feedback):
                    self.battle_manual = True
                    self.battle_auto_confirmed = False
                    self.battle_auto_started_at = None
                    self.manual_card_count = 0
                    LOG.warning(
                        "game reported auto battle unavailable; locking current battle to manual fallback"
                    )
            ratio = screen_change_ratio(before, after)
            record.changed = ratio >= 0.01
            if action.action == "tap" and ratio < 0.005:
                self.no_effect_tap_count += 1
                if action.x is not None and action.y is not None:
                    self.failed_tap_points.append((action.x, action.y))
            elif ratio >= 0.005:
                self.no_effect_tap_count = 0
                self.failed_tap_points.clear()
            self.memory.observe(
                workflow,
                action,
                visible_collection=visible_collection,
                changed=record.changed,
            )
            self.memory.save(self.memory_path)
            coordinates = (
                f" at ({action.x},{action.y})"
                if action.action == "tap"
                else ""
            )
            outcome = (
                f"step {step}: {action.action}{coordinates} {action.target!r}; "
                f"screen_change={ratio:.3f}; no_effect_taps={self.no_effect_tap_count}"
            )
            self.history.append(outcome)
            LOG.info(outcome)

            snapshot = self.settings.artifact_dir / "latest.png"
            after.save(snapshot)
            with Path("logs/steps.jsonl").open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

        LOG.warning("maximum step count reached without a finish decision")
        return None
