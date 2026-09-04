from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from app.core.config import settings
from app.orchestration.prompts import PROMPT

from app.core.llm import get_model, ModelConfig

model = get_model(ModelConfig(provider="chatgpt", model="gpt-5o-nano"))


async def call_model(state: MessagesState):
    formatted_prompt = PROMPT.invoke({"message": state["messages"][-1].content})
    response = await model.ainvoke(formatted_prompt)
    return {"messages": [response]}


def build_graph():
    builder = StateGraph(MessagesState)

    builder.add_node("model", call_model)
    
    builder.add_edge(START, "model")
    builder.add_edge("model", END)

    checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)
