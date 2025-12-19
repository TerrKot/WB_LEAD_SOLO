import json
import sys

try:
    with open('docs/example', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Разделяем на части
    parts = content.split('\n', 2)
    url = parts[0]
    empty = parts[1] if len(parts) > 1 else ''
    json_str = parts[2] if len(parts) > 2 else ''
    
    # Пробуем распарсить JSON
    json_obj = json.loads(json_str.strip())
    
    # Форматируем
    formatted = json.dumps(json_obj, ensure_ascii=False, indent=2)
    
    # Собираем результат
    result = url + '\n' + empty + '\n' + formatted
    
    # Записываем
    with open('docs/example', 'w', encoding='utf-8') as f:
        f.write(result)
    
    print("Файл успешно отформатирован")
    
except json.JSONDecodeError as e:
    print(f"Ошибка парсинга JSON: {e}")
    print(f"Позиция ошибки: {e.pos}")
    print(f"Контекст: {json_str[max(0, e.pos-50):e.pos+50]}")
    sys.exit(1)
except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
