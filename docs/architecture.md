# 架构与状态

## 一轮决策

`cli.py` 解析命令并创建 `GameAgent`。`agent.py` 中的循环通过 `adb.py` 截图，`vision.py` 做 OCR 与画面变化检测，`local_policy.py` 优先处理可由规则判断的场景。其余场景交给 `planner.py`：它通过 OpenAI 兼容的 Chat Completions 接口提交截图、OCR 文本及最近操作，要求返回单个 JSON 动作。`models.py` 解析动作，`agent.py` 校验后由 ADB 执行，再观察下一帧。

```text
MuMu 截图 → OCR / 本地规则 → 视觉模型（必要时） → 动作校验 → ADB 操作
     ↑                                                   │
     └────────────────── 下一轮截图和变化检测 ────────────────┘
```

这是一套自写的 agent loop，不依赖 LangGraph。

## 工作流与恢复

- `workflows.py` 生成主线或角色养成任务提示。
- `story_knowledge.py` 读取随包发布的 `data/story_mainline.json`，辅助识别常驻主线章节与关卡。
- `story_progress.py` 从本地步骤日志恢复部分前置剧情进度。
- `agent_memory.py` 将队伍、战败后养成标记及主线检查点写入 `work/agent_state.json`。`cli.py` 据此在主线与角色养成间切换。

`work/`、`logs/` 和 `artifacts/` 均是本地运行数据。复制项目到另一台电脑时不会自动携带这些状态。

## 外部依赖与边界

ADB 负责与模拟器交互；视觉模型服务负责不能由本地规则确定的动作；RapidOCR 是可选的本地 OCR 后端。动作只能是 `tap`、`swipe`、`back`、`wait`、`finish`，且执行前会检查坐标、体力道具与禁止目标。界面变化检测和有限的历史记录用于降低重复点击风险，但不能保证每次识别正确。
