from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Label, Header, Footer, Button
import sys
import traceback
from typing import List, Dict, Any, Tuple, Optional, Set

from ..utils.logging import get_logger
from ..execution_screen.execution_screen import ExecutionScreen

from .plugin_card import PluginCard
from .selected_plugins_panel import SelectedPluginsPanel
from .plugin_utils import load_plugin_info, get_plugin_folder_name
from .sequence_handler import SequenceHandler
from .template_handler import TemplateHandler

logger = get_logger('choice_screen')

class Choice(App):
    """
    Application principale pour la sélection et la configuration des plugins.

    Cette classe gère l'interface de sélection des plugins et des séquences,
    ainsi que le passage à l'écran de configuration.
    """

    BINDINGS = [
        ("escape", "quit", "Quitter"),  # Raccourci pour quitter l'application
    ]

    CSS_PATH = "../styles/choice.tcss"  # Chemin vers le fichier CSS

    def __init__(self):
        """Initialise l'application de sélection des plugins."""
        super().__init__()
        logger.debug("Initialisation de l'application Choice")

        # Initialisation des gestionnaires
        self.sequence_handler = SequenceHandler()
        self.template_handler = TemplateHandler()
        self.report_manager = None  # Initialisé si besoin

        # État de l'application
        self.total_id = 0
        self.theme="gruvbox"
        self.selected_plugins = []   # Liste des tuples (plugin_name, instance_id)
        self.instance_counter = {}   # Compteur d'instances par plugin
        self.plugin_templates = {}   # Templates par plugin
        self.sequence_file = None    # Fichier de séquence passé en argument
        self.auto_execute = False    # Mode exécution automatique
        self.report_file = None      # Fichier pour le rapport d'exécution
        self.report_format = 'csv'   # Format du rapport (csv ou txt)

        # Traiter les arguments de ligne de commande
        self._process_command_line_args()

    def _process_command_line_args(self) -> None:
        """
        Traite les arguments de ligne de commande.

        Format:
        - Le premier argument peut être un fichier de séquence
        - L'option --auto active l'exécution automatique
        - Les options --report=file.csv ou --format=txt définissent le rapport
        """
        if len(sys.argv) <= 1:
            return

        # Traiter le premier argument comme un fichier de séquence potentiel
        sequence_path = sys.argv[1]
        if not sequence_path.startswith('--'):
            sequence_file = Path(sequence_path)
            if sequence_file.exists():
                logger.info(f"Fichier de séquence détecté: {sequence_path}")
                self.sequence_file = sequence_file

        # Parcourir les autres arguments pour les options
        for arg in sys.argv[1:]:
            if arg == '--auto':
                self.auto_execute = True
                logger.info("Mode auto-exécution activé")
            elif arg.startswith('--report='):
                self.report_file = arg.split('=')[1]
                logger.info(f"Fichier de rapport défini: {self.report_file}")
            elif arg.startswith('--format='):
                self.report_format = arg.split('=')[1]
                logger.info(f"Format de rapport défini: {self.report_format}")

    def compose(self) -> ComposeResult:
        """
        Compose l'interface de sélection des plugins.

        Returns:
            ComposeResult: Résultat de la composition
        """
        yield Header()  # En-tête de l'application

        with Horizontal(id="main-content"):
            # Colonne gauche: cartes de plugins
            with Vertical(id="plugins-column"):
                yield Label("Sélectionnez vos plugins", classes="section-title")
                with ScrollableContainer(id="plugin-cards"):
                    yield from self._create_plugin_cards()

            # Colonne droite: plugins sélectionnés
            yield SelectedPluginsPanel(id="selected-plugins")

        # Boutons d'action en bas
        with Horizontal(id="button-container"):
            yield Button("Configurer", id="configure_selected", variant="primary")

        yield Footer()

    def _create_plugin_cards(self) -> List[PluginCard]:
        """
        Crée les cartes de plugins et de séquences.

        Returns:
            List[PluginCard]: Liste des cartes de plugins créées
        """
        plugin_cards = []
        plugins_dir = Path('plugins')

        try:
            # 1. Récupérer les plugins valides
            valid_plugins = self._discover_valid_plugins(plugins_dir)
            valid_plugins.sort(key=lambda x: x[0].lower())
            # 2. Ajouter les séquences comme plugins spéciaux
            self._add_sequences_to_plugins(valid_plugins)

            # 3. Trier et créer les cartes
            #valid_plugins.sort(key=lambda x: x[0].lower())
            for display_name, plugin_name in valid_plugins:
                plugin_cards.append(PluginCard(plugin_name))

            # 4. Si une séquence est spécifiée, la charger
            if self.sequence_file:
                self._load_sequence(self.sequence_file)

                # Si mode auto-exécution, passer directement à la configuration
                if self.auto_execute:
                    self.action_configure_selected()

            return plugin_cards

        except Exception as e:
            logger.error(f"Erreur lors de la découverte des plugins: {e}")
            logger.error(traceback.format_exc())
            return []

    def _discover_valid_plugins(self, plugins_dir: Path) -> List[Tuple[str, str]]:
        """
        Découvre les plugins valides dans le répertoire.

        Args:
            plugins_dir: Chemin vers le répertoire des plugins

        Returns:
            List[Tuple[str, str]]: Liste de tuples (nom_affichage, nom_plugin)
        """
        valid_plugins = []

        if not plugins_dir.exists():
            logger.error(f"Répertoire des plugins non trouvé: {plugins_dir}")
            return valid_plugins

        for plugin_path in plugins_dir.iterdir():
            if not plugin_path.is_dir():
                continue

            # Vérifier si c'est un plugin valide (settings.yml + exec.py/bash)
            settings_path = plugin_path / 'settings.yml'
            exec_py_path = plugin_path / 'exec.py'
            exec_bash_path = plugin_path / 'exec.bash'

            if (settings_path.exists() and (exec_py_path.exists() or exec_bash_path.exists())):
                try:
                    # Charger les infos du plugin
                    plugin_info = load_plugin_info(plugin_path.name)
                    display_name = plugin_info.get('name', plugin_path.name)
                    valid_plugins.append((display_name, plugin_path.name))

                    # Charger les templates du plugin
                    self.plugin_templates[plugin_path.name] = \
                        self.template_handler.get_plugin_templates(plugin_path.name)
                    logger.debug(f"Plugin valide trouvé: {plugin_path.name}, templates: {len(self.plugin_templates[plugin_path.name])}")
                except Exception as e:
                    logger.error(f"Erreur lors du chargement du plugin {plugin_path.name}: {e}")

        logger.info(f"Plugins valides trouvés: {len(valid_plugins)}")
        return valid_plugins

    def _add_sequences_to_plugins(self, valid_plugins: List[Tuple[str, str]]) -> None:
        """
        Ajoute les séquences disponibles à la liste des plugins.

        Args:
            valid_plugins: Liste des plugins valides à compléter
        """
        # Récupérer les séquences disponibles
        sequences = self.sequence_handler.get_available_sequences()
        logger.info(f"Séquences disponibles: {len(sequences)}")
        # Ajouter chaque séquence à la liste des plugins
        for seq in sequences:
            seq_name = seq['name']
            file_name = seq['file_name']
            # Ajouter directement la séquence sans préfixe dans le nom d'affichage
            valid_plugins.append((seq_name, f"__sequence__{file_name}"))
            logger.debug(f"Séquence ajoutée: {seq_name} ({file_name})")

    def _load_sequence(self, sequence_path: Path) -> None:
        """
        Charge une séquence depuis un fichier YAML.

        Args:
            sequence_path: Chemin vers le fichier de séquence
        """
        sequence = self.sequence_handler.load_sequence(sequence_path)
        if not sequence:
            logger.error(f"Impossible de charger la séquence: {sequence_path}")
            return

        try:
            # 1. Ajouter la séquence elle-même
            sequence_name = f"__sequence__{sequence_path.name}"
            self.selected_plugins.append((sequence_name, len(self.selected_plugins)))
            logger.info(f"Séquence ajoutée: {sequence_name}")

            # 2. Ajouter chaque plugin de la séquence
            for plugin_config in sequence['plugins']:
                self._add_sequence_plugin(plugin_config)

            # 3. Mettre à jour l'affichage
            self._update_selected_plugins_display()

            logger.info(f"Séquence chargée: {len(sequence['plugins'])} plugins")

        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence: {e}")
            logger.error(traceback.format_exc())

    def _add_sequence_plugin(self, plugin_config: Dict[str, Any]) -> None:
        """
        Ajoute un plugin de séquence à la liste des plugins sélectionnés.

        Args:
            plugin_config: Configuration du plugin dans la séquence
        """
        # Vérifier le format du plugin (dict ou str)
        if isinstance(plugin_config, dict) and 'name' in plugin_config:
            plugin_name = plugin_config['name']

            # Extraire la configuration
            config = {}
            if 'config' in plugin_config:
                config = plugin_config['config']
            elif 'variables' in plugin_config:  # Rétrocompatibilité
                config = plugin_config['variables']

            # Appliquer un template si spécifié
            if 'template' in plugin_config:
                template_name = plugin_config['template']
                if template_name in self.plugin_templates.get(plugin_name, {}):
                    logger.debug(f"Application du template {template_name} pour {plugin_name}")
                    plugin_config = self.template_handler.apply_template(
                        plugin_name, template_name, plugin_config
                    )
        elif isinstance(plugin_config, str):
            # Format simple: juste le nom du plugin
            plugin_name = plugin_config
            config = {}
        else:
            logger.error(f"Format de plugin invalide dans la séquence: {plugin_config}")
            return

        # Incrémenter le compteur d'instance global (pour tous les plugins)
        self.total_id += 1
        instance_id = self.total_id

        # Incrémenter aussi le compteur spécifique au plugin (pour l'affichage)
        if plugin_name not in self.instance_counter:
            self.instance_counter[plugin_name] = 0
        self.instance_counter[plugin_name] += 1

        # Ajouter à la liste des plugins sélectionnés
        self.selected_plugins.append((plugin_name, instance_id, config))
        logger.debug(f"Plugin ajouté depuis la séquence: {plugin_name} (ID: {instance_id}, Config: {config})")

    def _update_selected_plugins_display(self) -> None:
        """Met à jour l'affichage des plugins sélectionnés."""
        # Utiliser query au lieu de query_one pour éviter l'erreur si le widget n'est pas trouvé
        panels = self.query("#selected-plugins")
        if panels:
            # Si le panneau est trouvé, mettre à jour l'affichage
            panel = panels[0] # Prend le premier élément trouvé (normalement il n'y en a qu'un)
            panel.update_plugins(self.selected_plugins)
            logger.debug("Affichage des plugins sélectionnés mis à jour")
        else:
            # Loguer un avertissement si le panneau n'est pas trouvé, mais ne pas planter
            logger.warning("Le panneau '#selected-plugins' n'a pas été trouvé lors de la tentative de mise à jour de l'affichage.")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """
        Gère les clics sur les boutons de l'application.

        Args:
            event: Événement de bouton pressé
        """
        logger.debug(f"Bouton cliqué: {event.button.id}")

        if event.button.id == "configure_selected":
            await self.action_configure_selected()
        elif event.button.id == "quit":
            if self.auto_execute:
                # Sauvegarder le rapport avant de quitter
                self.save_execution_report()
            self.exit()

    def on_plugin_card_plugin_selection_changed(self, message: PluginCard.PluginSelectionChanged) -> None:
        """
        Gère les changements de sélection des plugins.

        Args:
            message: Message de changement de sélection
        """
        logger.debug(f"Changement sélection: {message.plugin_name} -> {message.selected}")

        # Vérifier si c'est une séquence
        if message.plugin_name.startswith('__sequence__'):
            if message.selected:
                # Charger la séquence
                seq_file = message.plugin_name.replace('__sequence__', '')
                sequence_path = Path('sequences') / seq_file
                self._load_sequence(sequence_path)
            return

        # Gestion normale des plugins
        if message.selected:
            self._add_plugin(message.plugin_name, message.source)
        else:
            self._remove_plugin(message.plugin_name)


    def _add_plugin(self, plugin_name: str, source_card: PluginCard) -> None:
        """
        Ajoute un plugin à la liste des plugins sélectionnés.

        Args:
            plugin_name: Nom du plugin à ajouter
            source_card: Carte source de l'événement
        """
        # Vérifier si le plugin est multiple
        plugin_info = load_plugin_info(plugin_name)
        multiple = plugin_info.get('multiple', False)

        # Si non multiple, vérifier qu'il n'est pas déjà sélectionné
        if not multiple and any(p[0] == plugin_name for p in self.selected_plugins):
            source_card.selected = False
            source_card.update_styles()
            return

        # Incrémenter le compteur d'instance global (pour tous les plugins)
        self.total_id += 1
        instance_id = self.total_id

        # Incrémenter aussi le compteur spécifique au plugin (pour l'affichage)
        if plugin_name not in self.instance_counter:
            self.instance_counter[plugin_name] = 0
        self.instance_counter[plugin_name] += 1

        # Ajouter à la sélection avec une configuration vide
        self.selected_plugins.append((plugin_name, instance_id, {}))
        logger.debug(f"Plugin ajouté: {plugin_name} (ID: {instance_id})")

        # Mettre à jour l'affichage
        self._update_selected_plugins_display()

    def _remove_plugin(self, plugin_name: str) -> None:
        """
        Retire un plugin de la liste des plugins sélectionnés.

        Args:
            plugin_name: Nom du plugin à retirer
        """
        # Filtrer pour garder seulement les plugins différents
        self.selected_plugins = [plugin_data for plugin_data in self.selected_plugins if plugin_data[0] != plugin_name]

        # Réinitialiser le compteur d'instance
        if plugin_name in self.instance_counter:
            del self.instance_counter[plugin_name]

        logger.debug(f"Plugin retiré: {plugin_name}")

        # Mettre à jour l'affichage
        self._update_selected_plugins_display()

    def on_plugin_card_add_plugin_instance(self, message: PluginCard.AddPluginInstance) -> None:
        """
        Gère l'ajout d'une instance pour les plugins multiples.

        Args:
            message: Message d'ajout d'instance
        """
        # Incrémenter le compteur d'instance global (pour tous les plugins)
        self.total_id += 1
        instance_id = self.total_id

        # Incrémenter aussi le compteur spécifique au plugin (pour l'affichage)
        if message.plugin_name not in self.instance_counter:
            self.instance_counter[message.plugin_name] = 0
        self.instance_counter[message.plugin_name] += 1

        # Ajouter la nouvelle instance avec une configuration vide
        self.selected_plugins.append((message.plugin_name, instance_id, {}))
        logger.debug(f"Instance supplémentaire ajoutée: {message.plugin_name} (ID: {instance_id})")

        # Mettre à jour l'affichage
        self._update_selected_plugins_display()

        # Effet visuel pour indiquer que l'instance a été ajoutée
        message.source.add_class("instance-added")

    async def action_configure_selected(self) -> None:
        """
        Passe à l'écran de configuration des plugins sélectionnés.
        """
        logger.debug("Début de la configuration des plugins sélectionnés")

        try:
            from ui.config_screen.config_screen import PluginConfig

            # Vérifier qu'il y a des plugins sélectionnés
            if not self.selected_plugins:
                logger.debug("Aucun plugin sélectionné")
                self.notify("Aucun plugin sélectionné", severity="error")
                return

            # Créer l'écran de configuration
            sequence_file = str(self.sequence_file) if self.sequence_file else None
            config_screen = PluginConfig(self.selected_plugins, sequence_file=sequence_file)

            # Afficher l'écran de configuration
            await self.push_screen(config_screen)
            logger.debug("Écran de configuration affiché")

            # Récupérer la configuration après retour
            if hasattr(config_screen, 'current_config'):
                config = config_screen.current_config
                logger.debug(f"Configuration récupérée: {len(config)} plugins")

                # Mettre à jour les configurations des plugins
                self._update_plugins_config(config)

                # Sauvegarder la séquence si nécessaire
                if self.sequence_file:
                    logger.debug(f"Sauvegarde de la séquence: {self.sequence_file}")
                    self._save_sequence(self.sequence_file)

                # En mode auto-exécution, passer à l'exécution
                if self.auto_execute:
                    logger.debug("Mode auto-exécution: passage à l'exécution")
                    execution_screen = ExecutionScreen(self.selected_plugins)
                    await self.push_screen(execution_screen)
            else:
                logger.debug("Pas de configuration retournée")

        except Exception as e:
            logger.error(f"Erreur lors de la configuration: {e}")
            logger.error(traceback.format_exc())
            self.notify(f"Erreur: {str(e)}", severity="error")

    def _update_plugins_config(self, config: Dict[str, Any]) -> None:
        """
        Met à jour les configurations des plugins sélectionnés.

        Args:
            config: Nouvelles configurations
        """
        updated_plugins = []

        # Parcourir tous les plugins sélectionnés
        for i, plugin_data in enumerate(self.selected_plugins):
            plugin_name, instance_id = plugin_data[0], plugin_data[1]

            # Récupérer la nouvelle config depuis l'ID unique
            plugin_key = f"{plugin_name}_{instance_id}"
            if plugin_key in config:
                new_config = config[plugin_key]
                # Créer un nouveau tuple avec la config mise à jour
                updated_plugins.append((plugin_name, instance_id, new_config))
                logger.debug(f"Config mise à jour pour {plugin_name} (ID: {instance_id})")
            else:
                # Garder l'ancienne config si elle existe
                updated_plugins.append(plugin_data)
                logger.debug(f"Pas de nouvelle config pour {plugin_name} (ID: {instance_id})")

        # Remplacer la liste des plugins
        self.selected_plugins = updated_plugins

        # Mettre à jour l'affichage
        self._update_selected_plugins_display()

    def _save_sequence(self, sequence_file: Path) -> bool:
        """
        Sauvegarde la liste des plugins sélectionnés dans un fichier de séquence.

        Args:
            sequence_file: Chemin du fichier de séquence

        Returns:
            bool: True si la sauvegarde a réussi
        """
        try:
            # Créer la structure de séquence
            sequence_data = {
                'name': sequence_file.stem,
                'description': f"Séquence générée automatiquement {sequence_file.name}",
                'plugins': []
            }

            # Ajouter chaque plugin (sauf les séquences)
            for plugin_data in self.selected_plugins:
                plugin_name = plugin_data[0]

                # Ignorer les séquences
                if plugin_name.startswith('__sequence__'):
                    continue

                # Construire la configuration du plugin
                if len(plugin_data) >= 3:
                    plugin_config = {
                        'name': plugin_name,
                        'config': plugin_data[2]
                    }
                else:
                    plugin_config = {
                        'name': plugin_name,
                        'config': {}
                    }

                sequence_data['plugins'].append(plugin_config)

            # Sauvegarder dans le fichier
            with open(sequence_file, 'w', encoding='utf-8') as f:
                self.sequence_handler.yaml.dump(sequence_data, f)

            logger.info(f"Séquence sauvegardée: {sequence_file}")
            return True

        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la séquence: {e}")
            logger.error(traceback.format_exc())
            return False

    def save_execution_report(self) -> None:
        """
        Sauvegarde le rapport d'exécution si configuré.
        """
        if not self.report_file:
            return

        try:
            # TODO: Implémentation du rapport d'exécution
            logger.info(f"Sauvegarde du rapport d'exécution: {self.report_file}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du rapport: {e}")

    def action_quit(self) -> None:
        """Quitte l'application."""
        logger.debug("Quitter l'application")
        self.exit()