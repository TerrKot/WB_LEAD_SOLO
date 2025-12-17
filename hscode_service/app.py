from __future__ import annotations

import importlib
from typing import Any, Dict
import logging

from fastapi import FastAPI, HTTPException
from libs.core.models import HSQuery, HSResult
from libs.core.config import settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="HSCode Service")


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


def _apply_req_map(data: Dict[str, Any]) -> Dict[str, Any]:
    m = settings.hscore_code_req_map
    return {m.get(k, k): v for k, v in data.items() if v is not None}


def _extract_res_map(raw: Dict[str, Any]) -> HSResult:
    m = settings.hscore_code_res_map
    raw_code = raw.get(m.get("code", "code"))
    code = str(raw_code) if raw_code not in (None, "None") else ""
    raw_rationale = raw.get(m.get("rationale", "rationale"))
    rationale = str(raw_rationale) if raw_rationale not in (None, "None") else ""
    tree_val = raw.get(m.get("tree", "tree"))
    tree_path = []
    if isinstance(tree_val, list):
        tree_path = [str(x) for x in tree_val]
    elif isinstance(tree_val, str) and tree_val:
        tree_path = [tree_val]
    return HSResult(code=code or "", rationale=rationale, tree_path=tree_path)


async def _call_http(payload: Dict[str, Any]) -> Dict[str, Any]:
    import httpx

    url = f"{settings.hscore_base_url}{settings.hscore_endpoint_code}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


async def _call_lib(payload: Dict[str, Any]) -> Dict[str, Any]:
    module_name, func_name = settings.hscore_lib_import.split(":", 1)
    mod = importlib.import_module(module_name)
    func = getattr(mod, func_name)
    return await func(payload)


async def _call_cli(payload: Dict[str, Any]) -> Dict[str, Any]:
    import subprocess, json

    cmd = settings.hscore_cli_code.split()
    result = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
    result.check_returncode()
    return json.loads(result.stdout)


