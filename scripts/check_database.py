"""Script to check if data is being saved to database."""
import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, func, text
from apps.bot_service.clients.database import DatabaseClient, User, Calculation
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


def print_error_and_exit(message: str, error: Exception = None):
    """Print error message and exit."""
    print(f"\n❌ {message}")
    if error:
        error_msg = str(error)
        if "getaddrinfo failed" in error_msg or "11001" in error_msg:
            print(f"   Ошибка: Не удалось разрешить имя хоста БД")
            print(f"   Детали: {error_msg[:200]}")
        else:
            print(f"   Ошибка: {error_msg[:200]}")
    
    db_url = config.DATABASE_URL
    print(f"\n📋 Текущий DATABASE_URL: {db_url}")
    
    print("\n💡 Решения:")
    print("   1. Если БД в Docker, используйте localhost:")
    print("      DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/bd_demo")
    print("   2. Проверьте, что PostgreSQL запущен:")
    print("      docker-compose ps")
    print("   3. Проверьте порт БД (обычно 5432):")
    print("      docker-compose up -d postgres")
    print("   4. Если БД на удаленном хосте, проверьте доступность")
    sys.exit(1)


async def check_users():
    """Check users table."""
    if not config.DATABASE_URL:
        print_error_and_exit("DATABASE_URL не настроен в конфигурации")
    
    # Fix URL for local execution
    db_url = fix_database_url_for_local(config.DATABASE_URL)
    print(f"🔌 Подключение к БД: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    
    db_client = DatabaseClient(db_url)
    try:
        await db_client.connect()
    except Exception as e:
        print_error_and_exit("Не удалось подключиться к базе данных", e)
    
    try:
        session = await db_client.get_session()
        try:
            # Count total users
            result = await session.execute(select(func.count(User.user_id)))
            total_users = result.scalar()
            print(f"📊 Всего пользователей: {total_users}")
            
            # Count users with agreement accepted (if column exists)
            try:
                result = await session.execute(
                    select(func.count(User.user_id)).where(User.agreement_accepted.isnot(None))
                )
                users_with_agreement = result.scalar()
                print(f"✅ Пользователей с принятым соглашением: {users_with_agreement}")
            except Exception as e:
                await session.rollback()
                print("⚠️  Колонка agreement_accepted не найдена (нужно обновить таблицу)")
            
            # Get last 5 users
            result = await session.execute(
                select(User).order_by(User.created_at.desc()).limit(5)
            )
            users = result.scalars().all()
            
            print("\n📋 Последние 5 пользователей:")
            for user in users:
                agreement_status = "✅" if user.agreement_accepted else "❌"
                agreement_text = user.agreement_accepted or 'Не принято' if user.agreement_accepted is not None else 'Не принято'
                print(f"  {agreement_status} ID: {user.user_id}, Username: {user.username or 'N/A'}, "
                      f"Имя: {user.first_name or 'N/A'}, Согласие: {agreement_text}")
        finally:
            await session.close()
    finally:
        await db_client.disconnect()


async def check_calculations():
    """Check calculations table."""
    if not config.DATABASE_URL:
        print_error_and_exit("DATABASE_URL не настроен в конфигурации")
    
    # Fix URL for local execution
    db_url = fix_database_url_for_local(config.DATABASE_URL)
    db_client = DatabaseClient(db_url)
    try:
        await db_client.connect()
    except Exception as e:
        print_error_and_exit("Не удалось подключиться к базе данных", e)
    
    try:
        session = await db_client.get_session()
        try:
            # Count total calculations
            result = await session.execute(select(func.count(Calculation.calculation_id)))
            total_calculations = result.scalar()
            print(f"\n📊 Всего расчетов: {total_calculations}")
            
            # Count by type
            result = await session.execute(
                select(Calculation.calculation_type, func.count(Calculation.calculation_id))
                .group_by(Calculation.calculation_type)
            )
            by_type = result.all()
            print("\n📋 По типам:")
            for calc_type, count in by_type:
                print(f"  {calc_type}: {count}")
            
            # Count by status
            result = await session.execute(
                select(Calculation.status, func.count(Calculation.calculation_id))
                .group_by(Calculation.status)
            )
            by_status = result.all()
            print("\n📋 По статусам:")
            for status, count in by_status:
                print(f"  {status}: {count}")
            
            # Get last 5 calculations
            result = await session.execute(
                select(Calculation).order_by(Calculation.created_at.desc()).limit(5)
            )
            calculations = result.scalars().all()
            
            print("\n📋 Последние 5 расчетов:")
            for calc in calculations:
                tn_ved = calc.tn_ved_code or "N/A"
                has_express = "✅" if calc.express_result else "❌"
                has_detailed = "✅" if calc.detailed_result else "❌"
                print(f"  ID: {calc.calculation_id[:8]}..., User: {calc.user_id}, "
                      f"Артикул: {calc.article_id}, Тип: {calc.calculation_type}, "
                      f"Статус: {calc.status}, ТН ВЭД: {tn_ved}, "
                      f"Экспресс: {has_express}, Подробный: {has_detailed}")
        finally:
            await session.close()
    finally:
        await db_client.disconnect()


async def check_specific_user(user_id: int):
    """Check specific user data."""
    if not config.DATABASE_URL:
        print_error_and_exit("DATABASE_URL не настроен в конфигурации")
    
    # Fix URL for local execution
    db_url = fix_database_url_for_local(config.DATABASE_URL)
    db_client = DatabaseClient(db_url)
    try:
        await db_client.connect()
    except Exception as e:
        print_error_and_exit("Не удалось подключиться к базе данных", e)
    
    try:
        session = await db_client.get_session()
        try:
            # Get user
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                print(f"❌ Пользователь {user_id} не найден")
                return
            
            print(f"\n👤 Пользователь {user_id}:")
            print(f"  Username: {user.username or 'N/A'}")
            print(f"  Имя: {user.first_name or 'N/A'}")
            print(f"  Фамилия: {user.last_name or 'N/A'}")
            print(f"  Язык: {user.language_code or 'N/A'}")
            print(f"  Согласие принято: {user.agreement_accepted or 'Нет'}")
            print(f"  Создан: {user.created_at}")
            print(f"  Обновлен: {user.updated_at}")
            
            # Get user calculations
            result = await session.execute(
                select(Calculation).where(Calculation.user_id == user_id)
                .order_by(Calculation.created_at.desc())
            )
            calculations = result.scalars().all()
            
            print(f"\n📊 Расчетов пользователя: {len(calculations)}")
            for calc in calculations[:5]:  # Show last 5
                print(f"  - {calc.calculation_type}: {calc.status}, Артикул: {calc.article_id}, "
                      f"ТН ВЭД: {calc.tn_ved_code or 'N/A'}, Дата: {calc.created_at}")
        finally:
            await session.close()
    finally:
        await db_client.disconnect()


async def main():
    """Main function."""
    # Show current DATABASE_URL (masked)
    db_url = config.DATABASE_URL
    if db_url:
        # Mask password in URL
        if '@' in db_url:
            parts = db_url.split('@')
            if '://' in parts[0]:
                protocol_user = parts[0].split('://')
                if ':' in protocol_user[1]:
                    user_pass = protocol_user[1].split(':')
                    masked_url = f"{protocol_user[0]}://{user_pass[0]}:****@{parts[1]}"
                else:
                    masked_url = db_url
            else:
                masked_url = db_url
        else:
            masked_url = db_url
        print(f"📋 DATABASE_URL: {masked_url}\n")
    else:
        print("⚠️  DATABASE_URL не настроен!\n")
    
    if len(sys.argv) > 1:
        # Check specific user
        try:
            user_id = int(sys.argv[1])
            await check_specific_user(user_id)
        except ValueError:
            print("❌ Неверный user_id. Используйте: python check_database.py [user_id]")
    else:
        # Check all data
        print("🔍 Проверка данных в базе данных...\n")
        try:
            await check_users()
            await check_calculations()
        except Exception as e:
            print_error_and_exit("Ошибка при проверке данных", e)


if __name__ == "__main__":
    asyncio.run(main())

