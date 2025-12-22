# Проверка сохранения данных в БД

## Как проверить, что данные сохраняются

### 1. Через скрипт проверки

```bash
# Проверить все данные
python scripts/check_database.py

# Проверить конкретного пользователя
python scripts/check_database.py 123456789
```

Скрипт покажет:
- Количество пользователей
- Количество пользователей с принятым соглашением
- Последние 5 пользователей
- Количество расчетов по типам и статусам
- Последние 5 расчетов
- Детальную информацию о пользователе (если указан user_id)

### 2. Через SQL запросы

Подключитесь к PostgreSQL:

```bash
# Локально (Docker)
docker exec -it <postgres_container> psql -U app -d app

# Или напрямую
psql -U app -d app -h localhost -p 5432
```

#### Проверка пользователей:

```sql
-- Всего пользователей
SELECT COUNT(*) FROM users;

-- Пользователи с принятым соглашением
SELECT COUNT(*) FROM users WHERE agreement_accepted IS NOT NULL;

-- Последние 10 пользователей
SELECT user_id, username, first_name, last_name, 
       agreement_accepted, created_at 
FROM users 
ORDER BY created_at DESC 
LIMIT 10;

-- Конкретный пользователь
SELECT * FROM users WHERE user_id = 123456789;
```

#### Проверка расчетов:

```sql
-- Всего расчетов
SELECT COUNT(*) FROM calculations;

-- По типам
SELECT calculation_type, COUNT(*) 
FROM calculations 
GROUP BY calculation_type;

-- По статусам
SELECT status, COUNT(*) 
FROM calculations 
GROUP BY status;

-- Последние 10 расчетов
SELECT calculation_id, user_id, article_id, 
       calculation_type, status, tn_ved_code, created_at 
FROM calculations 
ORDER BY created_at DESC 
LIMIT 10;

-- Расчеты с ТН ВЭД
SELECT calculation_id, article_id, tn_ved_code, status 
FROM calculations 
WHERE tn_ved_code IS NOT NULL 
ORDER BY created_at DESC 
LIMIT 10;

-- Расчеты конкретного пользователя
SELECT * FROM calculations 
WHERE user_id = 123456789 
ORDER BY created_at DESC;
```

#### Проверка результатов расчетов:

```sql
-- Расчеты с экспресс-результатами
SELECT calculation_id, article_id, status, 
       express_result->>'status' as express_status,
       express_result->>'tn_ved_code' as tn_ved
FROM calculations 
WHERE express_result IS NOT NULL 
ORDER BY created_at DESC 
LIMIT 10;

-- Расчеты с подробными результатами
SELECT calculation_id, article_id, 
       detailed_result->>'calculation_type' as calc_type,
       detailed_result->'detailed_result'->>'quantity' as quantity
FROM calculations 
WHERE detailed_result IS NOT NULL 
ORDER BY created_at DESC 
LIMIT 10;
```

### 3. Через логи

Проверьте логи на наличие сообщений:
- `user_saved` - пользователь сохранен
- `calculation_saved` - расчет сохранен
- `user_agreement_save_failed` - ошибка сохранения согласия
- `calculation_db_save_failed` - ошибка сохранения расчета

```bash
# В логах ищите:
grep "user_saved" logs/app.log
grep "calculation_saved" logs/app.log
grep "db_save_failed" logs/app.log
```

### 4. Что сохраняется

#### Пользователи (таблица `users`):
- ✅ `user_id` - ID пользователя Telegram
- ✅ `username` - Username пользователя
- ✅ `first_name` - Имя
- ✅ `last_name` - Фамилия
- ✅ `language_code` - Код языка
- ✅ `agreement_accepted` - **Дата и время принятия соглашения** (новое поле)
- ✅ `created_at` - Дата создания записи
- ✅ `updated_at` - Дата последнего обновления

#### Расчеты (таблица `calculations`):
- ✅ `calculation_id` - UUID расчета
- ✅ `user_id` - ID пользователя
- ✅ `article_id` - Артикул товара WB
- ✅ `calculation_type` - Тип расчета (express/detailed)
- ✅ `tn_ved_code` - Подобранный код ТН ВЭД
- ✅ `express_result` - JSON с результатами экспресс-анализа
- ✅ `detailed_result` - JSON с результатами подробного анализа
- ✅ `status` - Статус расчета (🟢/🟡/🟠/🔴/completed/failed и т.д.)
- ✅ `created_at` - Дата создания

### 5. Проверка в реальном времени

1. Запустите бота
2. Выполните `/start` и примите соглашение
3. Выполните расчет
4. Запустите скрипт проверки:
   ```bash
   python scripts/check_database.py
   ```
5. Проверьте, что появились новые записи

### 6. Устранение проблем

Если данные не сохраняются:

1. **Проверьте подключение к БД:**
   ```bash
   # Проверьте health endpoint
   curl http://localhost:8443/healthz
   ```

2. **Проверьте логи на ошибки:**
   ```bash
   grep "database_connection_failed" logs/app.log
   grep "user_save_failed" logs/app.log
   grep "calculation_save_failed" logs/app.log
   ```

3. **Проверьте переменные окружения:**
   ```bash
   echo $DATABASE_URL
   ```

4. **Проверьте, что таблицы созданы:**
   ```sql
   \dt  -- Список таблиц
   \d users  -- Структура таблицы users
   \d calculations  -- Структура таблицы calculations
   ```




