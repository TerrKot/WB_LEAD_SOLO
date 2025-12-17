#!/bin/bash
# Script for graceful Docker Compose shutdown

set -e

echo "Stopping Docker Compose services..."

# Stop services gracefully
docker compose -f infra/docker/docker-compose.yml down --timeout 30

# Find and remove networks
echo "Disconnecting containers from networks..."
NETWORKS=$(docker network ls --format "{{.Name}}" | grep -E "wb_lead.*network" || true)

if [ -n "$NETWORKS" ]; then
    while IFS= read -r network; do
        if [ -n "$network" ]; then
            echo "Processing network: $network"
            
            # Get containers connected to this network
            CONTAINERS=$(docker network inspect "$network" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "")
            
            if [ -n "$CONTAINERS" ]; then
                for container in $CONTAINERS; do
                    if [ -n "$container" ]; then
                        echo "  Disconnecting container: $container"
                        docker network disconnect -f "$network" "$container" 2>/dev/null || true
                    fi
                done
            fi
            
            # Remove network
            echo "Removing network: $network"
            docker network rm "$network" 2>/dev/null || true
        fi
    done <<< "$NETWORKS"
fi

echo "Docker Compose services stopped successfully."

