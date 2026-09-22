"""
Logging configuration for Daisy Risk Engine
"""

import logging
import sys
from typing import Optional

from app.config import settings


def setup_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Setup logger with proper formatting
    
    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL);
               defaults to settings.log_level (LOG_LEVEL env / .env)
    
    Returns:
        Configured logger instance
    """
    # Explicit parameter wins; otherwise the configured LOG_LEVEL (audit B17).
    log_level = (level or settings.log_level or "INFO").upper()
    try:
        numeric_level = getattr(logging, log_level)
        if not isinstance(numeric_level, int):
            raise AttributeError(log_level)
    except AttributeError:
        # typo'd LOG_LEVEL must not crash logger setup (falls back to INFO)
        numeric_level = logging.INFO

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger