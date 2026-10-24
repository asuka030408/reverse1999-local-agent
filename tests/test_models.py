import pytest
from pydantic import ValidationError

from reverse1999_agent.models import AgentAction


def test_tap_requires_coordinates() -> None:
    with pytest.raises(ValidationError):
        AgentAction(action="tap", target="button")


def test_wait_needs_no_coordinates() -> None:
    action = AgentAction(action="wait", wait_seconds=1.5)
    assert action.action == "wait"
