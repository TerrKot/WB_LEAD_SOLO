# Implementation Guide для Telegram-бота экспресс-оценки и расчёта белой логистики vs карго (WB)

Этот файл — практический чеклист для Cursor AI. Следуй ему при любой задаче: от парсинга WB до добавления новых расчётов.

---

## 1. Перед началом работы

1. Прочитай `.cursor/rules`, `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`, `ROADMAP.md`
2. Убедись, что `.env` содержит все переменные (см. `ARCHITECTURE.md` → «Конфигурация»), включая `BOT_TOKEN`, `GPT_API_KEY`, `REDIS_URL`
3. Проверь, что Redis запущен и доступен
4. Сверь текущую задачу с `ROADMAP.md`. **Внимание:** Порядок реализации: сначала Блок 1 (фундамент), затем Блок 2 (пользовательское соглашение)!

---

## 2. Пользовательское соглашение и старт

### 2.1 Обработка пользовательского соглашения

В `apps/bot_service/handlers/start.py`:

```python
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Показывает пользовательское соглашение и запрашивает подтверждение."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принимаю",
                callback_data="agreement_accepted"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data="agreement_rejected"
            )
        ]
    ])
    
    text = """Пользовательское соглашение

[Текст соглашения]

Согласие на обработку персональных данных

[Текст согласия]"""
    
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "agreement_accepted")
async def handle_agreement_accepted(callback: CallbackQuery):
    """После подтверждения сразу запускает экспресс-расчёт."""
    await callback.answer("Соглашение принято")
    await callback.message.answer("Введите артикул WB или ссылку на карточку товара:")
    # Устанавливаем состояние ожидания ввода артикула
```

---

## 3. Парсинг данных WB

### 3.1 Input Parser

В `apps/bot_service/services/input_parser.py`:

```python
import re
from urllib.parse import urlparse, parse_qs
from typing import Optional, List

def extract_article_from_url(url: str) -> Optional[int]:
    """Извлекает артикул из ссылки WB."""
    # https://www.wildberries.ru/catalog/154345562/detail.aspx
    match = re.search(r'/catalog/(\d+)/', url)
    if match:
        return int(match.group(1))
    return None

def extract_article_from_text(text: str) -> Optional[int]:
    """Извлекает артикул из текста (только цифры)."""
    # Удаляем все нецифровые символы
    digits = re.sub(r'\D', '', text)
    if digits and len(digits) >= 6:  # Минимальная длина артикула WB
        return int(digits)
    return None

def parse_input(input_text: str) -> Optional[int]:
    """Парсит входные данные и возвращает артикул."""
    if input_text.startswith("http"):
        return extract_article_from_url(input_text)
    else:
        return extract_article_from_text(input_text)
```

### 3.2 WB Parser Service

В `apps/bot_service/services/wb_parser.py` (использует логику из `scripts/wb_parser.py`):

```python
import requests
from typing import Dict, Any, Optional, List
from scripts.wb_parser import fetch_v4_data, normalize_product

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.wildberries.ru/",
    "Origin": "https://www.wildberries.ru"
}

async def fetch_wb_product(article_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает данные о товаре с Wildberries API v4.
    
    Args:
        article_id: Артикул товара (nmId)
    
    Returns:
        Нормализованные данные товара или None при ошибке
    """
    data = fetch_v4_data([article_id])
    
    if not data or 'products' not in data:
        return None
    
    products = data['products']
    if not products:
        return None
    
    # Нормализуем первый товар
    product = products[0]
    normalized = normalize_product(product)
    
    return normalized
```

---

## 4. Проверка обязательных полей

### 4.1 Required Fields Validator

В `apps/bot_service/services/fields_validator.py`:

```python
from typing import Dict, Any, List, Optional
from apps.bot_service.services.gpt_service import GPTService

REQUIRED_FIELDS = ['price', 'name', 'weight', 'volume']

def validate_required_fields(product: Dict[str, Any]) -> tuple[bool, List[str], Optional[Dict[str, Any]]]:
    """
    Проверяет обязательные поля товара.
    
    Returns:
        (is_valid, missing_fields, product_with_filled_fields)
    """
    missing_fields = []
    
    # Проверяем наличие обязательных полей
    for field in REQUIRED_FIELDS:
        if field not in product or product[field] is None or product[field] == "":
            missing_fields.append(field)
    
    # Если отсутствуют вес или объём, запрашиваем через GPT
    if 'weight' in missing_fields or 'volume' in missing_fields:
        gpt_service = GPTService()
        product_name = product.get('name', 'Товар')
        
        # Запрос к GPT для получения веса и объёма
        gpt_response = await gpt_service.get_weight_volume(product_name)
        
        if gpt_response:
            if 'weight' in missing_fields:
                product['weight'] = gpt_response.get('weight')
            if 'volume' in missing_fields:
                product['volume'] = gpt_response.get('volume')
            
            # Удаляем из списка отсутствующих полей
            missing_fields = [f for f in missing_fields if f not in ['weight', 'volume']]
    
    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields, product
```

