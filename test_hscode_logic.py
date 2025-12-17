"""Тест логики подбора кода ТН ВЭД из hscode_service."""
import asyncio
import json
import re
import aiohttp
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from pathlib import Path
import structlog
from bs4 import BeautifulSoup

load_dotenv(Path(__file__).parent / ".env")
logger = structlog.get_logger()


class HSCodeService:
    """Упрощенная версия логики из hscode_service."""
    
    def __init__(self, api_key: str, api_url: str = "https://api.openai.com/v1/chat/completions", model: str = "gpt-4o"):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
    
    async def _call_gpt_api(self, prompt: str, system_prompt: str = None) -> Optional[Dict[str, Any]]:
        """Вызов GPT API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 500,
        }
        
        if "gpt-5" in self.model:
            payload["max_completion_tokens"] = 500
            payload.pop("max_tokens", None)
        
        timeout = aiohttp.ClientTimeout(total=30)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error("gpt_api_error", status=resp.status, error=error_text[:500])
                        return None
                    
                    response_data = await resp.json()
                    return response_data
        except Exception as e:
            logger.error("gpt_api_error", error=str(e))
            return None
    
    async def get_keywords(self, description: str) -> str:
        """Извлекает ключевые слова из описания товара."""
        prompt = f"""Извлеки ключевые слова для поиска кода ТН ВЭД из описания товара.
        
Описание: {description}

Верни только ключевые слова через запятую, без дополнительных комментариев."""
        
        response = await self._call_gpt_api(prompt)
        if response:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content.strip()
        return description
    
    async def parse_ifcg_simulation(self, keywords: str) -> List[Dict[str, Any]]:
        """Симуляция parse_ifcg - используем GPT для поиска кодов на ifcg.ru (БЕЗ пошлин)."""
        prompt = f"""Найди коды ТН ВЭД на сайте ifcg.ru для товара по ключевым словам: {keywords}

Верни список из 3-5 наиболее подходящих кодов в формате JSON (БЕЗ информации о пошлинах):
{{
    "candidates": [
        {{
            "code": "10-значный код",
            "name": "название товара"
        }}
    ]
}}"""
        
        response = await self._call_gpt_api(prompt, system_prompt="Ты помощник для поиска кодов ТН ВЭД на ifcg.ru. Отвечай только валидным JSON.")
        if response:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Убираем markdown блоки
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            try:
                data = json.loads(content)
                return data.get("candidates", [])
            except json.JSONDecodeError:
                pass
        return []
    
    async def analyze_candidates(self, description: str, candidates: List[Dict[str, Any]]) -> str:
        """Анализирует кандидатов через GPT (только выбор кода, без пошлин)."""
        candidates_text = "\n".join([
            f"- Код: {c.get('code', '')}, Название: {c.get('name', '')}"
            for c in candidates
        ])
        
        prompt = f"""Проанализируй список кандидатов кодов ТН ВЭД и выбери наиболее подходящий для товара.

Описание товара: {description}

Кандидаты:
{candidates_text}

