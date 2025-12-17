"""
Скрипт для извлечения данных с Wildberries API v4 (u-card.wb.ru/cards/v4/list)
Извлекает все данные о товарах и форматирует их в читабельном виде
"""

import json
import requests
import sys
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from datetime import datetime


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.wildberries.ru/",
    "Origin": "https://www.wildberries.ru"
}


def extract_articles_from_url(url: str) -> List[int]:
    """Извлекает список артикулов из URL"""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    if 'nm' in params:
        nm_param = params['nm'][0]
        articles = [int(x.strip()) for x in nm_param.split(';') if x.strip().isdigit()]
        return articles
    
    return []


def fetch_v4_data(articles: List[int], dest: int = -1257786, spp: int = 30) -> Optional[Dict[str, Any]]:
    """
    Получает данные с API v4
    
    Args:
        articles: Список артикулов (nmId)
        dest: Регион доставки
        spp: Параметр spp
        
    Returns:
        JSON ответ от API или None при ошибке
    """
    if not articles:
        return None
    
    url = "https://u-card.wb.ru/cards/v4/list"
    params = {
        "appType": 1,
        "curr": "rub",
        "dest": dest,
        "spp": spp,
        "hide_vflags": 4294967296,
        "hide_dflags": 131072,
        "hide_dtype": "9;11;13",
        "ab_testing": "false",
        "lang": "ru",
        "nm": ";".join(str(a) for a in articles)
    }
    
    try:
        response = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка запроса: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        return None


