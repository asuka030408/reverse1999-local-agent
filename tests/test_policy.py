import pytest

from reverse1999_agent.agent import GameAgent, SafetyViolation
from reverse1999_agent.models import AgentAction
from reverse1999_agent.policy import DEFAULT_POLICY


def test_stamina_item_keeps_two_in_reserve() -> None:
    assert DEFAULT_POLICY.can_consume_stamina_items(3, 1)
    assert not DEFAULT_POLICY.can_consume_stamina_items(2, 1)
    assert not DEFAULT_POLICY.can_consume_stamina_items(5, 4)


def test_stamina_reserve_is_total_not_per_item_type() -> None:
    # For example, counts 1 + 1 + 2 across three types total four items.
    assert DEFAULT_POLICY.can_consume_stamina_items(4, 1)


def test_development_is_limited_to_current_team() -> None:
    team = {"环状水星", "J", "梅兰妮"}
    assert DEFAULT_POLICY.character_is_allowed("环状水星", team)
    assert not DEFAULT_POLICY.character_is_allowed("未上阵角色", team)


def test_validator_rejects_currency_for_stamina() -> None:
    action = AgentAction(
        action="tap",
        x=100,
        y=100,
        target="restore stamina",
        resource_type="currency",
    )
    with pytest.raises(SafetyViolation, match="currency"):
        GameAgent._validate(action, 1920, 1080)


def test_validator_requires_two_stamina_items_to_remain() -> None:
    action = AgentAction(
        action="tap",
        x=100,
        y=100,
        target="use stamina item",
        resource_type="stamina_item",
        stamina_items_total_before=2,
        consume_quantity=1,
    )
    with pytest.raises(SafetyViolation, match="fewer than two items in total"):
        GameAgent._validate(action, 1920, 1080)


def test_validator_requires_total_stamina_inventory() -> None:
    action = AgentAction(
        action="tap",
        x=100,
        y=100,
        target="use stamina item",
        resource_type="stamina_item",
        inventory_before=9,
        consume_quantity=1,
    )
    with pytest.raises(SafetyViolation, match="total stamina item count"):
        GameAgent._validate(action, 1920, 1080)


def test_validator_allows_negated_purchase_mention_in_safe_story_reason() -> None:
    action = AgentAction(
        state="story",
        action="tap",
        x=100,
        y=100,
        target="剧情选项：第一幕",
        reason="选择剧情选项继续推进，不涉及购买或付费",
        confidence=0.9,
    )
    GameAgent._validate(action, 1920, 1080)


def test_validator_still_rejects_positive_purchase_intent() -> None:
    action = AgentAction(
        state="popup",
        action="tap",
        x=100,
        y=100,
        target="购买礼包",
        reason="确认购买并领取资源",
        confidence=0.9,
    )
    with pytest.raises(SafetyViolation, match="forbidden target"):
        GameAgent._validate(action, 1920, 1080)


def test_validator_allows_stamina_cost_described_as_payment() -> None:
    action = AgentAction(
        state="story",
        action="tap",
        x=100,
        y=100,
        target="开始行动",
        reason="体力88足够支付18点消耗，点击开始行动推进主线。",
        confidence=0.9,
    )
    GameAgent._validate(action, 1920, 1080)
