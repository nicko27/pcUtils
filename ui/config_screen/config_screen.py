from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Container, ScrollableContainer, Horizontal, Vertical, VerticalGroup
from textual.widgets import Header, Footer, Button, Label, Checkbox
import os
import traceback
from ruamel.yaml import YAML
import asyncio
from typing import Dict, List, Tuple, Any, Optional, Set
from pathlib import Path

from ..utils.logging import get_logger
from ..choice_screen.plugin_utils import get_plugin_folder_name, get_plugin_settings_path
from .plugin_config_container import PluginConfigContainer
from .text_field import TextField
from .checkbox_field import CheckboxField
from .config_manager import ConfigManager
from .sequence_config_manager import SequenceConfigManager

logger = get_logger('config_screen')
# Configuration de ruamel.yaml pour préserver les commentaires
yaml = YAML()
yaml.preserve_quotes = True

class PluginConfig(Screen):
    """
    Écran de configuration des plugins.

    Cet écran permet de configurer les paramètres des plugins sélectionnés
    et de lancer leur exécution.
    """

    BINDINGS = [
        ("esc", "quit", "Quitter"),
    ]
    CSS_PATH = "../styles/config.tcss"

    def __init__(self, plugin_instances: List[Tuple[str, int, Optional[Dict]]],
                name: Optional[str] = None,
                sequence_file: Optional[str] = None) -> None:
        """
        Initialise l'écran de configuration.

        Args:
            plugin_instances: Liste des plugins à configurer (tuples plugin_name, instance_id, [config])
            name: Nom optionnel de l'écran
            sequence_file: Chemin optionnel vers un fichier de séquence
        """
        try:
            logger.debug("=== Début Initialisation de PluginConfig ===")
            super().__init__(name=name)

            # Initialisation des attributs
            self.plugin_instances = plugin_instances
            self.current_config = {}
            self.fields_by_plugin = {}
            self.fields_by_id = {}
            self.containers_by_id = {}
            self.plugins_remote_enabled = {}
            self.ssh_container = None
            self.sequence_file = sequence_file
            self.returning_from_execution = False

            # Initialiser le gestionnaire de séquence
            self.sequence_manager = SequenceConfigManager()

            # Initialiser le gestionnaire de configuration
            logger.debug("Création ConfigManager")
            self.config_manager = ConfigManager()

            # Charger les configurations
            self._load_configurations()

            logger.debug("PluginConfig initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing PluginConfig: {e}")
            logger.error(traceback.format_exc())
            raise

    def _load_configurations(self) -> None:
        """
        Charge toutes les configurations nécessaires.
        """
        try:
            # Récupérer le chemin racine du projet
            project_root = Path(__file__).parent.parent.parent

            # 1. Charger la configuration SSH
            ssh_config_path = project_root / 'ui' / 'ssh_manager' / 'ssh_fields.yml'
            logger.debug(f"Chargement config SSH depuis: {ssh_config_path}")
            self.config_manager.load_global_config('ssh', ssh_config_path)

            # 2. Charger les configurations des plugins
            for plugin_data in self.plugin_instances:
                # Extraire les informations du plugin
                if len(plugin_data) >= 3:
                    plugin_name, instance_id, _ = plugin_data
                else:
                    plugin_name, instance_id = plugin_data[:2]

                # Ignorer les séquences
                if plugin_name.startswith('__sequence__'):
                    continue

                # Charger la config du plugin depuis settings.yml
                settings_path = get_plugin_settings_path(plugin_name)
                logger.debug(f"Chargement config plugin depuis: {settings_path}")
                self.config_manager.load_plugin_config(plugin_name, settings_path)
                self.fields_by_plugin[plugin_name] = {}

                # MODIFICATION : Récupérer les valeurs par défaut
                default_values = self.config_manager.get_default_values(plugin_name)
                
                # Préparer l'ID d'instance unique
                plugin_instance_id = f"{plugin_name}_{instance_id}"
                
                # Si pas de configuration existante, charger les valeurs par défaut
                if plugin_instance_id not in self.current_config:
                    self.current_config[plugin_instance_id] = {
                        'plugin_name': plugin_name,
                        'instance_id': instance_id,
                        'config': default_values
                    }
                    logger.debug(f"Configuration par défaut chargée pour {plugin_instance_id}: {default_values}")


            # 3. Charger la séquence si spécifiée
            if self.sequence_file:
                try:
                    self.sequence_manager.load_sequence(self.sequence_file)
                    logger.debug(f"Séquence chargée: {self.sequence_manager.sequence_data}")
                except Exception as e:
                    logger.error(f"Erreur lors du chargement de la séquence: {e}")
                    logger.error(traceback.format_exc())

            # 4. Ajouter les configs existantes au sequence_manager
            for plugin_data in self.plugin_instances:
                if len(plugin_data) >= 3:
                    plugin_name, instance_id, config = plugin_data
                    if config:
                        self.sequence_manager.add_plugin_config(plugin_name, instance_id, config)
                        logger.debug(f"Config existante ajoutée pour {plugin_name}_{instance_id}")

            # 5. Appliquer les configurations finales
            self.current_config = self.sequence_manager.apply_configs_to_plugins(self.plugin_instances)
            logger.debug(f"Configurations finales après fusion: {self.current_config}")

        except Exception as e:
            logger.error(f"Erreur lors du chargement des configurations: {e}")
            logger.error(traceback.format_exc())
            # Initialiser une configuration vide en cas d'erreur
            self.current_config = {}

    def _initialize_default_config(self, plugin_name: str, instance_id: int) -> None:
        """
        Initialise la configuration par défaut d'un plugin.

        Args:
            plugin_name: Nom du plugin
            instance_id: ID d'instance du plugin
        """
        plugin_config = self.config_manager.plugin_configs.get(plugin_name, {})
        default_config = {'config': {}}

        # Récupérer les valeurs par défaut des champs
        for field_config in plugin_config.get('config_fields', {}).values():
            if isinstance(field_config, dict) and 'default' in field_config:
                variable_name = field_config.get('variable', field_config.get('id'))
                if variable_name is not None:
                    default_config['config'][variable_name] = field_config['default']
                    logger.debug(f"Valeur par défaut pour {plugin_name}.{variable_name}: {field_config['default']}")

        # Stocker la config par défaut
        plugin_instance_id = f"{plugin_name}_{instance_id}"
        self.current_config[plugin_instance_id] = default_config

    def compose(self) -> ComposeResult:
        """
        Compose l'interface de l'écran de configuration.

        Returns:
            ComposeResult: Résultat de la composition
        """
        try:
            logger.debug("PluginConfig.compose() started")

            yield Header()

            # Vérifier si des plugins supportent l'exécution à distance
            remote_plugins = self._get_remote_execution_plugins()
            has_remote_plugins = len(remote_plugins) > 0
            logger.debug(f"Has remote plugins: {has_remote_plugins}")

            # Titre de la configuration
            yield Label("Configuration des plugins", id="window-config-title", classes="section-title")

            # Conteneur principal avec défilement
            with ScrollableContainer(id="config-container-list"):
                # Ajouter les configurations de plugins
                for plugin_data in self.plugin_instances:
                    # Extraire les données du plugin
                    if len(plugin_data) >= 3:
                        plugin_name, instance_id, _ = plugin_data
                    else:
                        plugin_name, instance_id = plugin_data[:2]

                    # Ignorer les séquences
                    if plugin_name.startswith('__sequence__'):
                        continue

                    logger.debug(f"Creating config for plugin: {plugin_name}_{instance_id}")
                    plugin_container = self._create_plugin_config(plugin_name, instance_id)

                    # Vérifier que le container a été créé
                    if plugin_container is None:
                        logger.warning(f"Impossible de créer le conteneur pour {plugin_name}_{instance_id}")
                        continue

                    # Ajouter la case à cocher d'exécution distante si nécessaire
                    if plugin_name in remote_plugins:
                        self._add_remote_execution_checkbox(plugin_container, plugin_name, instance_id)

                    # Monter le conteneur
                    yield plugin_container

                # Ajouter le conteneur SSH vide si nécessaire
                if has_remote_plugins:
                    logger.debug("Ajout du conteneur SSH (contenu ajouté dans on_mount)")
                    self.ssh_container = Container(
                        id="ssh-config",
                        classes="ssh-container config-fields disabled-container disabled-ssh-container"
                    )
                    yield self.ssh_container

                # Ajouter un espace en bas pour le défilement
                yield Container(classes="scroll-spacer")

            # Boutons d'action
            with Horizontal(id="button-container-config"):
                with Vertical(id="button-container-config-left"):
                    yield Button("Retour", id="config-return", variant="error")
                with Vertical(id="button-container-config-right"):
                    yield Button("Exécuter", id="config-execute", variant="primary")

            yield Footer()

            logger.debug("PluginConfig.compose() completed")

        except Exception as e:
            logger.error(f"Error in PluginConfig.compose(): {e}")
            logger.error(traceback.format_exc())

            # En cas d'erreur, au moins retourner des widgets de base
            yield Label("Une erreur s'est produite lors du chargement de la configuration", id="error-message")
            yield Button("Retour", id="config-return", variant="error")

    async def on_mount(self) -> None:
        """
        Méthode appelée lors du montage de l'écran.
        """
        try:
            # Créer les conteneurs et les champs
            self.call_after_refresh(self.create_config_fields)

            # Restaurer les valeurs si on revient de l'écran d'exécution
            if self.returning_from_execution and self.current_config:
                logger.debug(f"Restauration de la configuration préservée")
                await asyncio.sleep(0.1)  # Délai pour la stabilisation du DOM
                self.call_after_refresh(self.restore_saved_configuration)

            logger.debug("PluginConfig.on_mount() completed")
        except Exception as e:
            logger.error(f"Error in PluginConfig.on_mount(): {e}")
            logger.error(traceback.format_exc())

    def create_config_fields(self) -> None:
        """
        Crée tous les champs de configuration.
        """
        try:
            logger.debug("Création des champs de configuration")

            # Réinitialiser le dictionnaire des containers
            self.containers_by_id = {}

            # Récupérer tous les containers de configuration
            config_containers = self.query(".config-container")
            logger.debug(f"Nombre de containers trouvés: {len(config_containers)}")

            # Indexer les containers par ID
            for container in config_containers:
                if hasattr(container, 'id'):
                    self.containers_by_id[container.id] = container
                    logger.debug(f"Container ajouté: {container.id}")

                    # Ajouter les champs du container à fields_by_id
                    if hasattr(container, 'fields_by_id'):
                        for field_id, field in container.fields_by_id.items():
                            self.fields_by_id[field_id] = field
                            logger.debug(f"Champ ajouté: {field_id}")

            # Ajouter les champs SSH au container SSH
            if self.ssh_container:
                self._populate_ssh_container()

            logger.debug(f"Total de {len(self.containers_by_id)} containers et {len(self.fields_by_id)} champs")
        except Exception as e:
            logger.error(f"Erreur lors de la création des champs de configuration: {e}")
            logger.error(traceback.format_exc())

    def _populate_ssh_container(self) -> None:
        """
        Remplit le conteneur SSH avec les champs de configuration.
        """
        try:
            # Obtenir les définitions de champs SSH
            ssh_config = self.config_manager.global_configs.get('ssh', {})
            ssh_fields = ssh_config.get('config_fields', {})

            if not ssh_fields:
                logger.warning("Aucun champ SSH trouvé dans la configuration")
                return

            logger.debug(f"Création de {len(ssh_fields)} champs SSH")

            # Ajouter un titre
            self.ssh_container.mount(Label("Configuration SSH", classes="section-title"))

            # Créer chaque champ selon son type
            from .text_field import TextField
            from .ip_field import IPField
            from .password_field import PasswordField
            from .checkbox_field import CheckboxField

            for field_id, field_config in ssh_fields.items():
                field_type = field_config.get('type', 'text')
                field_class = {
                    'text': TextField,
                    'ip': IPField,
                    'password': PasswordField,
                    'checkbox': CheckboxField
                }.get(field_type, TextField)

                # Créer et monter le champ
                field = field_class('ssh', field_id, field_config, self.fields_by_id)
                self.ssh_container.mount(field)

                # Enregistrer le champ
                self.fields_by_id[field_id] = field

            logger.debug("Conteneur SSH rempli avec succès")
        except Exception as e:
            logger.error(f"Erreur lors du remplissage du conteneur SSH: {e}")
            logger.error(traceback.format_exc())

    def _create_plugin_config(self, plugin: str, instance_id: int) -> Optional[Container]:
        """
        Crée un conteneur de configuration pour un plugin.

        Args:
            plugin: Nom du plugin
            instance_id: ID d'instance

        Returns:
            Optional[Container]: Conteneur créé ou None en cas d'erreur
        """
        try:
            # Vérifier si c'est une séquence
            if plugin.startswith('__sequence__'):
                logger.warning(f"Ignorer la configuration de la séquence: {plugin}")
                return None

            # Récupérer la configuration du plugin
            plugin_config = self.config_manager.plugin_configs.get(plugin, {})
            if not plugin_config:
                logger.error(f"Configuration non trouvée pour {plugin}")
                container = Container(id=f"plugin_{plugin}_{instance_id}", classes="config-container")
                return container

            # Préparer les champs
            self.fields_by_plugin[plugin] = {}
            fields_by_id = self.fields_by_id

            # Récupérer les métadonnées du plugin
            name = plugin_config.get('name', plugin)
            icon = plugin_config.get('icon', '📦')
            description = plugin_config.get('description', '')

            # Préparer les configurations de champs avec valeurs prédéfinies
            config_fields = []
            for field_id, field_config in plugin_config.get('config_fields', {}).items():
                # Créer une copie de la configuration
                field_config_copy = field_config.copy()
                field_config_copy['id'] = field_id

                # Appliquer les valeurs prédéfinies de la séquence/configuration
                plugin_instance_id = f"{plugin}_{instance_id}"
                
                # Générer un ID unique pour ce champ dans cette instance spécifique
                unique_field_id = f"{field_id}_{instance_id}"
                field_config_copy['unique_id'] = unique_field_id
                
                # Appliquer les valeurs prédéfinies si disponibles
                if plugin_instance_id in self.current_config:
                    predefined_config = self.current_config[plugin_instance_id]
                    variable_name = field_config_copy.get('variable', field_id)

                    # Chercher dans 'config' (nouveau format)
                    if 'config' in predefined_config and variable_name in predefined_config['config']:
                        value = predefined_config['config'][variable_name]
                        logger.debug(f"Valeur prédéfinie trouvée pour {plugin_instance_id}.{field_id} = {value}")
                        field_config_copy['default'] = value

                config_fields.append(field_config_copy)

            # Créer le conteneur
            return PluginConfigContainer(
                plugin=plugin,
                name=name,
                icon=icon,
                description=description,
                fields_by_plugin=self.fields_by_plugin,
                fields_by_id=fields_by_id,
                config_fields=config_fields,
                id=f"plugin_{plugin}_{instance_id}",
                classes="config-container"
            )

        except Exception as e:
            logger.error(f"Erreur dans _create_plugin_config pour {plugin}: {e}")
            logger.error(traceback.format_exc())
            return None

    def _add_remote_execution_checkbox(self, container: Container, plugin_name: str, instance_id: int) -> None:
        """
        Ajoute une case à cocher pour l'exécution distante à un conteneur.

        Args:
            container: Conteneur de configuration du plugin
            plugin_name: Nom du plugin
            instance_id: ID d'instance
        """
        try:
            logger.debug(f"Ajout de la case à cocher d'exécution distante pour {plugin_name}_{instance_id}")

            # Créer un ID unique
            remote_field_id = f"remote_exec_{plugin_name}_{instance_id}"

            # Configuration de la case à cocher
            remote_config = {
                "type": "checkbox",
                "label": "⚠️  Activer l'exécution distante pour ce plugin",
                "description": "Cochez cette case pour exécuter ce plugin via SSH sur des machines distantes",
                "default": False,
                "id": remote_field_id,
                "variable": "remote_execution_enabled",
                "required": True
            }

            # Créer le champ
            remote_field = CheckboxField(plugin_name, remote_field_id, remote_config, self.fields_by_id, is_global=False)
            remote_field.add_class("remote-execution-checkbox")

            # Enregistrer pour future référence
            self.fields_by_plugin[plugin_name][remote_field_id] = remote_field
            self.plugins_remote_enabled[f"{plugin_name}_{instance_id}"] = remote_field

            # Associer au conteneur
            container.remote_field = remote_field

        except Exception as e:
            logger.error(f"Erreur lors de l'ajout de la case à cocher d'exécution distante: {e}")

    def _get_remote_execution_plugins(self) -> List[str]:
        """
        Identifie les plugins qui supportent l'exécution à distance.

        Returns:
            List[str]: Liste des noms de plugins supportant l'exécution à distance
        """
        try:
            remote_plugins = []

            for plugin_data in self.plugin_instances:
                # Extraire le nom du plugin
                if len(plugin_data) >= 3:
                    plugin_name, _, _ = plugin_data
                else:
                    plugin_name = plugin_data[0]

                # Ignorer les séquences
                if plugin_name.startswith('__sequence__'):
                    continue

                # Vérifier si le plugin supporte l'exécution distante
                settings_path = get_plugin_settings_path(plugin_name)

                try:
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        settings = yaml.load(f)
                        if settings.get('remote_execution', False):
                            logger.debug(f"Plugin avec support d'exécution distante trouvé: {plugin_name}")
                            remote_plugins.append(plugin_name)
                except Exception as e:
                    logger.error(f"Erreur lors de la lecture de {settings_path}: {e}")

            return remote_plugins

        except Exception as e:
            logger.error(f"Erreur dans get_remote_execution_plugins: {e}")
            return []

    def restore_saved_configuration(self) -> None:
        """
        Restaure la configuration sauvegardée.
        """
        try:
            if not self.current_config:
                logger.debug("Pas de configuration à restaurer")
                return

            logger.debug(f"Début de la restauration pour {len(self.current_config)} plugins")

            # Parcourir tous les plugins
            for plugin_id, plugin_config in self.current_config.items():
                logger.debug(f"Restauration pour {plugin_id}")

                # Extraire le nom du plugin et la configuration
                plugin_name = plugin_id.split('_')[0]
                config = plugin_config.get('config', {})

                # Mettre à jour chaque champ
                for param_name, value in config.items():
                    field_id = f"{plugin_name}.{param_name}"

                    if field_id in self.fields_by_id:
                        field = self.fields_by_id[field_id]
                        logger.debug(f"Restauration du champ {field_id} avec {value}")

                        # Mettre à jour la valeur
                        if hasattr(field, 'set_value'):
                            field.set_value(value)
                        elif hasattr(field, 'value'):
                            field.value = value

                            # Mettre à jour le widget associé si possible
                            self._update_field_widget(field, value)

                # Restaurer l'état d'exécution distante
                remote_enabled = plugin_config.get('remote_execution', False)
                if plugin_id in self.plugins_remote_enabled:
                    logger.debug(f"Restauration de l'état SSH pour {plugin_id}: {remote_enabled}")
                    remote_field = self.plugins_remote_enabled[plugin_id]
                    remote_field.set_value(remote_enabled)

                    # Activer/désactiver la configuration SSH
                    if remote_enabled:
                        self.toggle_ssh_config(True)

            # Mettre à jour les dépendances
            self.update_all_dependencies()
            logger.debug("Restauration terminée")

        except Exception as e:
            logger.error(f"Erreur lors de la restauration: {e}")
            logger.error(traceback.format_exc())

    def _update_field_widget(self, field: Any, value: Any) -> None:
        """
        Met à jour le widget d'un champ avec une valeur.

        Args:
            field: Champ à mettre à jour
            value: Nouvelle valeur
        """
        try:
            # Différents types de widgets
            if hasattr(field, 'input'):
                field.input.value = str(value) if value is not None else ""
            elif hasattr(field, 'select'):
                field.select.value = value
            elif hasattr(field, 'checkbox'):
                field.checkbox.value = bool(value)
        except Exception as e:
            logger.debug(f"Erreur lors de la mise à jour du widget pour {field.field_id}: {e}")

    def update_all_dependencies(self) -> None:
        """
        Met à jour toutes les dépendances entre champs.
        Compatible avec la nouvelle structure standardisée des dépendances.
        """
        try:
            logger.debug("Mise à jour de toutes les dépendances")

            # Parcourir tous les conteneurs
            for container_id, container in self.containers_by_id.items():
                # Vérifier si c'est un ConfigContainer avec notre nouvelle structure de dépendances
                if hasattr(container, 'dependency_map'):
                    # Nouvelle méthode pour ConfigContainer modifié
                    self._update_dependencies_new(container)
                elif hasattr(container, 'update_dependent_fields'):
                    # Ancienne méthode pour compatibilité
                    self._update_dependencies_legacy(container)
                else:
                    logger.debug(f"Le conteneur {container_id} n'a pas de mécanisme de dépendances")
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des dépendances: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _update_dependencies_new(self, container) -> None:
        """
        Met à jour les dépendances avec la nouvelle structure standardisée.
        
        Args:
            container: Un conteneur utilisant la nouvelle structure dependency_map
        """
        # Stratégie : déclencher la mise à jour pour chaque champ source de dépendances
        processed_fields = set()
        
        # Pour chaque type de dépendance
        for dep_type in container.dependency_map:
            # Pour chaque champ source dans le cache des dépendances
            if hasattr(container, '_dependency_cache') and dep_type in container._dependency_cache:
                for source_field_id in container._dependency_cache[dep_type]:
                    # Éviter de traiter plusieurs fois le même champ
                    if source_field_id in processed_fields:
                        continue
                        
                    # Récupérer le champ source
                    if source_field_id in container.fields_by_id:
                        source_field = container.fields_by_id[source_field_id]
                        # Déclencher la mise à jour des dépendances
                        container.update_dependent_fields(source_field)
                        processed_fields.add(source_field_id)

    def _update_dependencies_legacy(self, container) -> None:
        """
        Met à jour les dépendances avec l'ancienne structure.
        
        Args:
            container: Un conteneur utilisant l'ancienne structure de dépendances
        """
        # Ancienne méthode : mise à jour pour chaque champ du conteneur
        for field_id, field in container.fields_by_id.items():
            container.update_dependent_fields(field)
            logger.debug(f"Dépendances mises à jour pour {field_id}")
            
    async def on_button_pressed(self, event: Button.Pressed) -> None:
            """
            Gère les clics sur les boutons.

            Args:
                event: Événement de bouton pressé
            """
            logger.debug(f"Bouton pressé: {event.button.id}")

            try:
                if event.button.id == "config-return":
                    logger.debug("Retour à l'écran précédent")
                    self.app.pop_screen()

                elif event.button.id == "config-execute":
                    logger.debug("Validation et passage à l'exécution")

                    # Vérifier tous les champs
                    if self._validate_all_fields():
                        # Collecter les configurations
                        self.collect_configurations()
                        logger.debug(f"Configuration finale: {len(self.current_config)} plugins")

                        # Créer l'écran d'exécution
                        try:
                            from ..execution_screen.execution_screen import ExecutionScreen
                            execution_screen = ExecutionScreen(self.current_config)
                            self.app.switch_screen(execution_screen)
                        except Exception as e:
                            logger.error(f"Erreur lors du passage à l'écran d'exécution: {e}")
                            logger.error(traceback.format_exc())
                            self.notify("Erreur lors du passage à l'exécution", severity="error")
            except Exception as e:
                logger.error(f"Erreur dans on_button_pressed: {e}")
                logger.error(traceback.format_exc())

    def _validate_all_fields(self) -> bool:
        """
        Valide tous les champs de configuration.

        Returns:
            bool: True si tous les champs sont valides
        """
        has_errors = False

        # Vérifier les champs SSH si nécessaires
        has_remote_enabled = False
        for plugin_key, field in self.plugins_remote_enabled.items():
            if field.get_value():
                has_remote_enabled = True
                break

        # Valider tous les champs de texte
        for field_id, field in self.fields_by_id.items():
            # Ignorer les champs désactivés
            if hasattr(field, 'disabled') and field.disabled:
                continue

            # Valider les champs de texte
            if isinstance(field, TextField) and hasattr(field, 'input'):
                value = field.input.value
                is_valid, error_msg = field.validate_input(value)

                if not is_valid:
                    field.input.add_class('error')
                    field.input.tooltip = error_msg
                    has_errors = True
                    logger.error(f"Erreur de validation pour {field_id}: {error_msg}")

        if has_errors:
            self.notify("Veuillez corriger les erreurs de validation", severity="error")
            return False

        return True

    def collect_configurations(self) -> None:
        """
        Collecte les configurations de tous les champs.
        """
        try:
            logger.debug("Collecte des configurations")
            self.current_config = {}

            # Récupérer la configuration SSH
            ssh_config = self._collect_ssh_config()

            # Collecter pour chaque plugin
            for plugin_instance in self.plugin_instances:
                # Ignorer les séquences
                if plugin_instance[0].startswith('__sequence__'):
                    continue

                # Extraire les informations du plugin
                if len(plugin_instance) >= 3:
                    plugin_name, instance_id, _ = plugin_instance
                else:
                    plugin_name, instance_id = plugin_instance[:2]

                logger.debug(f"Collecte pour {plugin_name}_{instance_id}")

                # Vérifier si le plugin supporte l'exécution distante
                plugin_settings = self.config_manager.plugin_configs.get(plugin_name, {})
                supports_remote = plugin_settings.get('remote_execution', False)

                # Vérifier si l'exécution distante est activée pour ce plugin
                plugin_key = f"{plugin_name}_{instance_id}"
                remote_enabled = False
                if plugin_key in self.plugins_remote_enabled:
                    remote_enabled = self.plugins_remote_enabled[plugin_key].get_value()

                # Récupérer les valeurs des champs
                config_values = self._collect_plugin_field_values(plugin_name, instance_id)

                # Ajouter les variables SSH si nécessaire
                if supports_remote and remote_enabled:
                    config_values.update(ssh_config)
                    config_values["remote_execution"] = True
                else:
                    config_values["remote_execution"] = False

                # Créer la configuration complète
                self.current_config[plugin_key] = {
                    'plugin_name': plugin_name,
                    'instance_id': instance_id,
                    'name': plugin_settings.get('name', plugin_name),
                    'show_name': plugin_settings.get('show_name', plugin_settings.get('plugin_name', plugin_name)),
                    'icon': plugin_settings.get('icon', '📦'),
                    'config': config_values,
                    'remote_execution': supports_remote and remote_enabled
                }

                logger.debug(f"Configuration collectée pour {plugin_key}")

            logger.debug(f"Configuration finale: {len(self.current_config)} plugins")
        except Exception as e:
            logger.error(f"Erreur lors de la collecte des configurations: {e}")
            logger.error(traceback.format_exc())
            # Assurer qu'on a au moins une config vide
            self.current_config = {}

    def _collect_ssh_config(self) -> Dict[str, Any]:
        """
        Collecte la configuration SSH.

        Returns:
            Dict[str, Any]: Configuration SSH
        """
        ssh_config = {}

        # Collecter tous les champs SSH
        ssh_fields = [f for f in self.fields_by_id.values()
                     if hasattr(f, 'source_id') and f.source_id == 'ssh']

        if ssh_fields:
            logger.debug(f"Collecte de {len(ssh_fields)} champs SSH")

            # Récupérer les valeurs de chaque champ
            for field in ssh_fields:
                if hasattr(field, 'field_id') and hasattr(field, 'get_value'):
                    ssh_config[field.field_id] = field.get_value()
                    logger.debug(f"SSH: {field.field_id} = {ssh_config[field.field_id]}")

        return ssh_config

    def _collect_plugin_field_values(self, plugin_name: str, instance_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Collecte les valeurs des champs d'un plugin.
        
        Args:
            plugin_name: Nom du plugin
            instance_id: ID d'instance optionnel pour différencier les instances multiples
        
        Returns:
            Dict[str, Any]: Valeurs des champs du plugin
        """
        config_values = {}

        # Trouver tous les champs du plugin
        if instance_id is not None:
            # Si un ID d'instance est spécifié, filtrer les champs par plugin ET instance
            plugin_instance_id = f"{plugin_name}_{instance_id}"
            container_id = f"plugin_{plugin_instance_id}"
            
            # Récupérer le conteneur spécifique à cette instance
            container = self.containers_by_id.get(container_id)
            
            if container and hasattr(container, 'fields_by_id'):
                # Utiliser les champs de ce conteneur spécifique
                # Filtrer pour ne récupérer que les champs qui ont un ID unique correspondant à cette instance
                plugin_fields = []
                for field in container.fields_by_id.values():
                    # Vérifier si le champ a un attribut unique_id qui correspond à cette instance
                    if hasattr(field, 'unique_id'):
                        if f"_{instance_id}" in field.unique_id:
                            plugin_fields.append(field)
                            logger.debug(f"Champ avec unique_id {field.unique_id} ajouté pour la collecte")
                    elif hasattr(field, 'source_id') and field.source_id == plugin_name:
                        # Fallback pour les champs sans ID unique
                        plugin_fields.append(field)
                        logger.debug(f"Fallback: Champ {field.field_id} ajouté pour la collecte (pas d'unique_id)")
                
                logger.debug(f"Collecte de {len(plugin_fields)} champs pour l'instance spécifique {plugin_instance_id}")
            else:
                # Fallback: filtrer par nom de plugin uniquement
                plugin_fields = [field for field in self.fields_by_id.values()
                                if hasattr(field, 'source_id') and field.source_id == plugin_name and
                                not field.field_id.startswith(f"remote_exec_{plugin_name}")]
                logger.debug(f"Conteneur {container_id} non trouvé, fallback au filtrage par nom de plugin")
        else:
            # Comportement original: filtrer par nom de plugin uniquement
            plugin_fields = [field for field in self.fields_by_id.values()
                            if hasattr(field, 'source_id') and field.source_id == plugin_name and
                            not field.field_id.startswith(f"remote_exec_{plugin_name}")]

        logger.debug(f"Collecte de {len(plugin_fields)} champs pour {plugin_name}")

        # Récupérer les valeurs de chaque champ
        for field in plugin_fields:
            if hasattr(field, 'variable_name') and hasattr(field, 'get_value'):
                # Utiliser le nom de variable pour l'export
                var_name = field.variable_name
                value = field.get_value()

                # Traitement spécial pour les checkbox_group
                if hasattr(field, 'field_config') and field.field_config.get('type') == 'checkbox_group':
                    # Assurer que c'est une liste
                    if not value:
                        value = []
                    elif not isinstance(value, list):
                        value = [value]

                config_values[var_name] = value
                logger.debug(f"Champ {plugin_name}.{field.field_id} (var: {var_name}) = {value}")

        return config_values

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """
        Gère les changements d'état des cases à cocher.
        
        Args:
            event: Événement de changement de case à cocher
        """
        try:
            checkbox_id = event.checkbox.id
            value = event.value
            logger.debug(f"Checkbox changée: {checkbox_id} -> {value}")

            # Vérifier si c'est une case à cocher d'exécution distante
            is_remote_checkbox = False
            for plugin_key, field in self.plugins_remote_enabled.items():
                if hasattr(field, 'source_id') and checkbox_id == f"checkbox_{field.source_id}_{field.field_id}":
                    is_remote_checkbox = True
                    break

            if is_remote_checkbox:
                # Vérifier si au moins un plugin a l'exécution distante activée
                has_remote_enabled = False
                for _, field in self.plugins_remote_enabled.items():
                    if field.get_value():
                        has_remote_enabled = True
                        break

                # Activer/désactiver la configuration SSH
                self.toggle_ssh_config(has_remote_enabled)
                
            # Vérifier si c'est une autre case à cocher SSH
            elif checkbox_id.startswith("checkbox_ssh_"):
                # Extraire l'ID du champ
                field_id = checkbox_id.replace("checkbox_ssh_", "")
                
                # Parcourir tous les champs SSH
                for ssh_field_id, ssh_field in self.fields_by_id.items():
                    if hasattr(ssh_field, 'enabled_if') and ssh_field.enabled_if and ssh_field.enabled_if.get('field') == field_id:
                        # Si ce champ dépend du champ qui a changé
                        logger.debug(f"Vérification du champ dépendant {ssh_field_id} qui dépend de {field_id}")
                        
                        # Activer/désactiver le champ selon la condition
                        should_enable = value == ssh_field.enabled_if.get('value')
                        self.toggle_field_state(ssh_field, should_enable)
                        logger.debug(f"État du champ {ssh_field_id} mis à jour: {'activé' if should_enable else 'désactivé'}")
                        
            else:                        
                for field_id, field in self.fields_by_id.items():
                    if hasattr(field, 'source_id') and hasattr(field, 'field_id') and checkbox_id == f"checkbox_{field.source_id}_{field.field_id}":
                        logger.debug(f"Notification des dépendances pour le champ {field_id}")
                        
                        # Trouver le conteneur parent
                        container = None
                        for container_id, container_obj in self.containers_by_id.items():
                            if hasattr(container_obj, 'fields_by_id') and field_id in container_obj.fields_by_id:
                                container = container_obj
                                break
                        
                        # Mettre à jour les dépendances
                        if container and hasattr(container, 'update_dependent_fields'):
                            container.update_dependent_fields(field)
                        break

        except Exception as e:
            logger.error(f"Erreur dans on_checkbox_changed: {e}")       

    def toggle_ssh_config(self, enable: bool) -> None:
        """
        Active ou désactive la configuration SSH.

        Args:
            enable: True pour activer, False pour désactiver
        """
        try:
            logger.debug(f"Configuration SSH: {enable}")

            if self.ssh_container:
                # Modifier les classes du conteneur
                if enable:
                    self.ssh_container.remove_class("disabled-ssh-container")
                    self.ssh_container.remove_class("disabled-container")
                else:
                    self.ssh_container.add_class("disabled-ssh-container")
                    self.ssh_container.add_class("disabled-container")

                # Mettre à jour l'état des champs
                for field_id, field in self.fields_by_id.items():
                    if hasattr(field, 'source_id') and field.source_id == 'ssh':
                        self.toggle_field_state(field, enable)

        except Exception as e:
            logger.error(f"Erreur dans toggle_ssh_config: {e}")

    def toggle_field_state(self, field: Any, enable: bool) -> None:
        """
        Active ou désactive un champ et ses widgets.

        Args:
            field: Champ à modifier
            enable: True pour activer, False pour désactiver
        """
        try:
            # Vérifier les conditions d'activation
            if hasattr(field, 'enabled_if') and field.enabled_if:
                # Récupérer le champ dont dépend l'activation
                dep_field_id = field.enabled_if['field']
                dep_field = self.fields_by_id.get(dep_field_id)

                if dep_field:
                    # Vérifier si la condition est satisfaite
                    dep_value = dep_field.get_value()
                    required_value = field.enabled_if['value']

                    logger.debug(f"Condition d'activation pour {field.field_id}: {dep_field_id}={dep_value}, requis={required_value}")

                    # Si la condition n'est pas satisfaite, forcer la désactivation
                    if dep_value != required_value:
                        logger.debug(f"Champ {field.field_id} désactivé en raison de enabled_if")
                        enable = False

            # Définir l'état du champ
            field.disabled = not enable

            # Mettre à jour les widgets selon leur type
            if hasattr(field, 'input'):
                field.input.disabled = not enable
                if enable:
                    field.input.remove_class('disabled')

                    # Restaurer la valeur si on active
                    self._restore_field_value(field)
                else:
                    field.input.add_class('disabled')

            elif hasattr(field, 'checkbox'):
                field.checkbox.disabled = not enable
                if enable:
                    field.checkbox.remove_class('disabled')
                else:
                    field.checkbox.add_class('disabled')

            elif hasattr(field, 'select'):
                field.select.disabled = not enable
                if enable:
                    field.select.remove_class('disabled')

                    # Restaurer la valeur si on active
                    self._restore_field_value(field)
                else:
                    field.select.add_class('disabled')

        except Exception as e:
            logger.error(f"Erreur dans toggle_field_state: {e}")

    def _restore_field_value(self, field: Any) -> None:
        """
        Restaure la valeur par défaut d'un champ.

        Args:
            field: Champ à restaurer
        """
        try:
            # Cas 1: Valeur dynamique
            if hasattr(field, 'field_config') and 'dynamic_default' in field.field_config:
                if hasattr(field, '_get_dynamic_default'):
                    dynamic_value = field._get_dynamic_default()
                    if dynamic_value:
                        logger.debug(f"Restauration de la valeur dynamique pour {field.field_id}: {dynamic_value}")
                        if hasattr(field, 'set_value'):
                            field.set_value(dynamic_value)
                        else:
                            field.value = dynamic_value

                            if hasattr(field, 'input'):
                                field.input.value = str(dynamic_value)
                            elif hasattr(field, 'select'):
                                field.select.value = str(dynamic_value)

            # Cas 2: Valeur statique par défaut
            elif hasattr(field, 'field_config') and 'default' in field.field_config:
                default_value = field.field_config['default']
                logger.debug(f"Restauration de la valeur par défaut pour {field.field_id}: {default_value}")

                if hasattr(field, 'set_value'):
                    field.set_value(default_value)
                else:
                    field.value = default_value

                    if hasattr(field, 'input'):
                        field.input.value = str(default_value)
                    elif hasattr(field, 'select'):
                        field.select.value = str(default_value)

        except Exception as e:
            logger.error(f"Erreur dans _restore_field_value: {e}")

    def action_quit(self) -> None:
        """Gère l'action de quitter l'écran."""
        logger.debug("Quitter l'écran de configuration")
        self.app.pop_screen()