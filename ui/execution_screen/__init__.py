"""
Module d'exécution des plugins, avec support local et SSH.
"""

import os
import logging

# Définir les constantes pour les chemins de logs
LOGS_BASE_DIR = '/tmp/pcUtils'
LOGS_DIR = os.path.join(LOGS_BASE_DIR, 'logs')

# Créer les répertoires de logs nécessaires avant tout import
os.makedirs(LOGS_DIR, exist_ok=True)

# Configurer le logger de base
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Maintenant que les répertoires de logs existent, importer les modules
from .execution_screen import ExecutionScreen
from .execution_widget import ExecutionWidget
from .plugin_container import PluginContainer

__all__ = ['ExecutionScreen', 'ExecutionWidget', 'PluginContainer']