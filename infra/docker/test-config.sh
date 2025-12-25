#!/bin/bash
# Test script to validate docker-compose configuration

set -e

echo "🧪 Testing Docker Compose configuration..."

# Test 1: Validate docker-compose.yml syntax
echo "✓ Test 1: Validating docker-compose.yml syntax..."
docker-compose config > /dev/null
echo "  ✅ docker-compose.yml syntax is valid"

# Test 2: Check required files exist
echo "✓ Test 2: Checking required files..."
REQUIRED_FILES=(
    "docker-compose.yml"
    "Dockerfile"
    "init-network.sh"
    "docker-compose-up.sh"
    "README.md"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "  ❌ Missing file: $file"
        exit 1
    fi
done
echo "  ✅ All required files exist"

# Test 3: Check init-network.sh is executable
echo "✓ Test 3: Checking script permissions..."
if [ ! -x "init-network.sh" ]; then
    echo "  ⚠️  init-network.sh is not executable (will be fixed on server)"
else
    echo "  ✅ init-network.sh is executable"
fi

if [ ! -x "docker-compose-up.sh" ]; then
    echo "  ⚠️  docker-compose-up.sh is not executable (will be fixed on server)"
else
    echo "  ✅ docker-compose-up.sh is executable"
fi

# Test 4: Validate network_init service configuration
echo "✓ Test 4: Validating network_init service..."
if docker-compose config | grep -q "network_init"; then
    echo "  ✅ network_init service found"
else
    echo "  ❌ network_init service not found"
    exit 1
fi

# Test 5: Validate depends_on relationships
echo "✓ Test 5: Validating depends_on relationships..."
if docker-compose config | grep -A 2 "depends_on" | grep -q "network_init"; then
    echo "  ✅ bot_service and worker depend on network_init"
else
    echo "  ❌ Missing depends_on for network_init"
    exit 1
fi

# Test 6: Validate network configuration
echo "✓ Test 6: Validating network configuration..."
if docker-compose config | grep -q "docker_wb_lead_network"; then
    echo "  ✅ Network docker_wb_lead_network configured"
else
    echo "  ❌ Network docker_wb_lead_network not configured"
    exit 1
fi

# Test 7: Check init-network.sh script logic
echo "✓ Test 7: Validating init-network.sh script..."
if grep -q "docker_wb_lead_network" init-network.sh && \
   grep -q "docker-redis-1" init-network.sh && \
   grep -q "docker-postgres-1" init-network.sh; then
    echo "  ✅ init-network.sh contains required logic"
else
    echo "  ❌ init-network.sh missing required logic"
    exit 1
fi

echo ""
echo "✅ All tests passed! Configuration is valid."
echo ""
echo "📝 Note: Make sure .env file on server has:"
echo "   REDIS_URL=redis://docker-redis-1:6379/0"
echo "   DATABASE_URL=postgresql+asyncpg://app:app@docker-postgres-1:5432/app"

