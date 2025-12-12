"""
WB Card JSON Link Generator + Parser
Основной модуль для работы с карточками товаров Wildberries
"""
import re
import logging
import time
import json as json_lib
from typing import Dict, Optional, Any
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,  # INFO уровень - только важная информация
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WBCardError(Exception):
    """Базовое исключение для ошибок WB Card"""
    pass


class InvalidInputError(WBCardError):
    """Ошибка невалидного входного значения"""
    pass


class NotFoundError(WBCardError):
    """Товар не найден"""
    pass


class NetworkError(WBCardError):
    """Ошибка сети"""
    pass


def extract_nmid(input_value: str) -> int:
    """
    Извлекает nmId из различных форматов входных данных.
    
    Поддерживает:
    - https://www.wildberries.ru/catalog/<nmId>/detail.aspx
    - https://www.wildberries.ru/catalog/<nmId>/detail.aspx?targetUrl=...
    - просто число <nmId>
    
    Args:
        input_value: URL или nmId
        
    Returns:
        int: nmId
        
    Raises:
        InvalidInputError: если не удалось извлечь nmId
    """
    input_value = input_value.strip()
    
    # Если это просто число
    if input_value.isdigit():
        return int(input_value)
    
    # Если это URL
    if input_value.startswith('http'):
        # Парсим URL
        parsed = urlparse(input_value)
        path = parsed.path
        
        # Ищем паттерн /catalog/<nmId>/detail.aspx
        match = re.search(r'/catalog/(\d+)/detail\.aspx', path)
        if match:
            return int(match.group(1))
        
        # Если не нашли в пути, проверяем query параметры
        query_params = parse_qs(parsed.query)
        if 'nm' in query_params:
            nmid_str = query_params['nm'][0]
            if nmid_str.isdigit():
                return int(nmid_str)
    
    raise InvalidInputError(f"Не удалось извлечь nmId из: {input_value}")


