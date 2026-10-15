from ipaddress import ip_address

from fastapi import HTTPException, Request, status


def require_local_read_export(request: Request) -> None:
    app_env = getattr(request.app.state.settings, "app_env", "production")
    if app_env == "production":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    if app_env == "test":
        return
    host = request.client.host if request.client else ""
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Local export is available only from the loopback interface.",
        )