### 4.2 GPT Service для веса/объёма

В `apps/bot_service/services/gpt_service.py`:

```python
import aiohttp
import json
from typing import Dict, Any, Optional

class GPTService:
    def __init__(self, api_key: str, api_url: str, model: str):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
    
    async def get_weight_volume(self, product_name: str) -> Optional[Dict[str, Any]]:
        """
        Запрашивает примерные характеристики веса и объёма упаковки для товара.
        
        Returns:
            {"weight": float, "volume": float} или None при ошибке
        """
        prompt = f"""Дай примерные характеристики веса и объёма упаковки для товара: {product_name}

Ответь строго в формате JSON:
{{
    "weight": число в кг,
    "volume": число в литрах
}}"""
        
        response = await self._call_gpt_api(prompt)
        
        if response:
            try:
                # Парсим JSON из ответа
                content = response["choices"][0]["message"]["content"]
                # Убираем markdown код блоки, если есть
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                data = json.loads(content)
                return data
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse GPT response: {e}")
                return None
        
        return None
    
    async def _call_gpt_api(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Вызывает GPT API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Ты помощник для определения характеристик товаров."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 200
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"GPT API error: {resp.status}")
                        return None
                    return await resp.json()
            except Exception as e:
                logger.error(f"GPT API request failed: {e}")
                return None
```

---

## 5. Подбор ТН ВЭД + пошлины и НДС

### 5.1 GPT Service для ТН ВЭД

В `apps/bot_service/services/gpt_service.py` (добавить метод):

```python
async def get_tnved_code(self, product_name: str) -> Optional[Dict[str, Any]]:
    """
    Подбирает код ТН ВЭД для товара, используя только данные с сайта ifcg.ru.
    
    Returns:
        {
            "tnved_code": "10-значный код",
            "duty_type": "по весу" | "по единице" | "по паре",
            "duty_rate": число,
            "vat_rate": число (процент НДС)
        } или None при ошибке
    """
    prompt = f"""Подбери код ТН ВЭД для товара "{product_name}", используя только данные с сайта ifcg.ru, и укажи пошлины (тип и ставку) и НДС для данного кода ТН ВЭД.

Ответь строго в формате JSON:
{{
    "tnved_code": "10-значный код ТН ВЭД",
    "duty_type": "по весу" или "по единице" или "по паре",
    "duty_rate": число (ставка пошлины),
    "vat_rate": число (процент НДС, обычно 20)
}}"""
    
    response = await self._call_gpt_api(prompt)
    
    if response:
        try:
            content = response["choices"][0]["message"]["content"]
            # Убираем markdown код блоки, если есть
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            return data
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse GPT response: {e}")
            return None
    
    return None
```

---

## 6. Проверка красной зоны ТН ВЭД

### 6.1 TN VED Red Zone Checker

В `apps/bot_service/services/tnved_checker.py`:

