#!/bin/bash
# Script to ensure network exists and connect external Redis
# External Redis container: checklist_redis

NETWORK_NAME="docker_wb_lead_network"
REDIS_CONTAINER="checklist_redis"

# Create network if it doesn't exist
if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Creating network $NETWORK_NAME..."
    docker network create "$NETWORK_NAME"
    echo "Network $NETWORK_NAME created."
else
    echo "Network $NETWORK_NAME already exists."
fi

# Connect external Redis container to network if it exists
if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
    if ! docker network inspect "$NETWORK_NAME" --format '{{range .Containers}}{{.Name}}{{end}}' | grep -q "$REDIS_CONTAINER"; then
        echo "Connecting external Redis container $REDIS_CONTAINER to network $NETWORK_NAME..."
        docker network connect "$NETWORK_NAME" "$REDIS_CONTAINER" 2>/dev/null && \
            echo "Redis container $REDIS_CONTAINER connected to network $NETWORK_NAME." || \
            echo "Failed to connect Redis container (may already be connected)."
    else
        echo "Redis container $REDIS_CONTAINER is already connected to network $NETWORK_NAME."
    fi
else
    echo "Warning: Redis container $REDIS_CONTAINER not found. Make sure it's running."
fi

echo "Network initialization complete."


