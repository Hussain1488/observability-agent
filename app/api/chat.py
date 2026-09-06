from collections.abc import AsyncIterator

from fastapi import APIRouter
from starlette.responses import StreamingResponse
from app.api.schemas import ChatRequest
from app.orchestration.graph import stream_tokens
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

ERROR_NOTICE = "\n\n[error] The assistant could not finish this answer. Please retry."


async def _guarded_stream(message: str) -> AsyncIterator[str]:
    """Stream the answer, turning a mid-stream failure into a visible notice.

    The status line is sent with the first byte, so a later failure cannot become
    a 500. Ending with an explicit notice beats a silently truncated answer that
    reads as if the assistant simply stopped talking.
    """
    try:
        async for token in stream_tokens(message):
            yield token
    except Exception:
        logger.exception("Streaming failed for message: %s", message)
        yield ERROR_NOTICE


@router.post("/ask")
async def ask_endpoint(request: ChatRequest) -> StreamingResponse:
    logger.info("Received chat request: %s", request.message)
    return StreamingResponse(
        _guarded_stream(request.message), media_type="text/plain"
    )
