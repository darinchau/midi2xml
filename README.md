# Start with 16 instances
docker compose up -d --scale flask-musescore=16

# Stop the application
docker compose down

# Restart the application
docker compose restart

# View logs
docker compose logs -f flask-musescore

# Enter the container shell for debugging
docker compose exec flask-musescore bash

# Rebuild after code changes
docker compose up --build

# View all logs from all services
docker compose logs

# Follow logs in real-time (like tail -f)
docker compose logs -f

# View logs from specific service
docker compose logs flask-musescore
docker compose logs nginx

# Follow logs from specific service
docker compose logs -f flask-musescore

# View last N lines
docker compose logs --tail=100

# View logs with timestamps
docker compose logs -t

# Combine options
docker compose logs -f -t --tail=50 flask-musescore
