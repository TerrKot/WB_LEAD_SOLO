"""Health check handler."""
from aiohttp import web
from typing import Dict, Any
import structlog

logger = structlog.get_logger()


async def health_handler(request: web.Request) -> web.Response:
    """
    Health check endpoint.

    Returns:
        JSON response with health status
    """
    health_status: Dict[str, Any] = {
        "status": "ok",
        "service": "bot_service"
    }
    
    # Check Redis connection
    redis_client = request.app.get("redis_client")
    if redis_client:
        try:
            await redis_client.redis.ping()
            health_status["redis"] = "ok"
        except Exception as e:
            health_status["redis"] = "error"
            health_status["redis_error"] = str(e)
            health_status["status"] = "degraded"
    else:
        health_status["redis"] = "not_configured"
    
    # Check PostgreSQL connection (optional)
    db_client = request.app.get("db_client")
    if db_client:
        try:
            from sqlalchemy import text
            session = await db_client.get_session()
            async with session:
                await session.execute(text("SELECT 1"))
            health_status["database"] = "ok"
        except Exception as e:
            health_status["database"] = "error"
            health_status["database_error"] = str(e)
            # Database is optional, so don't mark status as degraded
    else:
        health_status["database"] = "not_configured"
    
    status_code = 200 if health_status["status"] == "ok" else 503
    return web.json_response(health_status, status=status_code)

