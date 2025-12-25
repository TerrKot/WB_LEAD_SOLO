"""Migration script to add agreement_accepted column to users table."""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from apps.bot_service.clients.database import DatabaseClient
from apps.bot_service.config import config


def fix_database_url_for_local(db_url: str) -> str:
    """
    Fix database URL for local execution (replace Docker hostname with localhost).
    
    Args:
        db_url: Original database URL
        
    Returns:
        Fixed database URL for local access
    """
    if not db_url:
        return db_url
    
    # Replace Docker hostnames with localhost for local execution
    docker_hostnames = ["bd_demo_postgres", "postgres"]
    for hostname in docker_hostnames:
        if hostname in db_url:
            db_url = db_url.replace(hostname, "localhost")
            break
    
    return db_url


async def migrate():
    """Add agreement_accepted column to users table."""
    if not config.DATABASE_URL:
        print("❌ DATABASE_URL не настроен в конфигурации")
        sys.exit(1)
    
    # Fix URL for local execution
    db_url = fix_database_url_for_local(config.DATABASE_URL)
    print(f"🔌 Подключение к БД: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    
    db_client = DatabaseClient(db_url)
    try:
        await db_client.connect()
        print("✅ Подключено к базе данных")
    except Exception as e:
        print(f"❌ Не удалось подключиться к базе данных: {e}")
        sys.exit(1)
    
    try:
        async with db_client.engine.begin() as conn:
            # Check if column already exists
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'agreement_accepted'
            """)
            result = await conn.execute(check_query)
            exists = result.scalar_one_or_none() is not None
            
            if exists:
                print("⚠️  Колонка agreement_accepted уже существует")
            else:
                # Add column
                alter_query = text("""
                    ALTER TABLE users 
                    ADD COLUMN agreement_accepted TIMESTAMP WITH TIME ZONE
                """)
                await conn.execute(alter_query)
                print("✅ Колонка agreement_accepted успешно добавлена")
            
            # Verify
            verify_query = text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'users' AND column_name = 'agreement_accepted'
            """)
            result = await conn.execute(verify_query)
            row = result.fetchone()
            if row:
                print(f"✅ Проверка: колонка {row[0]} типа {row[1]} существует")
            
    except Exception as e:
        print(f"❌ Ошибка при выполнении миграции: {e}")
        sys.exit(1)
    finally:
        await db_client.disconnect()
        print("🔌 Отключено от базы данных")


async def main():
    """Main function."""
    print("🔄 Миграция: добавление колонки agreement_accepted в таблицу users\n")
    await migrate()
    print("\n✅ Миграция завершена")


if __name__ == "__main__":
    asyncio.run(main())





