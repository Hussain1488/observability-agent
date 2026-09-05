from fastapi import APIRouter
from starlette.responses import StreamingResponse
from app.api.schemas import ChatRequest
from app.orchestration.graph import stream_tokens
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/ask")
async def ask_endpoint(request: ChatRequest) -> StreamingResponse:

    logger.info("Received chat request: %s", request.message)
    return StreamingResponse(stream_tokens(request.message), media_type="text/plain")
