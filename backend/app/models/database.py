"""
SQLAlchemy database models for Daisy Risk Engine
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, Index, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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
    
    # Composite index and unique constraint for performance and atomic upserts
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_stock_timeseries_ticker_date"),
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


class NSEBhavcopy(Base):
    """Daily NSE equity bhavcopy with delivery metrics"""
    __tablename__ = "nse_bhavcopy"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    series = Column(String(10), default="EQ")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    prev_close = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    ttl_trd_qnty = Column(Integer, nullable=False)
    turnover_lacs = Column(Float, nullable=False)
    no_of_trades = Column(Integer, nullable=False, default=0)
    deliv_qty = Column(Integer, nullable=True)
    deliv_per = Column(Float, nullable=True)
    
    __table_args__ = (
        Index("ix_bhav_symbol_date", "symbol", "date"),
    )
    
    def __repr__(self):
        return f"<NSEBhavcopy(symbol='{self.symbol}', date='{self.date}', close={self.close}, deliv_per={self.deliv_per})>"


class NSEInstitutionalFlow(Base):
    """Daily FII / DII equity cash market flows"""
    __tablename__ = "nse_institutional_flows"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    category = Column(String(20), nullable=False)  # "FII", "DII", etc.
    buy_value_crores = Column(Float, nullable=False)
    sell_value_crores = Column(Float, nullable=False)
    net_value_crores = Column(Float, nullable=False)
    
    __table_args__ = (
        Index("ix_flow_date_cat", "date", "category"),
    )
    
    def __repr__(self):
        return f"<NSEInstitutionalFlow(date='{self.date}', category='{self.category}', net={self.net_value_crores})>"


class NSEBulkBlockDeal(Base):
    """NSE bulk and block deal transactions"""
    __tablename__ = "nse_bulk_block_deals"
    
    id = Column(Integer, primary_key=True, index=True)
    deal_type = Column(String(10), nullable=False)  # "BULK" or "BLOCK"
    date = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    client_name = Column(String(200), nullable=False)
    buy_sell = Column(String(10), nullable=False)  # "BUY" or "SELL"
    quantity = Column(Integer, nullable=False)
    trade_price = Column(Float, nullable=False)
    remarks = Column(String(200), nullable=True)
    
    __table_args__ = (
        Index("ix_deal_symbol_date", "symbol", "date"),
    )
    
    def __repr__(self):
        return f"<NSEBulkBlockDeal(deal_type='{self.deal_type}', symbol='{self.symbol}', client='{self.client_name}', buy_sell='{self.buy_sell}')>"


class NSEShareholdingPattern(Base):
    """Quarterly shareholding patterns and promoter pledge deltas"""
    __tablename__ = "nse_shareholding_patterns"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    period_ended = Column(String(20), nullable=False)  # e.g., "2024-12-31"
    promoter_pct = Column(Float, nullable=False)
    promoter_pledged_pct = Column(Float, default=0.0)
    fii_pct = Column(Float, default=0.0)
    dii_pct = Column(Float, default=0.0)
    public_pct = Column(Float, default=0.0)
    updated_on = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index("ix_shp_symbol_period", "symbol", "period_ended"),
    )
    
    def __repr__(self):
        return f"<NSEShareholdingPattern(symbol='{self.symbol}', period='{self.period_ended}', promoter={self.promoter_pct}%, pledged={self.promoter_pledged_pct}%)>"