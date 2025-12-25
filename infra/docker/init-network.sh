#!/bin/bash
# Script to ensure Redis and PostgreSQL are connected to wb_lead_network

NETWORK_NAME="docker_wb_lead_network"
REDIS_CONTAINER="docker-redis-1"
POSTGRES_CONTAINER="docker-postgres-1"

# Create network if it doesn't exist
if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Creating network $NETWORK_NAME..."
    docker network create "$NETWORK_NAME"
fi

# Connect Redis if not already connected
if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
    if ! docker network inspect "$NETWORK_NAME" | grep -q "\"${REDIS_CONTAINER}\""; then
        echo "Connecting $REDIS_CONTAINER to $NETWORK_NAME..."
        docker network connect "$NETWORK_NAME" "$REDIS_CONTAINER" 2>/dev/null || true
    fi
fi

# Connect PostgreSQL if not already connected
if docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
    if ! docker network inspect "$NETWORK_NAME" | grep -q "\"${POSTGRES_CONTAINER}\""; then
        echo "Connecting $POSTGRES_CONTAINER to $NETWORK_NAME..."
        docker network connect "$NETWORK_NAME" "$POSTGRES_CONTAINER" 2>/dev/null || true
    fi
fi

echo "Network initialization complete."

