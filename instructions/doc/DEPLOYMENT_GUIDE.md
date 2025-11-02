# Daisy Risk Engine - Production Deployment Guide

## Overview

This guide provides comprehensive instructions for deploying the Daisy Risk Engine in production environments with high availability, security, and monitoring.

## Prerequisites

### System Requirements

- **CPU**: 4+ cores recommended
- **RAM**: 8GB+ recommended (16GB for production)
- **Storage**: 50GB+ available space
- **Network**: Stable internet connection for external data APIs

### Software Dependencies

- Docker Engine 20.10+
- Docker Compose 2.0+
- Linux/macOS/Windows with WSL2

## Quick Start

### 1. Environment Setup

```bash
# Clone the repository
git clone https://github.com/your-org/daisy-risk-engine.git
cd daisy-risk-engine

# Copy environment configuration
cp .env.example .env

# Edit environment variables
nano .env
```

### 2. Development Deployment

```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f backend
```

### 3. Production Deployment

```bash
# Make deployment script executable
chmod +x scripts/deploy.sh

# Deploy to production
./scripts/deploy.sh production
```

## Production Configuration

### Environment Variables

#### Critical Security Settings

```bash
# Change these in production!
SECRET_KEY=your-256-bit-secret-key-here
JWT_SECRET=your-jwt-secret-here
CORS_ORIGINS=https://daisy-risk-engine.com

# Database Configuration
DATABASE_URL=sqlite:///./data/daisy.db
DATABASE_POOL_SIZE=20
MAX_OVERFLOW=30
POOL_TIMEOUT=30

# Application Settings
ENVIRONMENT=production
LOG_LEVEL=WARNING
```

#### Performance Settings

```bash
# Backend Performance
MAX_WORKERS=4
MAX_CONCURRENT_REQUESTS=100
REQUEST_TIMEOUT=30

# Frontend Performance
NODE_ENV=production
```

### SSL Certificate Setup

```bash
# Create SSL directory
mkdir -p ssl/

# Generate self-signed certificate (development only)
openssl req -x509 -newkey rsa:4096 -keyout ssl/key.pem -out ssl/cert.pem -days 365 -nodes

# For production, use Let's Encrypt or commercial certificates
```

### Database Optimization

```bash
# Enable WAL mode for better concurrency
sqlite3 backend/data/daisy.db "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
```

## Docker Deployment

### Development Environment

```bash
# Start development stack
docker-compose up -d

# Services included:
# - Backend (FastAPI): http://localhost:8000
# - Frontend (Next.js): http://localhost:3000
# - Nginx: http://localhost:80
# - Redis: http://localhost:6379
```

### Production Environment

```bash
# Deploy production stack
docker-compose -f docker-compose.prod.yml up -d

# Production services include:
# - Backend with resource limits
# - Frontend optimized build
# - Nginx with SSL
# - Prometheus monitoring
# - Grafana dashboards
# - ELK stack for logging
```

## Monitoring and Health Checks

### Application Health

```bash
# Backend health check
curl http://localhost:8000/health

# Frontend health check
curl http://localhost:3000

# Database connectivity
docker exec daisy-backend-prod sqlite3 /app/backend/data/daisy.db "SELECT 1;"
```

### Monitoring Dashboards

- **Grafana**: http://localhost:3001 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Kibana**: http://localhost:5601

### Log Aggregation

```bash
# View application logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Centralized logging (ELK stack)
curl http://localhost:5601
```

## Performance Tuning

### Backend Optimization

1. **Database Connection Pooling**
   ```python
   # In app/db/database.py
   engine = create_async_engine(
       settings.DATABASE_URL,
       pool_size=20,
       max_overflow=30,
       pool_timeout=30,
       pool_recycle=3600
   )
   ```

2. **Caching Strategy**
   ```python
   # Enable Redis caching
   REDIS_URL=redis://localhost:6379
   ENABLE_CACHING=true
   CACHE_TTL_SECONDS=3600
   ```

3. **API Rate Limiting**
   ```python
   # In app/main.py
   app.add_middleware(
       RateLimitMiddleware,
       calls=100,
       period=60
   )
   ```

### Frontend Optimization

1. **Build Optimization**
   ```bash
   npm run build
   # Creates optimized production bundle
   ```

2. **CDN Configuration**
   ```bash
   # Configure CDN for static assets
   NEXT_PUBLIC_CDN_URL=https://cdn.example.com
   ```

## Security Configuration

