from __future__ import annotations

import json

from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import AgentAction
from .vision import encode_jpeg


ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {
            "type": "string",
            "enum": ["home", "story", "battle", "result", "character", "resource_stage", "popup", "loading", "unknown"],
        },
        "action": {"type": "string", "enum": ["tap", "swipe", "back", "wait", "finish"]},
        "x": {"type": ["integer", "null"]},
        "y": {"type": ["integer", "null"]},
        "x2": {"type": ["integer", "null"]},
        "y2": {"type": ["integer", "null"]},
        "duration_ms": {"type": "integer", "minimum": 50, "maximum": 3000},
        "wait_seconds": {"type": "number", "minimum": 0.2, "maximum": 15},
        "target": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
        "resource_type": {
            "type": ["string", "null"],
            "enum": ["none", "stamina_item", "currency", None],
        },
        "inventory_before": {"type": ["integer", "null"]},
        "stamina_items_total_before": {"type": ["integer", "null"]},
        "consume_quantity": {"type": ["integer", "null"]},
        "selected_character": {"type": ["string", "null"]},
        "team_members": {
            "type": ["array", "null"],
            "items": {"type": "string"},
        },
    },
    "required": ["state", "action", "target", "reason", "confidence"],
    "additionalProperties": False,
}


def parse_action(content: str) -> AgentAction:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    payload = json.loads(cleaned)
    if payload.get("wait_seconds") is None:
        payload.pop("wait_seconds", None)
    else:
        payload["wait_seconds"] = min(15.0, max(0.2, float(payload["wait_seconds"])))
    if payload.get("duration_ms") is None:
        payload.pop("duration_ms", None)
    else:
        payload["duration_ms"] = min(3000, max(50, int(payload["duration_ms"])))
    if payload.get("selected_character") is None:
        payload["selected_character"] = ""
    if payload.get("team_members") is None:
        payload["team_members"] = []
    if payload.get("resource_type") is None:
        payload["resource_type"] = "none"
    if payload.get("consume_quantity") is None:
        payload["consume_quantity"] = 0
    return AgentAction.model_validate(payload)


class VisionPlanner:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        if not api_key:
            raise ValueError("R1999_API_KEY is empty; add it to .env")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((TimeoutError, ConnectionError)),
        reraise=True,
    )
    def decide(
        self,
        image,
        prompt: str,
        recent_context: str = "",
        ocr_text: str = "",
    ) -> AgentAction:
        width, height = image.size
        user_text = (
            f"当前截图尺寸：{width}x{height}。\n"
            f"最近执行的动作和结果：\n{recent_context or '（无）'}\n"
            f"本地OCR识别结果（可能包含识别错误）：\n{ocr_text or '（无）'}\n"
            "请只选择一个下一步动作。如果画面正在播放动画或处于加载过渡，优先选择 wait。"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": prompt + "\n必须遵守的JSON结构：\n" + json.dumps(ACTION_SCHEMA),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encode_jpeg(image)}",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Vision model returned an empty decision")
        return parse_action(content)
