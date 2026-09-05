from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, description="The message to send to the chat model.")
