# PowerShell script for graceful Docker Compose shutdown

Write-Host "Stopping Docker Compose services..." -ForegroundColor Yellow

# Stop services gracefully
docker compose -f infra/docker/docker-compose.yml down --timeout 30

# Get network name (Docker Compose adds prefix)
$NETWORK_NAME = "docker_wb_lead_network"
$COMPOSE_NETWORK_NAME = "wb_lead_wb_lead_network"

# Check which network exists
$networks = docker network ls --format "{{.Name}}" | Select-String -Pattern "wb_lead.*network"

if ($networks) {
    Write-Host "Disconnecting containers from network..." -ForegroundColor Yellow
    
    # Get all containers connected to the network
    foreach ($network in $networks) {
        $networkName = $network.ToString()
        Write-Host "Processing network: $networkName" -ForegroundColor Cyan
        
        # Get containers connected to this network
        $containers = docker network inspect $networkName --format '{{range .Containers}}{{.Name}} {{end}}' 2>$null
        
        if ($containers) {
            $containerList = $containers.Trim().Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)
            foreach ($container in $containerList) {
                if ($container) {
                    Write-Host "  Disconnecting container: $container" -ForegroundColor Gray
                    docker network disconnect -f $networkName $container 2>$null
                }
            }
        }
        
        # Remove network
        Write-Host "Removing network: $networkName" -ForegroundColor Yellow
        docker network rm $networkName 2>$null
    }
}

# Also try to remove by exact name if still exists
$allNetworks = docker network ls --format "{{.Name}}"
if ($allNetworks -match "wb_lead.*network") {
    Write-Host "Force removing remaining networks..." -ForegroundColor Yellow
    $remaining = $allNetworks | Select-String -Pattern "wb_lead.*network"
    foreach ($net in $remaining) {
        docker network rm -f $net.ToString() 2>$null
    }
}

Write-Host "Docker Compose services stopped successfully." -ForegroundColor Green

