"""
Portfolio API endpoints for portfolio management operations
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
import csv
import io

from app.db.database import get_db_session
from app.services.data_service import GlobalDataService, DataService
from app.models.database import PortfolioPosition
from app.models.schemas import (
    PortfolioPositionCreate, PortfolioPositionUpdate, PortfolioPositionResponse,
    PortfolioSummaryResponse, BulkAddRequest, BulkAddResponse,
    SuccessResponse
)
from app.services.currency_service import get_currency_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Create router
router = APIRouter()


# Dependency injection
def get_data_service(db: AsyncSession = Depends(get_db_session)) -> DataService:
    """Get data service instance"""
    return GlobalDataService(db).get_service()


@router.get("", response_model=PortfolioSummaryResponse)
async def get_portfolio(
    region: Optional[str] = Query(default=None, description="Filter by region"),
    sector: Optional[str] = Query(default=None, description="Filter by sector"),
    currency: str = Query(default="INR", description="Target currency (USD or INR)"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioSummaryResponse:
    """
    Get portfolio summary with all positions
    """
    try:
        # Build query
        query = select(PortfolioPosition)
        
        # Apply filters
        if region:
            query = query.where(PortfolioPosition.region == region)
        if sector:
            query = query.where(PortfolioPosition.sector == sector)
        
        # Execute query
        result = await db.execute(query)
        positions = result.scalars().all()
        
        if not positions:
            return PortfolioSummaryResponse(
                positions=[],
                total_value=0.0,
                total_positions=0,
                total_weight=0.0,
                sectors={}
            )
        
        # Update prices and market values
        await _update_portfolio_prices(positions, data_service)
        await db.commit()
        
        # Build response with live market-value weights
        position_responses = []
        total_value = 0.0
        currency_service = get_currency_service()
        sectors = {}
        total_mv_inr = sum((p.quantity or 0.0) * (p.last_price or 0.0) for p in positions)
        
        for position in positions:
            # Calculate portfolio metrics
            total_cost = position.quantity * position.buy_price
            current_value = position.quantity * position.last_price
            unrealized_gain_loss = current_value - total_cost
            unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
            live_weight = (current_value / total_mv_inr) if total_mv_inr > 0 else (position.weight or 0.0)
            
            # Convert to response model
            pos_response = PortfolioPositionResponse(
                id=position.id,
                ticker=position.ticker,
                weight=live_weight,
                quantity=position.quantity,
                buy_price=position.buy_price,
                last_price=position.last_price,
                market_value=position.market_value,
                sector=position.sector,
                industry=position.industry,
                custom_name=position.custom_name,
                added_on=position.added_on,
                updated_on=position.updated_on,
                total_cost=total_cost,
                unrealized_gain_loss=unrealized_gain_loss,
                unrealized_gain_loss_pct=unrealized_gain_loss_pct,
                current_value=current_value
            )
            position_responses.append(pos_response)
            
            # Calculate totals (convert to target currency)
            if currency != 'INR':
                total_value += await currency_service.convert_amount(current_value, 'INR', currency)
            else:
                total_value += current_value
            
            # Track sector allocation by market value
            sector_key = position.sector or "Unknown"
            sectors[sector_key] = sectors.get(sector_key, 0.0) + current_value
        
        # Normalize sector shares by total market value
        if total_mv_inr > 0:
            normalized_sectors = {k: v / total_mv_inr for k, v in sectors.items()}
        else:
            normalized_sectors = {}
        
        return PortfolioSummaryResponse(
            positions=position_responses,
            total_value=total_value,
            total_positions=len(positions),
            total_weight=total_weight,
            sectors=normalized_sectors
        )
        
    except Exception as e:
        logger.error(f"Error in get_portfolio: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/add", response_model=PortfolioPositionResponse)
async def add_portfolio_position(
    position: PortfolioPositionCreate,
    currency: str = Query(default="INR", description="Target currency (USD or INR)"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """
    Add a new portfolio position
    """
    try:
        # CRITICAL: Log incoming request for 422 debugging
        logger.info(f"=== ADD POSITION REQUEST RECEIVED ===")
        logger.info(f"Raw request data: {position}")
        logger.info(f"Request type: {type(position)}")
        logger.info(f"Position dict: {position.dict() if hasattr(position, 'dict') else 'N/A'}")
        logger.info(f"Currency: {currency}")
        logger.info(f"=== END REQUEST DATA ===")
        
        # Validate ticker exists with enhanced error handling and suggestions
        if not await data_service.validate_ticker(position.ticker):
            logger.error(f"Ticker validation failed for {position.ticker}")
            
            # Generate helpful error message with suggestions
            suggestions = _generate_ticker_suggestions(position.ticker)
            if suggestions:
                suggestion_text = f". Did you mean: {', '.join(suggestions)}?"
            else:
                suggestion_text = ""
                
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_TICKER",
                    "message": f"'{position.ticker}' is not a valid stock ticker symbol",
                    "suggestions": suggestions,
                    "help": f"Please enter a valid ticker symbol like AAPL, GOOGL, MSFT, TSLA, BRK.B{suggestion_text}",
                    "ticker": position.ticker
                }
            )
        
        # Check if ticker already exists in portfolio
        existing = await db.execute(
            select(PortfolioPosition).where(PortfolioPosition.ticker == position.ticker.upper())
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Ticker {position.ticker} already exists in portfolio"
            )
        
        # Fetch current price and metadata
        quote_data = await data_service.fetch_quote(position.ticker)
        if quote_data is None:
            raise HTTPException(
                status_code=400,
                detail=f"Could not fetch price data for {position.ticker}"
            )
        
        # Create position
        current_value = position.quantity * quote_data["current_price"]
        new_position = PortfolioPosition(
            ticker=position.ticker.upper(),
            weight=position.weight,
            quantity=position.quantity,
            buy_price=position.buy_price,
            region=position.region,
            primary_source="yfinance",
            last_validated_source="yfinance",
            last_price=quote_data["current_price"],
            market_value=current_value,
            sector=quote_data.get("sector", "Unknown"),
            industry=quote_data.get("industry", "Unknown"),
            custom_name=position.custom_name
        )
        
        db.add(new_position)
        await db.commit()
        await db.refresh(new_position)
        
        # Calculate response metrics
        total_cost = new_position.quantity * new_position.buy_price
        unrealized_gain_loss = current_value - total_cost
        unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
        
        logger.info(f"Added position {position.ticker} with weight {position.weight}")
        
        # Convert to response
        return PortfolioPositionResponse(
            id=new_position.id,
            ticker=new_position.ticker,
            weight=new_position.weight,
            quantity=new_position.quantity,
            buy_price=new_position.buy_price,
            last_price=new_position.last_price,
            market_value=new_position.market_value,
            sector=new_position.sector,
            industry=new_position.industry,
            custom_name=new_position.custom_name,
            added_on=new_position.added_on,
            updated_on=new_position.updated_on,
            total_cost=total_cost,
            unrealized_gain_loss=unrealized_gain_loss,
            unrealized_gain_loss_pct=unrealized_gain_loss_pct,
            current_value=current_value
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding position {position.ticker}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/bulk_add", response_model=BulkAddResponse)
async def bulk_add_positions(
    request: BulkAddRequest,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> BulkAddResponse:
    """
    Add multiple portfolio positions at once with proper transaction integrity
    """
    try:
        added_count = 0
        failed_count = 0
        added_positions = []
        failed_positions = []
        
        # STEP 1: Pre-Commit Business Rule Validation
        logger.info("Starting bulk add operation with pre-commit validation")
        
        # Validate all positions against business rules before any database operations
        validation_errors = []
        validated_positions = []
        
        for i, pos_data in enumerate(request.positions):
            position_errors = []
            
            # Business rule: quantity must be > 0
            if not hasattr(pos_data, 'quantity') or pos_data.quantity <= 0:
                position_errors.append(f"Position {i+1}: quantity must be greater than 0")
            
            # Business rule: buy_price must be > 0
            if not hasattr(pos_data, 'buy_price') or pos_data.buy_price <= 0:
                position_errors.append(f"Position {i+1}: buy_price must be greater than 0")
            
            # Business rule: weight must be between 0 and 1
            if not (0 < pos_data.weight <= 1):
                position_errors.append(f"Position {i+1}: weight must be between 0 and 1")
            
            # Business rule: ticker must be valid format
            if not pos_data.ticker or len(pos_data.ticker) > 10:
                position_errors.append(f"Position {i+1}: invalid ticker format")
            
            if position_errors:
                validation_errors.extend(position_errors)
            else:
                validated_positions.append(pos_data)
        
        if validation_errors:
            logger.warning(f"Bulk add validation failed: {validation_errors}")
            raise HTTPException(
                status_code=400,
                detail=f"Business rule validation failed: {'; '.join(validation_errors)}"
            )
        
        # STEP 2: Validate all tickers exist (external API validation)
        invalid_tickers = []
        for pos_data in validated_positions:
            if not await data_service.validate_ticker(pos_data.ticker):
                invalid_tickers.append(pos_data.ticker)
        
        if invalid_tickers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tickers (do not exist): {', '.join(invalid_tickers)}"
            )
        
        # STEP 3: Check for duplicates in existing portfolio
        existing_tickers = await db.execute(
            select(PortfolioPosition.ticker)
        )
        existing_set = set(existing_tickers.scalars().all())
        
        duplicate_tickers = []
        for pos_data in validated_positions:
            if pos_data.ticker.upper() in existing_set:
                duplicate_tickers.append(pos_data.ticker)
        
        if duplicate_tickers:
            logger.warning(f"Duplicate tickers found: {duplicate_tickers}")
            # Filter out duplicates but continue with valid positions
            validated_positions = [pos for pos in validated_positions
                                 if pos.ticker.upper() not in duplicate_tickers]
        
        # STEP 4: Create position objects and fetch quotes (IN MEMORY ONLY)
        for pos_data in validated_positions:
            try:
                ticker = pos_data.ticker.upper()
                
                # Fetch quote data
                quote_data = await data_service.fetch_quote(ticker)
                if quote_data is None:
                    logger.error(f"Failed to fetch quote for {ticker}")
                    failed_positions.append({"ticker": ticker, "reason": "Quote fetch failed"})
                    failed_count += 1
                    continue
                
                # Create position object (but don't add to DB yet)
                position = PortfolioPosition(
                    ticker=ticker,
                    weight=pos_data.weight,
                    quantity=pos_data.quantity,
                    buy_price=pos_data.buy_price,
                    region=pos_data.region,
                    primary_source="yfinance",
                    last_validated_source="yfinance",
                    last_price=quote_data["current_price"],
                    market_value=pos_data.quantity * quote_data["current_price"],
                    sector=quote_data.get("sector", "Unknown"),
                    industry=quote_data.get("industry", "Unknown"),
                    custom_name=pos_data.custom_name
                )
                
                # Validate position data before DB commit
                if not _validate_portfolio_position(position):
                    logger.error(f"Position validation failed for {ticker}")
                    failed_positions.append({"ticker": ticker, "reason": "Position validation failed"})
                    failed_count += 1
                    continue
                
                added_positions.append(position)
                added_count += 1
                
            except Exception as e:
                logger.error(f"Error processing position {pos_data.ticker}: {e}")
                failed_positions.append({"ticker": pos_data.ticker, "reason": str(e)})
                failed_count += 1
        
        # STEP 5: Auto-normalize weights if requested
        normalized = False
        if request.auto_normalize and added_positions:
            total_weight = sum(pos.weight for pos in added_positions)
            if total_weight > 1.0:
                normalized = True
                for position in added_positions:
                    position.weight = position.weight / total_weight
                    position.market_value = position.quantity * position.last_price
        
        # STEP 6: Response Schema Validation (PRE-COMMIT)
        logger.info(f"Validating response schema for {len(added_positions)} positions")
        
        # Validate response data structure before database commit
        response_errors = []
        for i, position in enumerate(added_positions):
            # Validate all response fields are present and valid
            if not position.ticker or not (0 < position.weight <= 1):
                response_errors.append(f"Position {i+1}: invalid response data")
            if position.quantity <= 0 or position.buy_price <= 0:
                response_errors.append(f"Position {i+1}: invalid business data")
            if position.last_price <= 0:
                response_errors.append(f"Position {i+1}: invalid price data")
        
        if response_errors:
            logger.error(f"Response schema validation failed: {response_errors}")
            raise HTTPException(
                status_code=500,
                detail=f"Response schema validation failed: {'; '.join(response_errors)}"
            )
        
        # STEP 7: ATOMIC DATABASE COMMIT (AFTER ALL VALIDATION PASSES)
        if added_positions:
            logger.info(f"Committing {len(added_positions)} positions to database atomically")
            try:
                # Add all positions to session
                for position in added_positions:
                    db.add(position)
                
                # Single atomic commit
                await db.commit()
                
                # Refresh all positions to get IDs and timestamps
                for position in added_positions:
                    await db.refresh(position)
                    
                logger.info(f"Successfully committed {len(added_positions)} positions to database")
                
            except Exception as e:
                logger.error(f"Database commit failed: {e}")
                await db.rollback()
                raise HTTPException(status_code=500, detail=f"Database commit failed: {str(e)}")
        
        # STEP 8: Build Response (POST-COMMIT)
        position_responses = []
        for position in added_positions:
            # Calculate response metrics
            total_cost = position.quantity * position.buy_price
            current_value = position.quantity * position.last_price
            unrealized_gain_loss = current_value - total_cost
            unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
            
            position_responses.append(PortfolioPositionResponse(
                id=position.id,
                ticker=position.ticker,
                weight=position.weight,
                quantity=position.quantity,
                buy_price=position.buy_price,
                last_price=position.last_price,
                market_value=position.market_value,
                sector=position.sector,
                industry=position.industry,
                custom_name=position.custom_name,
                added_on=position.added_on,
                updated_on=position.updated_on,
                total_cost=total_cost,
                unrealized_gain_loss=unrealized_gain_loss,
                unrealized_gain_loss_pct=unrealized_gain_loss_pct,
                current_value=current_value
            ))
        
        # Log operation summary
        logger.info(f"Bulk add completed: {added_count} added, {failed_count} failed, "
                   f"{len(duplicate_tickers)} duplicates filtered, normalized={normalized}")
        
        return BulkAddResponse(
            added=added_count,
            failed=failed_count,
            normalized=normalized,
            positions=position_responses
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Critical error in bulk_add_positions: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

def _validate_portfolio_position(position: PortfolioPosition) -> bool:
    """Validate portfolio position data integrity.

    Module-level helper (the stray ``self`` parameter previously made every
    bulk-add call raise TypeError, silently failing each position).
    """
    try:
        # Business rule validations
        if not position.ticker or len(position.ticker) > 10:
            return False
        if not (0 < position.weight <= 1):
            return False
        if position.quantity <= 0:
            return False
        if position.buy_price <= 0:
            return False
        if position.last_price <= 0:
            return False
        if position.market_value < 0:
            return False
        
        # Data consistency checks
        expected_market_value = position.quantity * position.last_price
        if abs(position.market_value - expected_market_value) > 0.01:  # Allow small floating point errors
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Position validation error: {e}")
        return False


@router.get("/{ticker}", response_model=PortfolioPositionResponse)
async def get_portfolio_position(
    ticker: str,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """
    Get a specific portfolio position by ticker
    """
    try:
        result = await db.execute(
            select(PortfolioPosition).where(PortfolioPosition.ticker == ticker.upper())
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        # Update price; market_value always derives from quantity x last_price.
        quote_data = await data_service.fetch_quote(ticker)
        if quote_data:
            position.last_price = quote_data["current_price"]
            position.market_value = (position.quantity or 0) * position.last_price
            position.updated_on = datetime.utcnow()
            await db.commit()

        # Reload eagerly: on-update server columns (updated_on) are otherwise
        # unfetched on fresh rows and lazy-load with sync IO outside greenlet.
        await db.refresh(position)

        total_cost = position.quantity * position.buy_price
        current_value = position.quantity * position.last_price
        unrealized_gain_loss = current_value - total_cost
        unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0

        return PortfolioPositionResponse(
            id=position.id,
            ticker=position.ticker,
            weight=position.weight,
            quantity=position.quantity,
            buy_price=position.buy_price,
            last_price=position.last_price,
            market_value=position.market_value,
            sector=position.sector,
            industry=position.industry,
            custom_name=position.custom_name,
            added_on=position.added_on,
            updated_on=position.updated_on,
            total_cost=total_cost,
            unrealized_gain_loss=unrealized_gain_loss,
            unrealized_gain_loss_pct=unrealized_gain_loss_pct,
            current_value=current_value
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting position {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/{ticker}", response_model=PortfolioPositionResponse)
async def update_portfolio_position(
    ticker: str,
    updates: PortfolioPositionUpdate,
    currency: str = Query(default="INR", description="Target currency (USD or INR)"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """
    Update a portfolio position
    """
    try:
        result = await db.execute(
            select(PortfolioPosition).where(PortfolioPosition.ticker == ticker.upper())
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        # Apply updates
        if updates.weight is not None:
            if updates.weight <= 0 or updates.weight > 1:
                raise HTTPException(
                    status_code=400,
                    detail="Weight must be between 0 and 1"
                )
            position.weight = updates.weight
        
        if updates.quantity is not None:
            if updates.quantity <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Quantity must be greater than 0"
                )
            position.quantity = updates.quantity
        
        if updates.buy_price is not None:
            if updates.buy_price <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Buy price must be greater than 0"
                )
            position.buy_price = updates.buy_price
        
        if updates.custom_name is not None:
            position.custom_name = updates.custom_name
        
        # Recalculate market value and metrics
        position.market_value = position.quantity * position.last_price
        position.updated_on = datetime.utcnow()
        
        await db.commit()
        await db.refresh(position)
        
        # Calculate response metrics
        total_cost = position.quantity * position.buy_price
        current_value = position.quantity * position.last_price
        unrealized_gain_loss = current_value - total_cost
        unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
        
        return PortfolioPositionResponse(
            id=position.id,
            ticker=position.ticker,
            weight=position.weight,
            quantity=position.quantity,
            buy_price=position.buy_price,
            last_price=position.last_price,
            market_value=position.market_value,
            sector=position.sector,
            industry=position.industry,
            custom_name=position.custom_name,
            added_on=position.added_on,
            updated_on=position.updated_on,
            total_cost=total_cost,
            unrealized_gain_loss=unrealized_gain_loss,
            unrealized_gain_loss_pct=unrealized_gain_loss_pct,
            current_value=current_value
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating position {ticker}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{ticker}")
async def delete_portfolio_position(
    ticker: str,
    db: AsyncSession = Depends(get_db_session)
) -> SuccessResponse:
    """
    Delete a portfolio position
    """
    try:
        result = await db.execute(
            select(PortfolioPosition).where(PortfolioPosition.ticker == ticker.upper())
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        await db.delete(position)
        await db.commit()
        
        return SuccessResponse(
            success=True,
            message=f"Position {ticker} deleted successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting position {ticker}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/export/csv")
async def export_portfolio_csv(
    db: AsyncSession = Depends(get_db_session)
) -> str:
    """
    Export portfolio as CSV
    """
    try:
        result = await db.execute(select(PortfolioPosition))
        positions = result.scalars().all()
        
        if not positions:
            raise HTTPException(status_code=404, detail="No positions to export")
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ticker', 'weight', 'region', 'last_price', 'market_value',
            'sector', 'industry', 'custom_name', 'added_on', 'updated_on'
        ])
        
        # Write data
        for position in positions:
            writer.writerow([
                position.ticker,
                position.weight,
                position.region,
                position.last_price,
                position.market_value,
                position.sector,
                position.industry,
                position.custom_name or '',
                position.added_on.isoformat(),
                # fresh rows have NULL updated_on until first update
                (position.updated_on or position.added_on).isoformat()
            ])
        
        # Return CSV content
        csv_content = output.getvalue()
        output.close()
        
        return csv_content
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting portfolio CSV: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/normalize")
async def normalize_portfolio_weights(
    method: str = Query(default="proportional", description="Normalization method"),
    db: AsyncSession = Depends(get_db_session)
) -> SuccessResponse:
    """
    Normalize portfolio weights to sum to 1.0
    """
    try:
        result = await db.execute(select(PortfolioPosition))
        positions = result.scalars().all()
        
        if not positions:
            raise HTTPException(status_code=404, detail="No positions to normalize")
        
        total_weight = sum(pos.weight for pos in positions)
        
        if total_weight <= 0:
            raise HTTPException(status_code=400, detail="Total weight must be positive")
        
        # Normalize weights only — market values are quantity x price and are
        # owned by the price-refresh path, not by weight bookkeeping.
        for position in positions:
            position.weight = position.weight / total_weight
            position.updated_on = datetime.utcnow()
        
        await db.commit()
        
        return SuccessResponse(
            success=True,
            message=f"Portfolio weights normalized. Total weight: {sum(pos.weight for pos in positions):.4f}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error normalizing portfolio: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


def _generate_ticker_suggestions(invalid_ticker: str) -> List[str]:
    """
    Generate helpful ticker suggestions based on common typos and similar tickers
    
    Args:
        invalid_ticker: The invalid ticker entered by user
        
    Returns:
        List of suggested ticker corrections
    """
    suggestions = []
    
    # Common ticker corrections and examples
    common_corrections = {
        # US Stocks
        'APPL': ['AAPL'],
        'GOOG': ['GOOGL'],
        'MSFT': ['MSFT'],
        'TSLA': ['TSLA'],
        'AMZN': ['AMZN'],
        'META': ['META'],
        'NVDA': ['NVDA'],
        'BRKB': ['BRK.B'],
        'GOOGL': ['GOOG'],
        # Popular Indian Stocks (NSE)
        'RELIANCE': ['RELIANCE.NS'],
        'TCS': ['TCS.NS'],
        'INFY': ['INFY.NS'],
        'HDFC': ['HDFCBANK.NS'],
        'ITC': ['ITC.NS'],
        'BHARTI': ['BHARTIARTL.NS'],
        'LT': ['LT.NS'],
        'KOTAK': ['KOTAKBANK.NS'],
        'ASIAN': ['ASIANPAINT.NS'],
        'MARUTI': ['MARUTI.NS'],
        'HCL': ['HCLTECH.NS'],
        'WIPRO': ['WIPRO.NS'],
        'ULTRA': ['ULTRACEMCO.NS'],
        'TATA': ['TATAMOTORS.NS'],
        'NESTLE': ['NESTLEIND.NS'],
        'BAJAJ': ['BAJFINANCE.NS'],
        'HINDU': ['HINDUNILVR.NS'],
        'POWER': ['POWERGRID.NS'],
        'NTPC': ['NTPC.NS'],
        'ONGC': ['ONGC.NS']
    }
    
    # Check for exact matches with common corrections
    if invalid_ticker.upper() in common_corrections:
        suggestions.extend(common_corrections[invalid_ticker.upper()])
    
    # Common pattern corrections
    ticker_upper = invalid_ticker.upper()
    
    # Check for missing letters (common typos)
    common_tick = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN', 'META', 'NVDA', 'BRK.B']
    for ticker in common_tick:
        # Calculate edit distance
        if _is_similar_ticker(ticker_upper, ticker):
            suggestions.append(ticker)
    
    # Remove duplicates and limit to 3 suggestions
    unique_suggestions = list(dict.fromkeys(suggestions))[:3]
    
    return unique_suggestions


def _is_similar_ticker(ticker1: str, ticker2: str, max_distance: int = 2) -> bool:
    """
    Check if two tickers are similar within edit distance threshold
    
    Args:
        ticker1: First ticker
        ticker2: Second ticker
        max_distance: Maximum allowed edit distance
        
    Returns:
        True if tickers are similar, False otherwise
    """
    if len(ticker1) > 10 or len(ticker2) > 10:
        return False
        
    # Simple edit distance calculation
    distances = [[0] * (len(ticker2) + 1) for _ in range(len(ticker1) + 1)]
    
    for i in range(len(ticker1) + 1):
        distances[i][0] = i
    
    for j in range(len(ticker2) + 1):
        distances[0][j] = j
    
    for i in range(1, len(ticker1) + 1):
        for j in range(1, len(ticker2) + 1):
            if ticker1[i - 1] == ticker2[j - 1]:
                distances[i][j] = distances[i - 1][j - 1]
            else:
                distances[i][j] = 1 + min(
                    distances[i - 1][j],    # deletion
                    distances[i][j - 1],    # insertion
                    distances[i - 1][j - 1] # substitution
                )
    
    return distances[len(ticker1)][len(ticker2)] <= max_distance


async def _update_portfolio_prices(positions: List[PortfolioPosition], data_service: DataService) -> None:
    """Update portfolio position prices"""
    for position in positions:
        try:
            quote_data = await data_service.fetch_quote(position.ticker)
            if quote_data:
                # Quantity is the share-count source of truth; never infer it
                # from a possibly-stale stored market value.
                position.last_price = quote_data["current_price"]
                position.market_value = (position.quantity or 0) * position.last_price
                position.updated_on = datetime.utcnow()
        except Exception as e:
            logger.error(f"Error updating price for {position.ticker}: {e}")