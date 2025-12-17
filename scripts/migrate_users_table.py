"""Migration script to update users table with all required columns."""
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


async def check_column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if column exists in table."""
    query = text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = :table_name AND column_name = :column_name
    """)
    result = await conn.execute(query, {"table_name": table_name, "column_name": column_name})
    return result.scalar_one_or_none() is not None


async def migrate():
    """Add missing columns to users table."""
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
            # Columns to add
            columns_to_add = [
                ("username", "VARCHAR(255)"),
                ("first_name", "VARCHAR(255)"),
                ("last_name", "VARCHAR(255)"),
                ("language_code", "VARCHAR(10)"),
                ("agreement_accepted", "TIMESTAMP WITH TIME ZONE"),
                ("created_at", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
                ("updated_at", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"),
            ]
            
            added_count = 0
            for column_name, column_type in columns_to_add:
                exists = await check_column_exists(conn, "users", column_name)
                if exists:
                    print(f"⏭️  Колонка {column_name} уже существует")
                else:
                    try:
                        alter_query = text(f"""
                            ALTER TABLE users 
                            ADD COLUMN {column_name} {column_type}
                        """)
                        await conn.execute(alter_query)
                        print(f"✅ Колонка {column_name} успешно добавлена")
                        added_count += 1
                    except Exception as e:
                        print(f"❌ Ошибка при добавлении колонки {column_name}: {e}")
            
            if added_count == 0:
                print("\n✅ Все колонки уже существуют, миграция не требуется")
            else:
                print(f"\n✅ Добавлено колонок: {added_count}")
            
            # Verify all columns
            print("\n📋 Проверка структуры таблицы users:")
            verify_query = text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)
            result = await conn.execute(verify_query)
            columns = result.fetchall()
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                print(f"  - {col[0]}: {col[1]} ({nullable})")
            
    except Exception as e:
        print(f"❌ Ошибка при выполнении миграции: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await db_client.disconnect()
        print("\n🔌 Отключено от базы данных")


async def main():
    """Main function."""
    print("🔄 Миграция: обновление таблицы users\n")
    await migrate()
    print("\n✅ Миграция завершена")


if __name__ == "__main__":
    asyncio.run(main())

