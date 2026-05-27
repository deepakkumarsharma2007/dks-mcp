from functools import wraps
from typing import Any, Optional
from mcp.server.fastmcp import Context


def trace_decorator_middleware():
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)

    def decorator(callerfunc):
        @wraps(callerfunc)
        async def wrapper(self, ctx: Context, auditcontext: Optional[dict[str, Any]] = None, **kwargs):
            with tracer.start_as_current_span(callerfunc.__qualname__, kind=trace.SpanKind.INTERNAL) as span:
                span.set_attribute("mcp.tool.name", self.name)
                span.set_attribute("mcp.tool.correlation_id", ctx.get('transaction_id'))
                span.set_attribute("mcp.tool.useralias", ctx.get("alias", "NOT_SET"))
                return await callerfunc(self, ctx, auditcontext, **kwargs)

        return wrapper

    return decorator