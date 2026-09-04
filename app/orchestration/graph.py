from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from app.core.agents import get_agent, ModelConfig

model = get_agent(ModelConfig("support"))


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