```python
import json
from typing import Dict, Any, Optional, Literal
from pathlib import Path

Decision = Literal["BLOCK", "RISK", "ALLOW"]

class TNVEDRedZoneChecker:
    def __init__(self, rules_file: str = "rules/TN VED RED ZONE RULES.json"):
        """Загружает правила из JSON файла."""
        with open(rules_file, 'r', encoding='utf-8') as f:
            self.rules_data = json.load(f)
        self.rules = self.rules_data.get('rules', [])
    
    def normalize_code(self, code: str) -> str:
        """Нормализует код ТН ВЭД до строки из 10 цифр."""
        # Оставляем только цифры
        digits = ''.join(filter(str.isdigit, code))
        # Обрезаем до 10 символов
        return digits[:10].zfill(10)
    
    def check_code(self, tnved_code: str) -> tuple[Decision, Optional[str]]:
        """
        Проверяет код ТН ВЭД по правилам красной зоны.
        
        Returns:
            (decision, reason) - решение и причина
        """
        normalized_code = self.normalize_code(tnved_code)
        
        # Проверяем правила сверху вниз
        for rule in self.rules:
            decision = rule.get('decision')
            conditions = rule.get('conditions', [])
            
            if self._matches_conditions(normalized_code, conditions):
                reason = rule.get('reason', '')
                return decision, reason
        
        # Если совпадений нет — ALLOW
        return "ALLOW", None
    
    def _matches_conditions(self, code: str, conditions: list) -> bool:
        """Проверяет, соответствует ли код условиям правила."""
        for condition in conditions:
            condition_type = condition.get('type')
            length = condition.get('length')
            value = condition.get('value')
            
            if condition_type == 'prefix':
                # Сравнение первых N цифр
                prefix = code[:length]
                if prefix == value:
                    return True
            
            elif condition_type == 'range':
                # Сравнение диапазона по первым N цифрам
                prefix = code[:length]
                if isinstance(value, list) and len(value) == 2:
                    start, end = value
                    if start <= prefix <= end:
                        return True
            
            elif condition_type == 'exact':
                # Точное совпадение 10-значного кода
                if code == value:
                    return True
        
        return False
```

---

## 7. Расчёт карго

### 7.1 Cargo Calculator

В `apps/bot_service/services/cargo_calculator.py` (использует правила из `rules/Cargo.md`):

