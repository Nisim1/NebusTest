from __future__ import annotations
import logging
import uvicorn
from repo_summarizer.infrastructure.config import get_settings

def main() -> None:
    """Start the uvicorn ASGI server."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    uvicorn.run(
        "repo_summarizer.interface.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
