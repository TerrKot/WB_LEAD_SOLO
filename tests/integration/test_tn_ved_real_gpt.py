"""Real GPT API test for TN VED code selection."""
import pytest
import os
from apps.bot_service.services.gpt_service import GPTService


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("GPT_API_KEY"),
    reason="GPT_API_KEY not set, skipping real API test"
)
async def test_tn_ved_real_gpt_request():
    """Test real GPT API request for TN VED code selection."""
    gpt_service = GPTService()
    
    # Real product name
    product_name = "Рюкзак городской повседневный для ноутбука"
    
    print("\n" + "="*80)
    print("РЕАЛЬНЫЙ ЗАПРОС К GPT API")
    print("="*80)
    print(f"Товар: {product_name}")
    print("Отправка запроса к GPT API...")
    print("="*80 + "\n")
    
    # Make real request
    result = await gpt_service.get_tn_ved_code(product_name=product_name)
    
    if result:
        print("\n" + "="*80)
        print("РЕЗУЛЬТАТ РЕАЛЬНОГО ЗАПРОСА К GPT API:")
        print("="*80)
        print(f"Товар: {product_name}")
        print("-"*80)
        print(f"Код ТН ВЭД: {result['tn_ved_code']}")
        print(f"Тип пошлины: {result['duty_type']}")
        print(f"Ставка пошлины: {result['duty_rate']}%")
        print(f"Ставка НДС: {result['vat_rate']}%")
        print("="*80 + "\n")
        
        # Verify result structure
        assert "tn_ved_code" in result
        assert "duty_type" in result
        assert "duty_rate" in result
        assert "vat_rate" in result
        assert len(result["tn_ved_code"]) == 10
        assert result["tn_ved_code"].isdigit()
    else:
        print("\n" + "="*80)
        print("ОШИБКА: GPT API не вернул результат")
        print("="*80 + "\n")
        pytest.fail("GPT API returned None")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("GPT_API_KEY"),
    reason="GPT_API_KEY not set, skipping real API test"
)
async def test_tn_ved_real_gpt_multiple_products():
    """Test real GPT API requests for multiple products."""
    gpt_service = GPTService()
    
    products = [
        "Рюкзак городской повседневный для ноутбука",
        "Смартфон Apple iPhone 15",
        "Одежда детская хлопковая футболка",
        "Мебель офисная стул вращающийся"
    ]
    
    print("\n" + "="*80)
    print("РЕАЛЬНЫЕ ЗАПРОСЫ К GPT API ДЛЯ РАЗНЫХ ТОВАРОВ")
    print("="*80)
    
    results = []
    for product_name in products:
        print(f"\nЗапрос для: {product_name}")
        result = await gpt_service.get_tn_ved_code(product_name=product_name)
        
        if result:
            print(f"  ✓ Код ТН ВЭД: {result['tn_ved_code']}")
            print(f"  ✓ Тип пошлины: {result['duty_type']}")
            print(f"  ✓ Пошлина: {result['duty_rate']}%")
            print(f"  ✓ НДС: {result['vat_rate']}%")
            results.append((product_name, result))
        else:
            print(f"  ✗ Ошибка: GPT API не вернул результат")
    
    print("\n" + "="*80)
    print("ИТОГОВЫЕ РЕЗУЛЬТАТЫ:")
    print("="*80)
    for product_name, result in results:
        print(f"\n{product_name}:")
        print(f"  Код ТН ВЭД: {result['tn_ved_code']}")
        print(f"  Пошлина: {result['duty_rate']}% ({result['duty_type']})")
        print(f"  НДС: {result['vat_rate']}%")
    print("="*80 + "\n")
    
    assert len(results) > 0, "At least one request should succeed"

