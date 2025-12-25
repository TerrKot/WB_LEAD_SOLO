"""Test basket number formula on multiple articles."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService

async def test_article(article_id: int, wb_parser: WBParserService):
    """Test single article."""
    print(f"\n{'='*80}")
    print(f"ТЕСТИРОВАНИЕ АРТИКУЛА: {article_id}")
    print(f"{'='*80}")
    
    # Calculate expected basket number
    article_str = str(article_id)
    vol = int(article_str[:4]) if len(article_str) >= 4 else int(article_str)
    
    # Calculate basket using our formula
    base = vol // 175
    if vol < 3000:
        adjustment = 2
    elif vol < 3200:
        adjustment = 1
    elif vol < 5000:
        adjustment = 0
    else:
        adjustment = -6
    
    expected_basket = base + adjustment
    expected_basket = max(0, min(99, expected_basket))
    
    print(f"vol (первые 4 цифры): {vol}")
    print(f"Ожидаемый basket: {expected_basket} (формула: ({vol} // 175) + {adjustment})")
    
    # Build URL
    url = wb_parser._build_card_url(article_id)
    print(f"URL: {url}")
    
    # Extract actual basket from URL
    actual_basket = int(url.split("basket-")[1].split(".wbbasket")[0])
    print(f"Фактический basket в URL: {actual_basket}")
    
    if expected_basket == actual_basket:
        print(f"✓ Формула работает корректно!")
    else:
        print(f"✗ Несоответствие! Ожидали {expected_basket}, получили {actual_basket}")
    
    # Try to fetch data
    print(f"\nПопытка получить данные...")
    card_data = await wb_parser.fetch_product_card_data(article_id)
    
    if card_data:
        print(f"✓ Данные получены успешно!")
        print(f"  imt_name: {card_data.get('imt_name', 'N/A')[:60]}...")
        print(f"  subj_name: {card_data.get('subj_name', 'N/A')}")
        
        # Test weight extraction
        weight = wb_parser.get_package_weight(card_data)
        if weight:
            print(f"  Вес упаковки: {weight} кг")
        else:
            print(f"  Вес упаковки: не найден")
        
        # Test dimensions
        dims = wb_parser.get_package_dimensions(card_data)
        if dims:
            print(f"  Габариты: {dims.get('length')}×{dims.get('width')}×{dims.get('height')} см")
            volume = wb_parser.calculate_package_volume(card_data)
            if volume:
                print(f"  Объем: {volume:.2f} литров")
        else:
            print(f"  Габариты: не найдены")
    else:
        print(f"✗ Не удалось получить данные")
    
    return {
        "article_id": article_id,
        "vol": vol,
        "expected_basket": expected_basket,
        "actual_basket": actual_basket,
        "formula_correct": expected_basket == actual_basket,
        "data_received": card_data is not None
    }

async def main():
    """Test multiple articles."""
    articles = [268776304, 148825453, 144196126]
    
    print("="*80)
    print("ТЕСТИРОВАНИЕ ФОРМУЛЫ РАСЧЕТА НОМЕРА КОРЗИНЫ")
    print("="*80)
    
    wb_parser = WBParserService()
    results = []
    
    for article_id in articles:
        result = await test_article(article_id, wb_parser)
        results.append(result)
        await asyncio.sleep(0.5)  # Small delay between requests
    
    # Summary
    print(f"\n{'='*80}")
    print("ИТОГОВЫЙ ОТЧЕТ")
    print(f"{'='*80}")
    
    print(f"\n{'Артикул':<15} {'vol':<8} {'Ожидаемый':<12} {'Фактический':<14} {'Формула':<10} {'Данные':<10}")
    print("-" * 80)
    
    for r in results:
        formula_status = "✓" if r["formula_correct"] else "✗"
        data_status = "✓" if r["data_received"] else "✗"
        print(f"{r['article_id']:<15} {r['vol']:<8} {r['expected_basket']:<12} {r['actual_basket']:<14} {formula_status:<10} {data_status:<10}")
    
    # Statistics
    formula_correct = sum(1 for r in results if r["formula_correct"])
    data_received = sum(1 for r in results if r["data_received"])
    
    print(f"\nСтатистика:")
    print(f"  Формула работает корректно: {formula_correct}/{len(results)}")
    print(f"  Данные получены: {data_received}/{len(results)}")
    
    if formula_correct == len(results):
        print(f"\n✓ Формула работает для всех протестированных артикулов!")
    else:
        print(f"\n✗ Формула требует доработки для некоторых артикулов")

if __name__ == "__main__":
    asyncio.run(main())






