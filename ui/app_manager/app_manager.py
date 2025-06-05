"""
Module principal de gestion de l'application pcUtils.

Ce module contient la classe principale qui coordonne les différents
composants de l'application et gère son démarrage et son exécution.
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
from textual.app import App
from ..utils.logging import get_logger
from ..choice_screen.choice_screen import Choice
from ..config_screen.config_screen import PluginConfig
from ..execution_screen.execution_screen import ExecutionScreen
from ..config_screen.auto_config import AutoConfig
from .argument_parser import ArgumentParser
from .config_loader import ConfigLoader
from .sequence_manager import SequenceManager

logger = get_logger('app_manager')

class AppManager:
    """
    Gestionnaire principal de l'application pcUtils.

    Cette classe est responsable de:
    - Analyser les arguments de ligne de commande
    - Démarrer l'application dans le mode approprié (normal, auto, plugin unique)
    - Coordonner les différents composants de l'application
    """

    def __init__(self, args=None):
        """
        Initialisation du gestionnaire d'application.

        Args:
            args: Arguments de ligne de commande (None pour utiliser sys.argv)
        """
        self.args = ArgumentParser.parse_args(args)
        self.sequence_manager = SequenceManager()
        self.config_loader = ConfigLoader()
        logger.debug("Initialisation du gestionnaire d'application")

    def run(self):
        """
        Lance l'application dans le mode approprié selon les arguments.
        """
        try:
            if self.args.auto:
                logger.info("Démarrage en mode automatique")
                self._run_auto_mode()
            elif self.args.plugin:
                logger.info(f"Démarrage en mode plugin unique: {self.args.plugin}")
                self._run_single_plugin()
            else:
                logger.info("Démarrage en mode normal (interface complète)")
                self._run_normal_mode()
        except Exception as e:
            logger.error(f"Erreur lors du démarrage de l'application: {e}")
            import traceback
            logger.error(traceback.format_exc())
            sys.exit(1)

    def _run_auto_mode(self):
        """
        Lance le mode automatique avec une séquence spécifiée.
        """
        sequence_path = None
        sequence_data = None

        # Obtenir la séquence à partir du raccourci ou du fichier
        if self.args.shortcut:
            sequence_path, sequence_data = self.sequence_manager.find_sequence_by_shortcut(self.args.shortcut)
            if not sequence_path or not sequence_data:
                logger.error(f"Impossible de trouver la séquence avec le raccourci: {self.args.shortcut}")
                sys.exit(1)
        elif self.args.sequence:
            sequence_path = self.args.sequence
            sequence_data = self.sequence_manager.load_sequence(sequence_path)
            if not sequence_data:
                logger.error(f"Impossible de charger la séquence: {sequence_path}")
                sys.exit(1)
        else:
            logger.error("Le mode automatisé nécessite soit un fichier de séquence (--sequence) soit un raccourci (--shortcut)")
            sys.exit(1)

        # Vérifier que la séquence contient des plugins
        plugins = sequence_data.get('plugins', [])
        if not plugins:
            logger.error(f"La séquence ne contient aucun plugin: {sequence_path}")
            sys.exit(1)

        # Préparer la configuration automatique
        auto_config = AutoConfig()

        # Créer une liste de tuples (nom, instance) avec des instances uniques
        plugin_instances = []
        instance_counters = {}

        for plugin in plugins:
            # Extraire le nom du plugin selon le format (dict ou string)
            if isinstance(plugin, dict) and 'name' in plugin:
                name = plugin['name']
            elif isinstance(plugin, str):
                name = plugin
            else:
                logger.warning(f"Format de plugin non reconnu dans la séquence, ignoré: {plugin}")
                continue

            # Gérer le compteur d'instances
            if name not in instance_counters:
                instance_counters[name] = 0
            instance_id = instance_counters[name]
            plugin_instances.append((name, instance_id))
            instance_counters[name] += 1

        # Traiter la configuration de la séquence
        config = auto_config.process_sequence(sequence_path, plugin_instances)

        # Vérifier si tous les champs requis sont remplis
        all_fields_filled = self._check_config_completeness(config)

        # Lancer l'écran approprié selon l'état de la configuration
        if not all_fields_filled:
            logger.info("Configuration incomplète, ouverture de l'écran de configuration")
            self._run_config_screen(plugin_instances, sequence_path)
        else:
            logger.info("Configuration complète, lancement de l'exécution")
            self._run_execution_screen(plugin_instances, config)

    def _check_config_completeness(self, config: Dict[str, Any]) -> bool:
        """
        Vérifie si tous les champs de configuration sont remplis.

        Args:
            config: Configuration à vérifier

        Returns:
            bool: True si tous les champs sont remplis
        """
        # Si pas de configuration, elle est incomplète
        if not config:
            return False

        # Vérifier chaque plugin
        for plugin_id, plugin_config in config.items():
            # Si pas de configuration pour ce plugin
            if not plugin_config:
                logger.warning(f"Configuration manquante pour {plugin_id}")
                return False

            # Vérifier que tous les champs ont une valeur non vide
            for key, value in plugin_config.items():
                if isinstance(value, str) and not value.strip():
                    logger.warning(f"Valeur vide pour {plugin_id}.{key}")
                    return False

        return True

    def _run_single_plugin(self):
        """
        Lance l'exécution d'un plugin unique avec sa configuration.
        """
        # Charger la configuration depuis le fichier si spécifié
        config = {}
        if self.args.config:
            config_from_file = ConfigLoader.load_config(self.args.config)
            if config_from_file:
                config.update(config_from_file)
            else:
                logger.warning(f"Impossible de charger la configuration depuis: {self.args.config}")

        # Ajouter les paramètres de ligne de commande
        if self.args.params:
            params_config = ConfigLoader.parse_params(self.args.params)
            config.update(params_config)

        # Créer la configuration pour l'exécution
        plugin_name = self.args.plugin
        plugins_config = {f"{plugin_name}_0": config}
        plugin_instances = [(plugin_name, 0)]

        # Lancer l'écran d'exécution
        self._run_execution_screen(plugin_instances, plugins_config)

    def _run_normal_mode(self):
        """
        Lance l'interface normale de l'application.
        """
        # Créer et lancer l'application avec l'écran de choix
        app = Choice()
        app.run()

    def _run_config_screen(self, plugin_instances: List[Tuple[str, int]], sequence_file: Optional[Union[str, Path]] = None):
        """
        Lance l'écran de configuration.

        Args:
            plugin_instances: Liste des tuples (nom_plugin, id_instance)
            sequence_file: Chemin vers le fichier de séquence (optionnel)
        """
        class ConfigApp(App):
            def __init__(self, instances, seq_file):
                super().__init__()
                self.instances = instances
                self.seq_file = seq_file

            def on_mount(self) -> None:
                self.push_screen(PluginConfig(self.instances, sequence_file=self.seq_file))

        app = ConfigApp(plugin_instances, sequence_file)
        app.run()

    def _run_execution_screen(self, plugin_instances: List[Tuple[str, int]], plugins_config: Dict[str, Any] = None):
        """
        Lance l'écran d'exécution.

        Args:
            plugin_instances: Liste des tuples (nom_plugin, id_instance)
            plugins_config: Configuration des plugins (optionnel)
        """
        class ExecutionApp(App):
            def __init__(self, instances, config, auto_exec=False):
                super().__init__()
                self.instances = instances
                self.config = config
                self.auto_execute = auto_exec

            def on_mount(self) -> None:
                self.push_screen(ExecutionScreen(
                    self.instances,
                    plugins_config=self.config,
                    auto_execute=self.auto_execute
                ))

        app = ExecutionApp(plugin_instances, plugins_config, auto_exec=self.args.auto)
        app.run()
