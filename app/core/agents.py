from pathlib import Path

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.tools.tools import get_tools

AGENTS_CONFIG_PATH = Path(__file__).parent / "agents.yaml"

with AGENTS_CONFIG_PATH.open("r", encoding="utf-8") as f:
    agents_config = yaml.safe_load(f)


def _build_model(config: dict) -> BaseChatModel:
    match config["provider"]:
        case "chatgpt":
            return ChatOpenAI(
                model=config["model"],
                api_key=settings.openai_api_key,
                temperature=config.get("temperature", 0.0),
            )
        case "GoogleGenAI":
            return ChatGoogleGenerativeAI(
                model=config["model"],
                api_key=settings.google_genai_api_key,
                temperature=config.get("temperature", 0.0),
            )
        case _:
            raise ValueError(f"Unsupported provider: {config['provider']}")


def agent_names() -> list[str]:
    return list(agents_config["agents"])


def get_agent(agent_name: str) -> tuple[BaseChatModel, str, list[BaseTool]]:
    agent = agents_config["agents"].get(agent_name)

    if agent is None:
        raise ValueError(
            f"Agent '{agent_name}' not found. Available agents: {agent_names()}"
        )

    return (
        _build_model(agent),
        agent["system_prompt"],
        get_tools(agent.get("tools", [])),
    )


def get_orchestrator_agent() -> tuple[BaseChatModel, str, str]:
    orchestrator = agents_config["orchestrator"]

    return (
        _build_model(orchestrator),
        orchestrator["system_prompt"],
        orchestrator.get("fallback_route", "support"),
    )
