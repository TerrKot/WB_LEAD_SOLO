"""Show GPT responses (candidates) for TN VED code selection."""
import asyncio
import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.gpt_service import GPTService

async def show_responses():
    article_id = 689623448
    
    print("="*80)
    print(f"ПОКАЗ ОТВЕТОВ GPT ДЛЯ АРТИКУЛА: {article_id}")
    print("="*80)
    
    wb_parser = WBParserService()
    gpt_service = GPTService()
    
    # Fetch card data
    print(f"\n1. Получение card_data для артикула {article_id}...")
    card_data = await wb_parser.fetch_product_card_data(article_id)
    
    if not card_data:
        print("❌ Не удалось получить card_data")
        return
    
    print("✅ card_data получен")
    
    # Stage 1: Basic data
    print("\n" + "="*80)
    print("ЭТАП 1: Запрос к GPT с базовыми полями")
    print("="*80)
    
    basic_data = wb_parser.get_tn_ved_basic_data(card_data, None)
    
    basic_info_parts = []
    if basic_data.get("subj_name"):
        basic_info_parts.append(f"Тип товара: {basic_data['subj_name']}")
    if basic_data.get("subj_root_name"):
        basic_info_parts.append(f"Категория: {basic_data['subj_root_name']}")
    if basic_data.get("imt_name"):
        basic_info_parts.append(f"Название товара: {basic_data['imt_name']}")
    
    basic_info = "\n".join(basic_info_parts) if basic_info_parts else "Данные отсутствуют"
    
    prompt_stage1 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

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
    
    print("\n📤 Отправка запроса в GPT...")
    try:
        response = await gpt_service._call_gpt_api(prompt_stage1)
        
        if not response:
            print("❌ GPT не вернул ответ")
        else:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                print("❌ Пустой ответ от GPT")
            else:
                # Remove markdown code blocks
                content_clean = content.strip()
                if "```json" in content_clean:
                    content_clean = content_clean.split("```json")[1].split("```")[0].strip()
                elif "```" in content_clean:
                    content_clean = content_clean.split("```")[1].split("```")[0].strip()
                
                print("\n📥 ОТВЕТ ОТ GPT (Stage 1):")
                print("-" * 80)
                print(content_clean[:2000])  # Show first 2000 chars
                if len(content_clean) > 2000:
                    print(f"\n... (показаны первые 2000 символов из {len(content_clean)})")
                print("-" * 80)
                
                # Try to parse and show structured
                try:
                    # Try to fix common JSON issues
                    content_fixed = content_clean
                    # Remove trailing incomplete strings
                    if content_fixed.count('"') % 2 != 0:
                        # Find last quote and try to close it
                        last_quote_idx = content_fixed.rfind('"')
                        if last_quote_idx > 0:
                            # Check if it's inside a string value
                            before_quote = content_fixed[:last_quote_idx]
                            if before_quote.count('"') % 2 != 0:
                                # It's an opening quote, try to close it
                                content_fixed = content_fixed[:last_quote_idx+1] + '"'
                    
                    data = json.loads(content_fixed)
                    
                    print("\n📊 СТРУКТУРИРОВАННЫЙ ОТВЕТ:")
                    print(f"  Основной код: {data.get('tn_ved_code', 'N/A')}")
                    
                    candidates = data.get("candidates", [])
                    print(f"  Количество кандидатов: {len(candidates)}")
                    
                    if candidates:
                        print("\n  Кандидаты:")
                        for i, candidate in enumerate(candidates, 1):
                            if isinstance(candidate, dict):
                                code = candidate.get("code", "N/A")
                                name = candidate.get("name", "N/A")
                                print(f"    {i}. Код: {code} | Описание: {name}")
                    
                    # Show all codes
                    all_codes = []
                    main_code = data.get("tn_ved_code", "").strip()
                    if main_code:
                        all_codes.append(("Основной", main_code))
                    
                    for candidate in candidates:
                        if isinstance(candidate, dict):
                            code = candidate.get("code", "").strip()
                            if code and code not in [c[1] for c in all_codes]:
                                all_codes.append(("Кандидат", code))
                    
                    print(f"\n  Всего уникальных кодов: {len(all_codes)}")
                    for code_type, code in all_codes:
                        print(f"    - {code_type}: {code}")
                        
                except json.JSONDecodeError as e:
                    print(f"\n⚠️  Не удалось распарсить JSON: {e}")
                    print("   Сырой ответ сохранен выше")
                    
    except Exception as e:
        print(f"❌ Ошибка при запросе к GPT: {e}")
        import traceback
        traceback.print_exc()
    
    # Stage 2: With description
    print("\n" + "="*80)
    print("ЭТАП 2: Запрос к GPT с базовыми полями + описание")
    print("="*80)
    
    data_with_desc = wb_parser.get_tn_ved_with_description(card_data, None)
    
    basic_info_parts_stage2 = []
    if data_with_desc.get("subj_name"):
        basic_info_parts_stage2.append(f"Тип товара: {data_with_desc['subj_name']}")
    if data_with_desc.get("subj_root_name"):
        basic_info_parts_stage2.append(f"Категория: {data_with_desc['subj_root_name']}")
    if data_with_desc.get("imt_name"):
        basic_info_parts_stage2.append(f"Название товара: {data_with_desc['imt_name']}")
    
    basic_info_stage2 = "\n".join(basic_info_parts_stage2) if basic_info_parts_stage2 else ""
    description = data_with_desc.get("description", "")
    
    prompt_stage2 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

