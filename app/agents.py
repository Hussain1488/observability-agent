from app.core.agents import get_agent



async def run_agent(agent_name: str, message: str):
    model, system_prompt = get_agent(agent_name)

    for chunk in model.astream(message, system_prompt=system_prompt):
        yield chunk