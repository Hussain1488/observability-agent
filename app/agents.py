import yaml
from app.core.llm import get_model

with open("app/core/agents.yaml", "r") as f:
    agents_config = yaml.safe_load(f)

def get_agent_config(agent_name: str):

    model = get_model(
        agent_config := agents_config["agents"].get(agent_name, None),
        agent_config['agents'][agent_name].get("model", None)
    )

    if model is None:
        raise ValueError(f"Agent '{agent_name}' not found in configuration.")
              
    return {
        "system_prompt": agents_config["agents"][agent_name].get("system_prompt", ""),
        "tools": agents_config["agents"][agent_name].get("tools", []),
        "model": model,
    }


async def run_agent(agent_name: str, message: str):

    if agent_name not in agents_config["agents"]:
        raise ValueError(f"Agent '{agent_name}' not found in configuration.")

    agent = get_agent_config(agent_name)

    model = agent.get("model")
    provider = agent.get("provider", "chatgpt")
