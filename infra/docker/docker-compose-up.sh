#!/bin/bash
# Wrapper script to ensure network connections before starting services
# This script should be used instead of 'docker-compose up' to ensure
# Redis and PostgreSQL are automatically connected to the network

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run network initialization
echo "🔧 Initializing network connections..."
bash "$SCRIPT_DIR/init-network.sh"

# Start services
echo "🚀 Starting services..."
cd "$SCRIPT_DIR"
docker-compose up -d "$@"

echo "✅ Services started. Use 'docker-compose logs -f' to view logs."

