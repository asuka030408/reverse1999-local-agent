from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .adb import AdbClient
from .agent import GameAgent
from .config import Settings
from .models import Workflow
from .vision import OcrReader, format_ocr


def configure_logging() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/agent.log", encoding="utf-8"),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reverse: 1999 local game agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="verify Python configuration and MuMu ADB connectivity")
    sub.add_parser("screenshot", help="capture the current MuMu screen")
    sub.add_parser("ocr", help="capture the current MuMu screen and print local OCR results")

    run = sub.add_parser("run", help="run a goal-directed workflow")
    run.add_argument("workflow", choices=[item.value for item in Workflow])
    run.add_argument("--max-steps", type=int)
    run.add_argument("--character", default="")
    run.add_argument("--target-level", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings()
    settings.ensure_dirs()
    configure_logging()
    adb = AdbClient(settings.adb_path, settings.adb_serial)

    try:
        if args.command == "doctor":
            print(adb.connect())
            print(f"device_state={adb.device_state()}")
            image = adb.screenshot()
            print(f"screenshot={image.width}x{image.height}")
            print(f"model={settings.model}")
            print(f"dry_run={settings.dry_run}")
            print(f"api_key={'configured' if settings.api_key else 'missing'}")
            return

        if args.command == "screenshot":
            adb.connect()
            image = adb.screenshot()
            destination = settings.artifact_dir / "current.png"
            image.save(destination)
            print(destination.resolve())
            return

        if args.command == "ocr":
            adb.connect()
            image = adb.screenshot()
            print(format_ocr(OcrReader(settings.enable_ocr).read(image)) or "(no text detected)")
            return

        requested_workflow = Workflow(args.workflow)
        if requested_workflow is Workflow.STORY:
            agent = GameAgent(settings)
            current_workflow = (
                Workflow.CHARACTER
                if agent.memory.development_required
                else Workflow.STORY
            )
            if current_workflow is Workflow.CHARACTER:
                logging.warning(
                    "unfinished development state restored; starting current-team "
                    "development before story"
                )
            while True:
                outcome = agent.run(
                    current_workflow,
                    max_steps=args.max_steps,
                    character=(
                        (
                            "仅限已保存的当前队伍角色："
                            + "、".join(agent.memory.current_team)
                            if agent.memory.current_team
                            else "当前队伍中的角色（尚未保存名单，不得猜测）"
                        )
                        if current_workflow is Workflow.CHARACTER
                        else args.character
                    ),
                    target_level=(
                        None
                        if current_workflow is Workflow.CHARACTER
                        else args.target_level
                    ),
                )
                if (
                    current_workflow is Workflow.STORY
                    and outcome is not None
                    and outcome.target == "story blocked by defeat"
                ):
                    logging.warning(
                        "story defeat detected; switching to current-team development workflow"
                    )
                    current_workflow = Workflow.CHARACTER
                    agent = GameAgent(settings)
                    continue
                if current_workflow is Workflow.CHARACTER:
                    if outcome is None:
                        logging.warning(
                            "development reached the step limit without finishing; "
                            "continuing development instead of resuming story"
                        )
                        agent = GameAgent(settings)
                        continue
                    logging.info(
                        "development workflow ended; resuming story from persistent checkpoint"
                    )
                    current_workflow = Workflow.STORY
                    agent = GameAgent(settings)
                    continue
                return

        agent = GameAgent(settings)
        agent.run(
            requested_workflow,
            max_steps=args.max_steps,
            character=args.character,
            target_level=args.target_level,
        )
    except KeyboardInterrupt:
        print("Stopped by user", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        logging.exception("Agent failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
