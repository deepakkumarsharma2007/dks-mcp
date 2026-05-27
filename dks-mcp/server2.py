import os
import click

from typing import Literal
from dotenv import load_dotenv
import uvicorn
# from user_mcp.user_tools.create_mcp_server import create_fdp_user_mcp_server
from core.create_mcp_server import create_dks_mcp_server
from core.lifespan_hook import lifespan
from core.logging_config import DKSMCPLogger
from core.server_settings import ServerSettings
# from core.health_check import setup_health_endpoints
# from core.telemetry import setup_app_insights
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

load_dotenv()

# Configure logging
# Setup logging configuration app wide
logger = DKSMCPLogger.get_logger()

@click.command()
@click.option("--port", default=8002, help="Port to listen on")
@click.option("--host", default="localhost", help="Host to bind to")
@click.option(
    "--transport",
    default="sse",
    type=click.Choice(["sse", "streamable-http"]),
    help="Transport protocol to use ('sse' or 'streamable-http')",
)
def main(port: int, host: str, transport: Literal["sse", "streamable-http"]) -> int:
    """
    Run the FDP User MCP Server.
    """
    # is_enabled = setup_app_insights(logger_name="fdp_user_mcp_logger")
    # logger.info(f"Application Insights enabled status: {is_enabled}")
    # AioHttpClientInstrumentor().instrument()
    try:
        settings = ServerSettings(host=host, port=port)
    except ValueError as ex:
        logger.error(f"""Failed to load FDP server settings. Make sure environment variable are set.
        Exception: {ex}")""")
        return 1
    
    
    try:
        """Create and configure the FDP MCP Server application
        """
        mcp_server = create_dks_mcp_server(settings)
        logger.info("FDP MCP Server configured")

        logger.info(f"""User details tool registered to MCP server")
        Starting MCP server with {transport} transport and port {port}.""")
        
        mcp_http_app = None
        if transport == "sse":
            mcp_http_app = mcp_server.sse_app()
            # Works on router based apps
            # mcp_http_app.router.lifespan_context = lifespan
            # setup_health_endpoints(mcp_http_app)
            
        elif transport == "streamable-http":
            mcp_http_app = mcp_server.streamable_http_app()
            # Works on router based apps
            # mcp_http_app.router.lifespan_context = lifespan
            # setup_health_endpoints(mcp_http_app)
        else:
            logger.error("Invalid transport!")
            return 1
        # if os.environ.get("FDP_ENABLE_APP_LEVEL_TELEMETRY") == "true":
        #     FastAPIInstrumentor.instrument_app(mcp_http_app)
            
        uvicorn.run(app=mcp_http_app, host=host, port=port)
    
    except Exception as ex:
        logger.error(f"Exception in main function: {ex}")
        return 1
    
    return 0

if __name__ == "__main__":
    main()