{basic_info_stage2}

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
    
    print("\n📤 Отправка запроса в GPT...")
    try:
        response = await gpt_service._call_gpt_api(prompt_stage2)
        
        if not response:
            print("❌ GPT не вернул ответ")
        else:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                print("❌ Пустой ответ от GPT")
            else:
                # Remove markdown code blocks
                content_clean = content.strip()
                if "```json" in content_clean:
                    content_clean = content_clean.split("```json")[1].split("```")[0].strip()
                elif "```" in content_clean:
                    content_clean = content_clean.split("```")[1].split("```")[0].strip()
                
                print("\n📥 ОТВЕТ ОТ GPT (Stage 2):")
                print("-" * 80)
                print(content_clean[:2000])  # Show first 2000 chars
                if len(content_clean) > 2000:
                    print(f"\n... (показаны первые 2000 символов из {len(content_clean)})")
                print("-" * 80)
                
                # Try to parse and show structured
                try:
                    # Try to fix common JSON issues
                    content_fixed = content_clean
                    # Remove trailing incomplete strings
                    if content_fixed.count('"') % 2 != 0:
                        # Find last quote and try to close it
                        last_quote_idx = content_fixed.rfind('"')
                        if last_quote_idx > 0:
                            # Check if it's inside a string value
                            before_quote = content_fixed[:last_quote_idx]
                            if before_quote.count('"') % 2 != 0:
                                # It's an opening quote, try to close it
                                content_fixed = content_fixed[:last_quote_idx+1] + '"'
                    
                    data = json.loads(content_fixed)
                    
                    print("\n📊 СТРУКТУРИРОВАННЫЙ ОТВЕТ:")
                    print(f"  Основной код: {data.get('tn_ved_code', 'N/A')}")
                    
                    candidates = data.get("candidates", [])
                    print(f"  Количество кандидатов: {len(candidates)}")
                    
                    if candidates:
                        print("\n  Кандидаты:")
                        for i, candidate in enumerate(candidates, 1):
                            if isinstance(candidate, dict):
                                code = candidate.get("code", "N/A")
                                name = candidate.get("name", "N/A")
                                print(f"    {i}. Код: {code} | Описание: {name}")
                    
                    # Show all codes
                    all_codes = []
                    main_code = data.get("tn_ved_code", "").strip()
                    if main_code:
                        all_codes.append(("Основной", main_code))
                    
                    for candidate in candidates:
                        if isinstance(candidate, dict):
                            code = candidate.get("code", "").strip()
                            if code and code not in [c[1] for c in all_codes]:
                                all_codes.append(("Кандидат", code))
                    
                    print(f"\n  Всего уникальных кодов: {len(all_codes)}")
                    for code_type, code in all_codes:
                        print(f"    - {code_type}: {code}")
                        
                except json.JSONDecodeError as e:
                    print(f"\n⚠️  Не удалось распарсить JSON: {e}")
                    print("   Сырой ответ сохранен выше")
                    
    except Exception as e:
        print(f"❌ Ошибка при запросе к GPT: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*80)
    print("ИТОГОВАЯ ИНФОРМАЦИЯ")
    print("="*80)
    print("Показаны ответы GPT на этапах 1 и 2.")
    print("На этапе 3 отправляется полный JSON карточки (слишком большой для показа).")
    print("\nПосле получения кандидатов система:")
    print("  1. Проверяет каждый код на ifcg.ru")
    print("  2. Парсит описание категории")
    print("  3. Рассчитывает match_score через GPT")
    print("  4. Выбирает лучший кандидат")

if __name__ == "__main__":
    asyncio.run(show_responses())