```python
from typing import Dict, Any
from decimal import Decimal, ROUND_HALF_UP

class CargoCalculator:
    def __init__(self, exchange_rates: Dict[str, float]):
        """
        Args:
            exchange_rates: {"usd_rub": 100.0, "usd_cny": 7.2}
        """
        self.usd_rub = exchange_rates.get('usd_rub', 100.0)
        self.usd_cny = exchange_rates.get('usd_cny', 7.2)
    
    def calculate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рассчитывает стоимость карго по правилам из Cargo.md.
        
        Args:
            input_data: {
                "weight_kg": float,
                "volume_m3": float,
                "quantity_units": int (опционально),
                "goods_value": {"amount": float, "currency": "USD"|"CNY"|"RUB"},
                "exchange_rates": {"usd_rub": float, "usd_cny": float}
            }
        
        Returns:
            Результат расчёта в формате из Cargo.md
        """
        # 1. Нормализация валют
        goods_value_usd = self._normalize_currency(
            input_data['goods_value']['amount'],
            input_data['goods_value']['currency']
        )
        
        goods_value_cny = goods_value_usd * self.usd_cny
        goods_value_rub = goods_value_usd * self.usd_rub
        
        # 2. Расчёт плотности
        weight_kg = input_data['weight_kg']
        volume_m3 = input_data['volume_m3']
        density_kg_m3 = weight_kg / volume_m3 if volume_m3 > 0 else 0
        
        # 3. Определение тарифного типа и ставки карго
        if density_kg_m3 < 100:
            tariff_type = "per_m3"
            tariff_value_usd = 500
            freight_usd = volume_m3 * 500
        else:
            tariff_type = "per_kg"
            tariff_value_usd = self._get_tariff_by_density(density_kg_m3)
            freight_usd = weight_kg * tariff_value_usd
        
        # 4. Страховка по удельной ценности
        specific_value_usd_per_kg = goods_value_usd / weight_kg if weight_kg > 0 else 0
        insurance_rate = self._get_insurance_rate(specific_value_usd_per_kg)
        insurance_usd = goods_value_usd * insurance_rate
        
        # 5. Комиссия байера (в CNY)
        buyer_commission_rate = self._get_buyer_commission_rate(goods_value_cny)
        buyer_commission_cny = goods_value_cny * buyer_commission_rate
        buyer_commission_usd = buyer_commission_cny / self.usd_cny
        
        # 6. Итог по карго
        total_cargo_usd = freight_usd + insurance_usd + buyer_commission_usd
        total_cargo_rub = total_cargo_usd * self.usd_rub
        
        # Расчёт на единицу
        quantity_units = input_data.get('quantity_units')
        cost_per_unit_usd = total_cargo_usd / quantity_units if quantity_units else None
        cost_per_unit_rub = total_cargo_rub / quantity_units if quantity_units else None
        
        cost_per_kg_usd = total_cargo_usd / weight_kg
        cost_per_kg_rub = total_cargo_rub / weight_kg
        
        return {
            "ok": True,
            "errors": [],
            "input_normalized": {
                **input_data,
                "goods_value_usd": round(goods_value_usd, 2),
                "goods_value_cny": round(goods_value_cny, 2),
                "goods_value_rub": round(goods_value_rub, 2),
                "exchange_rates": input_data.get('exchange_rates', {})
            },
            "cargo_params": {
                "density_kg_m3": round(density_kg_m3, 2),
                "tariff_type": tariff_type,
                "tariff_value_usd": round(tariff_value_usd, 2),
                "specific_value_usd_per_kg": round(specific_value_usd_per_kg, 2),
                "insurance_rate": insurance_rate,
                "buyer_commission_rate": buyer_commission_rate
            },
            "cargo_cost_usd": {
                "freight_usd": round(freight_usd, 2),
                "insurance_usd": round(insurance_usd, 2),
                "buyer_commission_usd": round(buyer_commission_usd, 2),
                "total_cargo_usd": round(total_cargo_usd, 2),
                "cost_per_kg_usd": round(cost_per_kg_usd, 2),
                "cost_per_unit_usd": round(cost_per_unit_usd, 2) if cost_per_unit_usd else None
            },
            "cargo_cost_rub": {
                "freight_rub": round(freight_usd * self.usd_rub, 2),
                "insurance_rub": round(insurance_usd * self.usd_rub, 2),
                "buyer_commission_rub": round(buyer_commission_usd * self.usd_rub, 2),
                "total_cargo_rub": round(total_cargo_rub, 2),
                "cost_per_kg_rub": round(cost_per_kg_rub, 2),
                "cost_per_unit_rub": round(cost_per_unit_rub, 2) if cost_per_unit_rub else None
            },
            "summary_for_manager": {
                "short_text": f"Итоговая стоимость карго: {round(total_cargo_rub, 2)} ₽",
                "details": f"Плотность: {round(density_kg_m3, 2)} кг/м³, тариф: {tariff_type}, страховка: {insurance_rate*100}%, комиссия байера: {buyer_commission_rate*100}%"
            }
        }
    
    def _normalize_currency(self, amount: float, currency: str) -> float:
        """Нормализует валюту в USD."""
        if currency == "USD":
            return amount
        elif currency == "CNY":
            return amount / self.usd_cny
        elif currency == "RUB":
            return amount / self.usd_rub
        else:
            raise ValueError(f"Unknown currency: {currency}")
    
    def _get_tariff_by_density(self, density: float) -> float:
        """Возвращает тариф по плотности (USD/кг)."""
        if 100 <= density <= 110:
            return 4.9
        elif 110 < density <= 120:
            return 4.8
        elif 120 < density <= 130:
            return 4.7
        elif 130 < density <= 140:
            return 4.6
        elif 140 < density <= 150:
            return 4.5
        elif 150 < density <= 160:
            return 4.4
        elif 160 < density <= 170:
            return 4.3
        elif 170 < density <= 180:
            return 4.2
        elif 180 < density <= 190:
            return 4.1
        elif 190 < density <= 200:
            return 4.0
        elif 200 < density <= 250:
            return 3.9
        elif 250 < density <= 300:
            return 3.8
        elif 300 < density <= 350:
            return 3.7
        elif 350 < density <= 400:
            return 3.6
        elif 400 < density <= 500:
            return 3.5
        elif 500 < density <= 600:
            return 3.4
        elif 600 < density <= 800:
            return 3.3
        elif 800 < density <= 1000:
            return 3.2
        else:  # > 1000
            return 3.1
    
    def _get_insurance_rate(self, specific_value: float) -> float:
        """Возвращает ставку страховки по удельной ценности."""
        if specific_value <= 30:
            return 0.01  # 1%
        elif specific_value <= 50:
            return 0.02  # 2%
        elif specific_value <= 100:
            return 0.03  # 3%
        elif specific_value <= 200:
            return 0.05  # 5%
        else:  # > 200
            return 0.10  # 10%
    
    def _get_buyer_commission_rate(self, goods_value_cny: float) -> float:
        """Возвращает ставку комиссии байера по стоимости товара в CNY."""
        if goods_value_cny <= 1000:
            return 0.05  # 5%
        elif goods_value_cny <= 5000:
            return 0.04  # 4%
        elif goods_value_cny <= 10000:
            return 0.03  # 3%
        elif goods_value_cny <= 50000:
            return 0.02  # 2%
        else:  # > 50000
            return 0.01  # 1%
```

