"""API routes — thin controllers that delegate to the use case."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from repo_summarizer.interface.dependencies import get_use_case
from repo_summarizer.interface.schemas import SummarizeRequest, SummarizeResponse
from repo_summarizer.services.summarize_repo import SummarizeRepoUseCase

router = APIRouter()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        422: {"description": "Invalid GitHub URL or empty repository"},
        403: {"description": "Repository is private"},
        404: {"description": "Repository not found"},
        429: {"description": "GitHub API rate limit exceeded"},
        502: {"description": "LLM provider error"},
    },
)
async def summarize(
    body: SummarizeRequest,
    use_case: SummarizeRepoUseCase = Depends(get_use_case),
) -> SummarizeResponse:
    """Summarise a public GitHub repository."""
    result = await use_case.execute(body.github_url)
    return SummarizeResponse(
        summary=result.summary,
        technologies=result.technologies,
        structure=result.structure,
    )
