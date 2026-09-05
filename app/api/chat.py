from fastapi import APIRouter
from starlette.responses import StreamingResponse
from app.orchestration.graph import build_graph
from app.api.schemas import ChatRequest, ChatResponse
from app.orchestration.graph import stream_tokens
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/ask", response_model=ChatResponse)
async def ask_endpoint(request: ChatRequest) -> StreamingResponse:
    logger.info(f"Received chat request: {request.message}")
    try:
        return StreamingResponse(stream_tokens(request.message), media_type="text/plain")
            
    except Exception as e:
        logger.error(f"error occured: {e}")
        raise
