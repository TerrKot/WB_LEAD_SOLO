# Установка Docker и Docker Compose на Ubuntu

## Быстрая установка

### 1. Обновление системы
```bash
sudo apt update
sudo apt upgrade -y
```

### 2. Установка зависимостей
```bash
sudo apt install -y ca-certificates curl gnupg lsb-release
```

### 3. Добавление официального GPG ключа Docker
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

### 4. Добавление репозитория Docker
```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 5. Установка Docker Engine и Docker Compose
```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 6. Проверка установки
```bash
docker --version
docker compose version
```

### 7. Добавление пользователя в группу docker (чтобы не использовать sudo)
```bash
sudo usermod -aG docker $USER
```

**Важно:** После добавления в группу нужно выйти и войти заново (или выполнить `newgrp docker`).

### 8. Проверка работы Docker
```bash
sudo systemctl start docker
sudo systemctl enable docker
docker run hello-world
```

## Альтернативный способ (через apt, если официальный репозиторий недоступен)

Если официальный репозиторий недоступен, можно использовать пакет из Ubuntu:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
```

**Примечание:** Версия Docker из Ubuntu может быть старше, но для большинства случаев подходит.

## После установки

1. Выйдите из сессии SSH и войдите заново (или выполните `newgrp docker`)
2. Перейдите в директорию проекта:
   ```bash
   cd ~/WB_LEAD_SOLO/infra/docker
   ```
3. Убедитесь, что файл `.env` настроен (скопируйте из `env.example` если нужно)
4. Запустите проект:
   ```bash
   docker compose up -d --build
   ```

## Troubleshooting

### Проблема: Permission denied при запуске docker
**Решение:** Выполните `newgrp docker` или выйдите/войдите в SSH сессию

### Проблема: Cannot connect to the Docker daemon
**Решение:** 
```bash
sudo systemctl start docker
sudo systemctl status docker
```

### Проблема: docker compose не найден
**Решение:** В новых версиях Docker Compose встроен в Docker. Используйте `docker compose` (с пробелом) вместо `docker-compose` (с дефисом)

