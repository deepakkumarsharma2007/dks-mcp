import click
from typing import Literal

from dotenv import load_dotenv
import uvicorn

from core.create_mcp_server import create_dks_mcp_server
from core.health_check import setup_health_endpoints
from core.logging_config import DKSMCPLogger
from core.server_settings import ServerSettings
from tools.mongodb.natural_language_query_tool_adapter import mongodb_document_search_agent_adapter

load_dotenv()
logger = DKSMCPLogger.get_logger()


@click.command()
@click.option("--port", default=8001, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option(
    "--transport",
    default="sse",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
def main(port: int, host: str, transport: Literal["sse", "streamable-http"]) -> int:
    """Run the DKS MCP Server."""
    try:
        settings = ServerSettings(host=host, port=port)
    except ValueError as ex:
        logger.error(
            "Failed to load server settings. Make sure environment variables are set. "
            f"Exception: {ex}"
        )
        return 1

    try:
        mcp_server = create_dks_mcp_server(settings)
        logger.info("DKS MCP Server configured")

        try:
            mongodb_query_tool = mongodb_document_search_agent_adapter()
            mcp_server.tool(
                name=mongodb_query_tool.name,
                description=mongodb_query_tool.description,
            )(mongodb_query_tool._arun)
            logger.info("MongoDB Query tool registered to MCP server")
        except Exception as tool_ex:
            logger.warning(f"MongoDB Query tool not registered: {tool_ex}")

        logger.info(
            f"Starting MCP server with {transport} transport and port {port}."
        )

        if transport == "sse":
            mcp_http_app = mcp_server.sse_app()
        elif transport == "streamable-http":
            mcp_http_app = mcp_server.streamable_http_app()
        else:
            logger.error("Invalid transport")
            return 1

        setup_health_endpoints(mcp_http_app)
        uvicorn.run(app=mcp_http_app, host=host, port=port)
    except Exception as ex:
        logger.error(f"Exception in main function: {ex}")
        return 1

    return 0


if __name__ == "__main__":
    main()
