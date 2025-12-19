import json
import re

# Читаем файл напрямую
with open('docs/example', 'r', encoding='utf-8') as f:
    content = f.read()

# Разделяем на части
parts = content.split('\n', 2)
url = parts[0]
empty = parts[1] if len(parts) > 1 else ''
json_str = parts[2] if len(parts) > 2 else ''

# Убираем все невидимые символы и пробелы в начале/конце
json_str = json_str.strip()

# Парсим JSON
obj = json.loads(json_str)
formatted = json.dumps(obj, ensure_ascii=False, indent=2)

result = url + "\n" + empty + "\n" + formatted

obj = json.loads(json_str)
formatted = json.dumps(obj, ensure_ascii=False, indent=2)

url = "https://basket-33.wbbasket.ru/vol6896/part689623/689623448/info/ru/card.json"
empty = ""

result = url + "\n" + empty + "\n" + formatted

with open('docs/example', 'w', encoding='utf-8') as f:
    f.write(result)

print("Файл отформатирован успешно!")

