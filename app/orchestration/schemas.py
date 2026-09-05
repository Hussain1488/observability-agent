from pydantic import BaseModel, Field
from typing import Literal

class RoutingDecision(BaseModel):
    agent: str

class RoutingResponse(BaseModel):
    routes: Literal["traces","logs","metrics","docs", "codes", "support"] = Field(description="The list of Agents to answer user message based on their tools and mission." )
    reasoning: str = Field(description="The reasoning behind the routing decision.")