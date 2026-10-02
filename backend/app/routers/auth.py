from fastapi import APIRouter, Depends

from app.core.security import AuthContext, get_auth_context
from app.schemas.user import AuthMeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthMeResponse)
def read_me(ctx: AuthContext = Depends(get_auth_context)) -> AuthMeResponse:
    provisioned = ctx.profile is not None
    return AuthMeResponse(
        uid=ctx.user.uid,
        email=ctx.user.email,
        email_verified=ctx.user.email_verified,
        display_name=ctx.user.display_name or (ctx.profile.display_name if ctx.profile else None),
        role=ctx.role,
        role_source=ctx.role_source,
        profile_provisioned=provisioned,
        profile=ctx.profile,
        message=None
        if provisioned
        else "Authenticated Firebase identity exists, but a portal profile has not yet been provisioned.",
    )
