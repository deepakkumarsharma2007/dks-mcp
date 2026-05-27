from contextlib import asynccontextmanager
from core.logging_config import DKSMCPLogger
from core.health_check import setup_health_endpoints

logger = DKSMCPLogger.get_logger()


@asynccontextmanager
async def lifespan(app):
    """Manage application startup and shutdown."""
    logger.info("Starting FDP MCP Server...")
    
    try:
        # Initialize
        logger.info("initialized")
        
        # Test connectivity
        health_status = await setup_health_endpoints(app)
        if health_status["status"] != "alive":
            logger.error(f"health check failed: {health_status}")
            raise Exception("Pod not healthy")
        
        logger.info("DKS MCP Server startup complete")
        yield
        
    except Exception as ex:
        logger.error(f"Startup failed: {ex}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down DKS MCP Server...")
        logger.info("DKS MCP Server shutdown complete")