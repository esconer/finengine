"""
Daisy Risk Engine - FastAPI Backend

Financial risk analytics engine with portfolio management,
risk calculations, and real-time data processing.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import time
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Any

from app.config import settings
from app.db.database import init_db
from app.api import portfolio, data, analytics, websocket, equity_research
from app.utils.logger import setup_logger


# Setup logging
logger = setup_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        start_time = time.time()
        
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # Add custom headers
        response.headers["X-API-Version"] = "v1"
        response.headers["X-Response-Time"] = f"{time.time() - start_time:.3f}s"
        
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("Starting Daisy Risk Engine Backend")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down Daisy Risk Engine Backend")


# Create FastAPI application
app = FastAPI(
    title="Daisy Risk Engine API",
    description="Financial risk analytics engine for portfolio management",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add production middleware
if os.getenv("ENVIRONMENT", "development") == "production":
    # Security middleware for production
    app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["daisy-risk-engine.com", "*.daisy-risk-engine.com", "localhost", "127.0.0.1"]
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler. Must return a Response (never a plain dict),
    otherwise Starlette raises a secondary failure while handling the error."""
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred",
            "status_code": 500,
        },
    )

# Include routers
app.include_router(
    portfolio.router,
    prefix="/api/v1/portfolio",
    tags=["portfolio"]
)

app.include_router(
    data.router,
    prefix="/api/v1/data",
    tags=["data"]
)

app.include_router(
    analytics.router,
    prefix="/api/v1/analytics",
    tags=["analytics"]
)

app.include_router(
    websocket.router,
    prefix="/api/v1/ws",
    tags=["websocket"]
)

app.include_router(
    equity_research.router,
    prefix="/api/v1",
    tags=["equity_research"]
)

# Health check endpoint
@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Daisy Risk Engine",
        "version": "0.1.0",
        "environment": "development"
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Daisy Risk Engine API",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
