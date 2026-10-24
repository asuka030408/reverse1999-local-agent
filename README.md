# Reverse: 1999 Local Agent

一个在本机运行的《重返未来：1999》实验性自动化项目。它通过 ADB 观察 MuMu 模拟器画面，结合本地 OCR、规则和可看图的模型决定下一步操作，再检查画面变化。

> 这是个人项目，与游戏官方无关。界面和关卡更新可能使识别或导航失效；首次运行请使用 dry run 检查决策。

## 功能

- **主线推进 (`story`)**：从主界面进入故事，选择可进入的章节和关卡，跳过对话，启用或等待自动战斗，处理结算页。内置的主线章节数据帮助区分常驻主线与活动入口。
- **角色养成 (`character`)**：识别目标角色的升级材料，导航至材料来源，刷取资源并重试升级。小字材料数量会用放大后的本地 OCR 再读一次。
- **战败后的衔接**：主线战败时记录关卡和当前队伍，转入当前队伍角色的养成流程；养成完成后尝试返回原主线进度。未完成的状态保存在本地，以供下次启动恢复。
- **运行检查**：`doctor` 检查 ADB 连接，`screenshot` 保存当前画面，`ocr` 输出本地识别结果。

项目仍处于实验阶段。自动导航依赖游戏界面和识别质量，不能保证无人值守通关；战败后的养成和恢复尤其需要人工观察。

## 技术栈与工作方式

Python 3.11+；OpenAI Python SDK 调用兼容 Chat Completions 的视觉模型；Pydantic / pydantic-settings 校验动作和读取配置；ADB 截图、点击与滑动；Pillow、OpenCV 和可选的 RapidOCR 处理画面；Tenacity 处理部分模型调用重试；pytest 做离线测试。

每轮执行遵循 `截图 → OCR / 本地规则 → 必要时调用视觉模型 → 校验动作 → ADB 执行 → 再截图`。模型每次只能提出一个 `tap`、`swipe`、`back`、`wait` 或 `finish` 动作，不能获得任意电脑操作权限。更详细的模块和状态说明见 [架构文档](docs/architecture.md)。

本项目的 agent loop 是自行实现的 Python 循环，**没有使用 LangGraph**。

## 安装

1. 安装 Python 3.11+，启动 MuMu 模拟器和游戏，并确认 ADB 可用。
2. 在项目目录执行：

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -e ".[dev,ocr]"
   Copy-Item .env.example .env
   ```

3. 编辑本地 `.env`：填写 `R1999_API_KEY`、`R1999_BASE_URL` 和支持图片输入及 JSON 输出的 `R1999_MODEL`。如果 `adb` 不在 PATH，设置 `R1999_ADB_PATH` 为模拟器附带的 `adb.exe` 完整路径。按实际模拟器端口调整 `R1999_ADB_SERIAL`。

`.env` 含密钥，已被 Git 忽略。示例文件不含真实密钥。

## 运行

先检查设备并做一次不点击的试运行：

```powershell
.\.venv\Scripts\r1999-agent.exe doctor
.\.venv\Scripts\r1999-agent.exe screenshot
.\.venv\Scripts\r1999-agent.exe ocr
.\.venv\Scripts\r1999-agent.exe run story --max-steps 1
```

检查日志和画面后，将 `.env` 中的 `R1999_DRY_RUN` 改为 `false`，再运行：

```powershell
.\.venv\Scripts\r1999-agent.exe run story
.\.venv\Scripts\r1999-agent.exe run character --character "角色名称" --target-level 30
```

Windows 上也可以运行 `Start_Story_Agent.cmd`。**该脚本会强制设置 `R1999_DRY_RUN=false` 并执行最多 500 步**，首次检查请用上面的命令。按 `Ctrl+C` 停止。运行日志、截图和恢复状态分别保存在 `logs/`、`artifacts/` 和 `work/`，均不提交到仓库。

## 操作边界

代码会检查动作坐标及目标，并拒绝充值、购买、抽卡、账号变更和删除等目标。使用体力道具前须读出所有类型道具的总量，使用后至少保留 2 个；禁止用付费货币恢复体力。战败后的自动养成只针对画面确认的当前队伍角色。实际执行前仍应自行观察屏幕和日志。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖离线的动作校验、OCR 辅助逻辑、主线知识与进度、角色养成策略等；它们不能替代连接模拟器的实际验证。