def normalize_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализует данные товара из API v4, сохраняя ВСЕ поля из исходного JSON
    Все поля присутствуют, даже если они пустые/null
    """
    # Создаем копию исходного продукта - сохраняем ВСЕ поля
    normalized = dict(product)
    
    # Обрабатываем вложенные структуры, сохраняя все поля
    if 'sizes' in normalized and isinstance(normalized['sizes'], list):
        normalized_sizes = []
        for size in normalized['sizes']:
            if isinstance(size, dict):
                normalized_size = dict(size)  # Сохраняем все поля размера
                # Обрабатываем цену в размере, сохраняя все поля
                if 'price' in normalized_size and isinstance(normalized_size['price'], dict):
                    price_info = normalized_size['price']
                    normalized_size['price'] = {
                        'basic': price_info.get('basic'),
                        'product': price_info.get('product'),
                        'logistics': price_info.get('logistics'),
                        'return': price_info.get('return')
                    }
                normalized_sizes.append(normalized_size)
            else:
                normalized_sizes.append(size)
        normalized['sizes'] = normalized_sizes
    
    if 'colors' in normalized and isinstance(normalized['colors'], list):
        normalized_colors = []
        for color in normalized['colors']:
            if isinstance(color, dict):
                normalized_colors.append({
                    'id': color.get('id'),
                    'name': color.get('name')
                })
            else:
                normalized_colors.append(color)
        normalized['colors'] = normalized_colors
    
    # Обрабатываем meta, если есть
    if 'meta' in normalized and isinstance(normalized['meta'], dict):
        normalized['meta'] = dict(normalized['meta'])
        if 'tokens' not in normalized['meta']:
            normalized['meta']['tokens'] = []
    
    # Убеждаемся, что все основные поля присутствуют (даже если пустые)
    # Это гарантирует, что структура всегда одинаковая
    default_fields = {
        'id': None,
        'name': '',
        'brand': '',
        'brandId': None,
        'siteBrandId': None,
        'supplier': '',
        'supplierId': None,
        'supplierRating': None,
        'supplierFlags': None,
        'rating': None,
        'reviewRating': None,
        'nmReviewRating': None,
        'feedbacks': None,
        'nmFeedbacks': None,
        'pics': None,
        'volume': None,
        'weight': None,
        'totalQuantity': None,
        'colors': [],
        'sizes': [],
        'subjectId': None,
        'subjectParentId': None,
        'entity': '',
        'matchId': None,
        'sort': None,
        'time1': None,
        'time2': None,
        'wh': None,
        'dtype': None,
        'dist': None,
        'root': None,
        'kindId': None,
        'viewFlags': None,
        'meta': {'tokens': []}
    }
    
    # Заполняем отсутствующие поля значениями по умолчанию
    for field, default_value in default_fields.items():
        if field not in normalized:
            normalized[field] = default_value
    
    return normalized


def print_formatted_data(data: Dict[str, Any], requested_articles: List[int], output_format: str = "table"):
    """
    Выводит данные в читабельном формате
    
    Args:
        data: JSON данные от API
        requested_articles: Список запрошенных артикулов
        output_format: Формат вывода ('table', 'json', 'both')
    """
    if not data or 'products' not in data:
        print("❌ Нет данных о товарах в ответе")
        return
    
    products = data['products']
    
    if not products:
        print("❌ Список товаров пуст")
        return
    
    # Определяем, какие товары не найдены
    found_articles = {p.get('id') for p in products}
    missing_articles = [a for a in requested_articles if a not in found_articles]
    
    print(f"\n{'='*80}")
    print(f"НАЙДЕНО ТОВАРОВ: {len(products)} из {len(requested_articles)}".center(80))
    if missing_articles:
        print(f"НЕ НАЙДЕНО: {len(missing_articles)} товаров".center(80))
        print(f"Артикулы: {', '.join(str(a) for a in missing_articles)}".center(80))
    print(f"{'='*80}\n")
    
    if output_format in ("table", "both"):
        # Табличный формат
        for idx, product in enumerate(products, 1):
            normalized = normalize_product(product)
            
            print(f"\n{'─'*80}")
            print(f"ТОВАР #{idx}".center(80))
            print(f"{'─'*80}")
            
            for key, value in normalized.items():
                if key == "Размеры":
                    continue  # Размеры выводим отдельно
                
                if value is not None and value != "" and value != 0:
                    if isinstance(value, list):
                        value_str = ", ".join(str(v) for v in value) if value else "нет"
                    elif isinstance(value, float):
                        value_str = f"{value:.2f}"
                    else:
                        value_str = str(value)
                    
                    print(f"  {key:.<40} {value_str}")
            
            # Выводим размеры отдельно
            if "Размеры" in normalized and normalized["Размеры"]:
                print(f"\n  Размеры ({len(normalized['Размеры'])}):")
                for size_idx, size in enumerate(normalized["Размеры"], 1):
                    print(f"    Размер #{size_idx}:")
                    for key, value in size.items():
                        if value is not None and value != "" and value != 0:
                            if isinstance(value, float):
                                value_str = f"{value:.2f}"
                            else:
                                value_str = str(value)
                            print(f"      {key:.<35} {value_str}")
            
            print()
    
    if output_format in ("json", "both"):
        # JSON формат
        normalized_products = [normalize_product(p) for p in products]
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "total_products": len(products),
            "products": normalized_products
        }
        
        print(f"\n{'='*80}")
        print("JSON ФОРМАТ".center(80))
        print(f"{'='*80}\n")
        print(json.dumps(output_data, ensure_ascii=False, indent=2))


def main():
    """Основная функция"""
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python wb_v4_fetcher.py <URL или артикулы через ;> [формат: table|json|both]")
        print("\nПримеры:")
        print("  python wb_v4_fetcher.py https://u-card.wb.ru/cards/v4/list?nm=461130092;462557405")
        print("  python wb_v4_fetcher.py 461130092;462557405;216013403")
        print("  python wb_v4_fetcher.py 461130092 json")
        sys.exit(1)
    
    input_arg = sys.argv[1]
    output_format = sys.argv[2] if len(sys.argv) > 2 else "table"
    
    if output_format not in ("table", "json", "both"):
        output_format = "table"
    
    # Извлекаем артикулы
    articles = []
    if input_arg.startswith("http"):
        articles = extract_articles_from_url(input_arg)
    else:
        # Прямой список артикулов через ;
        articles = [int(x.strip()) for x in input_arg.split(';') if x.strip().isdigit()]
    
    if not articles:
        print("❌ Не удалось извлечь артикулы из входных данных")
        sys.exit(1)
    
    print(f"🔍 Запрос данных для {len(articles)} товаров...")
    print(f"   Артикулы: {', '.join(str(a) for a in articles)}")
    
    # Получаем данные
    data = fetch_v4_data(articles)
    
    if data:
        print_formatted_data(data, articles, output_format)
        
        # Сохраняем в файл
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"wb_v4_data_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Полные данные сохранены в: {filename}")
    else:
        print("❌ Не удалось получить данные")
        sys.exit(1)


if __name__ == "__main__":
    main()

