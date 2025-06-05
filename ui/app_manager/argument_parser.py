"""
Module de gestion des arguments de ligne de commande pour pcUtils.
Ce module définit l'interface en ligne de commande de l'application.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Any, List
from ..utils.logging import get_logger

logger = get_logger('argument_parser')

class ArgumentParser:
    """
    Gestionnaire des arguments de ligne de commande pour pcUtils.
    
    Cette classe est responsable de définir et d'analyser les arguments
    de ligne de commande pour les différents modes de l'application.
    """
    
    @staticmethod
    def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
        """
        Parse les arguments de ligne de commande.
        
        Args:
            args: Liste d'arguments à parser (par défaut, utilise sys.argv)
            
        Returns:
            argparse.Namespace: Objet contenant les arguments parsés
        """
        parser = argparse.ArgumentParser(
            description='pcUtils - Utilitaire de gestion de plugins',
            epilog="Pour plus d'informations, consultez la documentation."
        )
        
        # Groupes d'arguments pour une meilleure organisation
        mode_group = parser.add_argument_group('Modes d\'exécution')
        sequence_group = parser.add_argument_group('Options de séquence')
        plugin_group = parser.add_argument_group('Options de plugin')
        
        # Mode automatique
        mode_group.add_argument('--auto', '-a', 
                          help='Active le mode automatique (exécution sans interface)',
                          action='store_true')
        
        # Options de séquence
        sequence_group.add_argument('--sequence', '-s',
                          help='Chemin vers le fichier de séquence à utiliser',
                          type=Path)
        sequence_group.add_argument('--shortcut',
                          help='Raccourci de la séquence à utiliser')
        
        # Mode plugin unique
        plugin_group.add_argument('--plugin', '-p',
                          help='Nom du plugin à exécuter')
        plugin_group.add_argument('--config', '-c',
                          help='Fichier de configuration à utiliser',
                          type=Path)
        plugin_group.add_argument('--params',
                          help='Paramètres supplémentaires au format key=value',
                          nargs='*')
        
        # Options communes
        parser.add_argument('--verbose', '-v',
                          help='Augmente le niveau de détail des logs',
                          action='count',
                          default=0)
        parser.add_argument('--quiet', '-q',
                          help='Réduit le niveau de détail des logs',
                          action='store_true')
        parser.add_argument('--log-file',
                          help='Fichier où enregistrer les logs',
                          type=Path)
        
        # Parse les arguments
        parsed_args = parser.parse_args(args)
        
        # Validation des arguments
        ArgumentParser._validate_args(parsed_args, parser)
        
        return parsed_args
    
    @staticmethod
    def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
        """
        Valide la cohérence des arguments fournis.
        
        Args:
            args: Arguments parsés
            parser: Parser utilisé pour afficher les erreurs
            
        Raises:
            SystemExit: Si les arguments sont incohérents
        """
        # Mode automatique avec séquence ou shortcut requis
        if args.auto and not (args.sequence or args.shortcut):
            parser.error("Le mode automatique (--auto) nécessite soit un fichier de séquence (--sequence) "
                        "soit un raccourci (--shortcut)")
        
        # Mode plugin avec nom de plugin requis
        if args.plugin and not args.plugin.strip():
            parser.error("Le nom du plugin ne peut pas être vide")
            
        # Vérifier si le fichier de séquence existe
        if args.sequence and not args.sequence.exists():
            logger.warning(f"Le fichier de séquence spécifié n'existe pas: {args.sequence}")
            
        # Vérifier si le fichier de configuration existe
        if args.config and not args.config.exists():
            logger.warning(f"Le fichier de configuration spécifié n'existe pas: {args.config}")
            
        # Ajuster le niveau de log en fonction des arguments
        if args.quiet:
            logger.setLevel("WARNING")
        elif args.verbose > 0:
            log_levels = ["INFO", "DEBUG"]
            level = log_levels[min(args.verbose - 1, len(log_levels) - 1)]
            logger.setLevel(level)
            
        # Log des arguments pour le débogage
        logger.debug(f"Arguments de ligne de commande: {args}")