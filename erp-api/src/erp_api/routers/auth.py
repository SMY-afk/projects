from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from erp_api.core.permissions import MODULE_PERMISSION_CODES, PermissionCode
from erp_api.services.auth import (
    AuthService,
    AuthSession,
    CurrentUser,
    verify_password,
)
from erp_api.services.auth_repository import AuthRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class CaptchaResponse(BaseModel):
    captchaId: str
    imageDataUrl: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    accessToken: str


class RoleResponse(BaseModel):
    id: str
    code: str
    name: str


class CurrentUserResponse(BaseModel):
    id: str
    name: str
    username: str
    roles: list[RoleResponse]
    permissions: list[str]


def _get_fingerprint(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{client_host}|{request.headers.get('user-agent', '')}"


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"}
    )


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_auth_repository(request: Request) -> AuthRepository:
    return request.app.state.auth_repository


async def require_session(
    authorization: Annotated[str | None, Header()] = None,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthSession:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized()
    session = await auth_service.get_session(token)
    if not session:
        raise _unauthorized()
    return session


async def get_authenticated_user(
    request: Request,
    session: AuthSession = Depends(require_session),
    auth_repository: AuthRepository = Depends(get_auth_repository),
) -> CurrentUser:
    user = await auth_repository.get_current_user(session.user_id, session.tenant_id)
    if not user:
        raise _unauthorized()
    request.state.tenant_id = session.tenant_id
    return user


def require_permissions(*permission_codes: PermissionCode):
    unsupported_permissions = set(permission_codes) - MODULE_PERMISSION_CODES
    if unsupported_permissions:
        raise ValueError(f"Unsupported permission code: {min(unsupported_permissions)}")

    async def permission_dependency(
        user: CurrentUser = Depends(get_authenticated_user),
    ) -> CurrentUser:
        if not set(permission_codes).issubset(user.permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return user

    return permission_dependency


@router.get("/captcha", response_model=CaptchaResponse)
async def get_captcha(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> CaptchaResponse:
    _no_store(response)
    captcha_id, image_data_url = await auth_service.create_captcha(
        _get_fingerprint(request)
    )
    return CaptchaResponse(captchaId=captcha_id, imageDataUrl=image_data_url)


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    auth_repository: AuthRepository = Depends(get_auth_repository),
) -> LoginResponse:
    _no_store(response)
    fingerprint = _get_fingerprint(request)
    if not await auth_service.allow_login_attempt(fingerprint):
        raise _unauthorized()
    account = await auth_repository.find_account_by_username(payload.username)
    if not account or not verify_password(payload.password, account.password_hash):
        raise _unauthorized()
    return LoginResponse(accessToken=await auth_service.create_session(account))


@router.get("/current-user", response_model=CurrentUserResponse)
async def get_current_user(
    response: Response,
    user: CurrentUser = Depends(get_authenticated_user),
) -> CurrentUserResponse:
    _no_store(response)
    return _to_current_user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    authorization: Annotated[str | None, Header()] = None,
    auth_service: AuthService = Depends(get_auth_service),
    _: AuthSession = Depends(require_session),
) -> Response:
    _, _, token = (authorization or "").partition(" ")
    await auth_service.revoke_session(token)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"}
    )


def _to_current_user_response(user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=str(user.id),
        name=user.name,
        username=user.username,
        roles=[RoleResponse(**role) for role in user.roles],
        permissions=user.permissions,
    )
