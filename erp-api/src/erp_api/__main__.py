import uvicorn

from erp_api.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "erp_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        # OAuth callbacks carry one-time credentials in the query string.
        # Application request logging records the path without query parameters.
        access_log=False,
    )


if __name__ == "__main__":
    main()