Верни анализ в формате JSON (только код, без пошлин):
{{
    "selected_code": "выбранный 10-значный код",
    "reason": "обоснование выбора"
}}"""
        
        response = await self._call_gpt_api(prompt, system_prompt="Ты эксперт по классификации товаров по ТН ВЭД. Отвечай только валидным JSON.")
        if response:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            # Убираем markdown блоки
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            return content
        return ""
    
    def extract_hs_code(self, analysis: str) -> Optional[str]:
        """Извлекает код ТН ВЭД из анализа."""
        try:
            data = json.loads(analysis)
            code = data.get("selected_code", "")
            # Нормализуем код: убираем точки, пробелы, дефисы
            if code:
                code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
                if len(code) == 10 and code.isdigit():
                    return code
        except json.JSONDecodeError:
            # Пробуем найти код в тексте
            match = re.search(r'\b(\d{2,10})\b', analysis)
            if match:
                code = match.group(1).replace(".", "").replace(" ", "").replace("-", "")
                if len(code) == 10 and code.isdigit():
                    return code
        return None
    
    async def get_duty_info(self, code: str) -> Dict[str, Any]:
        """Парсит информацию о пошлинах и НДС напрямую с сайта ifcg.ru."""
        url = f"https://www.ifcg.ru/kb/tnved/{code}/"
        
        logger.info("parsing_ifcg_duty", url=url, code=code)
        
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
                                if re.search(r'Евро|EUR', duty_value, re.I) and ("/" in duty_value or "/" in duty_value):
                                    duty_type = "specific"
                                    match = re.search(r'([\d,\.]+)', duty_value.replace(",", "."))
                                    if match:
                                        duty_rate = float(match.group(1))
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
    
    async def guess_code(self, description: str) -> Dict[str, Any]:
        """Основная функция подбора кода (как в hscode_service)."""
        # 1) Извлекаем ключевые слова
        keywords = await self.get_keywords(description)
        logger.info("keywords_extracted", keywords=keywords)
        
        # 2) Получаем кандидатов (симуляция parse_ifcg)
        candidates = await self.parse_ifcg_simulation(keywords)
        logger.info("candidates_found", count=len(candidates), candidates=candidates)
        
        if not candidates:
            return {
                "code": "",
                "duty_type": "ad_valorem",
                "duty_rate": 0.0,
                "vat_rate": 20.0,
                "error": "Не найдено кандидатов"
            }
        
        # 3) Анализируем кандидатов
        analysis = await self.analyze_candidates(description, candidates)
        logger.info("analysis_complete", analysis_len=len(analysis), analysis=analysis[:200])
        
        # 4) Извлекаем код
        code = self.extract_hs_code(analysis)
        logger.info("code_extracted", code=code)
        
        # Если код не извлекся, пробуем из кандидатов
        if not code and candidates:
            # Берем первый кандидат как fallback
            first_candidate = candidates[0]
            candidate_code = first_candidate.get("code", "")
            # Нормализуем код
            if candidate_code:
                candidate_code = candidate_code.replace(".", "").replace(" ", "").replace("-", "").strip()
                if len(candidate_code) == 10 and candidate_code.isdigit():
                    code = candidate_code
                    logger.info("code_from_candidate", code=code)
        
        # Нормализуем финальный код
        if code:
            code = code.replace(".", "").replace(" ", "").replace("-", "").strip()
        
        if not code:
            return {
                "code": "",
                "duty_type": "ad_valorem",
                "duty_rate": 0.0,
                "vat_rate": 20.0,
                "error": "Не удалось определить код ТН ВЭД"
            }
        
        # 5) ЭТАП 2: Получаем информацию о пошлинах и НДС для найденного кода
        logger.info("getting_duty_info", code=code)
        duty_info = await self.get_duty_info(code)
        logger.info("duty_info_received", duty_info=duty_info)
        
        # Если код вернул 404 или пошлина 0.0, пробуем другие кандидаты
        if duty_info["duty_rate"] == 0.0 and candidates:
            logger.warning("primary_code_failed", code=code, trying_alternatives=True)
            for candidate in candidates:
                candidate_code = candidate.get("code", "").replace(".", "").replace(" ", "").replace("-", "").strip()
                if candidate_code and candidate_code != code and len(candidate_code) == 10 and candidate_code.isdigit():
                    logger.info("trying_alternative_code", code=candidate_code)
                    alt_duty_info = await self.get_duty_info(candidate_code)
                    # Если альтернативный код вернул валидные данные (не 0.0 и не 404)
                    if alt_duty_info["duty_rate"] > 0.0:
                        logger.info("alternative_code_success", code=candidate_code, duty_info=alt_duty_info)
                        return {
                            "code": candidate_code,
                            "duty_type": alt_duty_info["duty_type"],
                            "duty_rate": alt_duty_info["duty_rate"],
                            "vat_rate": alt_duty_info["vat_rate"]
                        }
        
        return {
            "code": code,
            "duty_type": duty_info["duty_type"],
            "duty_rate": duty_info["duty_rate"],
            "vat_rate": duty_info["vat_rate"]
        }


async def test():
    """Тест на примере худи."""
    import os
    
    api_key = os.getenv("GPT_API_KEY")
    if not api_key:
        print("Ошибка: GPT_API_KEY не установлен")
        return
    
    service = HSCodeService(api_key=api_key, model="gpt-4o")
    
    product_name = "Худи оверсайз теплое с капюшоном y2k с начесом"
    
    print("=" * 80)
    print("ТЕСТ ЛОГИКИ ИЗ HSCODE_SERVICE")
    print("=" * 80)
    print(f"Товар: {product_name}\n")
    
    result = await service.guess_code(product_name)
    
    print("=" * 80)
    print("РЕЗУЛЬТАТ:")
    print("=" * 80)
    print(f"Код ТН ВЭД: {result['code']}")
    print(f"Тип пошлины: {result['duty_type']}")
    print(f"Ставка пошлины: {result['duty_rate']}")
    print(f"Ставка НДС: {result['vat_rate']}%")
    if "error" in result:
        print(f"Ошибка: {result['error']}")
    print("=" * 80)
    print("Ожидается:")
    print("  Код ТН ВЭД: 6110209100 или 6110209900")
    print("  Тип пошлины: specific")
    print("  Ставка пошлины: 1.75")
    print("  Ставка НДС: 20.0%")
    print("=" * 80)
    
    if result['code'] and result['duty_type'] == 'specific' and result['duty_rate'] == 1.75:
        print("✓ ПРАВИЛЬНО")
    else:
        print("✗ НЕПРАВИЛЬНО")


if __name__ == "__main__":
    asyncio.run(test())

