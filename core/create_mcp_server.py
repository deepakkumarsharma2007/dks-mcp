import os

from mcp.server.fastmcp import FastMCP
from core.server_settings import ServerSettings


def create_dks_mcp_server(settings: ServerSettings) -> FastMCP:
    dks_mcpapp = FastMCP(
        name="DKS MCP Server",
        instructions="DKS MCP Server",
        stateless_http=True,
        json_response=True,
        host=settings.host,
        port=settings.port,
        debug=True,
        log_level=os.environ.get("MCP_LOG_LEVEL", "INFO").upper(),
    )
    return dks_mcpapp
