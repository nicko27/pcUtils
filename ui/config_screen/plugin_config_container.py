"""
Conteneur de configuration pour les plugins.
Gère l'affichage et la manipulation des champs de configuration spécifiques aux plugins.
"""

from textual.app import ComposeResult
from textual.widgets import Label
from textual.containers import VerticalGroup, HorizontalGroup
from logging import getLogger
from typing import Dict, List, Any, Optional, Tuple, Set, Union
import traceback

from .config_container import ConfigContainer
from .template_field import TemplateField
from .template_manager import TemplateManager

logger = getLogger('plugin_config_container')

class PluginConfigContainer(ConfigContainer):
    """
    Conteneur pour les champs de configuration spécifiques aux plugins.

    Cette classe étend ConfigContainer pour ajouter des fonctionnalités
    spécifiques aux plugins comme les templates, les dépendances spéciales,
    et la gestion des valeurs par défaut ou prédéfinies.
    """

    def __init__(self, plugin: str, name: str, icon: str, description: str,
                 fields_by_plugin: Dict[str, Dict], fields_by_id: Dict[str, Any],
                 config_fields: List[Dict[str, Any]], **kwargs):
        """
        Initialise le conteneur de configuration pour un plugin.

        Args:
            plugin: Nom du plugin
            name: Nom d'affichage du plugin
            icon: Icône du plugin
            description: Description du plugin
            fields_by_plugin: Dictionnaire des champs indexés par plugin
            fields_by_id: Dictionnaire global des champs indexés par ID
            config_fields: Liste des configurations de champs
            **kwargs: Arguments supplémentaires pour le ConfigContainer
        """
        logger.debug(f"Initialisation du conteneur de configuration pour {plugin}")

        # Appeler le constructeur de la classe parente avec les paramètres communs
        super().__init__(
            source_id=plugin,
            title=name,
            icon=icon,
            description=description,
            fields_by_id=fields_by_id,
            config_fields=config_fields,
            is_global=False,
            **kwargs
        )

        # Garder une référence au dictionnaire des champs spécifiques au plugin
        self.fields_by_plugin = fields_by_plugin
        if plugin not in fields_by_plugin:
            fields_by_plugin[plugin] = {}
            logger.debug(f"Nouvelle collection de champs créée pour {plugin}")

        # Configuration spécifique pour ce plugin
        self.plugin_config = {}

        # Suivi des valeurs appliquées et des problèmes
        self._applied_values = {}                # Valeurs déjà appliquées
        self._field_errors = {}                  # Problèmes rencontrés par champ
        self._pending_values = {}                # Valeurs en attente d'application
        self._max_retry_attempts = 5             # Nombre maximum de tentatives d'application
        self._field_retry_counts = {}            # Compteurs de tentatives par champ

        # Champ d'exécution distante (sera défini par PluginConfig si nécessaire)
        self.remote_field = None

        # Initialiser le gestionnaire de templates
        self.template_manager = TemplateManager()
        logger.debug(f"Gestionnaire de templates initialisé pour {plugin}")

        # État pour le suivi des mises à jour
        self._is_updating_values = False         # Flag pour éviter les récursions

    def compose(self) -> ComposeResult:
        """
        Compose le conteneur avec les champs et options spécifiques au plugin.

        Returns:
            ComposeResult: Résultat de la composition
        """
        logger.debug(f"Composition du conteneur pour {self.source_id}")

        # Titre et description du plugin
        with VerticalGroup(classes="config-header"):
            yield Label(f"{self.icon} {self.title}", classes="config-title")
            if self.description:
                yield Label(self.description, classes="config-description")

        # Gérer le cas où il n'y a pas de champs de configuration
        if not self.config_fields and not self.remote_field:
            logger.debug(f"Aucun champ de configuration pour {self.source_id}")
            with VerticalGroup(classes="no-config"):
                with HorizontalGroup(classes="no-config-content"):
                    yield Label("ℹ️", classes="no-config-icon")
                    yield Label(f"Rien à configurer pour ce plugin", classes="no-config-label")
                return

        # Conteneur pour les champs de configuration
        with VerticalGroup(classes="config-fields"):
            # Vérifier et ajouter le champ de template si des templates sont disponibles
            templates = self.template_manager.get_plugin_templates(self.source_id)
            if templates:
                logger.debug(f"Templates trouvés pour {self.source_id}: {list(templates.keys())}")
                template_field = TemplateField(self.source_id, 'template', self.fields_by_id)
                template_field.on_template_applied = self.on_template_applied
                yield template_field

                # Stocker le champ de template dans le dictionnaire
                self.fields_by_id['template'] = template_field
            else:
                logger.debug(f"Aucun template trouvé pour {self.source_id}")

            # Créer et ajouter chaque champ de configuration
            for field_config in self.config_fields:
                field_id = field_config.get('id')
                unique_id = field_config.get('unique_id', field_id)

                if not field_id:
                    logger.warning(f"Champ sans identifiant dans {self.source_id}")
                    continue

                field_type = field_config.get('type', 'text')
                logger.debug(f"Création du champ {field_id} (unique_id: {unique_id}) de type {field_type}")

                # Déterminer la classe de champ à utiliser selon le type
                field_class = self._get_field_class_for_type(field_type)

                # Créer le champ avec accès aux autres champs
                try:
                    field = field_class(
                        self.source_id,
                        field_id,
                        field_config,
                        self.fields_by_id,
                        is_global=self.is_global
                    )

                    # Enregistrer le champ dans les dictionnaires
                    self.fields_by_id[unique_id] = field
                    self.fields_by_plugin[self.source_id][field_id] = field
                    logger.debug(f"Champ {field_id} créé et ajouté aux dictionnaires (unique_id: {unique_id})")

                    # Ajouter le champ à l'interface
                    yield field

                except Exception as e:
                    logger.error(f"Erreur lors de la création du champ {field_id}: {e}")
                    logger.error(traceback.format_exc())

            # Si nous avons un champ d'exécution distante, l'ajouter à la fin du conteneur
            if self.remote_field:
                logger.debug(f"Ajout du champ d'exécution distante pour {self.source_id}")
                with VerticalGroup(classes="remote-execution-container"):
                    yield self.remote_field

        # Analyser les dépendances entre champs après leur création
        self.call_after_refresh(self._analyze_field_dependencies)

    def on_mount(self) -> None:
        """
        Appelé lors du montage du conteneur dans l'interface.

        Cette méthode est exécutée après la création de tous les widgets
        mais avant leur affichage. C'est le moment idéal pour initialiser
        les valeurs des champs.
        """
        logger.debug(f"Montage du conteneur pour {self.source_id}")

        # Maintenant que les widgets sont créés, appliquer les valeurs prédéfinies
        self.call_after_refresh(self._apply_predefined_values)

    def _get_field_class_for_type(self, field_type: str) -> type:
        """
        Détermine la classe de champ à utiliser selon le type.

        Args:
            field_type: Type de champ (text, checkbox, select, etc.)

        Returns:
            type: Classe de champ à utiliser
        """
        # Utiliser le mapping défini dans la classe parente
        return self.FIELD_TYPES.get(field_type, self.FIELD_TYPES['text'])

    def _apply_predefined_values(self) -> None:
        """
        Applique les valeurs prédéfinies aux champs de configuration.

        Cette méthode récupère les valeurs depuis la configuration du plugin
        et les applique aux champs correspondants.
        """
        if self._is_updating_values:
            logger.debug("Application de valeurs déjà en cours, évitement de récursion")
            return

        try:
            self._is_updating_values = True

            logger.debug(f"Application des valeurs prédéfinies pour {self.source_id}")

            # Vérifier que nous sommes dans l'écran de configuration
            config_screen = self._get_config_screen()
            if not config_screen or not hasattr(config_screen, 'current_config'):
                logger.warning(f"Impossible d'accéder à current_config pour {self.source_id}")
                return

            # Récupérer l'ID de l'instance du plugin
            plugin_instance_id = self.id.replace('plugin_', '')
            if plugin_instance_id not in config_screen.current_config:
                logger.warning(f"Pas de configuration trouvée pour l'instance {plugin_instance_id}")
                return

            # Récupérer la configuration prédéfinie pour cette instance
            predefined_config = config_screen.current_config[plugin_instance_id]
            logger.debug(f"Configuration trouvée pour {plugin_instance_id}: {len(predefined_config)} clés")

            # Réinitialiser les structures de suivi
            self._applied_values = {}
            self._field_errors = {}
            self._pending_values = {}
            self._field_retry_counts = {}

            # Rassembler toutes les valeurs à appliquer
            values_to_apply = {}

            # Format 1: Nouveau format avec 'config'
            if 'config' in predefined_config and isinstance(predefined_config['config'], dict):
                values_to_apply.update(predefined_config['config'])
                logger.debug(f"Valeurs trouvées dans 'config': {len(predefined_config['config'])} paramètres")

            # Format 2: Ancien format à plat
            special_keys = {'plugin_name', 'instance_id', 'name', 'show_name', 'icon', 'remote_execution'}
            for key, value in predefined_config.items():
                if key not in special_keys and key != 'config':
                    values_to_apply[key] = value
                    logger.debug(f"Valeur trouvée à la racine: {key}={value}")

            # Appliquer chaque valeur au champ correspondant
            for var_name, value in values_to_apply.items():
                # Trouver le champ correspondant à cette variable
                field = self._find_field_for_variable(var_name)

                if field:
                    # Planifier l'application de la valeur
                    self._pending_values[field.field_id] = value

                    # Démarrer avec un premier essai d'application
                    self._apply_value_to_field(field, value)
                else:
                    logger.warning(f"Aucun champ trouvé pour la variable '{var_name}'")

            # Gérer les valeurs en attente non appliquées
            if self._pending_values:
                logger.debug(f"Valeurs en attente à réessayer: {len(self._pending_values)}")
                self.call_later(self._retry_pending_values, 0.1)

        except Exception as e:
            logger.error(f"Erreur lors de l'application des valeurs prédéfinies: {e}")
            logger.error(traceback.format_exc())
        finally:
            self._is_updating_values = False

    def _get_config_screen(self) -> Any:
        """
        Récupère l'écran de configuration parent.

        Returns:
            Any: L'écran de configuration ou None si non trouvé
        """
        # Rechercher l'écran de configuration dans la hiérarchie des ancêtres
        app = self.app if hasattr(self, 'app') and self.app else None
        if app and hasattr(app, 'screen'):
            from .config_screen import PluginConfig
            if isinstance(app.screen, PluginConfig):
                return app.screen
        return None

    def _find_field_for_variable(self, var_name: str) -> Optional[Any]:
        """
        Trouve le champ correspondant à une variable.

        Args:
            var_name: Nom de la variable

        Returns:
            Optional[Any]: Le champ correspondant ou None si non trouvé
        """
        # Stratégie 1: Recherche par nom de variable
        for field_id, field in self.fields_by_id.items():
            if (hasattr(field, 'source_id') and field.source_id == self.source_id and
                hasattr(field, 'variable_name') and field.variable_name == var_name):
                return field

        # Stratégie 2: Recherche par field_id exact
        field_id_to_check = f"{self.source_id}.{var_name}"
        if field_id_to_check in self.fields_by_id:
            return self.fields_by_id[field_id_to_check]

        # Stratégie 3: Recherche dans le dictionnaire spécifique au plugin
        if var_name in self.fields_by_plugin.get(self.source_id, {}):
            return self.fields_by_plugin[self.source_id][var_name]

        # Non trouvé
        return None

    def _apply_value_to_field(self, field: Any, value: Any, attempt: int = 0) -> bool:
        """
        Applique une valeur à un champ avec gestion des erreurs.

        Args:
            field: Champ à mettre à jour
            value: Valeur à appliquer
            attempt: Numéro de tentative (pour la gestion des réessais)

        Returns:
            bool: True si l'application a réussi, False sinon
        """
        field_id = getattr(field, 'field_id', 'unknown')
        field_type = getattr(field, 'field_config', {}).get('type', 'unknown')

        # Marquer cette tentative
        self._field_retry_counts[field_id] = attempt

        try:
            # Méthode 1: Utiliser set_value (méthode privilégiée)
            if hasattr(field, 'set_value'):
                success = field.set_value(value, update_dependencies=True)
                if success:
                    logger.debug(f"Valeur appliquée avec succès via set_value pour {field_id}")
                    self._applied_values[field_id] = value
                    # Supprimer de la liste des valeurs en attente
                    if field_id in self._pending_values:
                        del self._pending_values[field_id]
                    return True
                else:
                    logger.warning(f"Échec de set_value pour {field_id}")
                    self._field_errors[field_id] = "Échec de set_value"
                    return False

            # Méthode 2: Mettre à jour directement la valeur et le widget
            elif hasattr(field, 'value'):
                # Assigner la valeur
                field.value = value

                # Mettre à jour le widget associé selon son type
                self._update_field_widget(field, value)

                logger.debug(f"Valeur appliquée via attribute .value pour {field_id}")
                self._applied_values[field_id] = value

                # Supprimer de la liste des valeurs en attente
                if field_id in self._pending_values:
                    del self._pending_values[field_id]
                return True

            # Aucune méthode disponible
            else:
                logger.warning(f"Impossible d'appliquer la valeur à {field_id}: " +
                              f"pas de méthode set_value ou d'attribut value")
                self._field_errors[field_id] = "Aucune méthode d'application disponible"
                return False

        except Exception as e:
            error_msg = str(e)
            if attempt == 0:
                # Logguer l'erreur détaillée seulement à la première tentative
                logger.error(f"Erreur lors de l'application de la valeur '{value}' au champ {field_id}: {e}")
                logger.error(traceback.format_exc())
            else:
                # Log simplifié pour les tentatives suivantes
                logger.warning(f"Échec tentative {attempt+1} pour {field_id}: {error_msg}")

            self._field_errors[field_id] = error_msg
            return False

    def _retry_pending_values(self) -> None:
        """
        Réessaie d'appliquer les valeurs en attente.

        Cette méthode est appelée périodiquement pour tenter d'appliquer
        les valeurs qui n'ont pas pu être appliquées au premier essai.
        """
        if not self._pending_values:
            logger.debug("Aucune valeur en attente à réessayer")
            return

        # Copier pour éviter les modifications pendant l'itération
        pending_copy = self._pending_values.copy()
        logger.debug(f"Réessai de {len(pending_copy)} valeurs en attente")

        # Tenter d'appliquer chaque valeur en attente
        for field_id, value in pending_copy.items():
            # Récupérer le champ
            if field_id not in self.fields_by_id:
                logger.warning(f"Champ {field_id} non trouvé, suppression de la valeur en attente")
                if field_id in self._pending_values:
                    del self._pending_values[field_id]
                continue

            field = self.fields_by_id[field_id]

            # Déterminer le numéro de tentative
            attempt = self._field_retry_counts.get(field_id, 0) + 1

            # Vérifier si on a dépassé le nombre maximum de tentatives
            if attempt >= self._max_retry_attempts:
                logger.warning(f"Abandon après {attempt} tentatives pour {field_id}")
                if field_id in self._pending_values:
                    del self._pending_values[field_id]
                continue

            # Tenter d'appliquer la valeur
            self._apply_value_to_field(field, value, attempt)

        # Si des valeurs sont toujours en attente, planifier un nouveau réessai
        if self._pending_values:
            # Augmenter le délai exponentiellement (0.1s, 0.2s, 0.4s, 0.8s, ...)
            delay = 0.1 * (2 ** len(self._field_retry_counts))
            delay = min(delay, 2.0)  # Plafonner à 2 secondes

            logger.debug(f"Planification d'un nouveau réessai dans {delay:.1f}s " +
                        f"pour {len(self._pending_values)} valeurs")
            self.call_later(self._retry_pending_values, delay)
        else:
            logger.debug("Toutes les valeurs ont été appliquées avec succès")

    def on_template_applied(self, template_name: str, variables: Dict[str, Any]) -> None:
        """
        Gère l'application d'un template aux champs du plugin.

        Args:
            template_name: Nom du template appliqué
            variables: Variables du template à appliquer
        """
        logger.debug(f"Application du template '{template_name}' avec {len(variables)} variables")

        # Empêcher les mises à jour récursives
        if self._is_updating_values:
            logger.warning("Application de template ignorée pour éviter une récursion")
            return

        try:
            self._is_updating_values = True

            # Réinitialiser les structures de suivi
            self._applied_values = {}
            self._field_errors = {}
            self._pending_values = {}
            self._field_retry_counts = {}

            # Appliquer chaque variable du template
            for var_name, value in variables.items():
                field = self._find_field_for_variable(var_name)

                if field:
                    # Planifier l'application de la valeur
                    self._pending_values[field.field_id] = value

                    # Démarrer avec un premier essai d'application
                    self._apply_value_to_field(field, value)
                else:
                    logger.warning(f"Aucun champ trouvé pour la variable '{var_name}' du template")

            # Gérer les valeurs en attente non appliquées
            if self._pending_values:
                logger.debug(f"Valeurs de template en attente: {len(self._pending_values)}")
                self.call_later(self._retry_pending_values, 0.1)

        except Exception as e:
            logger.error(f"Erreur lors de l'application du template: {e}")
            logger.error(traceback.format_exc())
        finally:
            self._is_updating_values = False

    def collect_values(self) -> Dict[str, Any]:
        """
        Collecte toutes les valeurs actuelles des champs.

        Returns:
            Dict[str, Any]: Dictionnaire des valeurs {variable_name: value}
        """
        values = {}

        for field_id, field in self.fields_by_id.items():
            # Ne considérer que les champs de ce plugin
            if not hasattr(field, 'source_id') or field.source_id != self.source_id:
                continue

            # Ne pas inclure le champ de template
            if field_id == 'template':
                continue

            # Récupérer la valeur actuelle
            if hasattr(field, 'get_value'):
                # Utiliser le nom de variable pour l'export
                var_name = getattr(field, 'variable_name', field_id)

                try:
                    value = field.get_value()

                    # Traitement spécial pour les checkbox_group
                    if (hasattr(field, 'field_config') and
                        field.field_config.get('type') == 'checkbox_group'):
                        # Assurer que c'est une liste
                        if not value:
                            value = []
                        elif not isinstance(value, list):
                            value = [value]

                    # Ajouter à la collection
                    values[var_name] = value
                    logger.debug(f"Valeur collectée pour {var_name}: {value}")

                except Exception as e:
                    logger.error(f"Erreur lors de la collecte de la valeur pour {var_name}: {e}")

        return values

    def is_valid(self) -> bool:
        """
        Vérifie si tous les champs du conteneur sont valides.

        Returns:
            bool: True si tous les champs sont valides
        """
        for field_id, field in self.fields_by_id.items():
            # Ne considérer que les champs de ce plugin
            if not hasattr(field, 'source_id') or field.source_id != self.source_id:
                continue

            # Ignorer les champs désactivés
            if hasattr(field, 'disabled') and field.disabled:
                continue

            # Vérifier la validité du champ
            if hasattr(field, 'validate_input') and hasattr(field, 'get_value'):
                value = field.get_value()
                is_valid, error_msg = field.validate_input(value)

                if not is_valid:
                    logger.error(f"Validation échouée pour {field_id}: {error_msg}")
                    return False

        # Si tous les champs ont passé la validation
        return True

    def get_field_errors(self) -> Dict[str, str]:
        """
        Récupère les erreurs rencontrées lors de l'application des valeurs.

        Returns:
            Dict[str, str]: Dictionnaire des erreurs {field_id: error_message}
        """
        return self._field_errors.copy()

    def _update_field_widget(self, field: Any, value: Any) -> None:
        """
        Met à jour le widget d'un champ avec une valeur.

        Cette méthode est une version simplifiée qui utilise celle de la classe parente
        lorsqu'elle est disponible.

        Args:
            field: Champ dont le widget doit être mis à jour
            value: Nouvelle valeur
        """
        # Si la classe parente a la méthode _update_field_widget, l'utiliser
        if hasattr(super(), '_update_field_widget'):
            super()._update_field_widget(field, value)
            return

        # Sinon, implémentation de base ici
        try:
            # Type 1: Champ avec input (TextField, IPField, etc.)
            if hasattr(field, 'input'):
                field.input.value = str(value) if value is not None else ""

            # Type 2: Champ avec select (SelectField)
            elif hasattr(field, 'select'):
                field.select.value = str(value) if value is not None else ""

            # Type 3: Champ avec checkbox (CheckboxField)
            elif hasattr(field, 'checkbox'):
                # Normaliser en booléen
                if isinstance(value, str):
                    bool_value = value.lower() in ('true', 't', 'yes', 'y', '1')
                else:
                    bool_value = bool(value)
                field.checkbox.value = bool_value

        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du widget pour {field.field_id}: {e}")