
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse as StarletteJSONResponse
 
def setup_health_endpoints(app) -> None:
    """Add health check endpoints to the Starlette/FastAPI app."""
 
    async def liveness_check(request):
        """Kubernetes liveness probe endpoint."""
        return StarletteJSONResponse(
            status_code=200,
            content={"status": "alive"}
        )
   
    # Add route to Starlette app
    if hasattr(app, 'routes'):
        app.routes.append(Route("/health/live", liveness_check, methods=["GET"]))