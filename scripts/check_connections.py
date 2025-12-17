"""Script to check Redis and PostgreSQL connections."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from apps.bot_service.config import config
from apps.bot_service.clients.redis import RedisClient
from apps.bot_service.clients.database import DatabaseClient


async def check_redis():
    """Check Redis connection."""
    print("Checking Redis connection...")
    try:
        client = RedisClient(config.REDIS_URL)
        await client.connect()
        await client.redis.ping()
        print("✅ Redis connection: OK")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"❌ Redis connection: FAILED - {e}")
        return False


async def check_database():
    """Check PostgreSQL connection."""
    print("Checking PostgreSQL connection...")
    try:
        client = DatabaseClient(config.DATABASE_URL)
        await client.connect()
        from sqlalchemy import text
        session = await client.get_session()
        async with session:
            result = await session.execute(text("SELECT 1 as test"))
            row = result.scalar()
            if row == 1:
                print("✅ PostgreSQL connection: OK")
                await client.disconnect()
                return True
        await client.disconnect()
        return False
    except Exception as e:
        print(f"❌ PostgreSQL connection: FAILED - {e}")
        return False


async def main():
    """Main function."""
    print(f"Redis URL: {config.REDIS_URL}")
    print(f"Database URL: {config.DATABASE_URL.split('@')[-1]}")
    print()
    
    redis_ok = await check_redis()
    print()
    db_ok = await check_database()
    
    print()
    if redis_ok and db_ok:
        print("✅ All connections OK")
        sys.exit(0)
    else:
        print("❌ Some connections failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

