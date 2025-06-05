from textual.app import ComposeResult
from textual.widgets import Checkbox
from textual.containers import VerticalGroup
from typing import Any, Optional, Union, Dict

from .config_field import ConfigField
from ..utils.logging import get_logger

logger = get_logger('checkbox_field')

class CheckboxField(ConfigField):
    """
    Champ case à cocher avec valeur booléenne.

    Ce champ permet la sélection binaire (oui/non) et gère la conversion
    des différents formats en booléens.
    """

    def __init__(self, source_id: str, field_id: str, field_config: Dict[str, Any],
                 fields_by_id: Optional[Dict[str, Any]] = None, is_global: bool = False):
        """
        Initialisation du champ case à cocher.

        Args:
            source_id: Identifiant de la source (plugin ou config globale)
            field_id: Identifiant du champ
            field_config: Configuration du champ
            fields_by_id: Dictionnaire des champs par ID
            is_global: Si True, c'est un champ global
        """
        super().__init__(source_id, field_id, field_config, fields_by_id, is_global)

        # S'assurer que la valeur est normalisée en booléen
        self.value = self._normalize_boolean(self.value)

    def compose(self) -> ComposeResult:
        """
        Création des éléments visuels du champ.

        Returns:
            ComposeResult: Éléments UI du champ
        """
        # Rendre les éléments de base (label, etc.)
        yield from super().compose()

        # Essayer de récupérer la valeur de la configuration/séquence
        self._try_load_sequence_value()

        # Conteneur pour la checkbox
        with VerticalGroup(classes="checkbox-container"):
            logger.debug(f"Création de la checkbox {self.field_id} avec valeur {self.value}")

            # Création du widget Checkbox
            self.checkbox = Checkbox(
                id=f"checkbox_{self.source_id}_{self.field_id}",
                value=self.value,
                classes="field-checkbox"
            )

            # État initial: activé sauf si explicitement désactivé
            self.checkbox.disabled = self.disabled if hasattr(self, 'disabled') else False

            if hasattr(self, 'disabled') and self.disabled:
                self.checkbox.add_class('disabled')
            else:
                self.checkbox.remove_class('disabled')

            yield self.checkbox

    def _normalize_boolean(self, value: Any) -> bool:
        """
        Normalise une valeur en booléen.

        Args:
            value: Valeur à normaliser

        Returns:
            bool: Valeur booléenne normalisée
        """
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.lower() in ('true', 't', 'yes', 'y', '1', 'on')

        # Par défaut, conversion standard
        return bool(value)

    def _try_load_sequence_value(self) -> None:
        """
        Essaie de charger la valeur depuis la configuration prédéfinie (séquence).
        """
        try:
            # Rechercher l'écran de configuration dans la hiérarchie
            from .config_screen import PluginConfig

            # Récupérer l'application
            app = self.app if hasattr(self, 'app') and self.app else None
            if not app or not hasattr(app, 'screen') or not isinstance(app.screen, PluginConfig):
                return

            config_screen = app.screen

            # Récupérer le conteneur parent
            from .plugin_config_container import PluginConfigContainer
            parent = next((a for a in self.ancestors_with_self if isinstance(a, PluginConfigContainer)), None)
            if not parent or not hasattr(parent, 'id'):
                return

            # Récupérer l'ID unique de l'instance
            plugin_instance_id = parent.id.replace('plugin_', '')
            if plugin_instance_id not in config_screen.current_config:
                return

            # Récupérer la configuration existante
            config = config_screen.current_config[plugin_instance_id]

            # Obtenir le nom de variable (peut être différent de l'ID du champ)
            variable_name = self.field_config.get('variable', self.field_id)

            # Format 1: Nouvelle structure avec 'config'
            if 'config' in config and variable_name in config['config']:
                value = config['config'][variable_name]
                if value is not None:
                    logger.debug(f"Valeur trouvée dans config pour {variable_name}: {value}")
                    self.value = self._normalize_boolean(value)
                    return

            # Format 2: Ancienne structure plate
            if variable_name in config:
                value = config[variable_name]
                if value is not None:
                    logger.debug(f"Valeur trouvée dans structure plate pour {variable_name}: {value}")
                    self.value = self._normalize_boolean(value)
                    return

        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la valeur de séquence: {e}")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """
        Gestionnaire d'événement quand l'utilisateur modifie la case à cocher.

        Args:
            event: Événement de changement de case à cocher
        """
        # Vérifier que c'est bien notre checkbox qui a changé
        if event.checkbox.id != f"checkbox_{self.source_id}_{self.field_id}":
            return

        # Mettre à jour la valeur interne
        old_value = self.value
        self.value = event.value
        logger.debug(f"Valeur de la checkbox {self.field_id} changée de {old_value} à {self.value}")

        # Notifier les containers parents du changement
        self._notify_parent_containers()

    def set_value(self, value: Any, update_input: bool = True, update_dependencies: bool = True) -> bool:
        """
        Définit la valeur du champ.

        Args:
            value: Nouvelle valeur
            update_input: Si True, met à jour le widget
            update_dependencies: Si True, notifie les champs dépendants

        Returns:
            bool: True si la mise à jour a réussi
        """
        # Normaliser la valeur en booléen
        bool_value = self._normalize_boolean(value)

        logger.debug(f"set_value({value} -> {bool_value}) pour {self.field_id}")

        # Vérifier si la valeur change réellement
        if self.value == bool_value:
            logger.debug(f"Valeur déjà à {bool_value} pour {self.field_id}")
            return True

        # Mise à jour de la valeur interne
        self.value = bool_value

        # Mise à jour du widget si demandé
        if update_input and hasattr(self, 'checkbox'):
            self.checkbox.value = bool_value
            logger.debug(f"Widget checkbox mis à jour: {bool_value}")

        # Notification des dépendances si demandé
        if update_dependencies:
            self._notify_parent_containers()

        logger.debug(f"set_value réussi pour {self.field_id}")
        return True

    def get_value(self) -> Optional[bool]:
        """
        Récupère la valeur actuelle du champ.

        Returns:
            Optional[bool]: Valeur booléenne ou None si désactivé
        """
        # Si le champ est désactivé, renvoyer None conformément à l'interface ConfigField
        if hasattr(self, 'disabled') and self.disabled:
            return None

        return self.value