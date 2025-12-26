"""GPT Service for weight/volume estimation and TN VED code selection."""
import asyncio
import json
import re
import aiohttp
from typing import Optional, Dict, Any, List
import structlog
from bs4 import BeautifulSoup

from apps.bot_service.config import config
from apps.bot_service.utils.error_handler import ErrorHandler

logger = structlog.get_logger()


class GPTService:
    """Service for GPT API integration."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        model_for_code: Optional[str] = None,
    ):
        """
        Initialize GPT Service.

        Args:
            api_key: OpenAI API key (defaults to config.GPT_API_KEY)
            api_url: GPT API URL (defaults to config.GPT_API_URL)
            model: GPT model name (defaults to config.GPT_MODEL)
            model_for_code: GPT model name for code selection (defaults to config.GPT_MODEL_FOR_CODE)
        """
        self.api_key = api_key or config.GPT_API_KEY
        self.api_url = api_url or config.GPT_API_URL
        self.model = model or config.GPT_MODEL
        self.model_for_code = model_for_code or config.GPT_MODEL_FOR_CODE

        if not self.api_key:
            raise ValueError("GPT_API_KEY is required")

    def _truncate_name_to_first_words(self, name: str, num_words: int = 3) -> str:
        """
        Truncate product name to first N words for GPT matching.
        
        Args:
            name: Full product name
            num_words: Number of words to keep (default: 3)
            
        Returns:
            Truncated name with first N words
        """
        if not name:
            return name
        
        words = name.split()
        if len(words) <= num_words:
            return name
        
        return " ".join(words[:num_words])

    async def get_weight_volume(
        self, product_name: str, product_description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Request approximate weight and volume characteristics for a product.

        Args:
            product_name: Product name
            product_description: Optional product description

        Returns:
            {"weight": float, "volume": float} in kg and liters, or None on error
        """
        # Build context for GPT
        context = f"Товар: {product_name}"
        if product_description:
            context += f"\nОписание: {product_description}"

        prompt = f"""Дай примерные характеристики веса и объёма упаковки для товара.

{context}

Ответь строго в формате JSON (без markdown блоков, только чистый JSON):
{{
    "weight": число в кг (float),
    "volume": число в литрах (float)
}}

Важно:
- weight должен быть в килограммах (например, 1.5 для 1.5 кг)
- volume должен быть в литрах (например, 2.0 для 2 литров)
- Если не можешь определить точно, дай разумную оценку на основе названия товара"""

        try:
            response = await self._call_gpt_api(prompt)
            if not response:
                logger.error("gpt_weight_volume_no_response", product_name=product_name)
                return None

            # Parse JSON from response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error("gpt_weight_volume_empty_content", product_name=product_name)
                return None

            # Remove markdown code blocks if present
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(content)

            # Validate structure
            if "weight" not in data or "volume" not in data:
                logger.error(
                    "gpt_weight_volume_invalid_structure",
                    product_name=product_name,
                    data=data
                )
                return None

            weight = float(data["weight"])
            volume = float(data["volume"])

            # Validate values are positive
            if weight <= 0 or volume <= 0:
                logger.error(
                    "gpt_weight_volume_invalid_values",
                    product_name=product_name,
                    weight=weight,
                    volume=volume
                )
                return None

            logger.info(
                "gpt_weight_volume_success",
                product_name=product_name,
                weight=weight,
                volume=volume
            )

            return {"weight": weight, "volume": volume}

        except json.JSONDecodeError as e:
            logger.error(
                "gpt_weight_volume_json_error",
                product_name=product_name,
                error=str(e),
                content=content[:200] if "content" in locals() else None
            )
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.error(
                "gpt_weight_volume_parse_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return None
        except Exception as e:
            logger.error(
                "gpt_weight_volume_unexpected_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return None

    async def check_forbidden_categories(
        self, product_name: str, product_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Проверяет, относится ли товар к запрещенным категориям:
        смартфоны, ноутбуки, ювелирные изделия, бижутерия.
        
        Args:
            product_name: Название товара
            product_description: Опциональное описание товара
            
        Returns:
            {
                "is_forbidden": bool,
                "category": Optional[str] - название категории, если is_forbidden=True,
                "reason": Optional[str] - причина, если is_forbidden=True
            }
        """
        # Строим контекст для GPT
        context = f"Название товара: {product_name}"
        if product_description:
            context += f"\nОписание: {product_description}"
        
        prompt = f"""Определи, относится ли данный товар к следующим запрещенным категориям:
- смартфоны
- ноутбуки
- ювелирные изделия
- бижутерия

{context}

Ответь строго в формате JSON (без markdown блоков, только чистый JSON):
{{
    "is_forbidden": true или false (boolean),
    "category": "название категории из списка выше, если is_forbidden=true, иначе null",
    "reason": "краткое объяснение, почему товар относится к этой категории, если is_forbidden=true, иначе null"
}}

Важно:
- Если товар точно относится к одной из перечисленных категорий, верни is_forbidden=true
- Если товар не относится ни к одной категории, верни is_forbidden=false
- Будь строгим: только явное попадание в категорию должно возвращать is_forbidden=true"""
        
        try:
            response = await self._call_gpt_api(prompt)
            if not response:
                logger.error("gpt_forbidden_categories_no_response", product_name=product_name)
                # При ошибке API считаем, что товар не запрещен (продолжаем обработку)
                return {"is_forbidden": False}
            
            # Парсим JSON из ответа
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error("gpt_forbidden_categories_empty_content", product_name=product_name)
                return {"is_forbidden": False}
            
            # Удаляем markdown code blocks, если есть
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            # Парсим JSON
            data = json.loads(content)
            
            # Валидируем структуру
            is_forbidden = data.get("is_forbidden", False)
            
            # Если товар запрещен, проверяем наличие категории и причины
            if is_forbidden:
                category = data.get("category")
                reason = data.get("reason", "Товар относится к запрещенной категории")
                
                # Валидируем категорию
                allowed_categories = ["смартфоны", "ноутбуки", "ювелирные изделия", "бижутерия"]
                if category not in allowed_categories:
                    logger.warning(
                        "gpt_forbidden_categories_invalid_category",
                        product_name=product_name,
                        category=category
                    )
                    # Если категория невалидна, но is_forbidden=true, используем общую причину
                    category = "запрещенная категория"
                
                logger.info(
                    "gpt_forbidden_categories_detected",
                    product_name=product_name,
                    category=category,
                    reason=reason
                )
                
                return {
                    "is_forbidden": True,
                    "category": category,
                    "reason": reason
                }
            else:
                logger.info(
                    "gpt_forbidden_categories_not_detected",
                    product_name=product_name
                )
                return {"is_forbidden": False}
                
        except json.JSONDecodeError as e:
            logger.error(
                "gpt_forbidden_categories_json_error",
                product_name=product_name,
                error=str(e),
                content=content[:200] if "content" in locals() else None
            )
            # При ошибке парсинга считаем, что товар не запрещен
            return {"is_forbidden": False}
        except (KeyError, ValueError, TypeError) as e:
            logger.error(
                "gpt_forbidden_categories_parse_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return {"is_forbidden": False}
        except Exception as e:
            logger.error(
                "gpt_forbidden_categories_unexpected_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return {"is_forbidden": False}

    async def format_forbidden_category_message(
        self,
        product_name: str,
        category: str,
        product_weight_kg: Optional[float] = None,
        product_volume_liters: Optional[float] = None
    ) -> Optional[str]:
        """
        Генерирует детальное сообщение о красной зоне для запрещенной категории.
        
        Args:
            product_name: Название товара
            category: Категория товара (смартфоны, ноутбуки, ювелирные изделия, бижутерия)
            product_weight_kg: Вес товара в кг (опционально)
            product_volume_liters: Объём товара в литрах (опционально)
            
        Returns:
            Отформатированное сообщение или None при ошибке
        """
        # Детальные причины для каждой категории
        category_reasons = {
            "смартфоны": """Смартфоны и мобильные телефоны

• Попадают в зону регулирования по средствам связи и криптографии (IMEI, шифрование, радиомодули, ПО).
• Сильная зависимость от санкций и экспортного контроля по брендам и моделям.
• Повышенный контроль по серийникам / IMEI / параллельному импорту, высокий риск вопросов от таможни и правообладателей.

В рамках экспресс-теста относим к красной зоне: нормальная белая схема по смартфонам — это отдельный сложный проект, а не "просто карточка товара".""",
            
            "ноутбуки": """Ноутбуки (и близкие по логике: планшеты, системные блоки, «умные» ПК-устройства)

• Содержат криптографию, ПО и сложную электронику, могут попадать под экспортный контроль и спец-регулирование.
• Высокий риск санкций и ограничений по брендам/конфигурациям, отдельные модели формально относятся к товарам двойного назначения.
• Часто требуют отдельной экспертизы, сертификации, точной проработки кода ТН ВЭД и назначения.

В экспресс-оценке отправляем в красную зону: ноутбуки — это не массовый "белый товар по умолчанию", а отдельное направление с подготовкой.""",
            
            "ювелирные изделия": """Ювелирные изделия (из драгоценных металлов и камней)

• Попадают в зону регулирования по драгметаллам и драгкамням: пробирный надзор, учёт, повышенный контроль происхождения и стоимости.
• Идут по отдельным режимам таможенного и валютного контроля, часто с участием банков/финмониторинга.
• Высокий риск требований по документам и проверок (оценка, подлинность, происхождение, декларирование).

В экспресс-логике сразу относим ювелирку к красной зоне: без отдельного проекта и юр-подготовки белая схема здесь не рассматривается.""",
            
            "бижутерия": """Бижутерия (массовые украшения)

• Часто идёт по спорным составам и покрытиям, которые требуют подтверждения безопасности при контакте с кожей (ТР ТС по легпрому/игрушкам/изделиям для детей и т.п.).
• Высокий риск нарушения прав на товарные знаки и дизайн (копии брендов, логотипы, "похожий стиль" → претензии правообладателей и блокировки на маркетплейсах).
• Как категория — мелкий, лёгкий, но "ювелирно-проблемный" товар: низкий вес, большая номенклатура, частые вопросы по документам.

В рамках экспресс-теста относим бижутерию в красную зону: массово "обелять" её без глубокой подготовки мы не рассматриваем."""
        }
        
        # Получаем детальную причину для категории
        detailed_reason = category_reasons.get(category, f"Товар относится к категории: {category}")
        
        # Строим контекст для GPT
        context_parts = [f"Товар: {product_name}", f"Категория: {category}"]
        if product_weight_kg is not None:
            context_parts.append(f"Вес единицы товара: {product_weight_kg:.2f} кг")
        if product_volume_liters is not None:
            context_parts.append(f"Объём единицы товара: {product_volume_liters:.2f} л")
        
        context = "\n".join(context_parts)
        
        prompt = f"""Создай клиент-ориентированное сообщение о том, что товар попадает в красную зону из-за принадлежности к запрещенной категории.

{context}

КРИТИЧЕСКИ ВАЖНО: Товар относится к категории "{category}". Используй ТОЛЬКО информацию из блока "Детальная причина" ниже. НЕ упоминай бытовую химию, дезинфицирующие средства или сертификацию, если это не указано в детальной причине.

Детальная причина для категории "{category}":
{detailed_reason}

Создай сообщение в формате HTML (можно использовать <b>, <i>, <code>), которое:
1. Начинается с "🔴 <b>Белая доставка — только после подготовки / смены продукта, с текущей категорией товара белая схема не рекомендована.</b>"
2. Содержит название товара
3. ОБЯЗАТЕЛЬНО используй информацию из блока "Детальная причина" выше, адаптированную под клиентский язык (без технических терминов, понятно для бизнеса). НЕ придумывай причины, которых нет в детальной причине!
4. Заканчивается фразой о том, что товар не может быть доставлен белой логистикой
5. Будь кратким, но информативным (не более 10-12 строк)
6. Используй маркированные списки (•) для структурирования информации

Ответь только текстом сообщения в формате HTML, без дополнительных комментариев."""
        
        try:
            # Use direct API call for text generation (not JSON)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": f"Ты помощник для формирования клиенто-ориентированных сообщений. Отвечай только текстом сообщения без дополнительных комментариев, markdown блоков или пояснений. КРИТИЧЕСКИ ВАЖНО: Используй ТОЛЬКО информацию из блока 'Детальная причина' в запросе пользователя. НЕ упоминай бытовую химию, дезинфицирующие средства или сертификацию, если это не указано в детальной причине. Категория товара: {category}."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,  # Higher temperature for more natural text
            }
            
            # For GPT-5.x models use max_completion_tokens, for others use max_tokens
            if "gpt-5" in self.model:
                payload["max_completion_tokens"] = 800
            else:
                payload["max_tokens"] = 800

            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        error_type = "api_error" if resp.status >= 400 else "unknown"
                        logger.error(
                            "gpt_forbidden_category_message_api_error",
                            event_type="gpt_api_error",
                            error_type=error_type,
                            status=resp.status,
                            error=error_text[:200],
                            product_name=product_name,
                            category=category
                        )
                        return None

                    response_data = await resp.json()
                    content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    if not content:
                        logger.error(
                            "gpt_forbidden_category_message_empty_content",
                            product_name=product_name,
                            category=category
                        )
                        return None

                    # Remove markdown code blocks if present
                    content = content.strip()
                    if "```" in content:
                        # Try to extract text from markdown blocks
                        parts = content.split("```")
                        # Take the longest non-empty part (likely the actual message)
                        content = max([p.strip() for p in parts if p.strip() and not p.strip().startswith("html")], key=len, default=content)

                    logger.info(
                        "gpt_forbidden_category_message_success",
                        product_name=product_name,
                        category=category
                    )

                    return content

        except aiohttp.ClientError as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_forbidden_category_message_client_error",
                event_type="gpt_api_error",
                error_type=error_type,
                error=str(e)[:200],
                product_name=product_name,
                category=category
            )
            return None
        except asyncio.TimeoutError:
            logger.error(
                "gpt_forbidden_category_message_timeout",
                event_type="gpt_api_timeout",
                product_name=product_name,
                category=category
            )
            return None
        except Exception as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_forbidden_category_message_unexpected_error",
                event_type="gpt_api_unexpected_error",
                error_type=error_type,
                error=str(e)[:200],
                error_class=type(e).__name__,
                product_name=product_name,
                category=category
            )
            return None

    async def _parse_ifcg_duty(self, code: str) -> Dict[str, Any]:
        """
        Parse duty and VAT information directly from ifcg.ru website.
        
        Args:
            code: 10-digit TN VED code
            
        Returns:
            {
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float,
                "duty_minimum": Optional[Dict[str, Any]] - для приписок типа "не менее X EUR/кг"
            }
        """
        url = f"https://www.ifcg.ru/kb/tnved/{code}/"
        
        logger.info("parsing_ifcg_duty", code=code, url=url)
        
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.error("ifcg_request_failed", status=resp.status, code=code)
                        return {"duty_type": "ad_valorem", "duty_rate": 0.0, "vat_rate": 20.0}
                    
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Проверяем, что код существует на странице (ищем признаки валидной страницы)
                    # Если страница содержит "не найден" или "не существует", код невалиден
                    page_text = soup.get_text().lower()
                    if any(phrase in page_text for phrase in ["не найден", "не существует", "not found", "404", "ошибка"]):
                        logger.warning("ifcg_code_not_found", code=code, url=url)
                        return {"duty_type": "ad_valorem", "duty_rate": 0.0, "vat_rate": 20.0}
                    
                    duty_type = "ad_valorem"
                    duty_rate = 0.0
                    vat_rate = 20.0
                    duty_minimum = None  # Для приписок типа "не менее X EUR/кг"
                    
                    # Ищем строку "Импортная пошлина:"
                    duty_row = soup.find('td', string=re.compile(r'Импортная пошлина', re.I))
                    if duty_row:
                        tr = duty_row.find_parent('tr')
                        if tr:
                            tds = tr.find_all('td')
                            if len(tds) >= 2:
                                duty_value = tds[1].get_text(strip=True)
                                logger.info("duty_value_found", duty_value=duty_value)
                                
                                # Проверяем все ячейки строки на наличие приписки о минимальной пошлине
                                # Приписка может быть в третьей ячейке или в тексте второй ячейки
                                full_row_text = " ".join([td.get_text(strip=True) for td in tds])
                                
                                # Парсим приписку "не менее X EUR/кг" (минималка)
                                minimum_match = re.search(
                                    r'(?:но\s+)?не\s+менее\s+([\d,\.]+)\s*(?:Евро|EUR|€)\s*/?\s*(?:кг|kg)',
                                    full_row_text,
                                    re.I
                                )
                                if minimum_match:
                                    minimum_value = float(minimum_match.group(1).replace(",", "."))
                                    duty_minimum = {
                                        "value": minimum_value,
                                        "unit": "EUR/кг"
                                    }
                                    logger.info("duty_minimum_found", minimum=minimum_value)

                                # Парсим процент (адвалор)
                                percent_match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', full_row_text, re.I)
                                percent_value = float(percent_match.group(1).replace(",", ".")) if percent_match else None

                                # Парсим специфическую ставку в евро (как минимум или самостоятельную)
                                euro_match = re.search(r'([\d,\.]+)', duty_value.replace(",", ".")) if ("Евро" in duty_value or "EUR" in duty_value or "€" in duty_value) and ("/" in duty_value) else None
                                euro_value = float(euro_match.group(1)) if euro_match else None

                                # Решение: если есть процент — это адвалорная ставка, минимум добавляется отдельно
                                if percent_value is not None:
                                    duty_type = "ad_valorem"
                                    duty_rate = percent_value
                                    logger.info("ad_valorem_duty_found", rate=duty_rate, has_minimum=bool(duty_minimum), has_euro_min=bool(euro_value))
                                elif euro_value is not None:
                                    duty_rate = euro_value
                                    if re.search(r'/кг|/kg', duty_value, re.I):
                                        duty_type = "по весу"  # EUR/кг
                                    elif re.search(r'/пар|/pair', duty_value, re.I):
                                        duty_type = "по паре"  # EUR/пар
                                    elif re.search(r'/шт|/unit|/pc|/piece', duty_value, re.I):
                                        duty_type = "по единице"  # EUR/шт
                                    else:
                                        duty_type = "по единице"
                                elif "Отсутствует" in duty_value or "отсутствует" in duty_value or duty_value == "":
                                    duty_type = "exempt"
                                    duty_rate = 0.0
                    else:
                        # Если строка "Импортная пошлина" не найдена, код может не существовать
                        logger.warning("ifcg_duty_row_not_found", code=code, url=url)
                        # Возвращаем 0.0, чтобы вызвать fallback на альтернативные коды
                        return {"duty_type": "ad_valorem", "duty_rate": 0.0, "vat_rate": 20.0}
                    
                    # Ищем НДС
                    vat_row = soup.find('td', string=re.compile(r'Ввозной НДС|НДС', re.I))
                    if vat_row:
                        tr = vat_row.find_parent('tr')
                        if tr:
                            tds = tr.find_all('td')
                            if len(tds) >= 2:
                                vat_value = tds[1].get_text(strip=True)
                                logger.info("vat_value_found", vat_value=vat_value)
                                match = re.search(r'([\d,\.]+)', vat_value.replace(",", "."))
                                if match:
                                    vat_rate = float(match.group(1))
                    
                    result = {
                        "duty_type": duty_type,
                        "duty_rate": duty_rate,
                        "vat_rate": vat_rate
                    }
                    
                    # Добавляем информацию о минимальной пошлине, если она есть
                    if duty_minimum:
                        result["duty_minimum"] = duty_minimum
                        logger.info(
                            "duty_minimum_added_to_result",
                            code=code,
                            duty_minimum=duty_minimum,
                            result_keys=list(result.keys())
                        )
                    else:
                        logger.info(
                            "duty_minimum_not_found",
                            code=code,
                            full_row_text=full_row_text[:200] if 'full_row_text' in locals() else "N/A"
                        )
                    
                    logger.info("duty_info_parsed", result=result)
                    return result
                    
        except Exception as e:
            logger.error("ifcg_parsing_error", error=str(e), code=code)
            return {"duty_type": "ad_valorem", "duty_rate": 0.0, "vat_rate": 20.0}

    async def _parse_ifcg_category_description(self, code: str) -> Optional[str]:
        """
        Parse category description from ifcg.ru page.
        
        Args:
            code: 10-digit TN VED code
            
        Returns:
            Category description text or None if not found
        """
        url = f"https://www.ifcg.ru/kb/tnved/{code}/"
        
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Check if code exists
                    page_text = soup.get_text().lower()
                    if any(phrase in page_text for phrase in ["не найден", "не существует", "not found", "404", "ошибка"]):
                        return None
                    
                    # Try to find category description/name
                    # Usually in h1, h2, or specific divs
                    category_name = None
                    
                    # Try h1
                    h1 = soup.find('h1')
                    if h1:
                        category_name = h1.get_text(strip=True)
                    
                    # Try to find description in common places
                    description = None
                    desc_div = soup.find('div', class_=re.compile(r'description|content|text', re.I))
                    if desc_div:
                        description = desc_div.get_text(strip=True)
                    
                    # Combine category name and description
                    result_parts = []
                    if category_name:
                        result_parts.append(category_name)
                    if description and description != category_name:
                        result_parts.append(description)
                    
                    result = " ".join(result_parts) if result_parts else None
                    
                    if result:
                        logger.debug("ifcg_category_description_parsed", code=code, description_length=len(result))
                    
                    return result
                    
        except Exception as e:
            logger.warning("ifcg_category_description_parsing_error", code=code, error=str(e))
            return None

    async def _validate_candidate_code(
        self,
        code: str,
        product_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate a candidate TN VED code by checking:
        1. Code exists on ifcg.ru
        2. Category description matches product
        3. Duty information is valid
        
        Args:
            code: Candidate TN VED code
            product_data: Product data for comparison
            
        Returns:
            {
                "code": str,
                "exists": bool,
                "category_description": str or None,
                "duty_info": dict,
                "match_score": float (0.0-1.0),
                "is_valid": bool
            }
        """
        result = {
            "code": code,
            "exists": False,
            "category_description": None,
            "duty_info": None,
            "match_score": 0.0,
            "is_valid": False
        }
        
        # Check if code exists and get description
        category_description = await self._parse_ifcg_category_description(code)
        if category_description:
            result["exists"] = True
            result["category_description"] = category_description
        else:
            logger.debug("candidate_code_not_found_on_ifcg", code=code)
            return result
        
        # Get duty info
        duty_info = await self._parse_ifcg_duty(code)
        result["duty_info"] = duty_info
        
        # Code is valid if it exists on ifcg.ru and duty info was parsed successfully
        # 0% duty rate is valid - it means the code exists and has zero duty
        if duty_info and "duty_rate" in duty_info:
            result["is_valid"] = True
        
        # Calculate match score using GPT
        if category_description:
            match_score = await self._calculate_category_match_score(
                category_description,
                product_data
            )
            result["match_score"] = match_score
        
        return result

    async def _calculate_category_match_score(
        self,
        category_description: str,
        product_data: Dict[str, Any]
    ) -> float:
        """
        Calculate how well category description matches product data using GPT.
        
        Args:
            category_description: Category description from ifcg.ru
            product_data: Product data (can be basic data dict or full product)
            
        Returns:
            Match score from 0.0 to 1.0
        """
        # Extract key product info
        product_name = product_data.get("imt_name") or product_data.get("name") or "Товар"
        product_category = product_data.get("subj_name") or product_data.get("subj_root_name") or ""
        
        # Truncate product name to first 3 words for GPT matching
        truncated_name = self._truncate_name_to_first_words(product_name, 3)
        
        prompt = f"""Оцени, насколько описание категории ТН ВЭД соответствует товару.

Описание категории ТН ВЭД: {category_description}

Товар:
- Название: {truncated_name}
- Категория: {product_category}

Оцени соответствие от 0.0 до 1.0, где:
- 1.0 = идеальное соответствие
- 0.8-0.9 = очень хорошее соответствие
- 0.6-0.7 = хорошее соответствие
- 0.4-0.5 = частичное соответствие
- 0.0-0.3 = несоответствие

Верни только число (float) от 0.0 до 1.0, без дополнительного текста."""
        
        try:
            response = await self._call_gpt_api(prompt)
            if not response:
                return 0.5  # Default neutral score
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                return 0.5
            
            # Extract number from response
            content = content.strip()
            # Remove markdown if present
            if "```" in content:
                content = content.split("```")[-1].split("```")[0].strip()
            
            # Try to extract float
            match = re.search(r'([\d.]+)', content.replace(",", "."))
            if match:
                score = float(match.group(1))
                # Clamp to 0.0-1.0
                score = max(0.0, min(1.0, score))
                return score
            
            return 0.5
            
        except Exception as e:
            logger.warning("category_match_score_calculation_error", error=str(e))
            return 0.5

    async def _select_best_candidate(
        self,
        candidates: List[Dict[str, Any]],
        product_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Select best candidate from validated candidates.
        
        Selection criteria (in order):
        1. Code must exist on ifcg.ru
        2. Code must have valid duty info (duty_rate > 0 or exempt)
        3. Higher match_score is better
        4. Prefer codes with non-zero duty_rate over exempt (more specific)
        
        Args:
            candidates: List of validated candidate dicts from _validate_candidate_code
            product_data: Product data for context
            
        Returns:
            Best candidate dict with full info or None
        """
        if not candidates:
            return None
        
        # Filter valid candidates
        valid_candidates = [
            c for c in candidates
            if c.get("exists") and c.get("is_valid")
        ]
        
        if not valid_candidates:
            logger.warning("no_valid_candidates_found", total_candidates=len(candidates))
            return None
        
        # Sort by match_score (descending), then by duty_rate (descending, but exempt is special)
        def sort_key(c):
            match_score = c.get("match_score", 0.0)
            duty_info = c.get("duty_info", {})
            duty_rate = duty_info.get("duty_rate", 0.0)
            duty_type = duty_info.get("duty_type", "")
            
            # Exempt codes get slight penalty (prefer specific codes)
            exempt_penalty = -0.1 if duty_type == "exempt" else 0.0
            
            return (match_score + exempt_penalty, duty_rate)
        
        valid_candidates.sort(key=sort_key, reverse=True)
        
        best = valid_candidates[0]
        
        logger.info(
            "best_candidate_selected",
            code=best["code"],
            match_score=best["match_score"],
            duty_type=best["duty_info"].get("duty_type"),
            duty_rate=best["duty_info"].get("duty_rate"),
            total_candidates=len(candidates),
            valid_candidates=len(valid_candidates)
        )
        
        result = {
            "tn_ved_code": best["code"],
            "duty_type": best["duty_info"]["duty_type"],
            "duty_rate": best["duty_info"]["duty_rate"],
            "vat_rate": best["duty_info"]["vat_rate"],
            "match_score": best["match_score"],
            "category_description": best["category_description"]
        }
        
        # Добавляем duty_minimum, если он есть
        if "duty_minimum" in best["duty_info"]:
            result["duty_minimum"] = best["duty_info"]["duty_minimum"]
            logger.info(
                "duty_minimum_included_in_result",
                code=best["code"],
                duty_minimum=best["duty_info"]["duty_minimum"]
            )
        
        return result

    async def get_tn_ved_code(
        self,
        product_data: Dict[str, Any],
        card_data: Optional[Dict[str, Any]] = None,
        category_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Request TN VED code, duty type, duty rate and VAT rate for a product.
        Uses three-stage approach: 
        1. First attempt with basic fields (subj_name, subj_root_name, imt_name, type_name, category_name)
        2. If confidence is low, add description
        3. If still low, use full card data
        4. Direct parsing from ifcg.ru for duties.

        Args:
            product_data: Full product JSON data from WB API (all fields)
            card_data: Optional product card data from basket API
            category_data: Optional category data from webapi/product/data

        Returns:
            {
                "tn_ved_code": str (10 digits),
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float (percentage)
            } or None on error
        """
        # Import here to avoid circular dependency
        from apps.bot_service.services.wb_parser import WBParserService
        
        wb_parser = WBParserService()
        
        # Extract product name for logging
        product_name = product_data.get('name', 'Товар') or 'Товар'
        
        # If card_data is available, use new three-stage approach
        if card_data:
            return await self._get_tn_ved_code_with_card_data(
                card_data, category_data, product_name, wb_parser
            )
        
        # Fallback to old approach if card_data not available
        product_description = product_data.get('description', '') or ''
        
        # Truncate product name to first 3 words for GPT matching
        truncated_name = self._truncate_name_to_first_words(product_name, 3)
        
        # ЭТАП 1: Первая попытка - используем только название и описание
        prompt_stage1 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

Название товара: {truncated_name}
Описание товара: {product_description if product_description else 'Описание отсутствует'}

Верни код ТН ВЭД и уровень уверенности в формате JSON:
{{
    "tn_ved_code": "код из 10 цифр",
    "confidence": число от 0.0 до 1.0 (уверенность в правильности подбора кода)
}}"""

        try:
            # Первая попытка с минимальными данными
            response = await self._call_gpt_api(prompt_stage1, model=self.model_for_code)
            if not response:
                logger.warning("gpt_tn_ved_stage1_no_response", product_name=product_name, falling_back_to_full_data=True)
                # Переходим к полным данным
                return await self._get_tn_ved_code_with_full_data(product_data)

            # Parse JSON from response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.warning("gpt_tn_ved_stage1_empty_content", product_name=product_name, falling_back_to_full_data=True)
                return await self._get_tn_ved_code_with_full_data(product_data)

            # Remove markdown code blocks if present
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(content)
            
            # Extract and normalize code
            tn_ved_code = data.get("tn_ved_code", "").strip()
            confidence_raw = data.get("confidence", 0.0)
            
            # Преобразуем confidence в float, если это возможно
            try:
                confidence = float(confidence_raw) if confidence_raw is not None else 0.0
            except (ValueError, TypeError):
                confidence = 0.0
            
            # Если уверенность низкая (< 0.7) или код не найден, используем полные данные
            if not tn_ved_code or confidence < 0.7:
                logger.info(
                    "gpt_tn_ved_stage1_low_confidence",
                    product_name=product_name,
                    confidence=confidence,
                    falling_back_to_full_data=True
                )
                return await self._get_tn_ved_code_with_full_data(product_data)
            
            tn_ved_code = tn_ved_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            
            if not tn_ved_code.isdigit() or len(tn_ved_code) != 10:
                logger.warning(
                    "gpt_tn_ved_stage1_invalid_code",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code,
                    falling_back_to_full_data=True
                )
                return await self._get_tn_ved_code_with_full_data(product_data)
            
            # Validate section (first 2 digits: 01-97)
            section = int(tn_ved_code[:2])
            if section < 1 or section > 97:
                logger.warning(
                    "gpt_tn_ved_stage1_invalid_section",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code,
                    section=section,
                    falling_back_to_full_data=True
                )
                return await self._get_tn_ved_code_with_full_data(product_data)
            
            # Код найден с достаточной уверенностью, проверяем пошлины
            logger.info(
                "gpt_tn_ved_stage1_success",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                confidence=confidence
            )
            
            # ЭТАП 2: Парсим пошлины и НДС напрямую с ifcg.ru
            logger.info("getting_duty_info", code=tn_ved_code)
            duty_info = await self._parse_ifcg_duty(tn_ved_code)
            logger.info("duty_info_received", duty_info=duty_info)
            
            # 0% duty rate is valid - code exists on ifcg.ru and has zero duty
            # No need to try full data if duty was successfully parsed
            
            logger.info(
                "gpt_tn_ved_success",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                duty_type=duty_info["duty_type"],
                duty_rate=duty_info["duty_rate"],
                vat_rate=duty_info["vat_rate"],
                stage="minimal_data"
            )
            
            result = {
                "tn_ved_code": tn_ved_code,
                "duty_type": duty_info["duty_type"],
                "duty_rate": duty_info["duty_rate"],
                "vat_rate": duty_info["vat_rate"]
            }
            
            # Добавляем duty_minimum, если он есть
            if "duty_minimum" in duty_info:
                result["duty_minimum"] = duty_info["duty_minimum"]
                logger.info(
                    "duty_minimum_included_in_stage1_result",
                    code=tn_ved_code,
                    duty_minimum=duty_info["duty_minimum"]
                )
            
            return result

        except json.JSONDecodeError as e:
            logger.warning(
                "gpt_tn_ved_stage1_json_error",
                product_name=product_name,
                error=str(e),
                falling_back_to_full_data=True
            )
            return await self._get_tn_ved_code_with_full_data(product_data)
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(
                "gpt_tn_ved_stage1_parse_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__,
                falling_back_to_full_data=True
            )
            return await self._get_tn_ved_code_with_full_data(product_data)
        except Exception as e:
            logger.warning(
                "gpt_tn_ved_stage1_unexpected_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__,
                falling_back_to_full_data=True
            )
            return await self._get_tn_ved_code_with_full_data(product_data)

    async def _get_tn_ved_code_with_card_data(
        self,
        card_data: Dict[str, Any],
        category_data: Optional[Dict[str, Any]],
        product_name: str,
        wb_parser: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Request TN VED code using card data with three-stage approach.
        
        Args:
            card_data: Product card data from basket API
            category_data: Optional category data from webapi/product/data
            product_name: Product name for logging
            wb_parser: WBParserService instance
            
        Returns:
            {
                "tn_ved_code": str (10 digits),
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float (percentage)
            } or None on error
        """
        # ЭТАП 1: Базовые поля (subj_name, subj_root_name, imt_name, type_name, category_name)
        basic_data = wb_parser.get_tn_ved_basic_data(card_data, category_data)
        
        basic_info_parts = []
        if basic_data.get("subj_name"):
            basic_info_parts.append(f"Тип товара: {basic_data['subj_name']}")
        if basic_data.get("subj_root_name"):
            basic_info_parts.append(f"Категория: {basic_data['subj_root_name']}")
        if basic_data.get("type_name"):
            basic_info_parts.append(f"Тип: {basic_data['type_name']}")
        if basic_data.get("category_name"):
            basic_info_parts.append(f"Категория: {basic_data['category_name']}")
        if basic_data.get("imt_name"):
            # Truncate product name to first 3 words for GPT matching
            truncated_imt_name = self._truncate_name_to_first_words(basic_data['imt_name'], 3)
            basic_info_parts.append(f"Название товара: {truncated_imt_name}")
        
        basic_info = "\n".join(basic_info_parts) if basic_info_parts else "Данные отсутствуют"
        
        prompt_stage1 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

{basic_info}

Верни основной код ТН ВЭД и несколько альтернативных кандидатов (5-7 кодов) в формате JSON:
{{
    "tn_ved_code": "основной код из 10 цифр",
    "candidates": [
        {{"code": "альтернативный код 1", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 2", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 3", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 4", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 5", "name": "краткое описание категории"}}
    ]
}}"""
        
        try:
            response = await self._call_gpt_api(prompt_stage1, model=self.model_for_code)
            if not response:
                logger.warning("gpt_tn_ved_card_stage1_no_response", product_name=product_name, falling_back_to_stage2=True)
                return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)
            
            # Log full response for debugging GPT-5
            logger.debug("gpt_tn_ved_card_stage1_response", response_keys=list(response.keys()) if response else None, choices_count=len(response.get("choices", [])) if response else 0)
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.warning(
                    "gpt_tn_ved_card_stage1_empty_content",
                    product_name=product_name,
                    falling_back_to_stage2=True,
                    response_structure=str(response)[:500] if response else None
                )
                return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)
            
            # Remove markdown code blocks
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            # Extract all candidate codes
            candidates_list = []
            
            # Add main code
            main_code = data.get("tn_ved_code", "").strip()
            main_code = main_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            if main_code and main_code.isdigit() and len(main_code) == 10:
                section = int(main_code[:2])
                if 1 <= section <= 97:
                    candidates_list.append(main_code)
            
            # Add candidate codes
            candidates = data.get("candidates", [])
            for candidate in candidates:
                if isinstance(candidate, dict):
                    code = candidate.get("code", "").strip()
                    code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
                    if code and code.isdigit() and len(code) == 10:
                        section = int(code[:2])
                        if 1 <= section <= 97 and code not in candidates_list:
                            candidates_list.append(code)
            
            if not candidates_list:
                logger.warning("gpt_tn_ved_card_stage1_no_valid_codes", product_name=product_name, falling_back_to_stage2=True)
                return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)
            
            logger.info(
                "gpt_tn_ved_card_stage1_candidates_received",
                product_name=product_name,
                candidates_count=len(candidates_list)
            )
            
            # Validate all candidates
            product_data_for_validation = {
                "imt_name": basic_data.get("imt_name", product_name),
                "subj_name": basic_data.get("subj_name", ""),
                "subj_root_name": basic_data.get("subj_root_name", "")
            }
            
            validated_candidates = []
            for code in candidates_list:
                validated = await self._validate_candidate_code(code, product_data_for_validation)
                validated_candidates.append(validated)
            
            # Select best candidate
            best = await self._select_best_candidate(validated_candidates, product_data_for_validation)
            
            if best:
                logger.info(
                    "gpt_tn_ved_card_stage1_success",
                    product_name=product_name,
                    tn_ved_code=best["tn_ved_code"],
                    match_score=best.get("match_score", 0.0)
                )
                result = {
                    "tn_ved_code": best["tn_ved_code"],
                    "duty_type": best["duty_type"],
                    "duty_rate": best["duty_rate"],
                    "vat_rate": best["vat_rate"]
                }
                # Добавляем duty_minimum, если он есть
                if "duty_minimum" in best:
                    result["duty_minimum"] = best["duty_minimum"]
                    logger.info(
                        "duty_minimum_included_in_card_stage1_result",
                        code=best["tn_ved_code"],
                        duty_minimum=best["duty_minimum"]
                    )
                return result
            else:
                logger.warning("gpt_tn_ved_card_stage1_no_valid_candidate", product_name=product_name, falling_back_to_stage2=True)
                return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)
            
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("gpt_tn_ved_card_stage1_error", product_name=product_name, error=str(e), falling_back_to_stage2=True)
            return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)
        except Exception as e:
            logger.warning("gpt_tn_ved_card_stage1_unexpected_error", product_name=product_name, error=str(e), falling_back_to_stage2=True)
            return await self._get_tn_ved_code_card_stage2(card_data, category_data, product_name, wb_parser)

    async def _get_tn_ved_code_card_stage2(
        self,
        card_data: Dict[str, Any],
        category_data: Optional[Dict[str, Any]],
        product_name: str,
        wb_parser: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Stage 2: Add description to basic data.
        """
        data_with_desc = wb_parser.get_tn_ved_with_description(card_data, category_data)
        
        basic_info_parts = []
        if data_with_desc.get("subj_name"):
            basic_info_parts.append(f"Тип товара: {data_with_desc['subj_name']}")
        if data_with_desc.get("subj_root_name"):
            basic_info_parts.append(f"Категория: {data_with_desc['subj_root_name']}")
        if data_with_desc.get("type_name"):
            basic_info_parts.append(f"Тип: {data_with_desc['type_name']}")
        if data_with_desc.get("category_name"):
            basic_info_parts.append(f"Категория: {data_with_desc['category_name']}")
        if data_with_desc.get("imt_name"):
            # Truncate product name to first 3 words for GPT matching
            truncated_imt_name = self._truncate_name_to_first_words(data_with_desc['imt_name'], 3)
            basic_info_parts.append(f"Название товара: {truncated_imt_name}")
        
        basic_info = "\n".join(basic_info_parts) if basic_info_parts else ""
        description = data_with_desc.get("description", "")
        
        prompt_stage2 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

{basic_info}

Описание товара:
{description if description else 'Описание отсутствует'}

Верни основной код ТН ВЭД и несколько альтернативных кандидатов (5-7 кодов) в формате JSON:
{{
    "tn_ved_code": "основной код из 10 цифр",
    "candidates": [
        {{"code": "альтернативный код 1", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 2", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 3", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 4", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 5", "name": "краткое описание категории"}}
    ]
}}"""
        
        try:
            response = await self._call_gpt_api(prompt_stage2, model=self.model_for_code)
            if not response:
                logger.warning("gpt_tn_ved_card_stage2_no_response", product_name=product_name, falling_back_to_stage3=True)
                return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.warning(
                    "gpt_tn_ved_card_stage2_empty_content",
                    product_name=product_name,
                    falling_back_to_stage3=True,
                    response_structure=str(response)[:500] if response else None
                )
                return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)
            
            # Remove markdown code blocks
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            # Extract all candidate codes
            candidates_list = []
            
            # Add main code
            main_code = data.get("tn_ved_code", "").strip()
            main_code = main_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            if main_code and main_code.isdigit() and len(main_code) == 10:
                section = int(main_code[:2])
                if 1 <= section <= 97:
                    candidates_list.append(main_code)
            
            # Add candidate codes
            candidates = data.get("candidates", [])
            for candidate in candidates:
                if isinstance(candidate, dict):
                    code = candidate.get("code", "").strip()
                    code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
                    if code and code.isdigit() and len(code) == 10:
                        section = int(code[:2])
                        if 1 <= section <= 97 and code not in candidates_list:
                            candidates_list.append(code)
            
            if not candidates_list:
                logger.warning("gpt_tn_ved_card_stage2_no_valid_codes", product_name=product_name, falling_back_to_stage3=True)
                return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)
            
            logger.info(
                "gpt_tn_ved_card_stage2_candidates_received",
                product_name=product_name,
                candidates_count=len(candidates_list)
            )
            
            # Validate all candidates
            product_data_for_validation = {
                "imt_name": data_with_desc.get("imt_name", product_name),
                "subj_name": data_with_desc.get("subj_name", ""),
                "subj_root_name": data_with_desc.get("subj_root_name", ""),
                "description": description
            }
            
            validated_candidates = []
            for code in candidates_list:
                validated = await self._validate_candidate_code(code, product_data_for_validation)
                validated_candidates.append(validated)
            
            # Select best candidate
            best = await self._select_best_candidate(validated_candidates, product_data_for_validation)
            
            if best:
                logger.info(
                    "gpt_tn_ved_card_stage2_success",
                    product_name=product_name,
                    tn_ved_code=best["tn_ved_code"],
                    match_score=best.get("match_score", 0.0)
                )
                result = {
                    "tn_ved_code": best["tn_ved_code"],
                    "duty_type": best["duty_type"],
                    "duty_rate": best["duty_rate"],
                    "vat_rate": best["vat_rate"]
                }
                # Добавляем duty_minimum, если он есть
                if "duty_minimum" in best:
                    result["duty_minimum"] = best["duty_minimum"]
                    logger.info(
                        "duty_minimum_included_in_card_stage2_result",
                        code=best["tn_ved_code"],
                        duty_minimum=best["duty_minimum"]
                    )
                return result
            else:
                logger.warning("gpt_tn_ved_card_stage2_no_valid_candidate", product_name=product_name, falling_back_to_stage3=True)
                return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)
            
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("gpt_tn_ved_card_stage2_error", product_name=product_name, error=str(e), falling_back_to_stage3=True)
            return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)
        except Exception as e:
            logger.warning("gpt_tn_ved_card_stage2_unexpected_error", product_name=product_name, error=str(e), falling_back_to_stage3=True)
            return await self._get_tn_ved_code_card_stage3(card_data, product_name, wb_parser)

    async def _get_tn_ved_code_card_stage3(
        self,
        card_data: Dict[str, Any],
        product_name: str,
        wb_parser: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Stage 3: Use full card data.
        """
        full_data = wb_parser.get_tn_ved_full_data(card_data)
        
        # Truncate product name to first 3 words for GPT matching
        if full_data.get("imt_name"):
            full_data = full_data.copy()  # Create a copy to avoid modifying original
            full_data["imt_name"] = self._truncate_name_to_first_words(full_data["imt_name"], 3)
        
        # Convert to JSON string, limit size if needed
        try:
            card_json_str = json.dumps(full_data, ensure_ascii=False, indent=2)
            if len(card_json_str) > 50000:
                # Keep only essential fields
                essential_fields = ['imt_name', 'subj_name', 'subj_root_name', 'description', 'options']
                limited_data = {k: full_data.get(k) for k in essential_fields if k in full_data}
                card_json_str = json.dumps(limited_data, ensure_ascii=False, indent=2)
                logger.warning("card_json_truncated", product_name=product_name)
        except Exception as e:
            logger.error("card_json_serialization_error", product_name=product_name, error=str(e))
            return None
        
        prompt_stage3 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

Ниже представлены все данные о товаре из Wildberries в формате JSON. Используй всю доступную информацию для точного подбора кода ТН ВЭД:

{card_json_str}

Верни основной код ТН ВЭД и несколько альтернативных вариантов в формате JSON:
{{
    "tn_ved_code": "основной код из 10 цифр",
    "candidates": [
        {{"code": "альтернативный код 1", "name": "название категории"}},
        {{"code": "альтернативный код 2", "name": "название категории"}}
    ]
}}"""
        
        try:
            response = await self._call_gpt_api(prompt_stage3, model=self.model_for_code)
            if not response:
                logger.error("gpt_tn_ved_card_stage3_no_response", product_name=product_name)
                return None
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error(
                    "gpt_tn_ved_card_stage3_empty_content",
                    product_name=product_name,
                    response_structure=str(response)[:500] if response else None
                )
                return None
            
            # Remove markdown code blocks
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            # Extract all candidate codes
            candidates_list = []
            
            # Add main code
            main_code = data.get("tn_ved_code", "").strip()
            main_code = main_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            if main_code and main_code.isdigit() and len(main_code) == 10:
                section = int(main_code[:2])
                if 1 <= section <= 97:
                    candidates_list.append(main_code)
            
            # Add candidate codes
            candidates = data.get("candidates", [])
            for candidate in candidates:
                if isinstance(candidate, dict):
                    code = candidate.get("code", "").strip()
                    code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
                    if code and code.isdigit() and len(code) == 10:
                        section = int(code[:2])
                        if 1 <= section <= 97 and code not in candidates_list:
                            candidates_list.append(code)
            
            if not candidates_list:
                logger.error("gpt_tn_ved_card_stage3_no_valid_codes", product_name=product_name)
                return None
            
            logger.info(
                "gpt_tn_ved_card_stage3_candidates_received",
                product_name=product_name,
                candidates_count=len(candidates_list)
            )
            
            # Validate all candidates
            product_data_for_validation = {
                "imt_name": full_data.get("imt_name", product_name),
                "subj_name": full_data.get("subj_name", ""),
                "subj_root_name": full_data.get("subj_root_name", ""),
                "description": full_data.get("description", "")
            }
            
            validated_candidates = []
            for code in candidates_list:
                validated = await self._validate_candidate_code(code, product_data_for_validation)
                validated_candidates.append(validated)
            
            # Select best candidate
            best = await self._select_best_candidate(validated_candidates, product_data_for_validation)
            
            if best:
                logger.info(
                    "gpt_tn_ved_card_stage3_success",
                    product_name=product_name,
                    tn_ved_code=best["tn_ved_code"],
                    match_score=best.get("match_score", 0.0)
                )
                result = {
                    "tn_ved_code": best["tn_ved_code"],
                    "duty_type": best["duty_type"],
                    "duty_rate": best["duty_rate"],
                    "vat_rate": best["vat_rate"]
                }
                # Добавляем duty_minimum, если он есть
                if "duty_minimum" in best:
                    result["duty_minimum"] = best["duty_minimum"]
                    logger.info(
                        "duty_minimum_included_in_card_stage3_result",
                        code=best["tn_ved_code"],
                        duty_minimum=best["duty_minimum"]
                    )
                return result
            else:
                logger.warning("gpt_tn_ved_card_stage3_no_valid_candidate", product_name=product_name, falling_back_to_type_classification=True)
                # Fallback: classify product type and search by type
                return await self._get_tn_ved_code_by_product_type(
                    card_data, category_data, product_name, wb_parser
                )
            
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("gpt_tn_ved_card_stage3_error", product_name=product_name, error=str(e))
            return None
        except Exception as e:
            logger.error("gpt_tn_ved_card_stage3_unexpected_error", product_name=product_name, error=str(e))
            return None

    async def _get_tn_ved_code_by_product_type(
        self,
        card_data: Dict[str, Any],
        category_data: Optional[Dict[str, Any]],
        product_name: str,
        wb_parser: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Fallback: Classify product type using GPT, then search TN VED code by type.
        Used when all three stages failed to find valid candidates.
        
        Args:
            card_data: Product card data from basket API
            category_data: Optional category data from webapi/product/data
            product_name: Product name for logging
            wb_parser: WBParserService instance
            
        Returns:
            {
                "tn_ved_code": str (10 digits),
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float (percentage)
            } or None on error
        """
        logger.info(
            "gpt_tn_ved_type_classification_started",
            product_name=product_name
        )
        
        # Collect all available data for classification
        classification_data = {
            "product_name": card_data.get("imt_name", product_name),
            "subj_name": card_data.get("subj_name", ""),
            "subj_root_name": card_data.get("subj_root_name", ""),
            "description": card_data.get("description", "")[:500] if card_data.get("description") else "",  # Limit description length
            "options": card_data.get("options", [])[:10] if isinstance(card_data.get("options"), list) else [],  # Limit options
        }
        
        # Add category data if available
        if category_data:
            classification_data["type_name"] = category_data.get("type_name", "")
            classification_data["category_name"] = category_data.get("category_name", "")
        
        # Build prompt for product type classification
        prompt = f"""Определи точный тип товара для подбора кода ТН ВЭД.

Данные о товаре:
- Название: {classification_data['product_name']}
- Тип товара (WB): {classification_data.get('subj_name', 'не указан')}
- Категория (WB): {classification_data.get('subj_root_name', 'не указана')}
- Тип (WB): {classification_data.get('type_name', 'не указан')}
- Категория (WB): {classification_data.get('category_name', 'не указана')}
- Описание: {classification_data.get('description', 'отсутствует')}

Определи:
1. Точный тип товара (например: "детская одежда", "электроника", "мебель", "игрушки")
2. Основное назначение товара
3. Материал (если применимо)
4. Возрастная группа (если применимо)

Верни результат в формате JSON:
{{
    "product_type": "точный тип товара",
    "purpose": "основное назначение",
    "material": "материал или 'не применимо'",
    "age_group": "возрастная группа или 'не применимо'",
    "key_features": ["ключевая особенность 1", "ключевая особенность 2"]
}}"""
        
        try:
            # Get product type classification from GPT
            response = await self._call_gpt_api(prompt, model=self.model_for_code)
            if not response:
                logger.warning("gpt_type_classification_no_response", product_name=product_name)
                return None
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.warning("gpt_type_classification_empty_content", product_name=product_name)
                return None
            
            # Parse JSON response
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            type_data = json.loads(content)
            product_type = type_data.get("product_type", "")
            purpose = type_data.get("purpose", "")
            key_features = type_data.get("key_features", [])
            
            logger.info(
                "gpt_type_classification_received",
                product_name=product_name,
                product_type=product_type,
                purpose=purpose
            )
            
            # Now search TN VED code by classified type
            search_prompt = f"""Подбери код ТН ВЭД для товара на основе классификации типа.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

Тип товара: {product_type}
Назначение: {purpose}
Ключевые особенности: {', '.join(key_features[:3]) if key_features else 'не указаны'}
Название товара: {classification_data['product_name']}

Используй сайт ifcg.ru для поиска кода ТН ВЭД.
Верни 3-5 кандидатов кодов в формате JSON:
{{
    "candidates": [
        {{
            "tn_ved_code": "код из 10 цифр",
            "reason": "почему этот код подходит"
        }}
    ]
}}"""
            
            search_response = await self._call_gpt_api(search_prompt, model=self.model_for_code)
            if not search_response:
                logger.warning("gpt_tn_ved_search_by_type_no_response", product_name=product_name)
                return None
            
            search_content = search_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not search_content:
                logger.warning("gpt_tn_ved_search_by_type_empty_content", product_name=product_name)
                return None
            
            # Parse candidates
            search_content = search_content.strip()
            if "```json" in search_content:
                search_content = search_content.split("```json")[1].split("```")[0].strip()
            elif "```" in search_content:
                search_content = search_content.split("```")[1].split("```")[0].strip()
            
            candidates_data = json.loads(search_content)
            candidates_list = candidates_data.get("candidates", [])
            
            if not candidates_list:
                logger.warning("gpt_tn_ved_search_by_type_no_candidates", product_name=product_name)
                return None
            
            logger.info(
                "gpt_tn_ved_type_candidates_received",
                product_name=product_name,
                candidates_count=len(candidates_list)
            )
            
            # Extract codes and validate
            codes_to_validate = [c.get("tn_ved_code", "").strip() for c in candidates_list if c.get("tn_ved_code")]
            
            # Prepare product data for validation
            product_data_for_validation = {
                "imt_name": classification_data['product_name'],
                "subj_name": classification_data.get('subj_name', ''),
                "subj_root_name": classification_data.get('subj_root_name', ''),
                "description": classification_data.get('description', '')
            }
            
            # Validate candidates
            validated_candidates = []
            for code in codes_to_validate:
                validated = await self._validate_candidate_code(code, product_data_for_validation)
                validated_candidates.append(validated)
            
            # Select best candidate (with relaxed validation - accept lower match_score)
            best = await self._select_best_candidate_relaxed(validated_candidates, product_data_for_validation)
            
            if best:
                logger.info(
                    "gpt_tn_ved_type_classification_success",
                    product_name=product_name,
                    product_type=product_type,
                    tn_ved_code=best["tn_ved_code"],
                    match_score=best.get("match_score", 0.0)
                )
                result = {
                    "tn_ved_code": best["tn_ved_code"],
                    "duty_type": best["duty_type"],
                    "duty_rate": best["duty_rate"],
                    "vat_rate": best["vat_rate"],
                    "is_fallback": True  # Mark as fallback result
                }
                if "duty_minimum" in best:
                    result["duty_minimum"] = best["duty_minimum"]
                return result
            else:
                logger.warning("gpt_tn_ved_type_classification_no_valid_candidate", product_name=product_name)
                return None
                
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error("gpt_tn_ved_type_classification_error", product_name=product_name, error=str(e))
            return None
        except Exception as e:
            logger.error("gpt_tn_ved_type_classification_unexpected_error", product_name=product_name, error=str(e))
            return None

    async def _select_best_candidate_relaxed(
        self,
        candidates: List[Dict[str, Any]],
        product_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Select best candidate with relaxed validation (lower match_score threshold).
        Used for fallback scenarios.
        
        Args:
            candidates: List of validated candidate dicts
            product_data: Product data for context
            
        Returns:
            Best candidate dict or None
        """
        if not candidates:
            return None
        
        # Filter valid candidates (exists on ifcg.ru and has duty info)
        # Accept even with 0% duty rate
        valid_candidates = [
            c for c in candidates
            if c.get("exists") and c.get("is_valid")
        ]
        
        # If no valid candidates, try to use any that exists (even if not fully valid)
        if not valid_candidates:
            valid_candidates = [
                c for c in candidates
                if c.get("exists")
            ]
        
        if not valid_candidates:
            logger.warning("no_candidates_found_relaxed", total_candidates=len(candidates))
            return None
        
        # Sort by match_score (descending)
        valid_candidates.sort(key=lambda c: c.get("match_score", 0.0), reverse=True)
        
        best = valid_candidates[0]
        
        logger.info(
            "best_candidate_selected_relaxed",
            code=best["code"],
            match_score=best["match_score"],
            duty_type=best["duty_info"].get("duty_type") if best.get("duty_info") else None,
            duty_rate=best["duty_info"].get("duty_rate") if best.get("duty_info") else None,
            total_candidates=len(candidates),
            valid_candidates=len(valid_candidates)
        )
        
        # Get duty info
        duty_info = best.get("duty_info", {})
        if not duty_info:
            # Try to parse duty if not already parsed
            duty_info = await self._parse_ifcg_duty(best["code"])
        
        result = {
            "tn_ved_code": best["code"],
            "duty_type": duty_info.get("duty_type", "ad_valorem"),
            "duty_rate": duty_info.get("duty_rate", 0.0),
            "vat_rate": duty_info.get("vat_rate", 20.0),
            "match_score": best.get("match_score", 0.0),
            "category_description": best.get("category_description")
        }
        
        # Add duty_minimum if present
        if "duty_minimum" in duty_info:
            result["duty_minimum"] = duty_info["duty_minimum"]
        
        return result

    async def _get_tn_ved_code_with_full_data(
        self,
        product_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Request TN VED code using full product data (fallback when minimal data fails).
        
        Args:
            product_data: Full product JSON data from WB API (all fields)

        Returns:
            {
                "tn_ved_code": str (10 digits),
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float (percentage)
            } or None on error
        """
        product_name = product_data.get('name', 'Товар') or 'Товар'
        
        # Convert product data to JSON string for GPT context
        # Remove non-serializable fields and limit size if needed
        try:
            # Create a clean copy of product data for serialization
            clean_product_data = {}
            for key, value in product_data.items():
                # Truncate product name to first 3 words for GPT matching
                if key == 'name' and value:
                    value = self._truncate_name_to_first_words(value, 3)
                # Skip None values and non-serializable types
                if value is None:
                    continue
                # Skip very large payload fields that are not useful for TN VED selection
                if key == 'payload' and isinstance(value, str) and len(value) > 100:
                    continue
                # Try to serialize to check if it's JSON-compatible
                try:
                    json.dumps(value, ensure_ascii=False)
                    clean_product_data[key] = value
                except (TypeError, ValueError):
                    # Skip non-serializable values
                    continue
            
            product_json_str = json.dumps(clean_product_data, ensure_ascii=False, indent=2)
            
            # Limit JSON size to avoid token limits (approximately 50KB)
            if len(product_json_str) > 50000:
                # Keep only essential fields if JSON is too large
                essential_fields = ['name', 'description', 'brand', 'weight', 'volume', 'subjectId', 'subjectParentId', 'entity', 'colors', 'sizes']
                limited_data = {k: clean_product_data.get(k) for k in essential_fields if k in clean_product_data}
                product_json_str = json.dumps(limited_data, ensure_ascii=False, indent=2)
                logger.warning("product_json_truncated", product_name=product_name, original_size=len(str(clean_product_data)))
        except Exception as e:
            logger.error(
                "product_json_serialization_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            # Fallback to minimal data
            minimal_name = product_data.get('name', 'Товар')
            if minimal_name:
                minimal_name = self._truncate_name_to_first_words(minimal_name, 3)
            minimal_data = {
                'name': minimal_name,
                'description': product_data.get('description', ''),
                'brand': product_data.get('brand'),
                'weight': product_data.get('weight'),
                'volume': product_data.get('volume')
            }
            product_json_str = json.dumps(minimal_data, ensure_ascii=False, indent=2)

        # ЭТАП 1: GPT подбирает код ТН ВЭД с полными данными
        # Запрашиваем сразу несколько кандидатов (5-7) для повышения надёжности
        prompt = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

ВАЖНО: Отвечай кратко, только JSON без дополнительных рассуждений.

Ниже представлены все данные о товаре из Wildberries API в формате JSON. Используй всю доступную информацию для точного подбора кода ТН ВЭД:

{product_json_str}

Верни основной код ТН ВЭД и несколько альтернативных кандидатов (5-7 кодов) в формате JSON:
{{
    "tn_ved_code": "основной код из 10 цифр",
    "candidates": [
        {{"code": "альтернативный код 1", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 2", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 3", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 4", "name": "краткое описание категории"}},
        {{"code": "альтернативный код 5", "name": "краткое описание категории"}}
    ]
}}"""

        try:
            response = await self._call_gpt_api(prompt, model=self.model_for_code)
            if not response:
                logger.error("gpt_tn_ved_full_data_no_response", product_name=product_name)
                return None

            # Parse JSON from response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error("gpt_tn_ved_full_data_empty_content", product_name=product_name)
                return None

            # Remove markdown code blocks if present
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(content)
            
            # Extract all candidate codes
            candidates_list = []
            
            # Add main code
            main_code = data.get("tn_ved_code", "").strip()
            main_code = main_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            if main_code and main_code.isdigit() and len(main_code) == 10:
                section = int(main_code[:2])
                if 1 <= section <= 97:
                    candidates_list.append(main_code)
            
            # Add candidate codes
            candidates = data.get("candidates", [])
            for candidate in candidates:
                if isinstance(candidate, dict):
                    code = candidate.get("code", "").strip()
                    code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
                    if code and code.isdigit() and len(code) == 10:
                        section = int(code[:2])
                        if 1 <= section <= 97 and code not in candidates_list:
                            candidates_list.append(code)
            
            if not candidates_list:
                logger.error(
                    "gpt_tn_ved_full_data_no_valid_codes",
                    product_name=product_name,
                    data=data
                )
                return None
            
            logger.info(
                "gpt_tn_ved_full_data_candidates_received",
                product_name=product_name,
                candidates_count=len(candidates_list)
            )
            
            # Validate all candidates using multi-candidate validation
            product_data_for_validation = {
                "name": product_data.get("name", product_name),
                "description": product_data.get("description", ""),
                "brand": product_data.get("brand", ""),
                "imt_name": product_data.get("name", product_name),
                "subj_name": product_data.get("subjectName", ""),
                "subj_root_name": product_data.get("subjectParentName", "")
            }
            
            validated_candidates = []
            for code in candidates_list:
                validated = await self._validate_candidate_code(code, product_data_for_validation)
                validated_candidates.append(validated)
            
            # Select best candidate
            best = await self._select_best_candidate(validated_candidates, product_data_for_validation)
            
            if best:
                logger.info(
                    "gpt_tn_ved_full_data_success",
                    product_name=product_name,
                    tn_ved_code=best["tn_ved_code"],
                    match_score=best.get("match_score", 0.0)
                )
                result = {
                    "tn_ved_code": best["tn_ved_code"],
                    "duty_type": best["duty_type"],
                    "duty_rate": best["duty_rate"],
                    "vat_rate": best["vat_rate"]
                }
                # Добавляем duty_minimum, если он есть
                if "duty_minimum" in best:
                    result["duty_minimum"] = best["duty_minimum"]
                    logger.info(
                        "duty_minimum_included_in_full_data_result",
                        code=best["tn_ved_code"],
                        duty_minimum=best["duty_minimum"]
                    )
                return result
            else:
                logger.error(
                    "gpt_tn_ved_full_data_no_valid_candidate",
                    product_name=product_name,
                    candidates_tried=len(candidates_list)
                )
                return None

        except json.JSONDecodeError as e:
            logger.error(
                "gpt_tn_ved_json_error",
                product_name=product_name,
                error=str(e),
                content=content[:200] if "content" in locals() else None
            )
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.error(
                "gpt_tn_ved_parse_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return None
        except Exception as e:
            logger.error(
                "gpt_tn_ved_unexpected_error",
                product_name=product_name,
                error=str(e),
                error_type=type(e).__name__
            )
            return None

    async def check_orange_zone(
        self,
        product_name: str,
        tn_ved_code: str,
        duty_type: str,
        product_description: Optional[str] = None,
        product_brand: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Check if product falls into orange zone (requires "Честный знак" marking or has euro duty rate).
        GPT is used only as classifier, not text generator.
        
        Args:
            product_name: Product name
            tn_ved_code: 10-digit TN VED code
            duty_type: Duty type ("specific", "combined", "ad_valorem", "exempt")
            product_description: Optional product description
            product_brand: Optional product brand
            
        Returns:
            {
                "pass": 0 | 1,
                "reason": "string" (explanation text if pass = 0)
            } or None on error
        """
        # Build context for GPT
        context = f"Товар: {product_name}"
        if product_brand:
            context += f"\nБренд: {product_brand}"
        if product_description:
            context += f"\nОписание: {product_description}"
        context += f"\nКод ТН ВЭД: {tn_ved_code}"
        context += f"\nТип пошлины: {duty_type}"
        
        # Check if duty_type is specific or combined (euro duty rate)
        has_euro_duty = duty_type in ["specific", "combined"]
        
        prompt = f"""Проверь, относится ли товар к оранжевой зоне ТН ВЭД. Товар относится к оранжевой зоне, если:
1. Подлежит обязательной маркировке «Честный знак», или
2. Имеет евроставку (специфическую или комбинированную пошлину).

{context}

{"ВНИМАНИЕ: Товар имеет евроставку (специфическую или комбинированную пошлину), что является признаком оранжевой зоны." if has_euro_duty else ""}

Ответь строго в формате JSON (без markdown блоков, только чистый JSON):
{{
    "pass": 0 или 1 (0 = товар в оранжевой зоне, 1 = товар не в оранжевой зоне),
    "reason": "текст пояснения для пользователя" (обязательно заполни, даже если pass = 1, но для pass = 1 можешь написать коротко "Товар не требует маркировки «Честный знак» и не имеет евроставки")
}}

Важно:
- Если товар подлежит обязательной маркировке «Честный знак» → pass = 0
- Если товар имеет евроставку (специфическую или комбинированную пошлину) → pass = 0
- Если оба условия не выполняются → pass = 1
- В поле "reason" для pass = 0 напиши готовый текст пояснения для пользователя о том, почему товар в оранжевой зоне"""

        try:
            response = await self._call_gpt_api(prompt)
            if not response:
                logger.error("gpt_orange_zone_no_response", product_name=product_name, tn_ved_code=tn_ved_code)
                return None

            # Parse JSON from response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error("gpt_orange_zone_empty_content", product_name=product_name, tn_ved_code=tn_ved_code)
                return None

            # Remove markdown code blocks if present
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            # Parse JSON
            data = json.loads(content)

            # Validate structure
            if "pass" not in data or "reason" not in data:
                logger.error(
                    "gpt_orange_zone_invalid_structure",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code,
                    data=data
                )
                return None

            pass_value = data["pass"]
            reason = data["reason"]

            # Validate pass value
            if pass_value not in [0, 1]:
                logger.error(
                    "gpt_orange_zone_invalid_pass_value",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code,
                    pass_value=pass_value
                )
                return None

            logger.info(
                "gpt_orange_zone_success",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                pass_value=pass_value,
                has_euro_duty=has_euro_duty
            )

            return {
                "pass": pass_value,
                "reason": reason
            }

        except json.JSONDecodeError as e:
            logger.error(
                "gpt_orange_zone_json_error",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                error=str(e),
                content=content[:200] if "content" in locals() else None
            )
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.error(
                "gpt_orange_zone_parse_error",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                error=str(e),
                error_type=type(e).__name__
            )
            return None
        except Exception as e:
            logger.error(
                "gpt_orange_zone_unexpected_error",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                error=str(e),
                error_type=type(e).__name__
            )
            return None

    async def format_express_result_message(
        self,
        base_message: str,
        status: str,
        product_name: Optional[str] = None,
        tn_ved_code: Optional[str] = None,
        specific_value_usd_per_kg: Optional[float] = None,
        orange_zone_reason: Optional[str] = None,
        red_zone_reason: Optional[str] = None,
        product_weight_kg: Optional[float] = None,
        product_volume_liters: Optional[float] = None
    ) -> Optional[str]:
        """
        Format express calculation result message using GPT for better readability and client-oriented text.

        Args:
            base_message: Base template message from ExpressAssessmentGenerator
            status: Assessment status (🟢/🟡/🟠/🔴)
            product_name: Product name (optional)
            tn_ved_code: TN VED code (optional)
            specific_value_usd_per_kg: Specific value in USD/kg (for 🟢/🟡)
            orange_zone_reason: Orange zone reason (for 🟠)
            red_zone_reason: Red zone reason (for 🔴)
            product_weight_kg: Product weight in kg (optional)
            product_volume_liters: Product volume in liters (optional)

        Returns:
            Formatted message or None on error
        """
        # Build context for GPT
        context_parts = []
        if product_name:
            context_parts.append(f"Товар: {product_name}")
        if tn_ved_code:
            context_parts.append(f"Код ТН ВЭД: {tn_ved_code}")
        if specific_value_usd_per_kg is not None:
            context_parts.append(f"Удельная стоимость: {specific_value_usd_per_kg:.2f} USD/кг")
        if product_weight_kg is not None:
            context_parts.append(f"Вес единицы товара: {product_weight_kg:.2f} кг")
        if product_volume_liters is not None:
            context_parts.append(f"Объём единицы товара: {product_volume_liters:.2f} л")
        if orange_zone_reason:
            context_parts.append(f"Причина оранжевой зоны: {orange_zone_reason}")
        if red_zone_reason:
            context_parts.append(f"Причина красной зоны: {red_zone_reason}")
        
        context = "\n".join(context_parts) if context_parts else "Нет дополнительной информации"

        # Status titles for new format
        status_titles = {
            "🟢": "Белая доставка — фаворит",
            "🟡": "Белая доставка — рабочий вариант",
            "🟠": "Белая доставка — стратегическая цель",
            "🔴": "Белая — только после подготовки"
        }
        
        status_title = status_titles.get(status, "Неизвестный статус")
        
        # Build volume info for prompt
        volume_info = ""
        if product_weight_kg is not None:
            volume_info = f"\nВес единицы товара: ~{product_weight_kg:.2f} кг"
        if product_volume_liters is not None:
            if volume_info:
                volume_info += f" (~{product_volume_liters:.2f} л)"
            else:
                volume_info = f"\nОбъём единицы товара: ~{product_volume_liters:.2f} л"
        
        # Calculate recommended volume based on status and quantity
        recommended_volume_info = ""
        if product_weight_kg is not None and product_weight_kg > 0 and product_volume_liters is not None and product_volume_liters > 0:
            # Convert volume from liters to m³
            unit_volume_m3 = product_volume_liters * 0.001
            unit_weight_kg = product_weight_kg
            
            # Recommended base values by status
            recommended_bases = {
                "🟢": {"weight_kg": 800.0, "volume_m3": 3.69},
                "🟡": {"weight_kg": 1267.0, "volume_m3": 5.84},
                "🟠": {"weight_kg": 1900.0, "volume_m3": 8.76},
                "🔴": {"weight_kg": 1900.0, "volume_m3": 8.76}
            }
            
            base_values = recommended_bases.get(status)
            if base_values:
                recommended_weight_kg = base_values["weight_kg"]
                recommended_volume_m3 = base_values["volume_m3"]
                
                # Calculate quantity by weight and volume, take minimum
                quantity_by_weight = int(recommended_weight_kg / unit_weight_kg)
                quantity_by_volume = int(recommended_volume_m3 / unit_volume_m3)
                recommended_quantity = min(quantity_by_weight, quantity_by_volume)
                
                if recommended_quantity > 0:
                    recommended_volume_info = (
                        f"\n\nРекомендуемый выгодный объем (РАССЧИТАНО, НЕ ИЗМЕНЯТЬ):\n"
                        f"- Количество штук в партии: {recommended_quantity} шт\n"
                        f"ВАЖНО: Эти значения рассчитаны автоматически и их нельзя изменять в ответе!"
                    )

        # Instructions for each status
        status_instructions = {
            "🟢": """Для 🟢 Оценка товара: «Белая доставка — фаворит»:

В секции "Почему такой статус:":
- Товар не имеет ограничений и дополнительных требований при транспортировке
- Не подлежит уплате специальных таможенных платежей
- Низкая стоимость товара не нагружает высокими таможенными платежами

В секции "Про объём:":
Чем больше объем партии, тем выгоднее ставка на логистику.
Обязательно включи информацию о рекомендуемом выгодном объеме из контекста (если она есть), используя точное значение количества штук без изменений.

В секции "Рекомендация:":
Сделать детальные расчет стоимости официальной доставки и уже сейчас переходить на белый импорт.""",
            
            "🟡": """Для 🟡 Оценка товара: «Белая доставка — рабочий вариант»:

В секции "Почему такой статус:":
Обязательно используй формат с дефисом "-" перед каждым пунктом (как в других статусах):
- Товар подходит для белой доставки, однако чувствителен к расходам
- Стоимость товар ближе к "дорогим", поэтому его конечная цена зависит от ставки импортной пошлины и НДС
- Товар находится в "рабочей" зоне для белой логистики: можно возить в белую, но решение лучше принимать после точного расчёта под ваш объем и маржу.

В секции "Про объём:":
Чем больше объем партии, тем выгоднее ставка на логистику.
Обязательно включи информацию о рекомендуемом выгодном объеме из контекста (если она есть), используя точное значение количества штук без изменений.

В секции "Рекомендация:":
Сделать точный расчёт белой логистики (пошлина, НДС, логистика, курс), а затем принимать решение. Без расчёта оформлять поставку рискованно.""",
            
            "🟠": """Для 🟠 Оценка товара: «Белая доставка — стратегическая цель»:

В секции "Почему такой статус:":
- Товар относится к категории с обязательной маркировкой или особым режимом (например, «Честный знак» или евроставка)
- По этой группе выше внимание контролирующих органов, важны корректный код ТН ВЭД и полный комплект документов
- Ошибки в оформлении (код, документы, маркировка) могут приводить к доначислениям и блокировкам, поэтому товар стратегически нужно ориентировать на белый импорт

В секции "Про объём:":
Чем больше объём партии (особенно от средних и крупных партий), тем более оправдано выстраивать стабильную белую схему: стоимость единицы снижается, а выгода от прозрачной, прогнозируемой логистики растёт. На небольших объёмах экономика может быть на грани, но уже имеет смысл считать белый вариант цифрами.
Обязательно включи информацию о рекомендуемом выгодном объеме из контекста (если она есть), используя точные значения веса, объема и количества штук без изменений.

В секции "Рекомендация:":
Считать белую доставку для этого товара как целевой вариант: подготовить детальный расчёт официальной схемы (код ТН ВЭД, пошлина/евроставка, НДС, логистика), заранее продумать и оформить маркировку и документы, чтобы при росте объёмов перейти на полностью белый импорт без переделки схемы.""",
            
            "🔴": """Для 🔴 Оценка товара: «Белая — только после подготовки»:

В секции "Почему такой статус:":
- Товар относится к категории бытовой химии и дезинфицирующих средств, требует наличия специальных документов и разрешения транспортной компании для перевозки
- Товар подлежит сертификации, оформление которой приводит к удорожанию конечной стоимости товара

В секции "Рекомендация:":
Рекомендуем рассмотреть возможность изменения продукта или категории. Также можно вынести белую логистику по этому товару в отдельный сложный проект с необходимыми документами. В текущем виде белая схема не рекомендуется."""
        }

        instruction = status_instructions.get(status, "")

        # Формат сообщения зависит от статуса - для 🔴 нет секции "Про объём"
        if status == "🔴":
            message_format = f"""{status} <b>Оценка товара: «{status_title}»</b>

<b>Почему такой статус:</b>

[Следуй инструкциям ниже для этого статуса. ОБЯЗАТЕЛЬНО используй формат с дефисом "-" перед каждым пунктом, каждый пункт с новой строки]

<b>Рекомендация:</b>

[Следуй инструкциям ниже для этого статуса]"""
            
            requirements = """- Используй HTML разметку для форматирования (теги <b>, <i>, <code>)
- Сохраняй эмодзи статуса в начале
- Будь дружелюбным и понятным
- Нельзя использовать фразы подобно: "поэтому он не может быть доставлен с использованием белой логистики". Нужно сглаживать сложности и делать акцент на том что лучше изменить или какие есть сложности для перехода на белую доставку
- Заполни все секции: Почему такой статус, Рекомендация
- ОБЯЗАТЕЛЬНО: В секции "Почему такой статус" используй формат с дефисом "-" перед каждым пунктом, каждый пункт с новой строки."""
        else:
            message_format = f"""{status} <b>Оценка товара: «{status_title}»</b>

<b>Почему такой статус:</b>

[Следуй инструкциям ниже для этого статуса. ОБЯЗАТЕЛЬНО используй формат с дефисом "-" перед каждым пунктом, каждый пункт с новой строки]

<b>Про объём:</b>

[Следуй инструкциям ниже для этого статуса]

<b>Рекомендация:</b>

[Следуй инструкциям ниже для этого статуса]"""
            
            requirements = """- Используй HTML разметку для форматирования (теги <b>, <i>, <code>)
- Сохраняй эмодзи статуса в начале
- Будь дружелюбным и понятным
- Нельзя использовать фразы подобно: "поэтому он не может быть доставлен с использованием белой логистики". Нужно сглаживать сложности и делать акцент на том что лучше изменить или какие есть сложности для перехода на белую доставку
- Заполни все секции: Почему такой статус, Про объём, Рекомендация
- ОБЯЗАТЕЛЬНО: В секции "Почему такой статус" используй формат с дефисом "-" перед каждым пунктом, каждый пункт с новой строки. Это правило применяется ко ВСЕМ статусам (🟢, 🟡, 🟠, 🔴) без исключений!
- КРИТИЧЕСКИ ВАЖНО: Если в контексте есть информация о рекомендуемом выгодном объеме (количество штук), ты ОБЯЗАН включить это точное значение в секцию "Про объём" без каких-либо изменений. Нельзя округлять, изменять или пересчитывать это значение!"""

        prompt = f"""Ты помощник для формирования клиенто-ориентированных сообщений о результатах экспресс-расчета белой логистики.

Базовое сообщение:
{base_message}

Дополнительный контекст:
{context}
{volume_info}{recommended_volume_info}

Статус: {status} ({status_title})

Задача: Сформируй сообщение в строго заданном формате:

{message_format}

{instruction}

Требования к сообщению:
{requirements}

Верни только текст сообщения в указанном формате без дополнительных комментариев и без markdown блоков."""

        try:
            # Use different API call for text generation (not JSON)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты помощник для формирования клиенто-ориентированных сообщений. Отвечай только текстом сообщения без дополнительных комментариев, markdown блоков или пояснений."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,  # Higher temperature for more natural text
            }
            
            # For GPT-5.x models use max_completion_tokens, for others use max_tokens
            # Increased limit for longer messages with detailed sections
            if "gpt-5" in self.model:
                payload["max_completion_tokens"] = 1000
            else:
                payload["max_tokens"] = 1000

            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        error_type = "api_error" if resp.status >= 400 else "unknown"
                        logger.error(
                            "gpt_format_message_api_error",
                            event_type="gpt_api_error",
                            error_type=error_type,
                            status=resp.status,
                            error=error_text[:200]  # Truncate error message
                        )
                        return None

                    response_data = await resp.json()
                    content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    if not content:
                        logger.error("gpt_format_message_empty_content")
                        return None

                    # Remove markdown code blocks if present
                    content = content.strip()
                    if "```" in content:
                        # Try to extract text from markdown blocks
                        parts = content.split("```")
                        # Take the longest non-empty part (likely the actual message)
                        content = max([p.strip() for p in parts if p.strip() and not p.strip().startswith("html")], key=len, default=content)

                    # Add footer message about button
                    if content:
                        content += "\n\n💡 Используйте кнопку ниже для нового запроса"

                    logger.info(
                        "gpt_format_message_success",
                        status=status,
                        product_name=product_name
                    )

                    return content

        except aiohttp.ClientError as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_format_message_client_error",
                event_type="gpt_api_error",
                error_type=error_type,
                error=str(e)[:200]
            )
            return None
        except asyncio.TimeoutError:
            logger.error(
                "gpt_format_message_timeout",
                event_type="gpt_api_timeout"
            )
            return None
        except Exception as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_format_message_unexpected_error",
                event_type="gpt_api_unexpected_error",
                error_type=error_type,
                error=str(e)[:200],
                error_class=type(e).__name__
            )
            return None

    async def _call_gpt_api(self, prompt: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Call GPT API.

        Args:
            prompt: User prompt
            model: Optional model name (defaults to self.model)

        Returns:
            API response JSON or None on error
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        model_to_use = model or self.model
        
        payload = {
            "model": model_to_use,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты помощник для определения характеристик товаров. Отвечай только валидным JSON без дополнительных комментариев."
                },
                {"role": "user", "content": prompt}
            ]
        }
        
        # For GPT-5.x models use max_completion_tokens and don't set temperature (only default 1 is supported)
        # GPT-5 uses reasoning tokens, so we need significantly more tokens for reasoning + response
        # GPT-5 may not support response_format, so we'll request JSON in prompt instead
        if "gpt-5" in model_to_use:
            payload["max_completion_tokens"] = 2000  # Increased to allow reasoning + response
            # GPT-5 only supports default temperature (1), don't set it
            # GPT-5 may not support response_format, rely on prompt instructions
        else:
            payload["max_tokens"] = 200
            payload["temperature"] = 0.3
            payload["response_format"] = {"type": "json_object"}  # Force JSON response

        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        error_type = "api_error" if resp.status >= 400 else "unknown"
                        logger.error(
                            "gpt_api_error",
                            event_type="gpt_api_error",
                            error_type=error_type,
                            status=resp.status,
                            error=error_text[:200]  # Truncate error message
                        )
                        return None

                    response_data = await resp.json()
                    logger.debug(
                        "gpt_api_success",
                        model=model_to_use,
                        has_choices=bool(response_data.get("choices")),
                        choices_count=len(response_data.get("choices", [])),
                        first_choice_keys=list(response_data.get("choices", [{}])[0].keys()) if response_data.get("choices") else []
                    )
                    return response_data

        except aiohttp.ClientError as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_api_client_error",
                event_type="gpt_api_error",
                error_type=error_type,
                error=str(e)[:200]
            )
            return None
        except asyncio.TimeoutError:
            logger.error(
                "gpt_api_timeout",
                event_type="gpt_api_timeout"
            )
            return None
        except Exception as e:
            error_type = ErrorHandler.classify_gpt_error(e)
            logger.error(
                "gpt_api_unexpected_error",
                event_type="gpt_api_unexpected_error",
                error_type=error_type,
                error=str(e)[:200],
                error_class=type(e).__name__
            )
            return None

