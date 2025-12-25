#!/bin/bash
# Health check script for monitoring services and auto-restarting failed containers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MAX_RETRIES=3
RETRY_DELAY=5

check_service_health() {
    local service=$1
    local container_name=$2
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo "❌ Container ${container_name} is not running"
        return 1
    fi
    
    # Check container health status
    local health_status=$(docker inspect --format='{{.State.Health.Status}}' "${container_name}" 2>/dev/null)
    
    if [ "$health_status" = "unhealthy" ]; then
        echo "❌ Container ${container_name} is unhealthy"
        return 1
    fi
    
    echo "✅ Container ${container_name} is healthy"
    return 0
}

restart_service() {
    local service=$1
    echo "🔄 Restarting service: ${service}"
    docker compose restart "${service}" || docker compose up -d "${service}"
    sleep "${RETRY_DELAY}"
}

check_and_restart_workers() {
    local expected_workers=5
    local running_workers=$(docker compose ps worker --format json 2>/dev/null | grep -c '"State":"running"' || echo "0")
    
    if [ "$running_workers" -lt "$expected_workers" ]; then
        echo "⚠️  Only ${running_workers} workers running, expected ${expected_workers}"
        echo "🔄 Scaling workers to ${expected_workers}..."
        docker compose up -d --scale worker=${expected_workers} worker
        return 1
    fi
    
    echo "✅ All ${expected_workers} workers are running"
    return 0
}

# Check bot_service
if ! check_service_health "bot_service" "wb_lead_bot_service"; then
    restart_service "bot_service"
fi

# Check Redis
if ! check_service_health "redis" "wb_lead_redis"; then
    restart_service "redis"
fi

# Check PostgreSQL
if ! check_service_health "postgres" "wb_lead_postgres"; then
    restart_service "postgres"
fi

# Check and restart workers if needed
check_and_restart_workers

# Check worker health (check first few)
for i in {1..5}; do
    worker_name="wb_lead_solo-worker-${i}"
    if docker ps --format '{{.Names}}' | grep -q "^${worker_name}$"; then
        if ! check_service_health "worker" "${worker_name}"; then
            restart_service "worker"
            break
        fi
    fi
done

echo "✅ Health check completed"

