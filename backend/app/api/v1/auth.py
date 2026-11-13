from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.api.deps import AuthServiceDep, SettingsDep
from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.services.auth import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"  # noqa: S105 - the cookie's name, not a secret

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        # Not readable by JavaScript, so an XSS bug cannot steal it.
        httponly=True,
        secure=settings.cookie_secure,
        # Never sent on cross-site requests: this is the CSRF defence for the one
        # endpoint family that authenticates by cookie.
        samesite="strict",
        # Sent only to the auth endpoints, not with every API call.
        path=f"{settings.api_v1_prefix}/auth",
    )


def _token_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(access_token=pair.access_token, expires_in=pair.expires_in)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, auth: AuthServiceDep) -> UserRead:
    user = await auth.register(email=body.email, password=body.password)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> TokenResponse:
    _, pair = await auth.login(email=body.email, password=body.password)
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return _token_response(pair)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    if not refresh_token:
        raise AuthenticationError("Your session is no longer valid. Please sign in again.")
    pair = await auth.refresh(refresh_token=refresh_token)
    _set_refresh_cookie(response, pair.refresh_token, settings)
    return _token_response(pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> None:
    await auth.logout(refresh_token=refresh_token)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=f"{settings.api_v1_prefix}/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
