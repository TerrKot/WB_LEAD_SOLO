"""Script to export basket data (article_id, calculated_basket, actual_basket) to CSV."""
import asyncio
import csv
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, select
from apps.bot_service.clients.database import DatabaseClient, Calculation
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


async def export_basket_data(output_file: str = None):
    """
    Export basket data from calculations table to CSV.
    
    Args:
        output_file: Optional output CSV file path (default: basket_data_YYYYMMDD_HHMMSS.csv)
    """
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
        # Query calculations with basket data
        async with db_client.get_session() as session:
            query = select(
                Calculation.article_id,
                Calculation.calculated_basket,
                Calculation.actual_basket
            ).where(
                (Calculation.calculated_basket.isnot(None)) | (Calculation.actual_basket.isnot(None))
            ).distinct()
            
            result = await session.execute(query)
            rows = result.fetchall()
            
            if not rows:
                print("⚠️  Нет данных для экспорта (calculations с basket информацией не найдены)")
                return
            
            print(f"📊 Найдено записей: {len(rows)}")
            
            # Generate output filename if not provided
            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"basket_data_{timestamp}.csv"
            
            # Write to CSV
            output_path = Path(output_file)
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow(['article_id', 'calculated_basket', 'actual_basket'])
                
                # Write data
                for row in rows:
                    writer.writerow([
                        row.article_id,
                        row.calculated_basket if row.calculated_basket is not None else '',
                        row.actual_basket if row.actual_basket is not None else ''
                    ])
            
            print(f"✅ Данные экспортированы в файл: {output_path.absolute()}")
            print(f"   Всего записей: {len(rows)}")
            
            # Show statistics
            with_both = sum(1 for r in rows if r.calculated_basket is not None and r.actual_basket is not None)
            with_calculated = sum(1 for r in rows if r.calculated_basket is not None)
            with_actual = sum(1 for r in rows if r.actual_basket is not None)
            
            print(f"\n📈 Статистика:")
            print(f"   - С обоими значениями: {with_both}")
            print(f"   - С calculated_basket: {with_calculated}")
            print(f"   - С actual_basket: {with_actual}")
            
    except Exception as e:
        print(f"❌ Ошибка при экспорте данных: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await db_client.disconnect()
        print("\n🔌 Отключено от базы данных")


async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Экспорт данных о basket из БД в CSV')
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Путь к выходному CSV файлу (по умолчанию: basket_data_YYYYMMDD_HHMMSS.csv)'
    )
    
    args = parser.parse_args()
    
    print("🔄 Экспорт данных о basket из таблицы calculations\n")
    await export_basket_data(output_file=args.output)
    print("\n✅ Экспорт завершен")


if __name__ == "__main__":
    asyncio.run(main())

