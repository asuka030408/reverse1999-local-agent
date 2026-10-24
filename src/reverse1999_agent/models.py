from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Workflow(str, Enum):
    STORY = "story"
    CHARACTER = "character"


class ScreenState(str, Enum):
    HOME = "home"
    STORY = "story"
    BATTLE = "battle"
    RESULT = "result"
    CHARACTER = "character"
    RESOURCE_STAGE = "resource_stage"
    POPUP = "popup"
    LOADING = "loading"
    UNKNOWN = "unknown"


class AgentAction(BaseModel):
    state: ScreenState = ScreenState.UNKNOWN
    action: Literal["tap", "swipe", "back", "wait", "finish"]
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    x2: int | None = Field(default=None, ge=0)
    y2: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=350, ge=50, le=3000)
    wait_seconds: float = Field(default=2.0, ge=0.2, le=15.0)
    target: str = ""
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    resource_type: Literal["none", "stamina_item", "currency"] = "none"
    inventory_before: int | None = Field(default=None, ge=0)
    stamina_items_total_before: int | None = Field(default=None, ge=0)
    consume_quantity: int = Field(default=0, ge=0)
    selected_character: str = ""
    team_members: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "AgentAction":
        if self.action == "tap" and (self.x is None or self.y is None):
            raise ValueError("tap requires x and y")
        if self.action == "swipe" and None in (self.x, self.y, self.x2, self.y2):
            raise ValueError("swipe requires x, y, x2 and y2")
        return self


class StepRecord(BaseModel):
    step: int
    workflow: Workflow
    screenshot_size: tuple[int, int]
    action: AgentAction
    changed: bool | None = None