---

## 8. Расчёт белой логистики

### 8.1 White Logistics Calculator

В `apps/bot_service/services/white_logistics_calculator.py`:

```python
from typing import Dict, Any

class WhiteLogisticsCalculator:
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: {
                "base_price_usd": 1850,
                "docs_rub": 15000,
                "broker_rub": 25000,
                "exchange_rates": {"usd_rub": 100.0, "usd_cny": 7.2, "eur_rub": 110.0}
            }
        """
        self.base_price_usd = config.get('base_price_usd', 1850)
        self.docs_rub = config.get('docs_rub', 15000)
        self.broker_rub = config.get('broker_rub', 25000)
        self.usd_rub = config['exchange_rates'].get('usd_rub', 100.0)
        self.usd_cny = config['exchange_rates'].get('usd_cny', 7.2)
        self.eur_rub = config['exchange_rates'].get('eur_rub', 110.0)
    
    def calculate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рассчитывает стоимость белой логистики.
        
        Args:
            input_data: {
                "weight_kg": float,
                "volume_m3": float,
                "quantity_units": int,
                "goods_value_cny": float,
                "tnved_data": {
                    "duty_type": "по весу" | "по единице" | "по паре",
                    "duty_rate": float,
                    "vat_rate": float
                }
            }
        
        Returns:
            Результат расчёта белой логистики
        """
        # Базовая логистика
        logistics_usd = self.base_price_usd
        
        # Товар (в CNY)
        goods_value_cny = input_data['goods_value_cny']
        goods_value_usd = goods_value_cny / self.usd_cny
        
        # Документы и брокер (в RUB)
        docs_broker_rub = self.docs_rub + self.broker_rub
        
        # Пошлина
        duty_rub = self._calculate_duty(input_data)
        
        # НДС
        vat_rub = self._calculate_vat(goods_value_usd, duty_rub, input_data['tnved_data'])
        
        # Итог
        total_rub = (
            logistics_usd * self.usd_rub +
            goods_value_cny / self.usd_cny * self.usd_rub +
            docs_broker_rub +
            duty_rub +
            vat_rub
        )
        
        quantity_units = input_data.get('quantity_units', 1)
        cost_per_unit_rub = total_rub / quantity_units if quantity_units > 0 else total_rub
        
        return {
            "logistics_usd": round(logistics_usd, 2),
            "logistics_rub": round(logistics_usd * self.usd_rub, 2),
            "goods_value_cny": round(goods_value_cny, 2),
            "goods_value_rub": round(goods_value_cny / self.usd_cny * self.usd_rub, 2),
            "docs_rub": round(self.docs_rub, 2),
            "broker_rub": round(self.broker_rub, 2),
            "duty_rub": round(duty_rub, 2),
            "vat_rub": round(vat_rub, 2),
            "total_rub": round(total_rub, 2),
            "cost_per_unit_rub": round(cost_per_unit_rub, 2)
        }
    
    def _calculate_duty(self, input_data: Dict[str, Any]) -> float:
        """Рассчитывает пошлину."""
        tnved_data = input_data['tnved_data']
        duty_type = tnved_data['duty_type']
        duty_rate = tnved_data['duty_rate']
        
        if duty_type == "по весу":
            weight_kg = input_data['weight_kg']
            return weight_kg * duty_rate * self.eur_rub  # Предполагаем, что ставка в EUR
        elif duty_type in ["по единице", "по паре"]:
            quantity_units = input_data.get('quantity_units', 1)
            return quantity_units * duty_rate * self.eur_rub
        else:
            return 0.0
    
    def _calculate_vat(self, goods_value_usd: float, duty_rub: float, tnved_data: Dict[str, Any]) -> float:
        """Рассчитывает НДС."""
        vat_rate = tnved_data.get('vat_rate', 20) / 100  # Переводим проценты в долю
        goods_value_rub = goods_value_usd * self.usd_rub
        base_for_vat = goods_value_rub + 900 * self.usd_rub + duty_rub  # 900 USD = фиксированная стоимость логистики для НДС
        return base_for_vat * vat_rate
```

---

## 9. Очереди и воркеры

### 9.1 Redis очереди

