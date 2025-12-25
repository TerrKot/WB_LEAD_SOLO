#!/bin/bash
# Script to ensure network exists
# Note: Redis and PostgreSQL are now built-in and managed by docker-compose

NETWORK_NAME="docker_wb_lead_network"

# Create network if it doesn't exist
if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Creating network $NETWORK_NAME..."
    docker network create "$NETWORK_NAME"
    echo "Network $NETWORK_NAME created."
else
    echo "Network $NETWORK_NAME already exists."
fi

echo "Network initialization complete."


