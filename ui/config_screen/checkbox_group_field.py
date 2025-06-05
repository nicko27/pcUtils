from textual.app import ComposeResult
from textual.containers import VerticalGroup, HorizontalGroup
from textual.widgets import Checkbox, Label
import os
import importlib.util
import sys
import traceback

from .config_field import ConfigField
from ..utils.logging import get_logger

logger = get_logger('checkbox_group_field')

class CheckboxGroupField(ConfigField):
    """Field for multiple checkbox selection"""

    def __init__(self, source_id: str, field_id: str, field_config: dict, fields_by_id: dict = None, is_global: bool = False):
        super().__init__(source_id, field_id, field_config, fields_by_id, is_global)
        self.add_class("field-type-checkbox-group")
        self.checkboxes = {}
        self.options = []
        self.selected_values = []
        self.raw_data = None

        # Initialiser la dépendance si elle est définie dans la configuration
        self.depends_on = field_config.get('depends_on')
        if self.depends_on:
            logger.debug(f"Champ {self.field_id} dépend de {self.depends_on}")

        # Initialiser les valeurs par défaut si elles sont définies
        self.default_selected = field_config.get('default_selected', [])
        if self.default_selected:
            logger.debug(f"Valeurs par défaut pour {self.field_id}: {self.default_selected}")

    def compose(self) -> ComposeResult:
        # Créer le conteneur pour les checkboxes
        with VerticalGroup(classes="field-input-container checkbox-group-container"):
            # Get options for checkboxes
            self.options = self._get_options()
            logger.debug(f"Checkbox group options for {self.field_id}: {self.options}")

            if not self.options:
                logger.warning(f"No options available for checkbox group {self.field_id}")
            else:
                label = self.field_config.get('label', self.field_id)
                label_classes = "field-label"
                if self.field_config.get('required', False):
                    label_classes += " required-field"
                
                # Ajouter la classe 'hidden-label' par défaut
                label_classes += " hidden-label" 
                
                with HorizontalGroup(classes="field-header", id=f"header_{self.field_id}"):
                    yield Label(f"{label} *", classes=label_classes)

                # Create a checkbox for each option
                for option_label, option_value in self.options:
                    checkbox_id = f"checkbox_group_{self.source_id}_{self.field_id}_{option_value}".replace(".","_")
                    with HorizontalGroup(classes="checkbox-group-item"):
                        checkbox = Checkbox(
                            id=checkbox_id,
                            classes="field-checkbox-group-item",
                            value=option_value in self.selected_values
                        )
                        self.checkboxes[option_value] = checkbox

                        yield checkbox
                        yield Label(option_label, classes="checkbox-group-label")

    def _get_options(self) -> list:
        """Get options for the checkbox group, either static or dynamic"""
        if 'options' in self.field_config:
            logger.debug(f"Using static options from config: {self.field_config['options']}")
            return self._normalize_options(self.field_config['options'])

        if 'dynamic_options' in self.field_config:
            return self._get_dynamic_options()

        # Fallback if no options defined
        return [("No options defined", "no_options_defined")]

    def _get_dynamic_options(self) -> list:
        """Récupère les options dynamiques depuis un script externe"""
        dynamic_config = self.field_config['dynamic_options']
        logger.debug(f"Loading dynamic options with config: {dynamic_config}")

        # Determine script path (global or plugin)
        if dynamic_config.get('global', False):
            # Script in utils folder
            script_name = dynamic_config['script']
            script_path = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', script_name)
        else:
            # Script in plugin folder
            script_path = os.path.join(os.path.dirname(__file__), '..', '..', 'plugins', self.source_id, dynamic_config['script'])

        logger.debug(f"Loading script from: {script_path}")
        logger.debug(f"Script exists: {os.path.exists(script_path)}")

        try:
            # Import the script module
            sys.path.append(os.path.dirname(script_path))
            logger.debug(f"Python path: {sys.path}")

            spec = importlib.util.spec_from_file_location("dynamic_script", script_path)
            if not spec:
                logger.error("Failed to create module spec")
                return [("Error loading module", "error_loading")]

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Get the function name
            func_name = dynamic_config.get('function')
            if not func_name or not hasattr(module, func_name):
                logger.error(f"Function {func_name} not found in script")
                return [("Function not found", "function_not_found")]

            logger.debug(f"Using function: {func_name}")

            # Préparer les arguments
            args, kwargs = self._prepare_function_args(dynamic_config)

            logger.debug(f"Calling {func_name} with args={args}, kwargs={kwargs}")

            # Call the function with arguments
            if args and kwargs:
                result = getattr(module, func_name)(*args, **kwargs)
            elif args:
                result = getattr(module, func_name)(*args)
            elif kwargs:
                result = getattr(module, func_name)(**kwargs)
            else:
                result = getattr(module, func_name)()

            logger.debug(f"Result from {func_name}: {result}")

            # Stocker les données brutes pour une utilisation ultérieure
            self.raw_data = result

            return self._process_dynamic_result(result, dynamic_config)

        except Exception as e:
            logger.error(f"Error loading dynamic options: {e}")
            logger.error(traceback.format_exc())
            return [(f"Error: {str(e)}", "script_exception")]

    def _prepare_function_args(self, dynamic_config):
        """Prépare les arguments pour l'appel de fonction dynamique
        
        Utilise à la fois les arguments définis dans la configuration et 
        les arguments dynamiques passés lors de l'appel à update_dynamic_options
        """
        args = []
        kwargs = {}
        
        # 1. Ajouter les arguments dynamiques passés par le conteneur parent
        if hasattr(self, '_dynamic_args') and self._dynamic_args:
            logger.debug(f"Utilisation des arguments dynamiques pour {self.field_id}: {self._dynamic_args}")
            kwargs.update(self._dynamic_args)
        
        # 2. Ajouter les arguments définis dans la configuration
        if 'args' in dynamic_config:
            for arg_config in dynamic_config['args']:
                if 'field' in arg_config:
                    # Get value from another field
                    field_id = arg_config['field']
                    param_name = arg_config.get('param_name')
                    
                    # Vérifier si la valeur est déjà dans les arguments dynamiques
                    if param_name and param_name in kwargs:
                        logger.debug(f"Valeur pour {param_name} déjà fournie dans les arguments dynamiques")
                        continue
                    
                    # Chercher le champ dans les fields_by_id
                    found = False
                    for elt in self.fields_by_id:
                        if elt.startswith(f"{field_id}_"):
                            field_value = self.fields_by_id[elt].get_value()
                            if param_name:
                                kwargs[param_name] = field_value
                            else:
                                args.append(field_value)
                            found = True
                            break
                    
                    if not found:
                        logger.debug(f"Champ {field_id} non trouvé pour les arguments dynamiques")
                        
                elif 'value' in arg_config:
                    # Static value
                    param_name = arg_config.get('param_name')
                    if param_name and param_name not in kwargs:  # Ne pas écraser les valeurs dynamiques
                        kwargs[param_name] = arg_config['value']
                    elif not param_name:
                        args.append(arg_config['value'])

        logger.debug(f"Arguments préparés pour {self.field_id}: args={args}, kwargs={kwargs}")
        return args, kwargs

    def _process_dynamic_result(self, result, dynamic_config):
        """Traite le résultat d'une fonction dynamique"""
        # Process the result
        if isinstance(result, tuple) and len(result) == 2:
            success, data = result

            if not success:
                logger.error(f"Dynamic options script failed: {data}")
                return [("Script error", "script_error")]

            # If data is a list, process it
            if isinstance(data, list):
                # Extract value_key and label_key if specified
                value_key = dynamic_config.get('value')
                label_key = dynamic_config.get('description')

                # Récupérer les clés pour la sélection automatique
                auto_select_key = dynamic_config.get('auto_select_key')
                auto_select_value = dynamic_config.get('auto_select_value', True)

                options = []
                for item in data:
                    if isinstance(item, dict):
                        if value_key and label_key and value_key in item and label_key in item:
                            value = str(item[value_key])
                            options.append((str(item[label_key]), value))

                            # Vérifier si cet élément doit être sélectionné par défaut
                            if auto_select_key and auto_select_key in item and item[auto_select_key] == auto_select_value:
                                if value not in self.selected_values:
                                    self.selected_values.append(value)
                                    logger.debug(f"Auto-sélection de {value} basée sur {auto_select_key}={auto_select_value}")

                        elif value_key and value_key in item:
                            # Use value as label if no label_key specified
                            value = str(item[value_key])
                            options.append((value, value))

                            # Vérifier si cet élément doit être sélectionné par défaut
                            if auto_select_key and auto_select_key in item and item[auto_select_key] == auto_select_value:
                                if value not in self.selected_values:
                                    self.selected_values.append(value)
                                    logger.debug(f"Auto-sélection de {value} basée sur {auto_select_key}={auto_select_value}")
                    else:
                        # For simple values, use as both label and value
                        value = str(item)
                        options.append((value, value))

                # Appliquer les valeurs par défaut définies dans la configuration
                if self.default_selected:
                    for default_value in self.default_selected:
                        if any(opt[1] == default_value for opt in options) and default_value not in self.selected_values:
                            self.selected_values.append(default_value)
                            logger.debug(f"Sélection par défaut de {default_value} depuis la configuration")

                if options:
                    return options
                else:
                    # Si la liste est vide, retourner None pour que le champ soit supprimé
                    return None

            # If it's not a list, return an error
            logger.error(f"Expected list result, got {type(data)}")
            return None

        # If result is not a tuple, return an error
        logger.error(f"Expected tuple result (success, data), got {type(result)}")
        return [("Invalid result format", "invalid_format")]

    def _normalize_options(self, options: list) -> list:
        """
        Normalize options to format expected by checkbox group: (label, value)
        The value must be a string and must be unique.
        """
        normalized = []
        for opt in options:
            if isinstance(opt, (list, tuple)):
                # If it's already a tuple/list, make sure it has 2 elements
                if len(opt) >= 2:
                    normalized.append((str(opt[0]), str(opt[1])))
                else:
                    normalized.append((str(opt[0]), str(opt[0])))
            elif isinstance(opt, dict):
                # For dictionaries with description and value
                if 'description' in opt and 'value' in opt:
                    normalized.append((str(opt['description']), str(opt['value'])))
                else:
                    label = str(opt.get('description', opt.get('label', opt.get('name', ''))))
                    value = str(opt.get('value', opt.get('id', label)))
                    normalized.append((label, value))
            else:
                # For simple values, use same value for label and value
                normalized.append((str(opt), str(opt)))

        return normalized

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox state changes"""
        # Check if this is one of our checkboxes
        checkbox_id = event.checkbox.id
        logger.debug(f"Checkbox changed: {checkbox_id} -> {event.value}")

        for option_value, checkbox in self.checkboxes.items():
            if checkbox.id == checkbox_id:
                logger.debug(f"Found matching checkbox for option: {option_value}")

                # Update selected values
                if event.value and option_value not in self.selected_values:
                    self.selected_values.append(option_value)
                elif not event.value and option_value in self.selected_values:
                    self.selected_values.remove(option_value)

                logger.debug(f"Updated selected values: {self.selected_values}")
                break

    def get_value(self):
        """Return the list of selected values"""
        return self.selected_values
        
    def clear_display(self):
        """Vide l'affichage du champ sans perdre les valeurs sélectionnées.
        Cette méthode est appelée lorsque le champ est désactivé via enabled_if.
        """
        logger.debug(f"Nettoyage de l'affichage pour {self.field_id}")
        
        try:
            # Sauvegarder les options et les valeurs sélectionnées actuelles
            if not hasattr(self, '_saved_options'):
                self._saved_options = self.options.copy() if self.options else []
                logger.debug(f"Options sauvegardées pour {self.field_id}: {self._saved_options}")
                
            if not hasattr(self, '_saved_selected'):
                self._saved_selected = self.selected_values.copy() if self.selected_values else []
                logger.debug(f"Valeurs sélectionnées sauvegardées pour {self.field_id}: {self._saved_selected}")
            
            # Masquer le label si présent
            try:
                header_id = f"header_{self.field_id}"
                header = self.query_one(f"#{header_id}")
                if header:
                    header.add_class("hidden-label")
                    logger.debug(f"Label masqué pour {self.field_id}")
            except Exception as e:
                logger.debug(f"Pas de label à masquer pour {self.field_id}: {e}")
                
            # Vider le conteneur des checkboxes sans supprimer le champ
            container = self.query_one(".checkbox-group-container")
            if container:
                container.remove_children()
                logger.debug(f"Conteneur de checkboxes vidé pour {self.field_id}")
                
            # Vider les dictionnaires sans les supprimer
            self.checkboxes = {}
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage de l'affichage pour {self.field_id}: {e}")
    
    def restore_display(self, saved_value=None):
        """Restaure l'affichage du champ avec les valeurs sauvegardées.
        Cette méthode est appelée lorsque le champ est réactivé via enabled_if.
        
        Args:
            saved_value: Valeur sauvegardée par le conteneur parent (peut être None)
        """
        logger.debug(f"Restauration de l'affichage pour {self.field_id}")
        
        try:
            # Restaurer les options sauvegardées
            if hasattr(self, '_saved_options'):
                self.options = self._saved_options
                delattr(self, '_saved_options')
                logger.debug(f"Options restaurées pour {self.field_id}: {self.options}")
            
            # Restaurer les valeurs sélectionnées
            if hasattr(self, '_saved_selected'):
                self.selected_values = self._saved_selected
                delattr(self, '_saved_selected')
                logger.debug(f"Valeurs sélectionnées restaurées pour {self.field_id}: {self.selected_values}")
            elif saved_value is not None and isinstance(saved_value, list):
                self.selected_values = saved_value
                logger.debug(f"Valeurs sélectionnées restaurées depuis saved_value: {self.selected_values}")
            
            # Afficher le label si présent
            try:
                header_id = f"header_{self.field_id}"
                header = self.query_one(f"#{header_id}")
                if header:
                    header.remove_class("hidden-label")
                    logger.debug(f"Label affiché pour {self.field_id}")
            except Exception as e:
                logger.debug(f"Pas de label à afficher pour {self.field_id}: {e}")
            
            # Recréer les checkboxes
            container = self.query_one(".checkbox-group-container")
            if container and self.options:
                container.remove_children()
                
                # Recréer les checkboxes avec les options disponibles
                for label, value in self.options:
                    checkbox_id = f"{self.field_id}_{value}"
                    checkbox = Checkbox(label, id=checkbox_id, value=value in self.selected_values)
                    container.mount(checkbox)
                    self.checkboxes[value] = checkbox
                    logger.debug(f"Checkbox recréée pour {self.field_id}: {label} ({value})")
            
        except Exception as e:
            logger.error(f"Erreur lors de la restauration de l'affichage pour {self.field_id}: {e}")

    def update_dynamic_options(self, **kwargs):
        """Met à jour les options dynamiques du champ et affiche/masque son label
        
        Args:
            **kwargs: Arguments variables passés par le conteneur parent
                    Ces arguments sont utilisés par _get_options() si nécessaire
        """
        # Stocker les arguments pour les utiliser dans _get_options
        self._dynamic_args = kwargs
        logger.debug(f"Mise à jour des options pour {self.field_id} avec arguments: {kwargs}")
        
        new_options = self._get_options()

        # Si les options sont None ou vides, le champ doit être supprimé
        if new_options is None:
            logger.debug(f"Aucune option disponible pour {self.field_id}, le champ sera supprimé")
            self.options = []
            # Trouver le conteneur parent
            from .config_container import ConfigContainer
            parent = next((ancestor for ancestor in self.ancestors_with_self if isinstance(ancestor, ConfigContainer)), None)
            if parent:
                # Supprimer le champ du dictionnaire
                if self.field_id in parent.fields_by_id:
                    del parent.fields_by_id[self.field_id]
                # Supprimer le widget de l'interface
                self.remove()
            return

        # Mettre à jour les options
        self.options = new_options

        # Sauvegarder les valeurs sélectionnées qui sont toujours valides
        self.selected_values = [val for val in self.selected_values if any(opt[1] == val for opt in self.options)]
        
        # Contrôler l'affichage du label
        try:
            header_id = f"header_{self.field_id}"
            header = self.query_one(f"#{header_id}")
            
            # Chercher le label dans le header
            labels = header.query("Label")
            if labels and len(labels) > 0:
                label = labels[0]
                if new_options:  # Afficher le label si de nouvelles options sont disponibles
                    label.remove_class("hidden-label")
                else:  # Sinon, le masquer
                    label.add_class("hidden-label")
                logger.debug(f"Label du champ {self.field_id} {'affiché' if new_options else 'masqué'}")
            else:
                logger.warning(f"Aucun label trouvé dans le header pour {self.field_id}")
        except Exception as e:
            logger.error(f"Erreur lors de la gestion du label pour {self.field_id}: {e}")
            
            # Recréer le header s'il n'existe pas
            try:
                # Vérifier si le header existe déjà
                header = None
                for child in self.children:
                    if isinstance(child, HorizontalGroup) and child.id == f"header_{self.field_id}":
                        header = child
                        break
                        
                if not header:
                    # Créer le header s'il n'existe pas
                    header = HorizontalGroup(classes="field-header", id=f"header_{self.field_id}")
                    self.mount(header, before=self.query_one(".checkbox-group-container"))
                    
                    # Ajouter le label dans le header
                    label_text = self.field_config.get('label', self.field_id)
                    label_classes = "field-label"
                    if self.field_config.get('required', False):
                        label_classes += " required-field"
                    
                    # Ajouter la classe hidden-label si aucune option
                    if not new_options:
                        label_classes += " hidden-label"
                        
                    header.mount(Label(label_text, classes=label_classes))
                    logger.debug(f"Label recréé pour le champ {self.field_id}: {label_text}")
            except Exception as e:
                logger.error(f"Échec de la recréation du header pour {self.field_id}: {e}")

        # Supprimer tous les éléments du conteneur (checkboxes, labels, groupes)
        container = self.query_one('.checkbox-group-container')
        if container:
            # Vider complètement le conteneur
            for child in container.children:
                child.remove()
            
        # Réinitialiser la liste des checkboxes
        self.checkboxes.clear()
        
        # Si aucune option, ajouter un message
        if not self.options:
            logger.debug(f"Aucune option disponible pour {self.field_id}, affichage d'un message")
            if container:
                container.mount(Label("Aucune option disponible", classes="no-options-label"))
            return

        # Créer les nouveaux checkboxes et labels
        for option_label, option_value in self.options:
            checkbox_id = f"checkbox_group_{self.source_id}_{self.field_id}_{option_value}".replace(".", "_")
            # Créer le groupe horizontal
            group = HorizontalGroup(classes="checkbox-group-item")
            # Monter d'abord le groupe dans le conteneur
            container.mount(group)
            # Créer la checkbox
            checkbox = Checkbox(
                id=checkbox_id,
                classes="field-checkbox-group-item",
                value=option_value in self.selected_values
            )
            self.checkboxes[option_value] = checkbox
            # Créer le label
            label = Label(option_label, classes="checkbox-group-label")
            # Monter la checkbox et le label dans le groupe déjà monté
            group.mount(checkbox)
            group.mount(label)