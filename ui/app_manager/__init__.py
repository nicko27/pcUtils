"""
Module de gestion de l'application pcUtils.

Ce module fournit les fonctionnalités principales pour le démarrage et
la gestion de l'application dans ses différents modes (normal, auto, plugin unique).

Classes principales:
- AppManager: Gestionnaire principal de l'application
- ArgumentParser: Analyse des arguments de ligne de commande
- ConfigLoader: Chargement des configurations
- SequenceManager: Gestion des séquences

Utilisation typique:
    
    # Démarrage standard via ligne de commande
    from ui.app import AppManager
    app_manager = AppManager()
    app_manager.run()
    
    # Démarrage avec arguments personnalisés
    from ui.app import AppManager, ArgumentParser
    args = ArgumentParser.parse_args(['--auto', '--shortcut', 'my_shortcut'])
    app_manager = AppManager(args)
    app_manager.run()
"""

from .app_manager import AppManager
from .argument_parser import ArgumentParser
from .config_loader import ConfigLoader
from .sequence_manager import SequenceManager

__all__ = [
    'AppManager',
    'ArgumentParser',
    'ConfigLoader',
    'SequenceManager'
]

# Version du module
__version__ = '1.0.0'