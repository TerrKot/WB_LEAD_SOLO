#!/bin/bash
# Wrapper script to ensure network connections before starting services
# This script should be used instead of 'docker-compose up' to ensure
# Redis and PostgreSQL are automatically connected to the network
# Automatically scales workers to 10 instances

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_REPLICAS=${WORKER_REPLICAS:-10}

# Run network initialization
echo "🔧 Initializing network connections..."
bash "$SCRIPT_DIR/init-network.sh"

# Start services (excluding worker first)
echo "🚀 Starting core services..."
cd "$SCRIPT_DIR"
docker-compose up -d --no-deps redis postgres network_init bot_service

# Wait for dependencies to be ready
echo "⏳ Waiting for dependencies to be ready..."
sleep 5

# Start workers with scaling
echo "🚀 Starting ${WORKER_REPLICAS} worker instances..."
docker-compose up -d --scale worker=${WORKER_REPLICAS} worker

echo "✅ Services started with ${WORKER_REPLICAS} workers."
echo "📊 Check status: docker-compose ps"
echo "📋 View logs: docker-compose logs -f worker"

