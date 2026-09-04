from pydantic import BaseModel
from typing import Literal

class RoutingDecision(BaseModel):
    agent: str

class RoutingResponse(BaseModel):
    routes: str = Literal["traces","logs","metrics","docs", "codes", "support"]