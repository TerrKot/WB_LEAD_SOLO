"""Main entry point for bot service."""
import asyncio
import sys
import signal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from aiohttp import web
import structlog
import logging

from apps.bot_service.config import config, validate_config
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient
from apps.bot_service.handlers.start import router as start_router, set_redis_client, set_db_client, set_bot
from apps.bot_service.handlers.health import health_handler

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


async def main():
    """Main function."""
    # Validate required configuration
    validate_config()
    
    logger.info("bot_service_starting", port=config.SERVICE_PORT)
    
    # Initialize Redis client
    redis_client = RedisClient(config.REDIS_URL)
    try:
        await redis_client.connect()
        logger.info("redis_connected")
    except Exception as e:
        logger.error("redis_connection_failed", error=str(e))
        sys.exit(1)
    
    # Initialize database client
    db_client = None
    try:
        db_client = DatabaseClient(config.DATABASE_URL)
        await db_client.connect()
        logger.info("database_connected")
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        sys.exit(1)
    
    # Initialize bot
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Initialize FSM storage (Redis)
    storage = RedisStorage.from_url(config.REDIS_URL)
    
    # Initialize dispatcher with FSM storage
    dp = Dispatcher(storage=storage)
    # Set redis_client, db_client and bot for handlers
    set_redis_client(redis_client)
    if db_client:
        set_db_client(db_client)
    set_bot(bot)
    dp.include_router(start_router)
    
    # Set bot commands menu
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="newrequest", description="Новый запрос")
    ])
    logger.info("bot_commands_menu_set")
    
    # Setup HTTP server for health checks
    app = web.Application()
    app["redis_client"] = redis_client
    if db_client:
        app["db_client"] = db_client
    
    app.router.add_get("/healthz", health_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.SERVICE_PORT)
    await site.start()
    
    logger.info("health_endpoint_started", port=config.SERVICE_PORT)
    
    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Start polling
        logger.info("bot_polling_started")
        
        # Create polling task
        polling_task = asyncio.create_task(dp.start_polling(bot))
        
        # Wait for shutdown signal or polling completion
        done, pending = await asyncio.wait(
            [polling_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        if shutdown_event.is_set():
            logger.info("bot_stopping_gracefully")
            # Stop polling gracefully
            await dp.stop_polling()
            # Cancel polling task if still running
            if not polling_task.done():
                polling_task.cancel()
                try:
                    await polling_task
                except asyncio.CancelledError:
                    pass
    except KeyboardInterrupt:
        logger.info("bot_stopping")
        await dp.stop_polling()
    finally:
        logger.info("bot_cleanup_started")
        try:
            await bot.session.close()
        except Exception as e:
            logger.warning("bot_session_close_error", error=str(e))
        
        try:
            # Close FSM storage
            await storage.close()
        except Exception as e:
            logger.warning("storage_close_error", error=str(e))
        
        try:
            await redis_client.disconnect()
        except Exception as e:
            logger.warning("redis_disconnect_error", error=str(e))
        
        if db_client:
            try:
                await db_client.disconnect()
            except Exception as e:
                logger.warning("db_disconnect_error", error=str(e))
        
        try:
            await runner.cleanup()
        except Exception as e:
            logger.warning("runner_cleanup_error", error=str(e))
        
        logger.info("bot_service_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("bot_service_interrupted")
        sys.exit(0)

