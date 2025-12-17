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
    ):
        """
        Initialize GPT Service.

        Args:
            api_key: OpenAI API key (defaults to config.GPT_API_KEY)
            api_url: GPT API URL (defaults to config.GPT_API_URL)
            model: GPT model name (defaults to config.GPT_MODEL)
        """
        self.api_key = api_key or config.GPT_API_KEY
        self.api_url = api_url or config.GPT_API_URL
        self.model = model or config.GPT_MODEL

        if not self.api_key:
            raise ValueError("GPT_API_KEY is required")

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

    async def _parse_ifcg_duty(self, code: str) -> Dict[str, Any]:
        """
        Parse duty and VAT information directly from ifcg.ru website.
        
        Args:
            code: 10-digit TN VED code
            
        Returns:
            {
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float
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
                    
                    duty_type = "ad_valorem"
                    duty_rate = 0.0
                    vat_rate = 20.0
                    
                    # Ищем строку "Импортная пошлина:"
                    duty_row = soup.find('td', string=re.compile(r'Импортная пошлина', re.I))
                    if duty_row:
                        tr = duty_row.find_parent('tr')
                        if tr:
                            tds = tr.find_all('td')
                            if len(tds) >= 2:
                                duty_value = tds[1].get_text(strip=True)
                                logger.info("duty_value_found", duty_value=duty_value)
                                
                                # Парсим значение
                                # Специфическая пошлина: "X Евро/кг", "X EUR/кг", "X Евро/пар", "X EUR/пар", "X Евро/шт" и т.д.
                                if re.search(r'Евро|EUR', duty_value, re.I) and ("/" in duty_value):
                                    match = re.search(r'([\d,\.]+)', duty_value.replace(",", "."))
                                    if match:
                                        duty_rate = float(match.group(1))
                                        # Determine specific duty type based on unit
                                        if re.search(r'/кг|/kg', duty_value, re.I):
                                            duty_type = "по весу"  # EUR/кг
                                        elif re.search(r'/пар|/pair', duty_value, re.I):
                                            duty_type = "по паре"  # EUR/пар
                                        elif re.search(r'/шт|/unit|/pc|/piece', duty_value, re.I):
                                            duty_type = "по единице"  # EUR/шт
                                        else:
                                            # Default to per unit if unit not specified
                                            duty_type = "по единице"
                                elif "%" in duty_value:
                                    duty_type = "ad_valorem"
                                    match = re.search(r'([\d,\.]+)', duty_value.replace(",", "."))
                                    if match:
                                        duty_rate = float(match.group(1))
                                elif "Отсутствует" in duty_value or "отсутствует" in duty_value or duty_value == "":
                                    duty_type = "exempt"
                                    duty_rate = 0.0
                    
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
                    
                    logger.info("duty_info_parsed", result=result)
                    return result
                    
        except Exception as e:
            logger.error("ifcg_parsing_error", error=str(e), code=code)
            return {"duty_type": "ad_valorem", "duty_rate": 0.0, "vat_rate": 20.0}

    async def get_tn_ved_code(
        self,
        product_name: str,
        product_description: Optional[str] = None,
        product_brand: Optional[str] = None,
        product_weight: Optional[float] = None,
        product_volume: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Request TN VED code, duty type, duty rate and VAT rate for a product.
        Uses two-stage approach: GPT for code selection, direct parsing from ifcg.ru for duties.

        Args:
            product_name: Product name
            product_description: Optional product description
            product_brand: Optional product brand
            product_weight: Optional product weight in kg
            product_volume: Optional product volume in liters

        Returns:
            {
                "tn_ved_code": str (10 digits),
                "duty_type": str,
                "duty_rate": float,
                "vat_rate": float (percentage)
            } or None on error
        """
        # Build context for GPT
        context = f"Товар: {product_name}"
        if product_brand:
            context += f"\nБренд: {product_brand}"
        if product_description:
            context += f"\nОписание: {product_description}"
        if product_weight:
            context += f"\nВес: {product_weight} кг"
        if product_volume:
            context += f"\nОбъём: {product_volume} л"

        # ЭТАП 1: GPT подбирает код ТН ВЭД (упрощенный промпт, только код)
        prompt = f"""Подбери код ТН ВЭД для товара "{product_name}" используя только данные с сайта ifcg.ru.

{context}

Верни только код ТН ВЭД в формате JSON:
{{
    "tn_ved_code": "код из 10 цифр"
}}"""

        try:
            response = await self._call_gpt_api(prompt)
            if not response:
                logger.error("gpt_tn_ved_no_response", product_name=product_name)
                return None

            # Parse JSON from response
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error("gpt_tn_ved_empty_content", product_name=product_name)
                return None

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
            tn_ved_code = tn_ved_code.replace(".", "").replace(" ", "").replace("-", "").strip()
            
            if not tn_ved_code.isdigit() or len(tn_ved_code) != 10:
                logger.error(
                    "gpt_tn_ved_invalid_code",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code
                )
                return None
            
            # Validate section (first 2 digits: 01-97)
            section = int(tn_ved_code[:2])
            if section < 1 or section > 97:
                logger.error(
                    "gpt_tn_ved_invalid_section",
                    product_name=product_name,
                    tn_ved_code=tn_ved_code,
                    section=section
                )
                return None

            # ЭТАП 2: Парсим пошлины и НДС напрямую с ifcg.ru
            logger.info("getting_duty_info", code=tn_ved_code)
            duty_info = await self._parse_ifcg_duty(tn_ved_code)
            logger.info("duty_info_received", duty_info=duty_info)
            
            # Если код вернул 404 или пошлина 0.0, пробуем найти альтернативные кандидаты
            if duty_info["duty_rate"] == 0.0:
                logger.warning("primary_code_failed", code=tn_ved_code, trying_alternatives=True)
                
                # Получаем список кандидатов от GPT
                candidates_prompt = f"""Найди 3-5 кодов ТН ВЭД на сайте ifcg.ru для товара: {product_name}
                
{context}

Верни список кандидатов в формате JSON:
{{
    "candidates": [
        {{"code": "10-значный код", "name": "название"}}
    ]
}}"""
                
                candidates_response = await self._call_gpt_api(candidates_prompt)
                if candidates_response:
                    candidates_content = candidates_response.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if candidates_content:
                        # Remove markdown
                        if "```json" in candidates_content:
                            candidates_content = candidates_content.split("```json")[1].split("```")[0].strip()
                        elif "```" in candidates_content:
                            candidates_content = candidates_content.split("```")[1].split("```")[0].strip()
                        
                        try:
                            candidates_data = json.loads(candidates_content)
                            candidates = candidates_data.get("candidates", [])
                            
                            # Пробуем альтернативные кандидаты
                            for candidate in candidates:
                                candidate_code = candidate.get("code", "").replace(".", "").replace(" ", "").replace("-", "").strip()
                                if candidate_code and candidate_code != tn_ved_code and len(candidate_code) == 10 and candidate_code.isdigit():
                                    logger.info("trying_alternative_code", code=candidate_code)
                                    alt_duty_info = await self._parse_ifcg_duty(candidate_code)
                                    # Если альтернативный код вернул валидные данные (не 0.0)
                                    if alt_duty_info["duty_rate"] > 0.0:
                                        logger.info("alternative_code_success", code=candidate_code, duty_info=alt_duty_info)
                                        return {
                                            "tn_ved_code": candidate_code,
                                            "duty_type": alt_duty_info["duty_type"],
                                            "duty_rate": alt_duty_info["duty_rate"],
                                            "vat_rate": alt_duty_info["vat_rate"]
                                        }
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning("candidates_parse_failed", error=str(e))

            logger.info(
                "gpt_tn_ved_success",
                product_name=product_name,
                tn_ved_code=tn_ved_code,
                duty_type=duty_info["duty_type"],
                duty_rate=duty_info["duty_rate"],
                vat_rate=duty_info["vat_rate"]
            )
            
            return {
                "tn_ved_code": tn_ved_code,
                "duty_type": duty_info["duty_type"],
                "duty_rate": duty_info["duty_rate"],
                "vat_rate": duty_info["vat_rate"]
            }

            return {
                "tn_ved_code": tn_ved_code,
                "duty_type": duty_type,
                "duty_rate": duty_rate,
                "vat_rate": vat_rate
            }

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
            "🟢": "Белый фаворит",
            "🟡": "Белый рабочий вариант",
            "🟠": "Белая — стратегическая цель",
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

        # Instructions for each status
        status_instructions = {
            "🟢": """Для 🟢 Белый фаворит:

Сделай 2–3 пункта в секции "Почему такой статус:", где:
- Подчёркиваешь, что товар массовый и "нормальный" для белой логистики, без спецограничений.
- Говоришь, что по расчётам у товара низкая удельная стоимость, и доля логистики/пошлины/НДС в конечной цене комфортная.
- Делаешь вывод: «По экономике белая схема для этого товара выглядит уверенно: себестоимость остаётся конкурентной, а логистика предсказуемая.»

В секции "Про объём:":
Если данные о весе/объёме есть — пиши: «Сейчас ориентировочный объём партии — ~X кг (или Y шт/пар).»
Скажи, что при нормальных объёмах (от нескольких сотен кг и выше) белая схема обычно работает хорошо и предсказуемо.

В секции "Рекомендация:":
- Рекомендуй ориентироваться на белую схему как основную.
- Укажи, что имеет смысл делать детальный белый расчёт и планировать работу "в белую" уже сейчас.""",
            
            "🟡": """Для 🟡 Белый рабочий вариант:

Сделай 2–3 пункта в секции "Почему такой статус:", где:
- Объясняешь, что товар подходит для белой схемы, но чувствителен к расходам — доля логистики, пошлины и НДС в себестоимости уже заметная.
- Указываешь, что по удельной стоимости товар ближе к "дорогим", поэтому цена сильно зависит от ставок и курса.
- Делаешь вывод: «Товар находится в "рабочей" зоне для белой логистики: можно возить в белую, но решение лучше принимать после точного расчёта под ваши объёмы и маржу.»

В секции "Про объём:":
Если данные о весе/объёме есть — пиши: «Сейчас ориентировочный объём партии — ~X кг (или Y шт/пар).»
Отметь, что на маленьких объёмах белая может быть на грани по экономике, а при росте объёма важно считать аккуратнее, потому что товар чувствителен к ставкам и расходам.

В секции "Рекомендация:":
- Рекомендуй сначала сделать точный расчёт белой логистики (пошлина, НДС, логистика, курс), и уже от цифр принимать решение.
- Подчеркни, что без расчёта "на глаз" решать рискованно.""",
            
            "🟠": """Для 🟠 Белая — стратегическая цель:

В секции "Почему такой статус:":
- Используй информацию из причины оранжевой зоны (если она указана в контексте) - там уже есть информация о Честном знаке и/или евроставке.
- Укажи, что товар подпадает под Честный знак и/или евроставку (используй конкретную информацию из причины, если она есть).
- Отметь, что контроль и требования по таким товарам жёстче, а ошибки в коде ТН ВЭД/документах стоят дорого.
- Зафиксируй, что с ростом объёмов белая схема для этой категории неизбежно становится базовой.

В секции "Про объём:":
Если данные о весе/объёме есть — пиши: «Сейчас ориентировочный объём партии — ~X кг (или Y шт/пар).»
Напомни, что для ЧЗ/евроставки объём критичен:
- до ~800 кг — экономика может быть спорной, но считать уже нужно;
- от ~800 кг и выше — белая схема становится стратегически правильной.

В секции "Рекомендация:":
- Рекомендуй рассматривать белую схему как целевой вариант.
- Советуй сделать отдельный подробный расчёт по белой и готовить комплект документов / маркировку «Честный знак» для масштабирования.""",
            
            "🔴": """Для 🔴 Белая — только после подготовки / смены продукта:

В секции "Почему такой статус:":
- Используй информацию из причины красной зоны (если она указана в контексте) - там уже есть информация о категории товара.
- Чётко укажи, к какой красной категории относится товар (лекарства, БАДы, еда, химия, санкции, dual use и т.д.) - используй конкретную информацию из причины, если она есть.
- Объясни, что без серьёзной подготовки/документов белая схема сейчас нецелесообразна и/или слишком рискованна.

В секции "Про объём:":
Если данные о весе/объёме есть — пиши: «Сейчас ориентировочный объём партии — ~X кг (или Y шт/пар).»
Можешь отметить, что даже при больших объёмах без подготовки/документов по этой категории в белую идти нельзя, это отдельный сложный проект.

В секции "Рекомендация:":
- Рекомендуй либо менять продукт / категорию, либо выносить белую схему по этому товару в отдельный сложный проект с документами.
- Чётко обозначь, что в текущем виде белая схема не рекомендуется."""
        }

        instruction = status_instructions.get(status, "")

        prompt = f"""Ты помощник для формирования клиенто-ориентированных сообщений о результатах экспресс-расчета белой логистики.

Базовое сообщение:
{base_message}

Дополнительный контекст:
{context}
{volume_info}

Статус: {status} ({status_title})

Задача: Сформируй сообщение в строго заданном формате:

{status} <b>Оценка товара: «{status_title}»</b>

<b>Почему такой статус:</b>

[Следуй инструкциям ниже для этого статуса]

<b>Про объём:</b>

[Следуй инструкциям ниже для этого статуса]

<b>Рекомендация:</b>

[Следуй инструкциям ниже для этого статуса]

{instruction}

Требования к сообщению:
- Используй HTML разметку для форматирования (теги <b>, <i>, <code>)
- Сохраняй эмодзи статуса в начале
- Будь дружелюбным и понятным
- Нельзя использовать фразы подобно: "поэтому он не может быть доставлен с использованием белой логистики". Нужно сглаживать сложности и делать акцент на том что лучше изменить или какие есть сложности для перехода на белую доставку
- Заполни все секции: Почему такой статус, Про объём, Рекомендация
- Если данные о весе/объёме есть, обязательно используй их в секции "Про объём"

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

    async def _call_gpt_api(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Call GPT API.

        Args:
            prompt: User prompt

        Returns:
            API response JSON or None on error
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты помощник для определения характеристик товаров. Отвечай только валидным JSON без дополнительных комментариев."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"}  # Force JSON response
        }
        
        # For GPT-5.x models use max_completion_tokens, for others use max_tokens
        if "gpt-5" in self.model:
            payload["max_completion_tokens"] = 200
        else:
            payload["max_tokens"] = 200

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
                    logger.debug("gpt_api_success", model=self.model)
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

