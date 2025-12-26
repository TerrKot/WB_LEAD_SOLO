"""Main entry point for bot service."""
import asyncio
import sys
import signal
from pathlib import Path
from datetime import datetime
import pytz

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
from apps.bot_service.services.daily_report_service import DailyReportService

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


async def daily_report_scheduler(bot: Bot, db_client: DatabaseClient, shutdown_event: asyncio.Event):
    """
    Scheduler for daily reports at 12:00 Moscow time.
    
    Args:
        bot: Telegram bot instance
        db_client: Database client instance
        shutdown_event: Event to signal shutdown
    """
    if not config.REPORT_CHAT_ID:
        logger.warning("daily_report_scheduler_disabled", reason="REPORT_CHAT_ID not configured")
        return
    
    report_service = DailyReportService(bot, db_client)
    moscow_tz = pytz.timezone('Europe/Moscow')
    last_sent_date = None
    
    logger.info("daily_report_scheduler_started", report_time="12:00 MSK")
    
    while not shutdown_event.is_set():
        try:
            now_moscow = datetime.now(moscow_tz)
            current_date = now_moscow.date()
            current_hour = now_moscow.hour
            current_minute = now_moscow.minute
            
            # Check if it's 12:00 MSK and we haven't sent report today
            if current_hour == 12 and current_minute == 0 and last_sent_date != current_date:
                logger.info("daily_report_scheduler_triggered", time=now_moscow.strftime("%H:%M"))
                success = await report_service.send_report(config.REPORT_CHAT_ID)
                if success:
                    last_sent_date = current_date
                    logger.info("daily_report_sent_successfully")
                else:
                    logger.error("daily_report_send_failed")
            
            # Sleep for 60 seconds before next check
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("daily_report_scheduler_cancelled")
            break
        except Exception as e:
            logger.error("daily_report_scheduler_error", error=str(e))
            await asyncio.sleep(60)


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
        
        # Start daily report scheduler if configured
        report_scheduler_task = None
        if config.REPORT_CHAT_ID and db_client:
            report_scheduler_task = asyncio.create_task(
                daily_report_scheduler(bot, db_client, shutdown_event)
            )
        
        # Wait for shutdown signal or polling completion
        tasks_to_wait = [polling_task, asyncio.create_task(shutdown_event.wait())]
        if report_scheduler_task:
            tasks_to_wait.append(report_scheduler_task)
        
        done, pending = await asyncio.wait(
            tasks_to_wait,
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
            # Cancel report scheduler task if running
            if report_scheduler_task and not report_scheduler_task.done():
                report_scheduler_task.cancel()
                try:
                    await report_scheduler_task
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

