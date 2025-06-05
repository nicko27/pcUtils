"""
Champ de sélection de template pour la configuration des plugins.
"""
from textual.containers import VerticalGroup
from textual.widgets import Select, Label
from textual.app import ComposeResult
from logging import getLogger
from typing import Dict, Any, List, Optional, Callable, Union

from .template_manager import TemplateManager

logger = getLogger('template_field')

class TemplateField(VerticalGroup):
    """
    Champ de sélection de template pour la configuration des plugins.
    
    Permet à l'utilisateur de sélectionner un template prédéfini et de l'appliquer
    automatiquement aux autres champs de configuration.
    """

    def __init__(self, plugin_name: str, field_id: str, fields_by_id: Dict[str, Any]):
        """
        Initialise le champ de sélection de template.

        Args:
            plugin_name: Nom du plugin
            field_id: Identifiant du champ
            fields_by_id: Dictionnaire des champs par ID
        """
        super().__init__()
        self.plugin_name = plugin_name
        self.field_id = field_id
        self.fields_by_id = fields_by_id
        self.template_manager = TemplateManager()
        self.add_class("template-field")
        
        # Charger les templates disponibles
        self.templates = self.template_manager.get_plugin_templates(plugin_name)
        logger.debug(f"Initialisation du champ de template pour {plugin_name} - {len(self.templates)} templates trouvés")
        
        # Initialiser l'ID du select (sera défini dans compose)
        self.select_id = f"template_{self.plugin_name}_{self.field_id}"
        
        # Stocker la sélection actuelle
        self.current_template = None
        
        # Callback pour notifier de l'application d'un template
        self.on_template_applied = None

    def compose(self) -> ComposeResult:
        """
        Compose le champ de sélection de template.
        
        Returns:
            ComposeResult: Résultat de la composition
        """
        if not self.templates:
            logger.debug(f"Aucun template disponible pour {self.plugin_name}")
            yield Label("Aucun template disponible", classes="template-label no-templates")
            return

        yield Label("Template de configuration :", classes="template-label")
        
        # Créer les options avec nom et description
        options = self._get_template_options()
        
        # Créer le sélecteur avec l'option par défaut si disponible
        default_template_name = self._get_default_template_name()
        
        # Créer le widget Select avec un ID unique
        select_id = f"template_{self.plugin_name}_{self.field_id}"
        select = Select(
            options=options,
            value=default_template_name,
            id=select_id,
            classes="template-select"
        )
        
        # Stocker l'ID du select pour pouvoir le récupérer plus tard
        self.select_id = select_id
        self.current_template = default_template_name
        
        yield select

    def _get_template_options(self) -> List[tuple]:
        """
        Génère les options du sélecteur de template.
        
        Returns:
            List[tuple]: Liste de tuples (label, value) pour le widget Select
        """
        # Option spéciale pour "pas de template"
        options = [("-- Aucun template --", "")]
        
        # Ajouter les templates disponibles
        template_names = self.template_manager.get_template_names(self.plugin_name)
        
        for name in template_names:
            # Récupérer une description formatée pour l'affichage
            description = self._format_template_description(name)
            options.append((description, name))
            
        return options
        
    def _format_template_description(self, template_name: str) -> str:
        """
        Formate la description d'un template pour l'affichage.
        
        Args:
            template_name: Nom du template
            
        Returns:
            str: Description formatée
        """
        template = self.templates.get(template_name, {})
        
        # Utiliser le nom formaté ou le nom du fichier
        name = template.get('name', template_name)
        
        # Si c'est le template par défaut, l'indiquer
        if template_name == 'default':
            return f"{name} (défaut)"
        return name

    def _get_default_template_name(self) -> Optional[str]:
        """
        Détermine le template par défaut à sélectionner.
        
        Returns:
            Optional[str]: Nom du template par défaut ou None
        """
        # Vérifier si un template "default" existe
        if 'default' in self.templates:
            return 'default'
            
        # Sinon, utiliser le premier template disponible si la liste n'est pas vide
        template_names = list(self.templates.keys())
        if template_names:
            return template_names[0]
            
        # Aucun template disponible
        return None

    def _apply_template(self, template_name: str) -> None:
        """
        Applique un template aux champs de configuration.
        
        Args:
            template_name: Nom du template à appliquer
        """
        logger.info(f"Début de l'application du template '{template_name}' pour {self.plugin_name}")
        
        # Ignorer si aucun template n'est sélectionné
        if not template_name:
            logger.debug("Aucun template sélectionné, réinitialisation aux valeurs par défaut")
            self._reset_fields_to_defaults()
            return
            
        # Vérifier que le template existe
        if template_name not in self.templates:
            logger.warning(f"Template '{template_name}' non trouvé pour {self.plugin_name}")
            return

        # Récupérer les variables du template
        template = self.templates[template_name]
        variables = template.get('variables', {})
        
        if not variables:
            logger.warning(f"Template '{template_name}' ne contient aucune variable")
            return
        
        logger.info(f"Application de {len(variables)} variables du template '{template_name}'")
        
        # Si un callback est défini, l'utiliser pour appliquer le template
        if callable(self.on_template_applied):
            try:
                self.on_template_applied(template_name, variables)
                logger.debug(f"Template '{template_name}' appliqué via callback")
                return
            except Exception as e:
                logger.error(f"Erreur lors de l'application du template via callback: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Continuer avec la méthode standard en cas d'échec du callback
        
        # Méthode standard: appliquer chaque variable directement
        self._apply_template_variables(variables)

    def _apply_template_variables(self, variables: Dict[str, Any]) -> None:
        """
        Applique les variables d'un template directement aux champs correspondants.
        
        Args:
            variables: Variables du template à appliquer
        """
        # Liste des champs pour lesquels la mise à jour a réussi/échoué
        updated_fields = []
        failed_fields = []

        # Appliquer chaque variable aux champs correspondants
        for var_name, var_value in variables.items():
            # Tenter différentes stratégies pour trouver le champ correspondant
            field = self._find_matching_field(var_name)
            
            if field:
                # Tenter de mettre à jour le champ avec la nouvelle valeur
                success = self._update_field_value(field, var_value)
                if success:
                    updated_fields.append(var_name)
                else:
                    failed_fields.append(var_name)
            else:
                logger.warning(f"Aucun champ trouvé pour la variable '{var_name}'")
                failed_fields.append(var_name)
        
        # Journal des résultats
        if updated_fields:
            logger.info(f"Champs mis à jour avec succès: {', '.join(updated_fields)}")
        if failed_fields:
            logger.warning(f"Champs non mis à jour: {', '.join(failed_fields)}")

    def _find_matching_field(self, var_name: str) -> Optional[Any]:
        """
        Trouve le champ correspondant à une variable de template.
        Utilise plusieurs stratégies de recherche.
        
        Args:
            var_name: Nom de la variable
            
        Returns:
            Optional[Any]: Champ trouvé ou None
        """
        # Stratégie 1: Recherche directe par variable_name
        for field_id, field in self.fields_by_id.items():
            if hasattr(field, 'source_id') and field.source_id == self.plugin_name and \
               hasattr(field, 'variable_name') and field.variable_name == var_name:
                logger.debug(f"Champ trouvé pour variable '{var_name}' via variable_name")
                return field
        
        # Stratégie 2: Recherche par combinaisons d'IDs
        possible_ids = [
            var_name,                          # Nom de variable seul
            f"{self.plugin_name}.{var_name}",  # plugin_name.var_name
            f"{var_name}_{self.plugin_name}"   # var_name_plugin_name
        ]
        
        for field_id in possible_ids:
            if field_id in self.fields_by_id:
                logger.debug(f"Champ trouvé pour variable '{var_name}' avec ID: {field_id}")
                return self.fields_by_id[field_id]
        
        # Stratégie 3: Recherche dans les champs du plugin via fields_by_plugin
        for field_id, field in self.fields_by_id.items():
            if hasattr(field, 'source_id') and field.source_id == self.plugin_name and \
               hasattr(field, 'field_id') and field.field_id == var_name:
                logger.debug(f"Champ trouvé pour variable '{var_name}' via fields_by_id par plugin")
                return field
        
        logger.debug(f"Aucun champ trouvé pour variable '{var_name}'")
        return None

    def _update_field_value(self, field: Any, value: Any) -> bool:
        """
        Met à jour la valeur d'un champ de configuration.
        
        Args:
            field: Champ à mettre à jour
            value: Nouvelle valeur
            
        Returns:
            bool: True si la mise à jour a réussi
        """
        try:
            # Méthode 1: Utiliser set_value si disponible (méthode privilégiée)
            if hasattr(field, 'set_value') and callable(field.set_value):
                success = field.set_value(value, update_dependencies=True)
                if success:
                    logger.debug(f"Valeur mise à jour via set_value(): {value}")
                    return True
                else:
                    logger.warning(f"Échec de set_value() pour {field.field_id if hasattr(field, 'field_id') else 'unknown'}")
                    return False
                
            # Méthode 2: Modifier directement l'attribut value
            elif hasattr(field, 'value'):
                field.value = value
                logger.debug(f"Valeur mise à jour via attribut value: {value}")
                
                # Mettre à jour également le widget correspondant
                self._update_field_widget(field, value)
                return True
                
            else:
                logger.warning(f"Le champ ne possède ni set_value() ni attribut value")
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du champ: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _update_field_widget(self, field: Any, value: Any) -> None:
        """
        Met à jour le widget d'un champ avec la nouvelle valeur.
        
        Args:
            field: Champ dont le widget doit être mis à jour
            value: Nouvelle valeur
        """
        try:
            # Pour les différents types de widgets
            if hasattr(field, 'input') and field.input:
                field.input.value = str(value) if value is not None else ""
                logger.debug(f"Widget input mis à jour avec: {value}")
                
            elif hasattr(field, 'select') and field.select:
                # Pour les sélecteurs, vérifier si la valeur est dans les options
                if hasattr(field, 'options'):
                    available_values = [opt[1] for opt in field.options]
                    if str(value) in available_values:
                        field.select.value = str(value)
                        logger.debug(f"Widget select mis à jour avec: {value}")
                    else:
                        logger.warning(f"La valeur '{value}' n'est pas dans les options du select")
                else:
                    # Sans accès aux options, essayer quand même de mettre à jour
                    field.select.value = str(value)
                    logger.debug(f"Widget select mis à jour avec: {value} (sans vérification d'options)")
                    
            elif hasattr(field, 'checkbox') and field.checkbox:
                # Normaliser en booléen
                if isinstance(value, str):
                    bool_value = value.lower() in ('true', 't', 'yes', 'y', '1')
                else:
                    bool_value = bool(value)
                field.checkbox.value = bool_value
                logger.debug(f"Widget checkbox mis à jour avec: {bool_value}")
                
            else:
                logger.debug("Aucun widget reconnu trouvé pour la mise à jour")
                
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du widget: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _reset_fields_to_defaults(self) -> None:
        """
        Réinitialise tous les champs du plugin à leurs valeurs par défaut.
        Cette méthode est appelée lorsque l'option "Aucun template" est sélectionnée.
        """
        logger.info(f"Réinitialisation des champs aux valeurs par défaut pour {self.plugin_name}")
        
        # Récupérer tous les champs du plugin
        plugin_fields = {}
        for field_id, field in self.fields_by_id.items():
            if hasattr(field, 'source_id') and field.source_id == self.plugin_name:
                plugin_fields[field_id] = field
                
        if not plugin_fields:
            logger.warning(f"Aucun champ trouvé pour le plugin {self.plugin_name}")
            return
            
        logger.debug(f"Réinitialisation de {len(plugin_fields)} champs pour {self.plugin_name}")
        
        # Pour chaque champ, réinitialiser à la valeur par défaut
        for field_id, field in plugin_fields.items():
            try:
                # Ignorer le champ de template lui-même
                if field_id == 'template' or field == self:
                    continue
                    
                # Utiliser la méthode restore_default si disponible
                if hasattr(field, 'restore_default') and callable(field.restore_default):
                    logger.debug(f"Appel de restore_default() pour le champ {field_id}")
                    success = field.restore_default()
                    if not success:
                        logger.warning(f"Échec de restore_default() pour {field_id}")
                
                # Sinon, essayer d'accéder à default_value
                elif hasattr(field, 'default_value'):
                    logger.debug(f"Réinitialisation du champ {field_id} à default_value: {field.default_value}")
                    field.value = field.default_value
                    self._update_field_widget(field, field.default_value)
                
                # Sinon, essayer d'accéder à field_config['default']
                elif hasattr(field, 'field_config') and 'default' in field.field_config:
                    default_value = field.field_config['default']
                    logger.debug(f"Réinitialisation du champ {field_id} à la valeur par défaut: {default_value}")
                    if hasattr(field, 'set_value') and callable(field.set_value):
                        field.set_value(default_value, update_dependencies=True)
                    else:
                        field.value = default_value
                        self._update_field_widget(field, default_value)
                else:
                    logger.warning(f"Impossible de réinitialiser le champ {field_id}, aucune méthode disponible")
            except Exception as e:
                logger.error(f"Erreur lors de la réinitialisation du champ {field_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
        # Notifier les conteneurs de configuration pour mettre à jour les dépendances
        self._notify_parent_containers()

    def _notify_parent_containers(self) -> None:
        """
        Notifie les conteneurs parents de la mise à jour pour traiter les dépendances.
        """
        try:
            # Chercher le conteneur de configuration parent
            parent = self.parent
            while parent:
                # Si le parent est un ConfigContainer avec update_all_dependencies
                if hasattr(parent, 'update_all_dependencies') and callable(parent.update_all_dependencies):
                    logger.debug("Notification au conteneur parent avec update_all_dependencies")
                    parent.update_all_dependencies()
                    break
                # Si le parent a une méthode pour mettre à jour les dépendances
                elif hasattr(parent, '_analyze_field_dependencies') and callable(parent._analyze_field_dependencies):
                    logger.debug("Notification au conteneur parent avec _analyze_field_dependencies")
                    parent._analyze_field_dependencies()
                    break
                parent = parent.parent
        except Exception as e:
            logger.error(f"Erreur lors de la notification des conteneurs parents: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def on_mount(self) -> None:
        """
        Méthode appelée lorsque le widget est monté dans l'interface.
        Configure les gestionnaires d'événements.
        """
        try:
            # Récupérer le widget Select et configurer les gestionnaires d'événements
            select = self.query_one(f"#{self.select_id}", Select)
            logger.debug(f"Widget Select trouvé avec ID: {self.select_id}")
            
            # Utiliser les deux méthodes complémentaires pour être sûr de capturer l'événement
            select.on_changed = self.on_select_changed
            self.watch(select, "changed", self._on_select_changed_watch)
            
            # Sélectionner "Aucun template" par défaut (valeur vide)
            logger.debug("Sélection de 'Aucun template' par défaut")
            select.value = ""
            
            logger.debug("Gestionnaires d'événements configurés pour le sélecteur de template")
        except Exception as e:
            logger.error(f"Erreur lors de la configuration des événements: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def on_select_changed(self, event: Select.Changed) -> None:
        """
        Gère le changement de template sélectionné.
        
        Args:
            event: Événement de changement du Select
        """
        # Extraire la valeur de l'événement
        value = None
        if hasattr(event, 'value'):
            value = event.value
        elif hasattr(event, 'select') and hasattr(event.select, 'value'):
            value = event.select.value
        
        logger.debug(f"Template sélectionné pour {self.plugin_name}: {value}")
        
        # Mettre à jour la sélection actuelle
        old_template = self.current_template
        self.current_template = value
        
        # Si même template qu'avant, ne rien faire
        if old_template == value:
            logger.debug(f"Template '{value}' déjà sélectionné, aucune action nécessaire")
            return
        
        # Appliquer le template ou réinitialiser les champs
        self._apply_template(value)
        
    def _on_select_changed_watch(self, event: Select.Changed) -> None:
        """
        Méthode alternative pour gérer le changement via watch.
        
        Args:
            event: Événement de changement du Select
        """
        logger.debug(f"Événement watch déclenché pour le template")
        # Déléguer à la méthode principale
        self.on_select_changed(event)