async def _call_core(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = settings.hscore_mode
    if mode == "http":
        return await _call_http(payload)
    if mode == "lib":
        return await _call_lib(payload)
    if mode == "cli":
        return await _call_cli(payload)
    raise ValueError(f"Unknown HSCORE_MODE: {mode}")


@app.post("/hscode/need_more")
async def need_more(query: HSQuery) -> Dict[str, Any]:
    # если нет ключа — считаем, что данных хватает (избежать внешних вызовов в тестах)
    if not settings.openai_api_key:
        return {"missing": [], "questions": []}

    # прямой вызов lib для sufficiency - используем промпт из core/
    from core.ai_api import check_description_sufficiency

    try:
        # Формируем контекст из истории диалога, если она есть в description
        # Description уже содержит контекст диалога от orchestrator
        # Проверяем, есть ли в description блок "Контекст диалога:"
        context = None
        if "Контекст диалога:" in query.description:
            # Извлекаем контекст из description и формируем список сообщений
            parts = query.description.split("Контекст диалога:", 1)
            main_description = parts[0].strip()
            context_text = parts[1].strip() if len(parts) > 1 else ""
            
            # Парсим контекст в формат messages
            # Поддерживаем два формата:
            # 1. "Вопрос: ..." / "Ответ: ..." (из chat_handler.py)
            # 2. "Пользователь: ..." / "Бот: ..." (старый формат)
            # 3. "Описание товара: ..." (первое сообщение)
            context = []
            current_question = None
            for line in context_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Описание товара:"):
                    text = line.replace("Описание товара:", "").strip()
                    if text:
                        context.append({"role": "user", "content": text})
                elif line.startswith("Вопрос:"):
                    current_question = line.replace("Вопрос:", "").strip()
                    if current_question:
                        context.append({"role": "assistant", "content": current_question})
                elif line.startswith("Ответ:"):
                    text = line.replace("Ответ:", "").strip()
                    if text and current_question:
                        context.append({"role": "user", "content": text})
                        current_question = None
                    elif text:
                        # Ответ без вопроса - добавляем как user сообщение
                        context.append({"role": "user", "content": text})
                elif line.startswith("Пользователь:"):
                    text = line.replace("Пользователь:", "").strip()
                    if text:
                        context.append({"role": "user", "content": text})
                elif line.startswith("Бот:"):
                    text = line.replace("Бот:", "").strip()
                    if text:
                        context.append({"role": "assistant", "content": text})
            
            # Используем основную часть без контекста, контекст передадим отдельно
            description_for_check = main_description
        else:
            description_for_check = query.description
        
        # Вызываем с контекстом диалога
        ok_or_questions = await check_description_sufficiency(description_for_check, context=context)
        
        # НЕ фильтруем ответы LLM - доверяем промпту полностью
        if isinstance(ok_or_questions, tuple):
            ok, detail = ok_or_questions
            if ok:
                return {"missing": [], "questions": []}
            # LLM решил, что нужен вопрос - возвращаем его
            if detail:
                return {"missing": ["details"], "questions": [detail]}
        
        # Если не кортеж - считаем информацию достаточной (fallback только для ошибок)
        logger.warning(f"check_description_sufficiency returned non-tuple: {ok_or_questions}, treating as sufficient")
        return {"missing": [], "questions": []}
    except Exception as e:
        # Любая ошибка LLM — не блокируем пайплайн, считаем информацию достаточной
        logger.warning(f"need_more: LLM failed: {e}")
        return {"missing": [], "questions": []}


@app.post("/hscode/guess", response_model=HSResult)
async def guess(query: HSQuery) -> HSResult:
    """Подбор кода через ядро core/: get_keywords → parse_ifcg → analyze_parsed_results2 → extract_hs_code.
    При ошибке — fallback на _call_core (HTTP/CLI), если включено.
    """
    # Основной путь: прямой вызов core/ (как в ai_api.py)
    try:
        from core.ai_api import get_keywords, analyze_parsed_results2, extract_hs_code, reformulate_keywords
        from core.parser2 import parse_ifcg

        description = query.description.strip()
        logger.info(f"guess: start description='{description[:200]}'")
        
        # Формируем контекст из истории диалога, если она есть в description
        history = None
        main_description = description
        if "Контекст диалога:" in description:
            parts = description.split("Контекст диалога:", 1)
            main_description = parts[0].strip()
            context_text = parts[1].strip() if len(parts) > 1 else ""
            
            # Парсим контекст в формат messages для истории
            # Поддерживаем два формата:
            # 1. "Вопрос: ..." / "Ответ: ..." (из chat_handler.py)
            # 2. "Пользователь: ..." / "Бот: ..." (старый формат)
            # 3. "Описание товара: ..." (первое сообщение)
            history = []
            current_question = None
            for line in context_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Описание товара:"):
                    text = line.replace("Описание товара:", "").strip()
                    if text:
                        history.append({"role": "user", "text": text})
                elif line.startswith("Вопрос:"):
                    current_question = line.replace("Вопрос:", "").strip()
                    if current_question:
                        history.append({"role": "assistant", "text": current_question})
                elif line.startswith("Ответ:"):
                    text = line.replace("Ответ:", "").strip()
                    if text and current_question:
                        history.append({"role": "user", "text": text})
                        current_question = None
                    elif text:
                        # Ответ без вопроса - добавляем как user сообщение
                        history.append({"role": "user", "text": text})
                elif line.startswith("Пользователь:"):
                    text = line.replace("Пользователь:", "").strip()
                    if text:
                        history.append({"role": "user", "text": text})
                elif line.startswith("Бот:"):
                    text = line.replace("Бот:", "").strip()
                    if text:
                        history.append({"role": "assistant", "text": text})
        
        # 1) Ключевые слова с учётом истории
        kw = await get_keywords(main_description, history=history)
        logger.info(f"guess: keywords='{kw}'")
        if not isinstance(kw, str) or not kw:
            kw = main_description
        
        # 2) Кандидаты кодов с ifcg
        candidates = None
        try:
            candidates = await parse_ifcg(kw)
            logger.info(f"guess: candidates_count={len(candidates) if isinstance(candidates, list) else 'n/a'}")
        except Exception as e:
            logger.error(f"parse_ifcg failed for keywords '{kw}': {e}", exc_info=True)
            # При ошибке parse_ifcg (например, 503 от ifcg.ru) - пробуем переформулировать ключевые слова
            try:
                logger.warning(f"Trying reformulate_keywords after parse_ifcg error")
                reformulated_kw = await reformulate_keywords(kw, main_description)
                if reformulated_kw and reformulated_kw != kw:
                    logger.info(f"guess: reformulated keywords from '{kw}' to '{reformulated_kw}'")
                    candidates = await parse_ifcg(reformulated_kw)
                    logger.info(f"guess: after reformulation candidates_count={len(candidates) if isinstance(candidates, list) else 'n/a'}")
            except Exception as e2:
                logger.error(f"parse_ifcg failed even after reformulation: {e2}", exc_info=True)
                # Если и после переформулирования ошибка - возвращаем понятное сообщение
                return {
                    "code": "",
                    "tree_path": [],
                    "rationale": f"Временная недоступность сервиса поиска кодов ТН ВЭД. Попробуйте позже или уточните описание товара."
                }
        
        # 3) Если кандидатов нет - пробуем переформулировать ключевые слова
        if not candidates or len(candidates) == 0:
            logger.warning(f"parse_ifcg returned empty candidates for keywords '{kw}'. Trying reformulate_keywords.")
            try:
                reformulated_kw = await reformulate_keywords(kw, main_description)
                if reformulated_kw and reformulated_kw != kw:
                    logger.info(f"guess: reformulated keywords from '{kw}' to '{reformulated_kw}'")
                    candidates = await parse_ifcg(reformulated_kw)
                    logger.info(f"guess: after reformulation candidates_count={len(candidates) if isinstance(candidates, list) else 'n/a'}")
            except Exception as e:
                logger.error(f"parse_ifcg failed during reformulation: {e}", exc_info=True)
                # При ошибке возвращаем понятное сообщение
                return {
                    "code": "",
                    "tree_path": [],
                    "rationale": f"Временная недоступность сервиса поиска кодов ТН ВЭД. Попробуйте позже или уточните описание товара."
                }
            
            # Если после переформулирования всё ещё нет кандидатов - возвращаем пустой код
            if not candidates or len(candidates) == 0:
                logger.warning(f"parse_ifcg returned empty candidates even after reformulation. Returning empty code.")
                return {
                    "code": "",
                    "tree_path": [],
                    "rationale": f"Не удалось найти коды ТН ВЭД для запроса. Необходимо уточнить описание товара."
                }
        
        # 4) Анализ кандидатов LLM'ом
        analysis = await analyze_parsed_results2(main_description, candidates)
        logger.info(f"guess: analysis_len={len(analysis) if isinstance(analysis, str) else 'n/a'}")
        code = extract_hs_code(analysis) or ""
        logger.info(f"guess: extracted_code='{code}'")
        
        # ВАЛИДАЦИЯ: проверяем, что код есть в списке кандидатов
        if code:
            candidate_codes = [item.get('code', '') for item in candidates if isinstance(item, dict)]
            # Нормализуем коды: убираем пробелы, приводим к строке
            candidate_codes_clean = [str(c).replace(' ', '').strip() for c in candidate_codes if c]
            code_clean = code.replace(' ', '').strip()
            
            if code_clean not in candidate_codes_clean:
                logger.warning(f"Extracted code '{code}' not found in candidates list. Candidate codes: {candidate_codes_clean[:5]}")
                # Если код не найден в кандидатах - возвращаем ошибку
                return {
                    "code": "",
                    "tree_path": [],
                    "rationale": f"Не удалось подтвердить код ТН ВЭД '{code}' из предоставленного списка. Попробуйте уточнить описание товара."
                }
        # 5) Rationale берём из вывода модели (усекаем)
        rationale = str(analysis)[:1000]
        # Валидация уровня: субпозиция (>=6 знаков) и товарная позиция (10 знаков)
        desc_low = main_description.lower()
        if not code or not code.isdigit() or len(code) < 6:
            rationale = (
                "Код на уровне группы/позиции; требуется уточнение до субпозиции (>=6 знаков).\n"
                + rationale
            )
        # Эвристики отключены: выбираем код только через связку get_keywords → parse_ifcg → analyze_parsed_results2
        # 5) Пытаемся получить текстовое дерево с кодами и названиями (только с alta.ru)
        tree_path: list[str] = []
        try:
            from core.parser2 import parse_tnved_tree as _parse_tree
            import re as _re
            import html as _html

            # Парсим дерево только с alta.ru
            try:
                text = _html.unescape(str(await _parse_tree(code)))
                # Проверяем, что не получили сообщение об ошибке
                if text.startswith("⚠️") or "Не удалось" in text:
                    logger.warning(f"parse_tnved_tree returned error message: {text}")
                    raise ValueError(f"Failed to parse tree: {text}")
                
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                seen_codes = set()
                for ln in lines:
                    m = _re.search(r"\*?([0-9]{2,10})\*?\s*[—\-]\s+(.*)$", ln)
                    if m:
                        c, name = m.group(1).strip(), m.group(2).strip()
                        if c and name and c not in seen_codes:
                            seen_codes.add(c)
                            tree_path.append(f"{c} — {name}")
                
                # Сортируем дерево по длине кода (2, 4, 6, 8, 10 цифр) для правильного порядка
                if tree_path:
                    def get_code_length(item: str) -> int:
                        """Извлекает длину кода из элемента дерева"""
                        code_part = item.split(" — ")[0] if " — " in item else item
                        return len(code_part)
                    
                    tree_path.sort(key=get_code_length)
            except Exception as e:
                logger.warning(f"Failed to parse tree from alta.ru for code {code}: {e}")
                pass

            logger.info(f"guess: tree_path_levels={len(tree_path)}")
            # Последний резерв — чистые префиксы (если не удалось получить дерево с alta.ru)
            if not tree_path and len(code) == 10 and code.isdigit():
                tree_path = [code[:2], code[:4], code[:6], code[:8], code[:10]]
        except Exception as e:
            logger.warning(f"Failed to get tree for code {code}: {e}")
            if len(code) == 10 and code.isdigit():
                tree_path = [code[:2], code[:4], code[:6], code[:8], code[:10]]
        logger.info(f"guess: done code='{code}', tree_ok={bool(tree_path)}")
        return HSResult(code=code, rationale=rationale, tree_path=tree_path)
    except Exception as e:
        logger.exception(f"guess: main path failed: {e}")
        # Fallback: использовать настроенный адаптер (http/lib/cli), если доступен
        try:
            payload = _apply_req_map(query.model_dump())
            raw = await _call_core(payload)
            logger.warning("guess: fallback adapter path used")
            return _extract_res_map(raw)
        except Exception as e2:
            logger.exception(f"guess: fallback also failed: {e2}")
            # При ошибке fallback возвращаем понятное сообщение пользователю
            return HSResult(
                code="",
                rationale="Временная недоступность сервиса подбора кодов ТН ВЭД. Попробуйте позже или уточните описание товара.",
                tree_path=[]
            )

 

