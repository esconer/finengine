"""
Source preference store: user-selectable primary market-data vendor.

Persisted in the `app_settings` key-value table so the backend cascade can
honor the choice at fetch time. Alpha Vantage is always the final tier and is
not selectable as primary.

Fallback chains:
    primary = bfinance :  bfinance -> yfinance -> Alpha Vantage
    primary = yfinance :  yfinance -> bfinance -> Alpha Vantage
"""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import select

from app.models.database import AppSetting
from app.services.cache_service import invalidate_market_data_for_source_change
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

PREFERENCE_KEY = "primary_data_source"

# Vendors that can serve as primary; Alpha Vantage is deliberately excluded
# (always-last tier) and bfinance/yfinance are interchangeable.
SELECTABLE_SOURCES = ("bfinance", "yfinance")

DEFAULT_PRIMARY_SOURCE = "bfinance"
_ACTIVE_SOURCE_ORDER = [DEFAULT_PRIMARY_SOURCE, "yfinance"]


def validate_source(source: str) -> str:
    """Normalize and validate a primary-source choice; raise ValueError if unsupported."""
    s = (source or "").strip().lower()
    if s not in SELECTABLE_SOURCES:
        raise ValueError(
            f"Unsupported primary data source '{source}'. Choose one of: {', '.join(SELECTABLE_SOURCES)}"
        )
    return s


async def get_primary_source(db: AsyncSession) -> str:
    """Read the persisted primary source, defaulting to bfinance (Tier-1 legacy behavior)."""
    global _ACTIVE_SOURCE_ORDER
    value = await get_setting(db, PREFERENCE_KEY)
    primary = value.lower() if value and value.lower() in SELECTABLE_SOURCES else DEFAULT_PRIMARY_SOURCE
    _ACTIVE_SOURCE_ORDER = [primary, "yfinance" if primary == "bfinance" else "bfinance"]
    return primary


async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a raw app_settings value (None when unset or unreadable)."""
    try:
        result = await db.execute(
            select(AppSetting.value).where(AppSetting.key == key)
        )
        value = result.scalar_one_or_none()
        return value if value is not None else default
    except Exception as exc:
        logger.error("Error reading app setting '%s': %s", key, type(exc).__name__)
        return default


async def set_primary_source(db: AsyncSession, source: str) -> str:
    """Persist the primary source and invalidate data fetched under the old cascade."""
    global _ACTIVE_SOURCE_ORDER
    validated = validate_source(source)
    _ACTIVE_SOURCE_ORDER = source_order_for(validated)
    previous = await get_setting(db, PREFERENCE_KEY)
    stmt = sqlite_insert(AppSetting.__table__).values(key=PREFERENCE_KEY, value=validated)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_on": stmt.excluded.updated_on},
    )
    await db.execute(stmt)
    await db.commit()
    # Sessions built with expire_on_commit=False would otherwise serve the
    # pre-update identity-map row on subsequent entity selects.
    db.expire_all()
    if (previous or DEFAULT_PRIMARY_SOURCE).lower() != validated:
        # A ticker row has no source-preference dimension.  Clearing the market
        # cache is the only safe way to prevent an old primary/secondary result
        # from being served after a preference switch.
        await invalidate_market_data_for_source_change(db)
    logger.info("Primary data source set to '%s'", validated)
    return validated


def source_order_for(primary: str) -> List[str]:
    """Effective vendor cascade for a primary choice (Alpha Vantage excluded — always appended last)."""
    p = validate_source(primary)
    secondary = "yfinance" if p == "bfinance" else "bfinance"
    return [p, secondary]


def get_active_source_order() -> List[str]:
    """Return the last persisted source cascade for services without a DB handle."""
    return list(_ACTIVE_SOURCE_ORDER)
