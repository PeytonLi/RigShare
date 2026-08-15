"""Render Workflows entrypoint.

The web service uses `uvicorn app.main:app`. This file is only for Workflows.
Dashboard start command: python main.py
"""

from workflows.tasks import app

if __name__ == "__main__":
    app.start()
