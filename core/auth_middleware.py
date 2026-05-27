from typing import Any, Optional
import uuid
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from functools import wraps
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from core.logging_config import DKSMCPLogger
from core.auth_utils import verify_audience_and_expiry

logger = DKSMCPLogger.get_logger()


class AuditInfo(BaseModel):
    alias: str = Field(None, description="User alias")
    email: str = Field(None, description="User email")
    bearer_token: str = Field(None, description="Bearer token from MCP tool header")
    isAuthenticated: bool = Field(
        False, description="Whether the user is authenticated or not"
    )
    transaction_id: str = Field(None, description="Transaction ID for the request")


security = HTTPBearer()


def audit_info_decorator():
    def decorator(func):
        @wraps(func)
        async def wrapper(
            self, ctx: Context, auditcontext: Optional[dict[str, Any]] = None, **kwargs
        ):
            # Find the request object in args or kwargs
            request: Request | Any = (
                ctx.request_context.request if hasattr(ctx, "request_context") else None
            )
            if request is None:
                raise ToolError(
                    "Authentication failed. Request object not found in context. Make sure to pass the request object in the context when calling the tool."
                )
            else:
                authinfo = await authentication_middleware(request)

                if authinfo.isAuthenticated:
                    auditcontext = auditcontext or {}
                    auditcontext["alias"] = authinfo.alias
                    auditcontext["email"] = authinfo.email
                    auditcontext["bearer_token"] = authinfo.bearer_token
                    auditcontext["transaction_id"] = authinfo.transaction_id

                    return await func(self, ctx, auditcontext, **kwargs)

        return wrapper

    return decorator


async def authentication_middleware(request: Request) -> AuditInfo:
    if request.url.path.startswith("/mcp"):
        try:
            credentials = await security(request)
            if credentials is None:
                logger.error("Authentication failed: No credentials/token provided.")
                raise ToolError("Authentication failed: No credentials/token provided.")
            
            is_verified, user_id = verify_audience_and_expiry(credentials.credentials)
            if not is_verified:
                logger.error("Authentication failed: Token verification failed.")
                raise ToolError("Authentication failed: Token verification failed.")
            
            if user_id is None:
                logger.error("Authentication failed: Invalid token or user alias not found.")
                raise ToolError(
                    "Authentication failed: Invalid token or user alias not found."
                )

        except HTTPException as ex:
            logger.error(f"Authentication failed: {ex.detail} - {ex.status_code}")
            raise ToolError(f"Authentication failed: {ex.detail} - {ex.status_code}")

        # Extract alias as the part before '@' if user_id looks like an email
        alias = user_id.split("@")[0] if user_id and "@" in user_id else user_id

        correlation_id: str | None = request.headers.get("x-correlationid")

        if not correlation_id:
            correlation_id = "dks-" + str(uuid.uuid4())
        # Add correlation ID to the request state for later use in tools
        else:
            correlation_id = f"client-{correlation_id}"

        audit_info = AuditInfo(
            isAuthenticated=True,
            bearer_token=credentials.credentials,
            alias=alias,
            email=user_id,
            transaction_id=correlation_id,
        )

        request.state.audit_info = audit_info
        return audit_info
