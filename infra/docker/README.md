# Docker Compose Setup

## Автоматическая инициализация сети

При деплое на сервер используйте скрипт `docker-compose-up.sh`:

```bash
cd ~/WB_LEAD_SOLO/infra/docker
chmod +x docker-compose-up.sh
./docker-compose-up.sh
```

**Всё работает автоматически!** Скрипт:
1. Запустит Redis контейнер `wb_lead_redis` (встроенный Redis)
2. Запустит PostgreSQL контейнер `wb_lead_postgres` (встроенная БД для истории запросов)
3. Запустит init-контейнер `network_init`, который создаст сеть `docker_wb_lead_network` если её нет
4. После успешной инициализации запустит `bot_service` и **5 воркеров** (worker)

**Количество воркеров:** По умолчанию запускается 5 воркеров. Можно изменить через переменную окружения:
```bash
WORKER_REPLICAS=10 ./docker-compose-up.sh
```

**Альтернатива:** Можно использовать стандартную команду `docker-compose up` (но запустится только 1 воркер):
```bash
docker-compose up -d
docker-compose up -d --scale worker=5  # Для 5 воркеров
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

## Автозапуск при перезагрузке сервера

Для автоматического запуска всех сервисов при перезагрузке создайте systemd service:

```bash
# Скопируйте service файл
sudo cp /root/WB_LEAD_SOLO/infra/docker/wb-lead-bot.service /etc/systemd/system/

# Обновите путь в файле, если он отличается
sudo nano /etc/systemd/system/wb-lead-bot.service

# Перезагрузите systemd
sudo systemctl daemon-reload

# Включите автозапуск
sudo systemctl enable wb-lead-bot.service

# Запустите сервис
sudo systemctl start wb-lead-bot.service

# Проверьте статус
sudo systemctl status wb-lead-bot.service
```

После этого все сервисы (включая 5 воркеров) будут автоматически запускаться при перезагрузке сервера.

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

# Проверить количество запущенных воркеров
docker-compose ps worker | grep -c "Up"

# Подключиться к PostgreSQL для проверки
docker-compose exec postgres psql -U app -d app
```
