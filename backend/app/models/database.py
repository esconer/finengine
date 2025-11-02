"""
SQLAlchemy database models for Daisy Risk Engine
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, Index, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from app.db.database import Base


class PortfolioPosition(Base):
    """Portfolio position model"""
    __tablename__ = "portfolio_positions"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    weight = Column(Float, nullable=False)
    quantity = Column(Float, default=0.0, nullable=False)
    buy_price = Column(Float, default=0.0, nullable=False)
    region = Column(String(10), default="US")
    primary_source = Column(String(20), default="yfinance")
    fallback_source = Column(String(20), nullable=True)
    last_validated_source = Column(String(20), default="yfinance")
    last_price = Column(Float, default=0.0)
    market_value = Column(Float, default=0.0)
    sector = Column(String(50), default="Unknown")
    industry = Column(String(50), default="Unknown")
    custom_name = Column(String(100), nullable=True)
    added_on = Column(DateTime(timezone=True), server_default=func.now())
    updated_on = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    stock_data = relationship("StockTimeseries", back_populates="position")
    
    def __repr__(self):
        return f"<PortfolioPosition(id={self.id}, ticker='{self.ticker}', weight={self.weight})>"


class StockTimeseries(Base):
    """Stock timeseries data model"""
    __tablename__ = "stock_timeseries"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    adj_close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    source_used = Column(String(20), default="yfinance")
    fetch_status = Column(String(20), default="fresh")
    fetched_on = Column(DateTime(timezone=True), server_default=func.now())
    
    # Foreign key relationship
    position_id = Column(Integer, ForeignKey("portfolio_positions.id"), nullable=True)
    position = relationship("PortfolioPosition", back_populates="stock_data")
    
    # Composite index for performance
    __table_args__ = (
        Index("ix_ticker_date", "ticker", "date"),
    )
    
    def __repr__(self):
        return f"<StockTimeseries(ticker='{self.ticker}', date='{self.date}', close={self.close})>"


class AnalyticsCache(Base):
    """Analytics calculation cache model"""
    __tablename__ = "analytics_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    metric_name = Column(String(50), nullable=False)
    metric_value = Column(Float, nullable=False)
    calculation_date = Column(DateTime, nullable=False)
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    model_params = Column(JSON, default={})
    
    # Composite index for efficient lookups
    __table_args__ = (
        Index("ix_ticker_metric", "ticker", "metric_name"),
    )
    
    def __repr__(self):
        return f"<AnalyticsCache(ticker='{self.ticker}', metric='{self.metric_name}', value={self.metric_value})>"


class FetchLog(Base):
    """Data fetch attempt log model"""
    __tablename__ = "fetch_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    primary_attempt = Column(Boolean, default=False)
    fallback_attempt = Column(Boolean, default=False)
    status = Column(String(20), nullable=False)  # "success", "failed"
    error_message = Column(String(500), nullable=True)
    source_used = Column(String(20), default="yfinance")
    
    # Index for efficient queries
    __table_args__ = (
        Index("ix_ticker_timestamp", "ticker", "timestamp"),
        Index("ix_status_timestamp", "status", "timestamp"),
    )
    
    def __repr__(self):
        return f"<FetchLog(ticker='{self.ticker}', status='{self.status}', timestamp='{self.timestamp}')>"