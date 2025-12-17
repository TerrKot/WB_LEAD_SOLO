"""Redis client for queues and temporary data."""
import json
import redis.asyncio as redis
from typing import Optional, Dict, Any
import structlog
from apps.bot_service.utils.error_handler import ErrorHandler
from apps.bot_service.utils.logger_utils import log_event

logger = structlog.get_logger()


class RedisClient:
    """Redis client for managing queues and temporary data."""

    def __init__(self, redis_url: str):
        """
        Initialize Redis client.

        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None

    async def connect(self):
        """Connect to Redis."""
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()
            log_event("redis_connected", level="info", redis_url=self.redis_url)
        except Exception as e:
            error_type = ErrorHandler.classify_redis_error(e)
            log_event(
                "redis_connection_failed",
                level="error",
                error_type=error_type,
                error=str(e)[:200],
                redis_url=self.redis_url
            )
            raise

    async def disconnect(self):
        """Disconnect from Redis."""
        if self.redis:
            await self.redis.aclose()
            logger.info("redis_disconnected")

    async def push_calculation(self, calculation_id: str, data: Dict[str, Any]):
        """
        Add calculation task to queue.

        Args:
            calculation_id: Unique calculation ID
            data: Calculation data
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        try:
            task = {
                "calculation_id": calculation_id,
                "data": data
            }
            await self.redis.lpush("calculation_queue", json.dumps(task))
            log_event(
                "calculation_pushed",
                calculation_id=calculation_id,
                user_id=data.get("user_id"),
                level="info"
            )
        except Exception as e:
            error_type = ErrorHandler.classify_redis_error(e)
            log_event(
                "calculation_push_failed",
                calculation_id=calculation_id,
                user_id=data.get("user_id"),
                level="error",
                error_type=error_type,
                error=str(e)[:200]
            )
            raise

    async def push_gpt_task(self, task_id: str, task_data: Dict[str, Any]):
        """
        Add GPT task to queue.

        Args:
            task_id: Unique task ID
            task_data: GPT task data
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        task = {
            "task_id": task_id,
            "data": task_data
        }
        await self.redis.lpush("gpt_queue", json.dumps(task))
        logger.info("gpt_task_pushed", task_id=task_id)

    async def pop_gpt_task(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Pop GPT task from queue (blocking).

        Args:
            timeout: Timeout in seconds

        Returns:
            Task dict with task_id and data, or None if timeout
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        result = await self.redis.brpop("gpt_queue", timeout=timeout)
        if result:
            _, task_json = result
            task = json.loads(task_json)
            logger.debug("gpt_task_popped", task_id=task.get("task_id"))
            return task
        return None

    async def set_calculation_status(self, calculation_id: str, status: str):
        """
        Set calculation status.

        Args:
            calculation_id: Unique calculation ID
            status: Status (pending/processing/completed/failed)
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.set(f"calculation:{calculation_id}:status", status)
        logger.debug("calculation_status_set", calculation_id=calculation_id, status=status)

    async def get_calculation_status(self, calculation_id: str) -> Optional[str]:
        """
        Get calculation status.

        Args:
            calculation_id: Unique calculation ID

        Returns:
            Status or None if not found
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        return await self.redis.get(f"calculation:{calculation_id}:status")

    async def set_calculation_result(
        self, calculation_id: str, result: Dict[str, Any], ttl: int = 86400
    ):
        """
        Save calculation result.

        Args:
            calculation_id: Unique calculation ID
            result: Calculation result
            ttl: Time to live in seconds (default 24 hours)
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.setex(
            f"calculation:{calculation_id}:result",
            ttl,
            json.dumps(result)
        )
        logger.debug("calculation_result_saved", calculation_id=calculation_id, ttl=ttl)

    async def get_calculation_result(self, calculation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get calculation result.

        Args:
            calculation_id: Unique calculation ID

        Returns:
            Result or None if not found
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        result_json = await self.redis.get(f"calculation:{calculation_id}:result")
        if result_json:
            return json.loads(result_json)
        return None

    async def set_user_current_calculation(self, user_id: int, calculation_id: str):
        """
        Set current calculation for user.

        Args:
            user_id: Telegram user ID
            calculation_id: Unique calculation ID
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.set(f"user:{user_id}:current_calculation", calculation_id)
        logger.debug("user_calculation_set", user_id=user_id, calculation_id=calculation_id)

    async def get_user_current_calculation(self, user_id: int) -> Optional[str]:
        """
        Get current calculation for user.

        Args:
            user_id: Telegram user ID

        Returns:
            Calculation ID or None if not found
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        return await self.redis.get(f"user:{user_id}:current_calculation")

    async def set_user_agreement_accepted(self, user_id: int, ttl: int = 31536000):
        """
        Mark user agreement as accepted.

        Args:
            user_id: Telegram user ID
            ttl: Time to live in seconds (default 1 year)
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.setex(
            f"user:{user_id}:agreement_accepted",
            ttl,
            "1"
        )
        logger.debug("user_agreement_accepted", user_id=user_id)

    async def is_user_agreement_accepted(self, user_id: int) -> bool:
        """
        Check if user has accepted agreement.

        Args:
            user_id: Telegram user ID

        Returns:
            True if agreement is accepted, False otherwise
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        result = await self.redis.get(f"user:{user_id}:agreement_accepted")
        return result == "1"

    async def set_calculation_product_data(
        self, calculation_id: str, product_data: Dict[str, Any], ttl: int = 3600
    ):
        """
        Save product data for calculation.

        Args:
            calculation_id: Unique calculation ID
            product_data: Product data from WB API
            ttl: Time to live in seconds (default 1 hour)
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.setex(
            f"calculation:{calculation_id}:product_data",
            ttl,
            json.dumps(product_data)
        )
        logger.debug("calculation_product_data_saved", calculation_id=calculation_id, ttl=ttl)

    async def get_calculation_product_data(self, calculation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get product data for calculation.

        Args:
            calculation_id: Unique calculation ID

        Returns:
            Product data or None if not found
        """
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        product_data_json = await self.redis.get(f"calculation:{calculation_id}:product_data")
        if product_data_json:
            return json.loads(product_data_json)
        return None

