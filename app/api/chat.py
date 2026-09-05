from fastapi import APIRouter
from app.orchestration.graph import build_graph
from app.api.schemas import ChatRequest, ChatResponse
from app.orchestration.graph import stream_chat

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> any:
    print(f"Received chat request: {request.message}")
    try:
        async for chunk in stream_chat(request.message):
            print(f"Streaming chunk: {chunk}")
            yield chunk
            
    except Exception as e:
        print(f"Error occurred: {e}")
        raise
