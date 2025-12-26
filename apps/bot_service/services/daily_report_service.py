"""Daily report service for sending statistics to Telegram group."""
from typing import Dict
from datetime import datetime
import pytz
from aiogram import Bot
import structlog

from apps.bot_service.clients.database import DatabaseClient

logger = structlog.get_logger()


class DailyReportService:
    """Service for generating and sending daily reports."""

    def __init__(self, bot: Bot, db_client: DatabaseClient):
        """
        Initialize daily report service.

        Args:
            bot: Telegram bot instance
            db_client: Database client instance
        """
        self.bot = bot
        self.db_client = db_client

    async def generate_report(self) -> str:
        """
        Generate daily report text.

        Returns:
            Formatted report text
        """
        try:
            # Get statistics
            mau = await self.db_client.get_mau()
            wau = await self.db_client.get_wau()
            dau = await self.db_client.get_dau()
            new_users_24h = await self.db_client.get_new_users_24h()
            total_calculations_24h = await self.db_client.get_total_calculations_24h()
            calculations_by_status = await self.db_client.get_calculations_24h_by_status()

            # Format date (Moscow timezone)
            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)
            date_str = now.strftime("%d.%m.%Y")

            # Format status counts (only emoji statuses)
            status_counts_str = ""
            status_order = ["🟢", "🟡", "🟠", "🔴"]
            status_parts = []
            for status in status_order:
                count = calculations_by_status.get(status, 0)
                if count > 0:
                    status_parts.append(f"{status}{count}")
            
            if status_parts:
                status_counts_str = "(" + "".join(status_parts) + ")"
            else:
                status_counts_str = ""

            # Generate report
            report = f"""{date_str} WB бот отчет:
-MAU: {mau}
-WAU: {wau}
-DAU: {dau}
-Новых юзеров (24ч): {new_users_24h}
-Кол-во расчетов (24ч): {total_calculations_24h} {status_counts_str}"""

            logger.info(
                "daily_report_generated",
                mau=mau,
                wau=wau,
                dau=dau,
                new_users_24h=new_users_24h,
                total_calculations_24h=total_calculations_24h
            )

            return report

        except Exception as e:
            logger.error("daily_report_generation_failed", error=str(e))
            raise

    async def send_report(self, chat_id: str) -> bool:
        """
        Generate and send daily report to specified chat.

        Args:
            chat_id: Telegram chat ID to send report to

        Returns:
            True if report was sent successfully, False otherwise
        """
        try:
            report_text = await self.generate_report()
            
            await self.bot.send_message(
                chat_id=chat_id,
                text=report_text
            )

            logger.info("daily_report_sent", chat_id=chat_id)
            return True

        except Exception as e:
            logger.error("daily_report_send_failed", chat_id=chat_id, error=str(e))
            return False

