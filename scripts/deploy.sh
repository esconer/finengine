#!/bin/bash

# Daisy Risk Engine Production Deployment Script
# This script handles production deployment with proper error handling and rollback capabilities

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="daisy-risk-engine"
DOCKER_REGISTRY="your-registry.com/daisy-risk-engine"
ENVIRONMENT=${1:-production}
COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_RETENTION_DAYS=7

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
    log_info "Checking dependencies..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    if ! command -v curl &> /dev/null; then
        log_error "curl is not installed. Please install curl first."
        exit 1
    fi
    
    log_info "All dependencies are available."
}

check_environment() {
    log_info "Checking environment configuration..."
    
    if [ ! -f ".env" ]; then
        log_error ".env file not found. Please create .env from .env.example"
        exit 1
    fi
    
    # Check critical environment variables
    source .env
    
    if [ -z "${SECRET_KEY:-}" ] || [ "$SECRET_KEY" = "your-secret-key-here-change-in-production" ]; then
        log_error "SECRET_KEY is not properly configured in .env"
        exit 1
    fi
    
    log_info "Environment configuration is valid."
}

backup_database() {
    log_info "Creating database backup..."
    
    BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Create database backup
    if docker exec daisy-backend-prod python -c "
import sqlite3
import os
conn = sqlite3.connect('/app/backend/data/daisy.db')
with open('$BACKUP_DIR/database.sql', 'w') as f:
    for line in conn.iterdump():
        f.write('%s\n' % line)
conn.close()
print('Database backup completed')
"; then
        log_info "Database backup created successfully"
    else
        log_error "Database backup failed"
        return 1
    fi
    
    # Compress backup
    cd "$BACKUP_DIR"
    tar -czf ../database_backup_$(date +%Y%m%d_%H%M%S).tar.gz database.sql
    cd - > /dev/null
    
    # Clean up old backups
    find backups/ -name "database_backup_*.tar.gz" -mtime +$BACKUP_RETENTION_DAYS -delete
    
    log_info "Backup process completed"
}

pull_images() {
    log_info "Pulling latest Docker images..."
    
    docker-compose -f $COMPOSE_FILE pull --parallel
    log_info "Docker images pulled successfully"
}

deploy_application() {
    log_info "Deploying application..."
    
    # Stop existing services
    docker-compose -f $COMPOSE_FILE down
    
    # Start services with new images
    docker-compose -f $COMPOSE_FILE up -d
    
    log_info "Application deployment completed"
}

health_check() {
    log_info "Performing health checks..."
    
    # Wait for services to be ready
    sleep 30
    
    # Check backend health
    BACKEND_URL="http://localhost:8000"
    FRONTEND_URL="http://localhost:3000"
    
    # Backend health check
    if curl -f "$BACKEND_URL/health" > /dev/null 2>&1; then
        log_info "Backend health check passed"
    else
        log_error "Backend health check failed"
        return 1
    fi
    
    # Frontend health check
    if curl -f "$FRONTEND_URL" > /dev/null 2>&1; then
        log_info "Frontend health check passed"
    else
        log_warn "Frontend health check failed (may still be starting)"
    fi
    
    # Database connectivity check
    if docker exec daisy-backend-prod python -c "
import sqlite3
try:
    conn = sqlite3.connect('/app/backend/data/daisy.db')
    conn.execute('SELECT 1')
    conn.close()
    print('Database connectivity OK')
except Exception as e:
    print(f'Database error: {e}')
    exit(1)
" > /dev/null 2>&1; then
        log_info "Database connectivity check passed"
    else
        log_error "Database connectivity check failed"
        return 1
    fi
    
    log_info "All health checks passed"
}

cleanup() {
    log_info "Cleaning up old containers and images..."
    
    # Remove stopped containers
    docker container prune -f
    
    # Remove unused images
    docker image prune -f
    
    # Remove unused volumes
    docker volume prune -f
    
    log_info "Cleanup completed"
}

rollback() {
    log_error "Deployment failed. Initiating rollback..."
    
    # Stop current services
    docker-compose -f $COMPOSE_FILE down
    
    # Start services with previous images
    docker-compose -f $COMPOSE_FILE up -d
    
    log_info "Rollback completed"
}

print_usage() {
    echo "Usage: $0 [environment]"
    echo "Environment options: production, staging"
    echo "Example: $0 production"
}

main() {
    log_info "Starting deployment of Daisy Risk Engine..."
    
    if [ $# -eq 0 ]; then
        print_usage
        exit 1
    fi
    
    case "$1" in
        "production"|"staging")
            ENVIRONMENT=$1
            ;;
        "help"|"-h"|"--help")
            print_usage
            exit 0
            ;;
        *)
            log_error "Unknown environment: $1"
            print_usage
            exit 1
            ;;
    esac
    
    log_info "Deploying to $ENVIRONMENT environment"
    
    # Check if deployment is running in CI/CD
    if [ "${CI:-false}" = "true" ]; then
        log_info "Running in CI/CD environment"
        ENVIRONMENT_FILE=".env.ci"
    else
        ENVIRONMENT_FILE=".env"
    fi
    
    # Set environment file for docker-compose
    export COMPOSE_ENV_FILE="$ENVIRONMENT_FILE"
    
    # Trap for cleanup on exit
    trap cleanup EXIT
    
    # Deploy with error handling
    if check_dependencies && \
       check_environment && \
       backup_database && \
       pull_images && \
       deploy_application && \
       health_check; then
        
        log_info "Deployment completed successfully!"
        
        # Print deployment summary
        echo ""
        echo "=== DEPLOYMENT SUMMARY ==="
        echo "Environment: $ENVIRONMENT"
        echo "Backend URL: http://localhost:8000"
        echo "Frontend URL: http://localhost:3000"
        echo "API Docs: http://localhost:8000/docs"
        echo "Health Check: http://localhost:8000/health"
        echo "========================"
        
    else
        log_error "Deployment failed!"
        rollback
        exit 1
    fi
}

# Run main function
main "$@"