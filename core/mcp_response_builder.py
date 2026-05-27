from mcp.types import TextContent, CallToolResult
from pydantic import BaseModel
from typing import Any, Union


class MCPResponseBuilder:
    """
    Builds MCP CallToolResult with separate content (short text) 
    and structuredContent (full data).
    """

    @staticmethod
    def build(summary: str, data: Union[BaseModel, dict, list, None] = None) -> CallToolResult:
        """
        Build a CallToolResult with a short text summary and optional structured content.

        Args:
            summary: Short text for LLM consumption.
            data: Full structured data (Pydantic model, dict, or list). Optional.

        Returns:
            CallToolResult with content and structuredContent separated.
        """
        structured = None
        if data is not None:
            if isinstance(data, BaseModel):
                structured = data.model_dump()
            elif isinstance(data, dict):
                structured = data
            elif isinstance(data, list):
                structured = {"result": data}
            else:
                raise TypeError(f"data must be a Pydantic model, dict, or list. Got: {type(data)}")

        return CallToolResult(
            content=[TextContent(type="text", text=summary)],
            structuredContent=structured,
        )