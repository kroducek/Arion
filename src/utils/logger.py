"""
Centralizovaný logging pro ArionBot a ArionDND.
Poskytuje:
- Structured logging (JSON-like)
- Error tracking + context
- Separate bot/user logs
"""

import logging
import os
import sys
from datetime import datetime
from typing import Optional

LOG_DIR = os.environ.get("LOG_DIR", os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
))

os.makedirs(LOG_DIR, exist_ok=True)

# Nízkoprahová konfigurace loggeru
def configure_logging(bot_name: str = "Arion"):
    """
    Nastav centralizovaný logging.
    bot_name: "ArionBOT" nebo "ArionDND"
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Odstraň existující handlery (v případě reinitializace)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Handler: konzole (INFO a výše)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # Handler: soubor (DEBUG a výše)
    log_file = os.path.join(LOG_DIR, f"{bot_name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # Handler: error soubor (ERROR a výše)
    error_file = os.path.join(LOG_DIR, f"{bot_name}_errors_{datetime.now().strftime('%Y%m%d')}.log")
    error_handler = logging.FileHandler(error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_format)
    logger.addHandler(error_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Vrátí logger pro daný modul."""
    return logging.getLogger(name)


def log_error(context: str, error: Exception, extra_info: Optional[dict] = None):
    """
    Log chybu s kontextem.
    context: co se pokoušelo dělat (např. "saving player perks")
    error: Exception objekt
    extra_info: dict s dalšími údaji
    """
    logger = get_logger("ArionError")
    extra_msg = f" | {extra_info}" if extra_info else ""
    logger.error(f"[{context}] {type(error).__name__}: {str(error)}{extra_msg}")


def log_cog_load(cog_name: str, success: bool, error: Optional[Exception] = None):
    """Log načítání coga."""
    logger = get_logger("CogLoader")
    if success:
        logger.info(f"✅ Cog loaded: {cog_name}")
    else:
        logger.error(f"❌ Cog failed: {cog_name}", exc_info=error)


def log_command_execution(command_name: str, user_id: int, guild_id: Optional[int] = None):
    """Log spuštění příkazu."""
    logger = get_logger("Commands")
    logger.debug(f"Executing /{command_name} | User: {user_id} | Guild: {guild_id}")


def log_data_operation(operation: str, file_path: str, success: bool, error: Optional[Exception] = None):
    """Log operaci na souborem (load/save)."""
    logger = get_logger("DataOps")
    if success:
        logger.debug(f"{operation.upper()} | {os.path.basename(file_path)}")
    else:
        logger.error(f"{operation.upper()} FAILED | {os.path.basename(file_path)}", exc_info=error)
