"""Shared logging helpers."""

import logging

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def add_console_logging(logger: logging.Logger, level=logging.INFO):
    """Add a console handler to a logger if one doesn't exist."""
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    ):
        ch = logging.StreamHandler()
        ch.setLevel(level)
        formatter = logging.Formatter(LOG_FORMAT)
        ch.setFormatter(formatter)
        logger.addHandler(ch)


def create_logger(name: str, log_file: str) -> logging.Logger:
    """Create a logger with file + console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(LOG_FORMAT)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    add_console_logging(logger, level=logging.INFO)
    return logger
