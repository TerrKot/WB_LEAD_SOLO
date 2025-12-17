# ⚡ Quick Start: Telegram-бот экспресс-оценки и расчёта белой логистики vs карго (WB)

## 🎯 5 шагов до работающего бота

### 1. Подготовка окружения
```powershell
cd C:\Projects\WB_lead
copy .env.example .env  # заполнить токены
```
Обязательно установи в `.env`: `BOT_TOKEN`, `GPT_API_KEY`, `GPT_API_URL`, `GPT_MODEL`, `REDIS_URL`, `EXCHANGE_RATE_USD_RUB`, `EXCHANGE_RATE_USD_CNY`, `EXCHANGE_RATE_EUR_RUB`.

**Примечание:** `DATABASE_URL` опционально (для истории расчётов). Если не указан, система работает только с Redis.

### 2. Запуск Docker Compose (включает Redis и опционально PostgreSQL)
```powershell
# Запуск redis, postgres (опционально), bot_service, worker
docker compose up -d

# Проверка, что контейнеры запущены
docker compose ps
```

**Примечание:** Redis обязателен для работы системы. PostgreSQL опционален (для истории расчётов).

### 3. Инициализация БД (опционально)
```powershell
# Запуск скрипта инициализации БД (только если используешь PostgreSQL)
docker compose exec bot_service python scripts/init_db.py
```

### 4. Smoke-тест
```powershell
# Проверка health endpoint
curl http://localhost:8443/healthz
# → {"status":"ok","redis":true,"database":true}

# Проверка подключения к Redis
docker compose exec bot_service python -c "import redis; r = redis.Redis.from_url('redis://redis:6379/0'); print(r.ping())"
# → True
```

Затем проверь работу бота:
```powershell
# В Telegram отправь боту команду
/start
# → должен показать пользовательское соглашение

# После подтверждения отправь артикул или ссылку WB
154345562
# или
https://www.wildberries.ru/catalog/154345562/detail.aspx
# → должен начать экспресс-расчёт
```

### 5. Проверка очередей
```powershell
# Проверка очереди расчётов в Redis
docker compose exec redis redis-cli LLEN calculation_queue
# → количество задач в очереди

# Проверка статусов расчётов
docker compose exec redis redis-cli KEYS "calculation:*:status"
# → список всех расчётов
```

### 6. Логи и остановка
```powershell
# Смотреть логи
docker compose logs -f bot_service
docker compose logs -f worker

# Остановить
docker compose down
```

---

## 🧪 Полезные команды

### Тесты
```powershell
# Все тесты (179 тестов)
pytest tests/ -v

# Unit тесты
pytest tests\unit -q

# Integration тесты
pytest tests\integration -q

# End-to-end тесты экспресс-расчёта
pytest tests\integration\test_express_calculation_e2e.py -v

# End-to-end тесты подробного расчёта
pytest tests\integration\test_detailed_calculation_e2e.py -v
```

### Линтинг
```powershell
ruff check apps scripts tests
black --check apps scripts tests
```

### Redis (через redis-cli)
```redis
# Проверка очереди
LLEN calculation_queue

# Просмотр задач в очереди
LRANGE calculation_queue 0 10

# Проверка статуса расчёта
GET calculation:123e4567-e89b-12d3-a456-426614174000:status

# Проверка результата расчёта
GET calculation:123e4567-e89b-12d3-a456-426614174000:result
```

### База данных (через psql, опционально)
```sql
-- Проверка истории расчётов
SELECT calculation_id, user_id, article_id, status, created_at
FROM calculations
ORDER BY created_at DESC
LIMIT 10;

-- Проверка кэша товаров WB
SELECT article_id, updated_at
FROM wb_products_cache
ORDER BY updated_at DESC
LIMIT 10;
```

---

## 📂 Напоминание о структуре
```
apps/bot_service/        # бот + сервисы
apps/bot_service/workers/ # воркеры для обработки очередей
scripts/                 # wb_parser.py, init_db.py
infra/docker/            # Dockerfile + compose
```

---

## ✅ Мини-checklist перед коммитом
- [ ] `.env` заполнен, но не закоммичен
- [ ] Docker Compose запущен, Redis работает
- [ ] Бот отвечает на `/start`
- [ ] Экспресс-расчёт работает (парсинг WB, подбор ТН ВЭД, проверка красной зоны)
- [ ] Подробный расчёт работает (карго и белая логистика)
- [ ] `pytest`, `ruff`, `black` — зелёные
- [ ] `ROADMAP.md` и документация обновлены

Если что-то не работает — смотри `IMPLEMENTATION_GUIDE.md` (секция Troubleshooting) или логи бота/воркера.
