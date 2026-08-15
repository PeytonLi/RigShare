"""Placeholder worker so Render can boot the agent service.

Real Matcher / Condition / Clerk loops land in a later commit.
"""

import time


def main() -> None:
    print("rigshare-agents worker started (idle until agents are wired)")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
