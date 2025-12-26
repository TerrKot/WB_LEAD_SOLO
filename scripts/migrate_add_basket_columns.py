"""Migration script to add calculated_basket and actual_basket columns to calculations table."""
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
    Only applies if running outside Docker (checking environment).
    
    Args:
        db_url: Original database URL
        
    Returns:
        Fixed database URL for local access
    """
    if not db_url:
        return db_url
    
    # Only fix URL if running outside Docker (check if we're in Docker)
    import os
    is_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'
    
    if not is_docker:
        # Replace Docker hostnames with localhost for local execution
        docker_hostnames = ["bd_demo_postgres", "postgres"]
        for hostname in docker_hostnames:
            if hostname in db_url:
                db_url = db_url.replace(hostname, "localhost")
                break
    
    return db_url


async def migrate():
    """Add calculated_basket and actual_basket columns to calculations table."""
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
            # Check if columns already exist
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'calculations' 
                AND column_name IN ('calculated_basket', 'actual_basket')
            """)
            result = await conn.execute(check_query)
            existing_columns = {row[0] for row in result.fetchall()}
            
            # Add calculated_basket column if not exists
            if 'calculated_basket' not in existing_columns:
                alter_query1 = text("""
                    ALTER TABLE calculations 
                    ADD COLUMN calculated_basket INTEGER
                """)
                await conn.execute(alter_query1)
                print("✅ Колонка calculated_basket успешно добавлена")
            else:
                print("⚠️  Колонка calculated_basket уже существует")
            
            # Add actual_basket column if not exists
            if 'actual_basket' not in existing_columns:
                alter_query2 = text("""
                    ALTER TABLE calculations 
                    ADD COLUMN actual_basket INTEGER
                """)
                await conn.execute(alter_query2)
                print("✅ Колонка actual_basket успешно добавлена")
            else:
                print("⚠️  Колонка actual_basket уже существует")
            
            # Verify
            verify_query = text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'calculations' 
                AND column_name IN ('calculated_basket', 'actual_basket')
                ORDER BY column_name
            """)
            result = await conn.execute(verify_query)
            rows = result.fetchall()
            if rows:
                print("\n✅ Проверка колонок:")
                for row in rows:
                    print(f"   - {row[0]}: {row[1]}")
            
    except Exception as e:
        print(f"❌ Ошибка при выполнении миграции: {e}")
        sys.exit(1)
    finally:
        await db_client.disconnect()
        print("\n🔌 Отключено от базы данных")


async def main():
    """Main function."""
    print("🔄 Миграция: добавление колонок calculated_basket и actual_basket в таблицу calculations\n")
    await migrate()
    print("\n✅ Миграция завершена")


if __name__ == "__main__":
    asyncio.run(main())

