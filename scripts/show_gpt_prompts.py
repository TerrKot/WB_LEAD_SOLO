"""Show GPT prompts for TN VED code selection."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService
from apps.bot_service.services.gpt_service import GPTService

async def show_prompts():
    article_id = 689623448
    
    print("="*80)
    print(f"ПОКАЗ ПРОМПТОВ ДЛЯ АРТИКУЛА: {article_id}")
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
    
    # Extract basic data for stage 1
    print("\n" + "="*80)
    print("ЭТАП 1: Базовые поля (subj_name, subj_root_name, imt_name)")
    print("="*80)
    
    basic_data = wb_parser.get_tn_ved_basic_data(card_data, None)
    
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
    
    print("\n📤 ПРОМПТ ДЛЯ GPT (Stage 1):")
    print("-" * 80)
    print(prompt_stage1)
    print("-" * 80)
    
    # Stage 2: With description
    print("\n" + "="*80)
    print("ЭТАП 2: Базовые поля + описание товара")
    print("="*80)
    
    data_with_desc = wb_parser.get_tn_ved_with_description(card_data, None)
    
    basic_info_parts_stage2 = []
    if data_with_desc.get("subj_name"):
        basic_info_parts_stage2.append(f"Тип товара: {data_with_desc['subj_name']}")
    if data_with_desc.get("subj_root_name"):
        basic_info_parts_stage2.append(f"Категория: {data_with_desc['subj_root_name']}")
    if data_with_desc.get("type_name"):
        basic_info_parts_stage2.append(f"Тип: {data_with_desc['type_name']}")
    if data_with_desc.get("category_name"):
        basic_info_parts_stage2.append(f"Категория: {data_with_desc['category_name']}")
    if data_with_desc.get("imt_name"):
        basic_info_parts_stage2.append(f"Название товара: {data_with_desc['imt_name']}")
    
    basic_info_stage2 = "\n".join(basic_info_parts_stage2) if basic_info_parts_stage2 else ""
    description = data_with_desc.get("description", "")
    
    # Limit description length for display
    description_preview = description[:500] + "..." if len(description) > 500 else description
    
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
    
    print("\n📤 ПРОМПТ ДЛЯ GPT (Stage 2):")
    print("-" * 80)
    print(prompt_stage2)
    print("-" * 80)
    print(f"\n📝 Длина описания: {len(description)} символов")
    if len(description) > 500:
        print(f"   (Показаны первые 500 символов)")
    
    # Stage 3: Full card data
    print("\n" + "="*80)
    print("ЭТАП 3: Полные данные карточки товара (JSON)")
    print("="*80)
    
    full_data = wb_parser.get_tn_ved_full_data(card_data)
    
    import json
    try:
        card_json_str = json.dumps(full_data, ensure_ascii=False, indent=2)
        if len(card_json_str) > 50000:
            essential_fields = ['imt_name', 'subj_name', 'subj_root_name', 'description', 'options']
            limited_data = {k: full_data.get(k) for k in essential_fields if k in full_data}
            card_json_str = json.dumps(limited_data, ensure_ascii=False, indent=2)
            print("⚠️  JSON был обрезан до основных полей (размер > 50KB)")
        
        prompt_stage3 = f"""Подбери код ТН ВЭД для товара используя только данные с сайта ifcg.ru.

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
        
        print("\n📤 ПРОМПТ ДЛЯ GPT (Stage 3):")
        print("-" * 80)
        print(prompt_stage3[:2000])  # Show first 2000 chars
        if len(prompt_stage3) > 2000:
            print(f"\n... (показаны первые 2000 символов из {len(prompt_stage3)})")
        print("-" * 80)
        print(f"\n📊 Размер JSON данных: {len(card_json_str)} символов")
        print(f"📊 Размер полного промпта: {len(prompt_stage3)} символов")
        
    except Exception as e:
        print(f"❌ Ошибка при сериализации JSON: {e}")
    
    # Show match score calculation prompt
    print("\n" + "="*80)
    print("ВАЛИДАЦИЯ КАНДИДАТОВ: Промпт для расчета match_score")
    print("="*80)
    
    match_score_prompt_example = f"""Оцени, насколько описание категории ТН ВЭД соответствует товару.

Описание категории ТН ВЭД: [описание с ifcg.ru]

Товар:
- Название: {basic_data.get('imt_name', 'Товар')}
- Категория: {basic_data.get('subj_name', '')}

Оцени соответствие от 0.0 до 1.0, где:
- 1.0 = идеальное соответствие
- 0.8-0.9 = очень хорошее соответствие
- 0.6-0.7 = хорошее соответствие
- 0.4-0.5 = частичное соответствие
- 0.0-0.3 = несоответствие

Верни только число (float) от 0.0 до 1.0, без дополнительного текста."""
    
    print("\n📤 ПРОМПТ ДЛЯ GPT (Match Score):")
    print("-" * 80)
    print(match_score_prompt_example)
    print("-" * 80)
    
    print("\n" + "="*80)
    print("ИТОГОВАЯ ИНФОРМАЦИЯ")
    print("="*80)
    print(f"Артикул: {article_id}")
    print(f"Название товара: {basic_data.get('imt_name', 'N/A')}")
    print(f"Тип товара: {basic_data.get('subj_name', 'N/A')}")
    print(f"Категория: {basic_data.get('subj_root_name', 'N/A')}")
    print(f"Длина описания: {len(description)} символов")
    print(f"\nЭтапы валидации:")
    print("  1. Stage 1: Базовые поля → запрос 5-7 кандидатов")
    print("  2. Для каждого кандидата:")
    print("     - Проверка существования на ifcg.ru")
    print("     - Парсинг описания категории")
    print("     - Расчет match_score через GPT")
    print("     - Парсинг пошлин")
    print("  3. Выбор лучшего кандидата по комбинации критериев")
    print("  4. Если Stage 1 не дал результата → Stage 2 (с описанием)")
    print("  5. Если Stage 2 не дал результата → Stage 3 (полный JSON)")

if __name__ == "__main__":
    asyncio.run(show_prompts())