def _get_basket_number(nmid: int) -> str:
    """
    Определяет номер basket сервера на основе nmId.
    Используется для распределения нагрузки по серверам.
    """
    # Алгоритм определения basket сервера (обычно по последним цифрам nmId)
    basket_num = (nmid // 100000) % 10
    if basket_num < 1:
        basket_num = 1
    elif basket_num > 3:
        basket_num = 3
    return f"{basket_num:02d}"


def generate_json_url(
    nmid: int, 
    curr: str = "rub", 
    dest: int = -1257786,
    regions: str = "80,64,83,4,38,33,70,69,86,30,40,48,1,66,31,22",
    app_type: int = 1,
    spp: int = 0,
    endpoint_type: str = "auto"
) -> str:
    """
    Генерирует прямую ссылку на JSON карточки WB.
    Использует публичный эндпоинт card.wb.ru/cards/detail (без v1).
    
    Args:
        nmid: ID товара
        curr: Валюта (по умолчанию rub)
        dest: Регион доставки (по умолчанию -1257786 для Москвы/РФ)
        regions: Список регионов через запятую (по умолчанию основные регионы РФ)
        app_type: Тип приложения (по умолчанию 1 - веб-приложение)
        spp: Параметр spp (по умолчанию 0 - без спец. скидок)
        endpoint_type: Тип эндпоинта ('auto', 'card', 'basket')
        
    Returns:
        str: URL для получения JSON карточки
    """
    if endpoint_type == "basket":
        basket_num = _get_basket_number(nmid)
        vol = nmid // 100000
        part = nmid // 1000
        return f"https://basket-{basket_num}.wb.ru/vol{vol}/part{part}/{nmid}/info/ru.json"
    else:
        # Основной публичный эндпоинт card.wb.ru/cards/detail (без v1!)
        # Формат: nm={nmId}; (точка с запятой в конце рекомендуется)
        params = {
            'appType': app_type,
            'curr': curr,
            'dest': dest,
            'regions': regions,
            'spp': spp,
            'nm': f"{nmid};"  # Точка с запятой в конце для корректности
        }
        
        # Формируем URL с параметрами
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return f"https://card.wb.ru/cards/detail?{query_string}"


def _get_available_endpoints(nmid: int) -> list:
    """
    Возвращает список доступных эндпоинтов для попытки запроса.
    Приоритет: card.wb.ru/cards/detail (публичный JSON-эндпоинт) -> basket-*.wb.ru (внутренние серверы).
    """
    endpoints = []
    
    # 1. Основной публичный эндпоинт card.wb.ru/cards/detail (правильный формат без v1)
    # Используем стандартные параметры для РФ
    dest = -1257786
    regions = "80,64,83,4,38,33,70,69,86,30,40,48,1,66,31,22"
    endpoints.append(
        f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest={dest}&regions={regions}&spp=0&nm={nmid};"
    )
    
    # 2. Альтернативный вариант с упрощенными параметрами (на случай если первый не работает)
    endpoints.append(
        f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&regions=80&spp=0&nm={nmid};"
    )
    
    # 3. Старый формат с v1 (на случай если новый не работает)
    endpoints.append(
        f"https://card.wb.ru/cards/v1/detail?nm={nmid}&curr=rub&lang=ru&regions=80"
    )
    
    # 4. Basket эндпоинты (распределенные внутренние серверы, альтернативный формат)
    vol = nmid // 100000
    part = nmid // 1000
    
    # Пробуем несколько basket серверов
    for basket_num in ["01", "02", "03", "04", "05"]:
        endpoints.append(f"https://basket-{basket_num}.wb.ru/vol{vol}/part{part}/{nmid}/info/ru.json")
    
    return endpoints


def _create_session() -> requests.Session:
    """Создает сессию requests с настройками retry и таймаутов"""
    session = requests.Session()
    
    # Настройка retry стратегии
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def _parse_card_api_response(data: dict, nmid: int) -> Dict[str, Any]:
    """
    Парсит ответ от card.wb.ru/cards/detail API (формат с data.products).
    """
    # Проверяем структуру ответа
    if not data.get('data'):
        # Возможно, ответ уже содержит products напрямую
        if isinstance(data, list) and len(data) > 0:
            products = data
        elif isinstance(data, dict) and 'products' in data:
            products = data['products']
        else:
            raise NotFoundError(f"Товар с nmId={nmid} не найден (неверная структура ответа)")
    else:
        products = data['data'].get('products', [])
    
    if not products or len(products) == 0:
        raise NotFoundError(f"Товар с nmId={nmid} не найден")
    
    # Ищем товар с нужным nmId (на случай если запрашивали несколько товаров)
    product = None
    for p in products:
        if p.get('id') == nmid or p.get('nmId') == nmid:
            product = p
            break
    
    if not product:
        # Если не нашли по ID, берем первый
        product = products[0]
    
    result = {
        "nmId": product.get('id') or product.get('nmId') or nmid,
        "name": product.get('name', ''),
        "brand": product.get('brand', ''),
        "price": product.get('salePriceU', 0) / 100 if product.get('salePriceU') else None,
        "priceOld": product.get('priceU', 0) / 100 if product.get('priceU') else None,
        "currency": "RUB",
    }
    
    # Процент скидки - может быть уже в ответе как 'sale', или вычисляем
    if product.get('sale') is not None:
        result["discountPercent"] = product.get('sale')
    elif result['price'] and result['priceOld']:
        discount = ((result['priceOld'] - result['price']) / result['priceOld']) * 100
        result["discountPercent"] = round(discount, 2)
    else:
        result["discountPercent"] = None
    
    # Преобразуем характеристики
    characteristics = {}
    if product.get('characteristics'):
        for char in product['characteristics']:
            if isinstance(char, list) and len(char) >= 2:
                char_name = char[0] if isinstance(char[0], str) else str(char[0])
                char_value = char[1] if len(char) > 1 else ''
                characteristics[char_name] = char_value
    
    result["characteristics"] = characteristics
    return result, product


def _parse_basket_api_response(data: dict, nmid: int) -> Dict[str, Any]:
    """
    Парсит ответ от basket-*.wb.ru API (прямой формат товара).
    """
    if not data:
        raise NotFoundError(f"Товар с nmId={nmid} не найден")
    
    result = {
        "nmId": nmid,
        "name": data.get('imt_name', ''),
        "brand": data.get('selling', {}).get('brand_name', ''),
        "price": data.get('price', {}).get('price', 0) / 100 if data.get('price', {}).get('price') else None,
        "priceOld": data.get('price', {}).get('old_price', 0) / 100 if data.get('price', {}).get('old_price') else None,
        "currency": "RUB",
    }
    
    # Вычисляем процент скидки
    if result['price'] and result['priceOld']:
        discount = ((result['priceOld'] - result['price']) / result['priceOld']) * 100
        result["discountPercent"] = round(discount, 2)
    else:
        result["discountPercent"] = None
    
    # Преобразуем характеристики
    characteristics = {}
    if data.get('options'):
        for option in data['options']:
            if isinstance(option, dict) and 'name' in option and 'value' in option:
                characteristics[option['name']] = option['value']
    
    result["characteristics"] = characteristics
    return result, data


def _check_product_exists(nmid: int) -> bool:
    """
    Проверяет существование товара через веб-страницу.
    """
    try:
        url = f"https://www.wildberries.ru/catalog/{nmid}/detail.aspx"
        session = _create_session()
        response = session.get(url, timeout=5, allow_redirects=False)
        session.close()
        # Если товар существует, вернется 200, если нет - 404 или редирект
        return response.status_code == 200
    except:
        return True  # Если не удалось проверить, предполагаем что существует


def _fetch_official_api(nmid: int, api_token: str, include_raw: bool = False) -> Dict[str, Any]:
    """
    Получает данные через официальный API Wildberries (требует токен продавца).
    Этот API не требует PoW и работает стабильно.
    """
    url = "https://suppliers-api.wildberries.ru/content/v1/cards/cursor/list"
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json',
    }
    
    # Официальный API использует POST запрос с фильтрацией по nmID
    payload = {
        "filter": {
            "nmID": [nmid]
        },
        "limit": 1
    }
    
    session = _create_session()
    try:
        logger.info(f"Запрос к официальному API для nmId={nmid}")
        response = session.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('data', {}).get('cards') or len(data['data']['cards']) == 0:
            raise NotFoundError(f"Товар с nmId={nmid} не найден в официальном API")
        
        card = data['data']['cards'][0]
        
        # Нормализуем данные из официального API
        result = {
            "nmId": card.get('nmID', nmid),
            "name": card.get('imtName', ''),
            "brand": card.get('brand', ''),
            "price": None,  # Цена в официальном API получается отдельно
            "priceOld": None,
            "currency": "RUB",
            "discountPercent": None,
            "characteristics": {},
        }
        
        # Преобразуем характеристики
        if card.get('characteristics'):
            for char in card['characteristics']:
                if isinstance(char, dict):
                    char_name = char.get('name', '')
                    char_value = char.get('value', '')
                    if char_name:
                        result["characteristics"][char_name] = char_value
        
        if include_raw:
            result["raw"] = data
        
        logger.info("Данные успешно получены через официальный API")
        return result
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise NetworkError("Неверный API токен. Проверьте токен в личном кабинете продавца.")
        elif e.response.status_code == 403:
            raise NetworkError("Нет доступа к Content API. Убедитесь, что токен имеет права на категорию 'Контент'.")
        else:
            raise NetworkError(f"Ошибка официального API: {e.response.status_code}")
    finally:
        session.close()