### API Security

1. **HTTPS Enforcement**
   ```bash
   # Force HTTPS in production
   ENVIRONMENT=production
   ```

2. **Security Headers**
   ```python
   # Implemented in SecurityHeadersMiddleware
   - X-Content-Type-Options: nosniff
   - X-Frame-Options: DENY
   - X-XSS-Protection: 1; mode=block
   - Strict-Transport-Security: max-age=31536000
   ```

3. **CORS Configuration**
   ```python
   # Restrict origins in production
   CORS_ORIGINS=https://daisy-risk-engine.com
   ```

### Database Security

1. **SQLite Security**
   ```bash
   # Set proper file permissions
   chmod 600 backend/data/daisy.db
   ```

2. **Backup Encryption**
   ```bash
   # Encrypt backups
   gpg --cipher-algo AES256 --compress-algo 1 --s2k-mode 3 --s2k-digest-algo SHA512 --s2k-count 65536 --force-mdc --quiet --no-greeting --batch --yes --no-tty --symmetric backup.sql
   ```

## Backup and Recovery

### Database Backup

```bash
# Create backup
./scripts/backup.sh

# Restore from backup
./scripts/restore.sh backup_20231102_120000.tar.gz
```

### Application Backup

```bash
# Backup application data
tar -czf application_backup_$(date +%Y%m%d_%H%M%S).tar.gz \
    backend/data/ \
    logs/ \
    ssl/ \
    .env
```

### Automated Backup

```bash
# Add to crontab
0 2 * * * /path/to/scripts/backup.sh
```

## Troubleshooting

### Common Issues

1. **Backend not starting**
   ```bash
   # Check logs
   docker-compose logs backend
   
   # Common causes:
   # - Missing environment variables
   # - Database permission issues
   # - Port conflicts
   ```

2. **Frontend build failures**
   ```bash
   # Check Node.js version
   node --version  # Should be 18+
   
   # Clear cache
   npm run clean
   npm install
   ```

3. **Database errors**
   ```bash
   # Check database integrity
   docker exec daisy-backend-prod sqlite3 /app/backend/data/daisy.db "PRAGMA integrity_check;"
   ```

### Log Analysis

```bash
# Search for errors
grep -i error logs/backend.log

# Monitor real-time logs
tail -f logs/backend.log

# Analyze slow requests
grep "response_time.*[5-9]\.[0-9]" logs/backend.log
```

## Scaling

### Horizontal Scaling

```bash
# Scale backend instances
docker-compose up --scale backend=3 -d

# Load balancing with Nginx
# Configure upstream servers in nginx/nginx.conf
```

### Vertical Scaling

```bash
# Increase resource limits
# Edit docker-compose.prod.yml
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 8G
```

## CI/CD Pipeline

### GitHub Actions Workflow

The project includes automated CI/CD pipeline:

1. **Code Quality Checks**
   - Backend: Ruff linting, mypy type checking
   - Frontend: ESLint, TypeScript checking

2. **Automated Testing**
   - Backend: pytest with coverage
   - Frontend: Vitest with coverage
   - Integration: End-to-end tests

3. **Security Scanning**
   - Dependency vulnerability scanning
   - CodeQL analysis

4. **Deployment**
   - Docker image building
   - ECR/registry pushing
   - Kubernetes deployment

### Manual Deployment

```bash
# Build and push images
docker build -t daisy-risk-engine-backend:latest backend/
docker build -t daisy-risk-engine-frontend:latest frontend/

# Deploy to production
kubectl apply -f k8s/
```

## Maintenance

### Regular Tasks

1. **Daily**
   - Monitor application health
   - Check error logs
   - Verify backup completion

2. **Weekly**
   - Update dependencies
   - Review security alerts
   - Performance analysis

3. **Monthly**
   - Database maintenance
   - SSL certificate renewal
   - Security audit

### Update Procedures

```bash
# Update application
git pull origin main
./scripts/deploy.sh production

# Update dependencies
# Backend
cd backend && uv pip install --upgrade --frozen-lockfile

# Frontend
cd frontend && npm update
```

## Support

### Documentation

- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/health
- Monitoring: http://localhost:3001 (Grafana)

### Contact

- GitHub Issues: https://github.com/your-org/daisy-risk-engine/issues
- Documentation: https://docs.daisy-risk-engine.com

---

**Last Updated**: November 2, 2025
**Version**: 1.0.0
**Maintainer**: Daisy Risk Engine Team