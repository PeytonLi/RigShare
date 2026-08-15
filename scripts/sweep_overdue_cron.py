"""Render Cron Job entrypoint: kick the sweepOverdue workflow task.

Render Workflows has no scheduler of its own, so a cron job has to start the task.
Going through Workflows (instead of doing the sweep here) keeps every overdue chase
in the same task-run history judges are looking at.

Local run: python scripts/sweep_overdue_cron.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# `python scripts/sweep_overdue_cron.py` puts scripts/ on the path, not the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from app.config import get_settings  # noqa: E402
from app.workflows_client import start_task  # noqa: E402


def main() -> int:
    if not get_settings().render_workflow_slug:
        print("RENDER_WORKFLOW_SLUG unset; nothing to start", file=sys.stderr)
        return 1
    result = start_task("sweepOverdue", "")
    print(f"sweepOverdue -> {result}")
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
