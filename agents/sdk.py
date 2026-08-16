"""Band SDK imports. PyPI 1.6 uses `band`; older docs used `thenvoi` / `band_sdk`."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_IMPORTS = (
    ("band", "band.adapters"),
    ("thenvoi", "thenvoi.adapters"),
    ("band_sdk.agent", "band_sdk.adapter.langgraph"),
)


def load_band_stack() -> tuple[Any, Any, Any, Any]:
    """Return Agent, LangGraphAdapter, ChatOpenAI, InMemorySaver."""
    last: Exception | None = None
    Agent = None
    LangGraphAdapter = None
    for agent_mod, adapter_mod in _IMPORTS:
        try:
            Agent = getattr(__import__(agent_mod, fromlist=["Agent"]), "Agent")
            LangGraphAdapter = getattr(
                __import__(adapter_mod, fromlist=["LangGraphAdapter"]),
                "LangGraphAdapter",
            )
            log.info("band sdk: Agent from %s", agent_mod)
            break
        except ImportError as exc:
            last = exc

    if Agent is None or LangGraphAdapter is None:
        raise ImportError(
            "Install band-sdk[langgraph]. Tried band, thenvoi, and band_sdk."
        ) from last

    try:
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as exc:
        raise ImportError(
            "langchain-openai and langgraph are required for Band agents"
        ) from exc

    return Agent, LangGraphAdapter, ChatOpenAI, InMemorySaver


def tool_decorator():
    try:
        from langchain_core.tools import tool

        return tool
    except ImportError:
        pass
    for module_name in ("band.types", "thenvoi.types", "band_sdk.types"):
        try:
            module = __import__(module_name, fromlist=["tool"])
            return module.tool
        except ImportError:
            continue
    return None
