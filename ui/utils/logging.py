"""Logging configuration for the application"""
import os
import logging
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
# Remonter de deux niveaux depuis utils pour atteindre la racine du projet
LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs'))
os.makedirs(LOGS_DIR, exist_ok=True)

# Configure the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Create formatters
console_formatter = logging.Formatter('%(levelname)s: %(message)s')
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Create and configure file handler
log_file = os.path.join(LOGS_DIR, 'debug.log')
if os.path.exists(log_file):
    os.remove(log_file)
file_handler = RotatingFileHandler(log_file, mode='w', maxBytes=1024*1024, backupCount=3)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(file_formatter)
root_logger.addHandler(file_handler)

# Create a logger for our application
logger = logging.getLogger('pcUtils')
logger.setLevel(logging.DEBUG)

def get_logger(name=None):
    """Get a logger for the application 
    
    Args:
        name: Optional name to append to 'pcUtils'
        
    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f'pcUtils.{name}')
    return logger