def _parse_html_page(nmid: int) -> Optional[Dict[str, Any]]:
    """
    Парсит HTML страницу товара и извлекает все данные: цена, размеры, вес, название, описание.
    Используется как основной способ получения данных, если API недоступен.
    """
    try:
        url = f"https://www.wildberries.ru/catalog/{nmid}/detail.aspx"
        logger.info(f"Парсинг HTML страницы: {url}")
        
        session = _create_session()
        # Более реалистичные заголовки браузера
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }
        
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        session.close()
        
        if response.status_code == 498:
            logger.warning("HTML страница заблокирована антибот защитой (498)")
            raise NetworkError(
                "Страница товара заблокирована антибот защитой Wildberries (статус 498). "
                "Возможные причины: автоматические запросы, доступ из другой страны, или временная блокировка. "
                "Попробуйте позже, используйте VPN/прокси с российским IP, или проверьте товар вручную на сайте."
            )
        elif response.status_code not in [200, 301, 302]:
            logger.warning(f"HTML страница вернула статус {response.status_code}")
            if response.status_code == 403:
                raise NetworkError(
                    "Доступ запрещен (403). Возможно, Wildberries блокирует автоматические запросы. "
                    "Попробуйте позже."
                )
            return None
        
        html = response.text
        
        result = {
            'nmId': nmid,
            'name': '',
            'price': None,
            'priceOld': None,
            'weight': None,
            'dimensions': None,
            'description': '',
            'characteristics': {},
        }
        
        # 1. Ищем встроенный JSON с данными товара
        json_patterns = [
            r'window\.__APP_DATA__\s*=\s*({.+?});',
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'window\.__WB_DATA__\s*=\s*({.+?});',
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>({.+?})</script>',
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json_lib.loads(match.group(1))
                    # Ищем данные товара в разных местах структуры
                    product = None
                    
                    # Пробуем разные пути в структуре
                    paths = [
                        ['data', 'product'],
                        ['props', 'pageProps', 'product'],
                        ['product'],
                        ['card'],
                        ['goods'],
                        ['data', 'card'],
                    ]
                    
                    for path in paths:
                        temp = data
                        for key in path:
                            if isinstance(temp, dict) and key in temp:
                                temp = temp[key]
                            else:
                                temp = None
                                break
                        if temp and isinstance(temp, dict):
                            product = temp
                            break
                    
                    if product:
                        # Извлекаем данные из JSON
                        result['name'] = product.get('name') or product.get('imt_name') or product.get('title') or ''
                        result['price'] = product.get('salePriceU', 0) / 100 if product.get('salePriceU') else None
                        result['priceOld'] = product.get('priceU', 0) / 100 if product.get('priceU') else None
                        
                        # Характеристики
                        if product.get('characteristics'):
                            for char in product['characteristics']:
                                if isinstance(char, list) and len(char) >= 2:
                                    name = str(char[0])
                                    value = str(char[1])
                                    result['characteristics'][name] = value
                                    
                                    # Ищем вес и размеры в характеристиках
                                    if 'вес' in name.lower() or 'weight' in name.lower():
                                        result['weight'] = value
                                    if 'размер' in name.lower() or 'dimension' in name.lower() or 'габарит' in name.lower():
                                        result['dimensions'] = value
                        
                        logger.info("Данные извлечены из встроенного JSON")
                        return result
                except (json_lib.JSONDecodeError, KeyError, TypeError) as e:
                    logger.debug(f"Ошибка парсинга JSON: {e}")
                    continue
        
        # 2. Парсим HTML напрямую, если JSON не найден
        # Название из title или h1
        title_match = re.search(r'<title>(.+?)</title>', html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            # Убираем лишнее из title
            title = re.sub(r'\s*-\s*Wildberries.*$', '', title, flags=re.IGNORECASE)
            result['name'] = title
        
        h1_match = re.search(r'<h1[^>]*>(.+?)</h1>', html, re.IGNORECASE | re.DOTALL)
        if h1_match and not result['name']:
            result['name'] = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()
        
        # Цена
        price_patterns = [
            r'"salePriceU":\s*(\d+)',
            r'"priceU":\s*(\d+)',
            r'data-price=["\'](\d+)["\']',
            r'class="price[^"]*"[^>]*>.*?(\d+[.,]\d+)',
            r'<span[^>]*class="[^"]*price[^"]*"[^>]*>.*?(\d+[.,]?\d*)',
        ]
        for pattern in price_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                try:
                    price_val = float(matches[0].replace(',', '.'))
                    if price_val > 100:  # Если цена в копейках
                        price_val = price_val / 100
                    if not result['price']:
                        result['price'] = price_val
                    elif not result['priceOld']:
                        result['priceOld'] = price_val
                except:
                    continue
        
        # Описание
        desc_patterns = [
            r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.+?)</div>',
            r'<p[^>]*class="[^"]*description[^"]*"[^>]*>(.+?)</p>',
            r'<div[^>]*id="description"[^>]*>(.+?)</div>',
            r'"description":\s*"([^"]+)"',
        ]
        for pattern in desc_patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                desc = match.group(1)
                desc = re.sub(r'<[^>]+>', '', desc)  # Убираем HTML теги
                desc = re.sub(r'\s+', ' ', desc).strip()
                if desc and len(desc) > 10:
                    result['description'] = desc
                    break
        
        # Размеры и вес из текста страницы
        size_weight_patterns = [
            (r'Размеры?[^:]*:\s*([^\n<]+)', 'dimensions'),
            (r'Вес[^:]*:\s*([^\n<]+)', 'weight'),
            (r'Габариты[^:]*:\s*([^\n<]+)', 'dimensions'),
            (r'Масса[^:]*:\s*([^\n<]+)', 'weight'),
        ]
        for pattern, key in size_weight_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match and not result[key]:
                result[key] = match.group(1).strip()
        
        # Характеристики из таблицы
        char_table_pattern = r'<tr[^>]*>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?</tr>'
        char_matches = re.findall(char_table_pattern, html, re.IGNORECASE | re.DOTALL)
        for name, value in char_matches:
            name = name.strip()
            value = value.strip()
            if name and value:
                result['characteristics'][name] = value
                # Проверяем вес и размеры
                if ('вес' in name.lower() or 'weight' in name.lower()) and not result['weight']:
                    result['weight'] = value
                if ('размер' in name.lower() or 'dimension' in name.lower() or 'габарит' in name.lower()) and not result['dimensions']:
                    result['dimensions'] = value
        
        if result['name'] or result['price']:
            logger.info("Данные извлечены из HTML")
            return result
        
        return None
    except Exception as e:
        logger.error(f"Ошибка парсинга HTML: {type(e).__name__}: {e}")
        return None


def fetch_card_data(nmid: int, include_raw: bool = False) -> Dict[str, Any]:
    """
    Забирает данные карточки товара с WB API.
    Пробует несколько эндпоинтов до успешного ответа.
    
    Args:
        nmid: ID товара
        include_raw: Включать ли полный raw JSON ответ
        
    Returns:
        dict: Нормализованные данные карточки
        
    Raises:
        NotFoundError: если товар не найден
        NetworkError: при ошибках сети
    """
    # Пробуем публичные API эндпоинты
    endpoints = _get_available_endpoints(nmid)
    logger.info(f"Попытка получить данные для nmId={nmid} через {len(endpoints)} эндпоинтов")
    
    session = _create_session()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.wildberries.ru/',
        'Origin': 'https://www.wildberries.ru',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }
    
    last_error = None
    
    for i, json_url in enumerate(endpoints):
        # Добавляем небольшую задержку между попытками
        if i > 0:
            time.sleep(0.5)
        try:
            logger.debug(f"[{i+1}/{len(endpoints)}] {json_url[:80]}...")
            
            response = session.get(
                json_url,
                timeout=(5, 10),  # connect timeout, read timeout
                headers=headers
            )
            
            # Проверяем PoW защиту
            if 'x-pow' in response.headers:
                pow_status = response.headers['x-pow']
                if 'status=invalid' in pow_status:
                    logger.warning(f"Эндпоинт защищен PoW (Proof of Work) - требуется токен")
                    raise NetworkError("API защищен Proof of Work. Wildberries требует решение вычислительной задачи для доступа.")
            
            if response.status_code != 200:
                logger.warning(f"Статус {response.status_code} для эндпоинта {i+1}")
            
            response.raise_for_status()
            
            try:
                data = response.json()
            except ValueError as e:
                logger.warning(f"Ошибка парсинга JSON: {e}")
                raise
            
            # Определяем тип ответа и парсим
            # Проверяем формат card.wb.ru API (data.products или прямой products)
            if ('data' in data and 'products' in data.get('data', {})) or \
               ('products' in data and isinstance(data['products'], list)) or \
               (isinstance(data, list) and len(data) > 0):
                # Формат card.wb.ru/cards/detail API
                try:
                    result, product_data = _parse_card_api_response(data, nmid)
                    if include_raw:
                        result["raw"] = data
                    logger.info(f"Успешно получены данные через card API")
                    return result
                except (KeyError, IndexError, TypeError) as e:
                    # Если не удалось распарсить как card API, пробуем basket формат
                    logger.debug(f"Не удалось распарсить как card API: {e}, пробуем basket формат")
                    result, product_data = _parse_basket_api_response(data, nmid)
                    if include_raw:
                        result["raw"] = data
                    logger.info(f"Успешно получены данные через basket API")
                    return result
            else:
                # Формат basket-*.wb.ru API
                result, product_data = _parse_basket_api_response(data, nmid)
                if include_raw:
                    result["raw"] = data
                logger.info(f"Успешно получены данные через basket API")
                return result
                
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else 'N/A'
            
            # Проверяем PoW защиту
            if hasattr(e, 'response') and e.response and 'x-pow' in e.response.headers:
                pow_status = e.response.headers['x-pow']
                if 'status=invalid' in pow_status:
                    logger.warning(f"Эндпоинт {i+1} защищен PoW")
                    last_error = NetworkError(
                        "API Wildberries защищен Proof of Work (PoW). "
                        "Требуется решение вычислительной задачи для доступа. "
                        "Публичные эндпоинты больше не доступны без авторизации."
                    )
                    continue
            
            if status_code == 404:
                logger.debug(f"404 для эндпоинта {i+1}")
                # 404 может означать как отсутствие товара, так и географическую блокировку
                last_error = NotFoundError(
                    f"Товар с nmId={nmid} не найден или эндпоинт недоступен (404). "
                    f"Возможно, требуется доступ из России или товар не существует."
                )
                continue
            elif status_code == 429:
                logger.warning(f"429 Too Many Requests")
                last_error = NetworkError(f"Слишком много запросов (429), попробуйте позже")
                continue
            else:
                logger.debug(f"HTTP {status_code} для эндпоинта {i+1}")
                last_error = NetworkError(f"HTTP ошибка {status_code}")
                continue
        except requests.exceptions.Timeout:
            logger.debug(f"Таймаут для эндпоинта {i+1}")
            last_error = NetworkError(f"Таймаут при запросе данных")
            continue
        except requests.exceptions.ConnectionError as e:
            logger.debug(f"Ошибка подключения для эндпоинта {i+1}")
            last_error = NetworkError(f"Ошибка подключения: {str(e)}")
            continue
        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Ошибка парсинга для эндпоинта {i+1}: {type(e).__name__}")
            last_error = NetworkError(f"Ошибка парсинга ответа: {str(e)}")
            continue
        except Exception as e:
            logger.debug(f"Ошибка для эндпоинта {i+1}: {type(e).__name__}: {str(e)}")
            last_error = NetworkError(f"Ошибка: {str(e)}")
            continue
    
    # Если все эндпоинты не сработали, используем парсинг HTML
    session.close()
    
    logger.info(f"Парсинг HTML страницы товара...")
    try:
        html_data = _parse_html_page(nmid)
    except NetworkError as e:
        # Если парсинг HTML тоже не сработал из-за блокировки, пробрасываем ошибку
        raise e
    
    if html_data:
        # Преобразуем данные из HTML в нужный формат
        result = {
            "nmId": html_data.get('nmId', nmid),
            "name": html_data.get('name', ''),
            "brand": html_data.get('brand', ''),
            "price": html_data.get('price'),
            "priceOld": html_data.get('priceOld'),
            "currency": "RUB",
            "weight": html_data.get('weight'),
            "dimensions": html_data.get('dimensions'),
            "description": html_data.get('description', ''),
            "discountPercent": None,
            "characteristics": html_data.get('characteristics', {}),
        }
        
        # Вычисляем скидку
        if result['price'] and result['priceOld']:
            discount = ((result['priceOld'] - result['price']) / result['priceOld']) * 100
            result["discountPercent"] = round(discount, 2)
        
        if include_raw:
            result["raw"] = {"source": "html_parsing", "data": html_data}
        
        logger.info(f"Данные успешно получены через парсинг HTML")
        return result
    
    # Если и парсинг не сработал
    if last_error:
        error_msg = str(last_error)
        if "PoW" in error_msg or "Proof of Work" in error_msg:
            raise NetworkError(
                f"❌ Проблема: API Wildberries защищен Proof of Work (PoW).\n"
                f"Все публичные эндпоинты требуют решения вычислительной задачи для доступа.\n"
                f"В официальной документации нет информации о том, как обойти PoW для публичных эндпоинтов.\n\n"
                f"✅ Решение: Используйте официальный API с токеном продавца (не требует PoW):\n"
                f"1. Получите токен: seller.wildberries.ru → Настройки → Интеграции по API\n"
                f"2. Установите переменную окружения: $env:WB_API_TOKEN='ваш_токен'\n"
                f"3. Запустите утилиту снова - она автоматически использует официальный API\n\n"
                f"Альтернатива: Проверьте товар вручную: https://www.wildberries.ru/catalog/{nmid}/detail.aspx"
            )
        elif "404" in error_msg or "не найден" in error_msg.lower():
            raise NotFoundError(
                f"Товар с nmId={nmid} не найден. "
                f"Проверьте артикул на сайте: https://www.wildberries.ru/catalog/{nmid}/detail.aspx"
            )
        else:
            raise last_error
    else:
        raise NetworkError(
            f"Не удалось получить данные для nmId={nmid}. "
            f"Проверьте товар на сайте: https://www.wildberries.ru/catalog/{nmid}/detail.aspx"
        )


def get_link(input_value: str) -> Dict[str, Any]:
    """
    Генерирует ссылку на JSON карточки WB.
    
    Args:
        input_value: URL или nmId
        
    Returns:
        dict: Содержит nmId и jsonUrl
    """
    nmid = extract_nmid(input_value)
    json_url = generate_json_url(nmid)
    
    return {
        "nmId": nmid,
        "jsonUrl": json_url
    }


def get_data(input_value: str, include_raw: bool = False) -> Dict[str, Any]:
    """
    Получает нормализованные данные карточки товара.
    
    Args:
        input_value: URL или nmId
        include_raw: Включать ли полный raw JSON ответ
        
    Returns:
        dict: Нормализованные данные карточки
    """
    nmid = extract_nmid(input_value)
    return fetch_card_data(nmid, include_raw=include_raw)

