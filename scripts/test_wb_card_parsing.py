"""Test script for WB card data parsing functionality."""
import asyncio
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.gpt_service import GPTService
from apps.bot_service.config import config


async def test_card_parsing(article_id: int):
    """Test card data parsing for given article ID."""
    print("=" * 80)
    print(f"ТЕСТИРОВАНИЕ ПАРСИНГА ДАННЫХ ДЛЯ АРТИКУЛА: {article_id}")
    print("=" * 80)
    print()
    
    wb_parser = WBParserService()
    
    # Test 1: Fetch card data
    print("1. Получение данных из card.json...")
    print("-" * 80)
    card_data = await wb_parser.fetch_product_card_data(article_id)
    
    if not card_data:
        print("[ERROR] ОШИБКА: Не удалось получить card_data")
        return
    
    print("[OK] card_data получен успешно")
    print(f"   Ключи в ответе: {list(card_data.keys())[:10]}...")
    print()
    
    # Test 2: Extract basic TN VED data
    print("2. Извлечение базовых данных для ТН ВЭД...")
    print("-" * 80)
    basic_data = wb_parser.get_tn_ved_basic_data(card_data)
    print(f"   subj_name: {basic_data.get('subj_name')}")
    print(f"   subj_root_name: {basic_data.get('subj_root_name')}")
    print(f"   imt_name: {basic_data.get('imt_name')}")
    print()
    
    # Test 3: Fetch category data
    print("3. Получение данных категории из webapi/product/data...")
    print("-" * 80)
    subject_id = card_data.get("data", {}).get("subject_id")
    category_data = await wb_parser.fetch_product_category_data(article_id, subject_id)
    
    if category_data:
        print("[OK] category_data получен успешно")
        print(f"   type_name: {category_data.get('type_name')}")
        print(f"   category_name: {category_data.get('category_name')}")
        basic_data_with_category = wb_parser.get_tn_ved_basic_data(card_data, category_data)
        print(f"   type_name (в basic_data): {basic_data_with_category.get('type_name')}")
        print(f"   category_name (в basic_data): {basic_data_with_category.get('category_name')}")
    else:
        print("[WARN] category_data не получен (может быть нормально)")
    print()
    
    # Test 4: Extract package weight
    print("4. Извлечение веса упаковки...")
    print("-" * 80)
    package_weight = wb_parser.get_package_weight(card_data)
    if package_weight:
        print(f"[OK] Вес упаковки: {package_weight} кг")
    else:
        print("[WARN] Вес упаковки не найден")
    print()
    
    # Test 5: Extract package dimensions
    print("5. Извлечение габаритов упаковки...")
    print("-" * 80)
    dimensions = wb_parser.get_package_dimensions(card_data)
    if dimensions:
        print(f"[OK] Габариты упаковки:")
        print(f"   Длина: {dimensions.get('length')} см")
        print(f"   Ширина: {dimensions.get('width')} см")
        print(f"   Высота: {dimensions.get('height')} см")
    else:
        print("[WARN] Габариты упаковки не найдены")
    print()
    
    # Test 6: Calculate package volume
    print("6. Расчет объема упаковки...")
    print("-" * 80)
    package_volume = wb_parser.calculate_package_volume(card_data)
    if package_volume:
        print(f"[OK] Объем упаковки: {package_volume:.2f} литров")
    else:
        print("[WARN] Объем упаковки не может быть рассчитан (нет габаритов)")
    print()
    
    # Test 7: Test TN VED data extraction stages
    print("7. Тестирование этапов извлечения данных для ТН ВЭД...")
    print("-" * 80)
    
    # Stage 1: Basic data
    basic_data_full = wb_parser.get_tn_ved_basic_data(card_data, category_data)
    print("Этап 1 (базовые данные):")
    print(json.dumps(basic_data_full, ensure_ascii=False, indent=2))
    print()
    
    # Stage 2: With description
    data_with_desc = wb_parser.get_tn_ved_with_description(card_data, category_data)
    print("Этап 2 (с описанием):")
    desc_preview = data_with_desc.get('description', '')[:200] + '...' if len(data_with_desc.get('description', '')) > 200 else data_with_desc.get('description', '')
    print(f"   description (первые 200 символов): {desc_preview}")
    print()
    
    # Stage 3: Full data
    full_data = wb_parser.get_tn_ved_full_data(card_data)
    print(f"Этап 3 (полные данные):")
    print(f"   Размер JSON: {len(json.dumps(full_data, ensure_ascii=False))} символов")
    print(f"   Ключи: {list(full_data.keys())[:15]}...")
    print()
    
    # Test 8: GPT TN VED code selection (if API key available)
    print("8. Тестирование определения ТН ВЭД через GPT...")
    print("-" * 80)
    
    if not config.GPT_API_KEY:
        print("[WARN] GPT_API_KEY не установлен, пропускаем тест GPT")
    else:
        try:
            gpt_service = GPTService()
            
            # Create mock product_data for compatibility
            product_data = {
                'id': article_id,
                'name': basic_data.get('imt_name', 'Товар'),
                'description': data_with_desc.get('description', '')
            }
            
            print("   Отправка запроса к GPT API...")
            tn_ved_data = await gpt_service.get_tn_ved_code(
                product_data=product_data,
                card_data=card_data,
                category_data=category_data
            )
            
            if tn_ved_data:
                print("[OK] ТН ВЭД код определен успешно:")
                print(f"   Код ТН ВЭД: {tn_ved_data.get('tn_ved_code')}")
                print(f"   Тип пошлины: {tn_ved_data.get('duty_type')}")
                print(f"   Ставка пошлины: {tn_ved_data.get('duty_rate')}")
                print(f"   Ставка НДС: {tn_ved_data.get('vat_rate')}")
            else:
                print("[ERROR] ОШИБКА: Не удалось определить ТН ВЭД код")
        except Exception as e:
            print(f"[ERROR] ОШИБКА при запросе к GPT: {str(e)}")
            print(f"   Тип ошибки: {type(e).__name__}")
    
    print()
    print("=" * 80)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 80)
    
    # Summary
    print()
    print("ИТОГОВЫЙ ОТЧЕТ:")
    print("-" * 80)
    print(f"[{'OK' if card_data else 'ERROR'}] card_data: {'Получен' if card_data else 'Не получен'}")
    print(f"[{'OK' if category_data else 'WARN'}] category_data: {'Получен' if category_data else 'Не получен'}")
    print(f"[{'OK' if package_weight else 'WARN'}] Вес упаковки: {package_weight if package_weight else 'Не найден'} кг")
    print(f"[{'OK' if dimensions else 'WARN'}] Габариты: {'Найдены' if dimensions else 'Не найдены'}")
    print(f"[{'OK' if package_volume else 'WARN'}] Объем: {package_volume if package_volume else 'Не рассчитан'} л")
    if config.GPT_API_KEY:
        print(f"[{'OK' if tn_ved_data else 'ERROR'}] ТН ВЭД код: {tn_ved_data.get('tn_ved_code') if tn_ved_data else 'Не определен'}")


if __name__ == "__main__":
    article_id = 458510242
    asyncio.run(test_card_parsing(article_id))

