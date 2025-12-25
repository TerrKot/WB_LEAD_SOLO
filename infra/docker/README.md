# Docker Compose Setup

## Автоматическая инициализация сети

При деплое на сервер просто используйте стандартную команду `docker-compose up`:

```bash
cd ~/WB_LEAD/infra/docker
docker-compose up -d
```

**Всё работает автоматически!** Docker Compose:
1. Запустит Redis контейнер `wb_lead_redis` (встроенный Redis)
2. Запустит PostgreSQL контейнер `wb_lead_postgres` (встроенная БД для истории запросов)
3. Запустит init-контейнер `network_init`, который создаст сеть `docker_wb_lead_network` если её нет
4. После успешной инициализации запустит `bot_service` и `worker`

**Альтернатива:** Можно использовать скрипт `docker-compose-up.sh` для дополнительной диагностики:

```bash
./docker-compose-up.sh
```

## Обычные команды

```bash
# Запуск
docker-compose up -d

# Перезапуск с пересборкой
docker-compose up -d --build

# Пересоздание контейнеров
docker-compose up -d --force-recreate

# Остановка
docker-compose down

# Просмотр логов
docker-compose logs -f worker
docker-compose logs -f bot_service
docker-compose logs -f redis
docker-compose logs -f postgres
docker-compose logs -f network_init
```

## Требования

- Docker и Docker Compose установлены
- Файл `.env` должен быть настроен с правильными значениями `REDIS_URL` и `DATABASE_URL`
- **Redis и PostgreSQL теперь встроены** и запускаются автоматически в составе docker-compose

## Переменные окружения

Убедитесь, что в `.env` указаны:
- `REDIS_URL=redis://redis:6379/0` (встроенный Redis, имя сервиса `redis`)
- `DATABASE_URL=postgresql+asyncpg://app:app@postgres:5432/app` (встроенный PostgreSQL, имя сервиса `postgres`)

## Как это работает

1. При запуске `docker-compose up` сначала запускаются инфраструктурные сервисы:
   - Redis контейнер (`wb_lead_redis`) для очередей и временных данных
   - PostgreSQL контейнер (`wb_lead_postgres`) для хранения истории запросов
2. Затем запускается контейнер `network_init`, который создаёт сеть `docker_wb_lead_network` если её нет
3. После успешной инициализации Redis и PostgreSQL запускаются основные сервисы (`bot_service` и `worker`)
4. Все сервисы автоматически подключаются к нужной сети и используют встроенные Redis и PostgreSQL
5. Таблицы БД создаются автоматически при первом подключении через SQLAlchemy

## Troubleshooting

Если возникают проблемы с подключением:

```bash
# Проверить статус init контейнера
docker-compose logs network_init

# Проверить подключение сервисов к сети
docker network inspect docker_wb_lead_network

# Проверить статус сервисов
docker-compose ps
docker-compose logs redis
docker-compose logs postgres

# Подключиться к PostgreSQL для проверки
docker-compose exec postgres psql -U app -d app
```
