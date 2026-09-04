from fastapi import APIRouter

from app.api.schemas import ChatRequest, ChatResponse

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    try:
        

    except Exception as e:
        print(f"Error occurred: {e}")
        raise
    raise NotImplementedError
