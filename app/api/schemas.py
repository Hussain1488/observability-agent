from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, description="The message to send to the chat model.")

class ChatResponse(BaseModel):
    response: str = Field(min_length=2, description="The response from the chat model.")
