# Docker Compose Setup

## Автоматическая инициализация сети

При деплое на сервер просто используйте стандартную команду `docker-compose up`:

```bash
cd ~/WB_LEAD/infra/docker
docker-compose up -d
```

**Всё работает автоматически!** Docker Compose:
1. Запустит init-контейнер `network_init`, который:
   - Создаст сеть `docker_wb_lead_network` если её нет
   - Подключит `docker-redis-1` к сети
   - Подключит `docker-postgres-1` к сети
2. После успешной инициализации запустит `bot_service` и `worker`

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
docker-compose logs -f network_init
```

## Требования

- Docker и Docker Compose установлены
- Контейнеры `docker-redis-1` и `docker-postgres-1` должны быть запущены
- Файл `.env` должен быть настроен с правильными значениями `REDIS_URL` и `DATABASE_URL`

## Переменные окружения

Убедитесь, что в `.env` указаны:
- `REDIS_URL=redis://docker-redis-1:6379/0`
- `DATABASE_URL=postgresql+asyncpg://app:app@docker-postgres-1:5432/app`

## Как это работает

1. При запуске `docker-compose up` сначала запускается контейнер `network_init`
2. Этот контейнер имеет доступ к Docker socket и может управлять сетями
3. Он создаёт сеть и подключает внешние контейнеры Redis и PostgreSQL
4. После успешного завершения `network_init` запускаются основные сервисы
5. Все сервисы автоматически подключаются к нужной сети

## Troubleshooting

Если возникают проблемы с подключением:

```bash
# Проверить статус init контейнера
docker-compose logs network_init

# Проверить подключение Redis и PostgreSQL к сети
docker network inspect docker_wb_lead_network

# Вручную запустить инициализацию сети
./init-network.sh
```
