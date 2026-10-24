from reverse1999_agent.planner import parse_action


def test_parse_action_clamps_model_wait_time() -> None:
    action = parse_action(
        '{"state":"character","action":"tap","x":10,"y":20,'
        '"target":"jump","reason":"test","confidence":0.9,"wait_seconds":0}'
    )
    assert action.wait_seconds == 0.2


def test_parse_action_accepts_json_fence() -> None:
    action = parse_action(
        '```json\n{"state":"loading","action":"wait","target":"",'
        '"reason":"loading","confidence":0.8}\n```'
    )
    assert action.action == "wait"


def test_parse_action_uses_defaults_for_null_optional_timing() -> None:
    action = parse_action(
        '{"state":"home","action":"tap","x":10,"y":20,"target":"entry",'
        '"reason":"test","confidence":0.8,"wait_seconds":null,"duration_ms":null}'
    )
    assert action.wait_seconds == 2.0
    assert action.duration_ms == 350


def test_parse_action_normalizes_null_optional_policy_fields() -> None:
    action = parse_action(
        '{"state":"story","action":"tap","x":10,"y":20,"target":"next",'
        '"reason":"test","confidence":0.8,"selected_character":null,'
        '"resource_type":null,"consume_quantity":null}'
    )
    assert action.selected_character == ""
    assert action.resource_type == "none"
    assert action.consume_quantity == 0
