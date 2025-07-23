#!/bin/bash

echo "Checking MuseScore processes across all containers..."

# Check each container
for container in $(docker ps --filter "name=flask-musescore" --format "{{.Names}}"); do
    echo "Container: $container"
    docker exec $container ps aux | grep musescore | grep -v grep || echo "  No MuseScore processes"
done

# Check overall stats
echo -e "\nProcess counts:"
curl -s http://localhost:8129/system/processes | jq .