В `apps/bot_service/clients/redis.py`:

```python
import redis.asyncio as redis
import json
from typing import Optional, Dict, Any

class RedisClient:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)
    
    async def push_calculation(self, calculation_id: str, data: Dict[str, Any]):
        """Добавляет задачу расчёта в очередь."""
        await self.redis.lpush("calculation_queue", json.dumps({
            "calculation_id": calculation_id,
            "data": data
        }))
    
    async def set_calculation_status(self, calculation_id: str, status: str):
        """Устанавливает статус расчёта."""
        await self.redis.set(f"calculation:{calculation_id}:status", status)
    
    async def set_calculation_result(self, calculation_id: str, result: Dict[str, Any], ttl: int = 86400):
        """Сохраняет результат расчёта."""
        await self.redis.setex(
            f"calculation:{calculation_id}:result",
            ttl,
            json.dumps(result)
        )
    
    async def get_calculation_result(self, calculation_id: str) -> Optional[Dict[str, Any]]:
        """Получает результат расчёта."""
        result_json = await self.redis.get(f"calculation:{calculation_id}:result")
        if result_json:
            return json.loads(result_json)
        return None
```

---

## 10. Тестирование

### 10.1 Unit тесты

Проект включает 179 unit тестов, покрывающих все основные компоненты:

- `tests/unit/test_wb_parser.py` — парсинг WB API (17 тестов)
- `tests/unit/test_cargo_calculator.py` — расчёт карго (15 тестов)
- `tests/unit/test_white_logistics_calculator.py` — расчёт белой логистики (8 тестов)
- `tests/unit/test_tn_ved_red_zone_checker.py` — проверка красной зоны ТН ВЭД (11 тестов)
- `tests/unit/test_gpt_service.py` — GPT сервис (10 тестов)
- `tests/unit/test_fields_validator.py` — валидация полей (8 тестов)
- `tests/unit/test_input_parser.py` — парсинг входных данных (6 тестов)
- `tests/unit/test_specific_value_calculator.py` — расчёт удельной ценности (5 тестов)
- `tests/unit/test_express_assessment_generator.py` — генерация экспресс-оценки (5 тестов)
- `tests/unit/test_detailed_calculation_service.py` — подробный расчёт (6 тестов)
- `tests/unit/test_detailed_calculation.py` — обработчики подробного расчёта (12 тестов)
- `tests/unit/test_start_handler.py` — обработчики старта (8 тестов)
- И другие...

Все тесты проходят успешно (100% success rate).

### 10.2 Integration тесты

- `tests/integration/test_redis_integration.py` — интеграция с Redis
- `tests/integration/test_database_integration.py` — интеграция с PostgreSQL
- `tests/integration/test_tn_ved_real_gpt.py` — тесты с реальным GPT API
- `tests/integration/test_express_calculation_e2e.py` — **end-to-end тест экспресс-расчёта** (полный цикл от ввода артикула до результата)
- `tests/integration/test_detailed_calculation_e2e.py` — **end-to-end тест подробного расчёта** (полный цикл от параметров до результата)

End-to-end тесты проверяют:
- Полный цикл экспресс-расчёта: ввод артикула → парсинг WB → подбор ТН ВЭД → проверка красной зоны → экспресс-оценка
- Полный цикл подробного расчёта: выбор параметров → расчёт карго и белой логистики → вывод результата
- Обработку красной зоны (🔴 блокировка)
- Интеграцию с очередями Redis и статусами расчётов

---

## 11. Troubleshooting

| Симптом | Шаги |
|---------|------|
| Не парсится артикул из ссылки | Проверь регулярное выражение в `input_parser.py`, логи парсинга |
| GPT не возвращает JSON | Проверь промпт, логи ответа GPT, обработку ошибок |
| Красная зона не определяется | Проверь нормализацию кода ТН ВЭД, загрузку правил из JSON |
| Расчёт карго неправильный | Проверь формулы из `Cargo.md`, логи промежуточных расчётов |
| Очередь не обрабатывается | Проверь подключение к Redis, логи воркера |

---

## 12. Workflow напоминание

1. Чтение правил (`.cursor/rules`, `ARCHITECTURE.md`, `ROADMAP.md`)
2. План (какие компоненты затрагиваем)
3. Реализация (код + тесты)
4. Обновление документации
5. Тестирование
6. Ответ пользователю: конкретные изменения, команды, статусы
