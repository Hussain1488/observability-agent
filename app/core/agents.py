from pydantic import BaseModel, Field
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import settings
import yaml


with open("app/core/agents.yaml", "r") as f:
    agents_config = yaml.safe_load(f)


def get_agent(config: str | None = None):
    
    if config is None:
        raise ValueError("Agent name is required!")

    agent = agents_config["agents"].get(config.agent_name)

    if agent is None:
        raise ValueError(f"Agent '{config.agent_name}' not found in configuration.")

    system_prompt = agent.get("system_prompt")
    match agent["provider"]:
        case "chatgpt":
            model = ChatOpenAI(
                model=agent.get("model"),
                api_key=settings.openai_api_key,
                temperature=0.0,            
            ) 
            return model, system_prompt
        
        case "GoogleGenAI":
            model = ChatGoogleGenerativeAI(
                model=agent.get("model"),
                api_key=settings.google_genai_api_key,
            )
            return model, system_prompt
        case _:
            raise ValueError(f"Unsupported provider: {agent['provider']}")

   
    raise ValueError(f"Unsupported provider: {agent['provider']}")