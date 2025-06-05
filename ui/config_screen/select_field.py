from textual.app import ComposeResult
from textual.widgets import Select
from textual.containers import VerticalGroup
from typing import Dict, List, Any, Optional, Tuple, Union, cast
import os
import importlib.util
import sys
import traceback

from .config_field import ConfigField
from ..utils.logging import get_logger

logger = get_logger('select_field')

class SelectField(ConfigField):
    """
    Champ de sélection avec options statiques ou dynamiques.

    Ce champ permet de choisir une valeur parmi une liste d'options
    qui peuvent être définies statiquement ou générées dynamiquement.
    """

    def __init__(self, source_id: str, field_id: str, field_config: Dict[str, Any],
                fields_by_id: Optional[Dict[str, Any]] = None, is_global: bool = False):
        """
        Initialisation du champ de sélection.

        Args:
            source_id: Identifiant de la source (plugin ou config globale)
            field_id: Identifiant du champ
            field_config: Configuration du champ
            fields_by_id: Dictionnaire des champs par ID
            is_global: Si True, c'est un champ global
        """
        # Initialiser les attributs spécifiques avant d'appeler super().__init__
        self._value = None  # Valeur interne
        self.options = []  # Liste des options [(label, value), ...]

        # Flag pour éviter les mises à jour cycliques
        self._updating_widget = False

        # Appeler l'initialisation du parent
        super().__init__(source_id, field_id, field_config, fields_by_id, is_global)


    def compose(self) -> ComposeResult:
        """
        Création des éléments visuels du champ.

        Returns:
            ComposeResult: Éléments UI du champ
        """
        # Rendre les éléments de base (label, etc.)
        yield from super().compose()

        # Charger les options
        self.options = self.get_options()
        logger.debug(f"Options chargées pour {self.field_id}: {len(self.options)} options")

        # Déterminer la valeur initiale
        self._initialize_value()

        # Conteneur pour le select
        with VerticalGroup(classes="field-input-container select-container"):
            try:
                # Créer le widget Select
                self.select = Select(
                    options=self.options,
                    value=self.value,
                    id=f"select_{self.field_id}",
                    classes="field-select",
                    allow_blank=self.field_config.get('allow_blank', False)
                )

                # État initial: activé sauf si explicitement désactivé
                self.select.disabled = self.disabled if hasattr(self, 'disabled') else False

                if hasattr(self, 'disabled') and self.disabled:
                    self.select.add_class('disabled')
                else:
                    self.select.remove_class('disabled')

                yield self.select

            except Exception as e:
                logger.error(f"Erreur lors de la création du widget Select pour {self.field_id}: {e}")
                logger.error(traceback.format_exc())

                # Fallback en cas d'erreur
                self.select = Select(
                    options=[("Erreur de chargement", "error")],
                    value="error",
                    id=f"select_{self.field_id}",
                    classes="field-select error-select"
                )
                yield self.select

    def _initialize_value(self) -> None:
        """
        Initialise la valeur en tenant compte des options disponibles.
        """
        # Extraire les valeurs disponibles
        available_values = [opt[1] for opt in self.options]

        # Cas 1: Pas de valeur définie
        if self.value is None:
            # Utiliser la première option si disponible
            if available_values:
                self._value = available_values[0]
                logger.debug(f"Valeur initiale pour {self.field_id}: {self._value}")
            else:
                self._value = None
                logger.debug(f"Aucune option disponible pour {self.field_id}")
            return

        # Cas 2: Valeur définie mais pas dans les options
        if str(self.value) not in available_values:
            # Essayer de trouver une correspondance partielle
            for option_value in available_values:
                if (str(option_value).startswith(str(self.value)) or
                    str(self.value).startswith(str(option_value).split('.')[0])):
                    self._value = option_value
                    logger.debug(f"Correspondance partielle trouvée pour {self.field_id}: {self._value}")
                    return

            # Si aucune correspondance, utiliser la première option
            if available_values:
                self._value = available_values[0]
                logger.debug(f"Aucune correspondance trouvée pour {self.value}, utilisation de {self._value}")
            else:
                self._value = None
                logger.debug(f"Aucune option disponible pour {self.field_id}")

    def normalize_options(self, options: List[Any]) -> List[Tuple[str, str]]:
        """
        Normalise les options au format attendu par le widget Select: (label, value).

        Args:
            options: Options à normaliser (divers formats possibles)

        Returns:
            List[Tuple[str, str]]: Options normalisées
        """
        normalized = []

        for opt in options:
            # Format 1: Tuple ou liste (label, value)
            if isinstance(opt, (list, tuple)):
                if len(opt) >= 2:
                    normalized.append((str(opt[0]), str(opt[1])))
                else:
                    # Utiliser la valeur comme label si un seul élément
                    normalized.append((str(opt[0]), str(opt[0])))

            # Format 2: Dictionnaire avec description et value
            elif isinstance(opt, dict):
                if 'description' in opt and 'value' in opt:
                    normalized.append((str(opt['description']), str(opt['value'])))
                else:
                    # Extraire label et value de différentes clés possibles
                    label = str(opt.get('description', opt.get('label', opt.get('title', opt.get('name', '')))))
                    value = str(opt.get('value', opt.get('id', label)))
                    normalized.append((label, value))

            # Format 3: Valeur simple
            else:
                # Utiliser la même valeur pour le label et la value
                normalized.append((str(opt), str(opt)))

        # Éliminer les doublons de valeurs (garder le premier label rencontré)
        seen_values = set()
        unique_options = []

        for label, value in normalized:
            if value not in seen_values:
                seen_values.add(value)
                unique_options.append((label, value))
            else:
                logger.debug(f"Valeur en double ignorée: {value}")

        return unique_options

    def get_options(self) -> List[Tuple[str, str]]:
        """
        Récupère les options du champ, soit statiques, soit dynamiques.

        Returns:
            List[Tuple[str, str]]: Liste des options au format (label, value)
        """
        # Cas 1: Options statiques dans la configuration
        if 'options' in self.field_config:
            logger.debug(f"Utilisation des options statiques pour {self.field_id}")
            return self.normalize_options(self.field_config['options'])

        # Cas 2: Options dynamiques via script
        if 'dynamic_options' in self.field_config:
            logger.debug(f"Chargement des options dynamiques pour {self.field_id}")
            return self.get_dynamic_options()

        # Cas par défaut: Aucune option
        logger.warning(f"Aucune option définie pour {self.field_id}")
        return [("Aucune option disponible", "no_options")]

    def get_dynamic_options(self) -> List[Tuple[str, str]]:
        """
        Récupère les options dynamiques via un script externe.

        Returns:
            List[Tuple[str, str]]: Liste des options générées dynamiquement
        """
        try:
            # Récupérer la configuration des options dynamiques
            dynamic_config = self.field_config['dynamic_options']
            script_name = dynamic_config.get('script')

            if not script_name:
                logger.error(f"Nom de script non spécifié pour {self.field_id}")
                return [("Erreur: script non spécifié", "error_script")]

            # Déterminer le chemin du script
            script_path = self.resolve_script_path(dynamic_config)

            if not os.path.exists(script_path):
                logger.error(f"Script {script_path} non trouvé pour {self.field_id}")
                return [("Erreur: script non trouvé", "error_not_found")]

            # Importer le module
            module = self.import_script_module(script_path)
            if not module:
                return [("Erreur: import du module échoué", "error_import")]

            # Déterminer la fonction à appeler
            function_name = dynamic_config.get('function')
            if not function_name:
                # Essayer de trouver une fonction qui commence par get_
                function_name = next((name for name in dir(module)
                                     if name.startswith('get_') and callable(getattr(module, name))), None)

            if not function_name or not hasattr(module, function_name):
                logger.error(f"Fonction {function_name} non trouvée dans {script_name}")
                return [("Erreur: fonction non trouvée", "error_function")]

            # Préparer les arguments
            function_args = self.prepare_dynamic_function_args(dynamic_config)

            # Appeler la fonction
            result = getattr(module, function_name)(**function_args)

            # Traiter le résultat
            return self.process_dynamic_result(result, dynamic_config)

        except Exception as e:
            logger.error(f"Erreur lors du chargement des options dynamiques pour {self.field_id}: {e}")
            logger.error(traceback.format_exc())
            return [("Erreur: " + str(e)[:30], "error_exception")]

    def resolve_script_path(self, dynamic_config: Dict[str, Any]) -> str:
        """
        Résout le chemin du script pour les options dynamiques.

        Args:
            dynamic_config: Configuration des options dynamiques

        Returns:
            str: Chemin complet vers le script
        """
        script_name = dynamic_config['script']

        # Cas 1: Script global
        if dynamic_config.get('global', False):
            return os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', script_name)

        # Cas 2: Chemin personnalisé
        if 'path' in dynamic_config:
            path = dynamic_config['path']

            # Chemin absolu
            if os.path.isabs(path):
                return os.path.join(path, script_name)

            # Chemin relatif avec syntaxe spéciale @[dossier]
            if path.startswith('@[') and path.endswith(']'):
                dir_name = path[2:-1]
                return os.path.join(os.path.dirname(__file__), '..', '..', dir_name, script_name)

            # Chemin relatif standard
            return os.path.join(path, script_name)

        # Cas 3: Script dans le dossier du plugin
        return os.path.join(os.path.dirname(__file__), '..', '..', 'plugins', self.source_id, script_name)

    def import_script_module(self, script_path: str) -> Optional[Any]:
        """
        Importe un module Python depuis un chemin de fichier.

        Args:
            script_path: Chemin vers le script

        Returns:
            Optional[Any]: Module importé ou None en cas d'erreur
        """
        try:
            # Ajouter le dossier du script au chemin de recherche
            script_dir = os.path.dirname(script_path)
            if script_dir not in sys.path:
                sys.path.append(script_dir)

            # Créer un spécificateur de module
            spec = importlib.util.spec_from_file_location("dynamic_module", script_path)
            if not spec:
                logger.error(f"Impossible de créer un spécificateur pour {script_path}")
                return None

            # Charger le module
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            logger.error(f"Erreur lors de l'importation du module {script_path}: {e}")
            return None

    def prepare_dynamic_function_args(self, dynamic_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prépare les arguments pour la fonction d'options dynamiques.

        Args:
            dynamic_config: Configuration des options dynamiques

        Returns:
            Dict[str, Any]: Arguments à passer à la fonction
        """
        args = {}

        if 'args' not in dynamic_config:
            return args

        for arg_config in dynamic_config['args']:
            # Argument provenant d'un autre champ
            if 'field' in arg_config:
                field_id = arg_config['field']

                # Chercher le champ dans fields_by_id
                if field_id in self.fields_by_id:
                    field = self.fields_by_id[field_id]

                    # Ne pas utiliser les valeurs des champs désactivés
                    if not (hasattr(field, 'disabled') and field.disabled):
                        field_value = self.get_field_value(field)
                        param_name = arg_config.get('param_name', field_id)
                        args[param_name] = field_value
                else:
                    logger.debug(f"Champ {field_id} non trouvé pour l'argument d'options dynamiques")

            # Argument avec valeur directe
            elif 'value' in arg_config:
                param_name = arg_config.get('param_name')
                if param_name:
                    args[param_name] = arg_config['value']

        return args

    def get_field_value(self, field: Any) -> Any:
        """
        Récupère la valeur d'un champ de manière sécurisée.

        Args:
            field: Champ dont il faut récupérer la valeur

        Returns:
            Any: Valeur du champ ou None en cas d'erreur
        """
        try:
            if hasattr(field, 'get_value'):
                return field.get_value()
            elif hasattr(field, 'value'):
                return field.value
            return None
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la valeur du champ: {e}")
            return None

    def process_dynamic_result(self, result: Any, dynamic_config: Dict[str, Any]) -> List[Tuple[str, str]]:
        """
        Traite le résultat d'une fonction d'options dynamiques.

        Args:
            result: Résultat de la fonction
            dynamic_config: Configuration des options dynamiques

        Returns:
            List[Tuple[str, str]]: Options traitées
        """
        # Cas 1: Résultat au format (success, data)
        if isinstance(result, tuple) and len(result) == 2:
            success, data = result

            if not success:
                logger.error(f"La fonction d'options dynamiques a échoué: {data}")
                return [("Erreur: " + str(data)[:30], "error_function_failed")]

            # Utiliser data comme résultat
            result = data

        # Cas 2: Résultat est une liste
        if isinstance(result, list):
            return self.normalize_options(result)

        # Cas 3: Résultat est un dictionnaire
        if isinstance(result, dict):
            # Si une clé dict est spécifiée dans la config, extraire cette partie
            if 'dict' in dynamic_config:
                dict_key = dynamic_config['dict']
                if dict_key in result and isinstance(result[dict_key], (list, dict)):
                    result = result[dict_key]

            # Si result est maintenant un dictionnaire
            if isinstance(result, List):
                if dynamic_config.get('value') and dynamic_config.get('description'):
                    value_key=dynamic_config.get('value')
                    desc_key=dynamic_config.get('description')
                else:
                    value_key="value"
                    desc_key="description"
                options = []
                for item in result:
                    # Format avec clés spécifiées pour value et description
                    if value_key in item and desc_key in item:
                        options.append((str(item[desc_key]), str(item[value_key])))
                return options or [("Aucune option trouvée", "no_options")]

        # Cas 4: Format non reconnu ou non traité
        logger.error(f"Format de résultat non reconnu: {type(result)}")
        return [("Format non reconnu", "error_format")]


    def set_value(self, value: Any, update_input: bool = True, update_dependencies: bool = True) -> bool:
        """
        Définit la valeur du champ de sélection.

        Args:
            value: Nouvelle valeur
            update_input: Si True, met à jour le widget select
            update_dependencies: Si True, notifie les champs dépendants

        Returns:
            bool: True si la mise à jour a réussi
        """
        # Conversion à la chaîne (les valeurs de select sont toujours des chaînes)
        value_str = str(value) if value is not None else ""

        logger.debug(f"set_value({value_str}) pour {self.field_id}")

        # Vérifier si la valeur change réellement
        if self._value == value_str:
            logger.debug(f"Valeur déjà à '{value_str}' pour {self.field_id}")
            return True

        # Mise à jour de la valeur interne
        old_value = self._value
        self._value = value_str
        logger.debug(f"Valeur interne mise à jour pour {self.field_id}: '{old_value}' → '{value_str}'")

        # Mise à jour du widget si demandé
        if update_input and hasattr(self, 'select') and not self._updating_widget:
            try:
                # Marquer que nous mettons à jour le widget pour éviter les cycles
                self._updating_widget = True

                # Vérifier que la valeur existe dans les options
                available_values = [opt[1] for opt in self.options]

                # Cas 1: Valeur exacte dans les options
                if value_str in available_values:
                    if self.select.value != value_str:
                        logger.debug(f"Mise à jour du widget select pour {self.field_id}: '{self.select.value}' → '{value_str}'")
                        self.select.value = value_str

                # Cas 2: Valeur non trouvée - essayer une correspondance partielle
                else:
                    found = False
                    for option_value in available_values:
                        if option_value.startswith(value_str) or value_str.startswith(option_value.split('.')[0]):
                            if self.select.value != option_value:
                                logger.debug(f"Correspondance partielle pour {self.field_id}: '{value_str}' → '{option_value}'")
                                self.select.value = option_value
                                self._value = option_value  # Mettre à jour la valeur interne avec la correspondance
                            found = True
                            break

                    # Cas 3: Aucune correspondance - utiliser la première option
                    if not found and available_values:
                        logger.warning(f"Valeur '{value_str}' non trouvée dans les options pour {self.field_id}, " +
                                     f"utilisation de '{available_values[0]}'")
                        self.select.value = available_values[0]
                        self._value = available_values[0]  # Mettre à jour la valeur interne

            finally:
                # Toujours réinitialiser le flag
                self._updating_widget = False

        # Notification des dépendances si demandé
        if update_dependencies:
            self._notify_parent_containers()

        logger.debug(f"set_value réussi pour {self.field_id}")
        return True

    def on_select_changed(self, event: Select.Changed) -> None:
        """
        Gestionnaire d'événement quand l'utilisateur modifie la sélection.

        Args:
            event: Événement de changement de select
        """
        # Vérifier que c'est bien notre select qui a changé
        if event.select.id != f"select_{self.field_id}":
            return

        # Si nous sommes en train de mettre à jour le widget, ignorer l'événement
        if self._updating_widget:
            logger.debug(f"Ignorer l'événement on_select_changed pendant la mise à jour pour {self.field_id}")
            return

        # Récupérer la nouvelle valeur
        new_value = event.value

        # Valeur différente de la valeur interne?
        if self._value == new_value:
            logger.debug(f"on_select_changed: valeur déjà à jour pour {self.field_id}: '{new_value}'")
            return

        logger.debug(f"on_select_changed pour {self.field_id}: '{self._value}' → '{new_value}'")

        # Appeler set_value sans mettre à jour le select (déjà fait par l'utilisateur)
        self.set_value(new_value, update_input=False)

    def get_value(self) -> Optional[str]:
        """
        Récupère la valeur actuelle du champ.

        Returns:
            Optional[str]: Valeur du champ ou None si désactivé
        """
        # Si le champ est désactivé, renvoyer None conformément à l'interface ConfigField
        if hasattr(self, 'disabled') and self.disabled:
            return None

        # Filtrer certaines valeurs d'erreur
        error_values = ["no_options", "placeholder", "fallback", "error_loading",
                       "error_function", "error_script", "error_format", "error_not_found",
                       "error_import", "error_exception", "error_function_failed"]

        if self._value in error_values:
            return ""

        return self._value

    @property
    def value(self) -> str:
        """
        Accesseur pour la valeur interne.

        Returns:
            str: Valeur du champ
        """
        # Pour l'interface Select, priorité au widget s'il existe
        if hasattr(self, 'select'):
            return self.select.value
        return self._value if self._value is not None else ""

    @value.setter
    def value(self, new_value: Any) -> None:
        """
        Modification de la valeur via l'accesseur.

        Args:
            new_value: Nouvelle valeur
        """
        # Déléguer à set_value
        self.set_value(new_value)

    def update_dynamic_options(self, **kwargs) -> bool:
        """
        Met à jour les options dynamiques du champ.

        Args:
            **kwargs: Arguments dynamiques pour l'actualisation des options

        Returns:
            bool: True si les options ont été mises à jour avec succès
        """
        logger.debug(f"Mise à jour des options dynamiques pour {self.field_id} avec {kwargs}")

        # Si le champ est désactivé, ne pas mettre à jour les options
        if hasattr(self, 'disabled') and self.disabled:
            logger.debug(f"Champ {self.field_id} désactivé, pas de mise à jour des options")
            return False

        try:
            # Sauvegarder la valeur actuelle
            current_value = self._value

            # Charger les nouvelles options
            old_options = self.options
            dynamic_config = self.field_config.get('dynamic_options', {})

            # Préparer la configuration avec les arguments fournis
            merged_config = dynamic_config.copy()
            if 'args' in merged_config:
                for arg in merged_config['args']:
                    if 'field' in arg and 'param_name' in arg:
                        param_name = arg['param_name']
                        if param_name in kwargs:
                            # Injecter les arguments fournis
                            arg['_value'] = kwargs[param_name]

            # Récupérer les options en utilisant les arguments fournis
            new_options = self.get_dynamic_options()

            # Si aucune option, c'est un échec
            if not new_options or len(new_options) == 0:
                logger.warning(f"Aucune option obtenue pour {self.field_id}")
                self.options = [("Aucune option disponible", "no_options")]

                # Mettre à jour le widget si existant
                if hasattr(self, 'select'):
                    self.select.options = self.options
                    self.select.value = "no_options"
                    self._value = "no_options"

                return False

            # Mettre à jour les options
            self.options = new_options
            logger.debug(f"Options mises à jour pour {self.field_id}: {len(new_options)} options")

            # Mettre à jour le widget si existant
            if hasattr(self, 'select'):
                self.select.options = new_options

                # Essayer de restaurer la valeur précédente
                available_values = [opt[1] for opt in new_options]

                if current_value in available_values:
                    # Valeur existante toujours disponible
                    self.select.value = current_value
                elif available_values:
                    # Utiliser la première option disponible
                    self.select.value = available_values[0]
                    self._value = available_values[0]
                    logger.debug(f"Valeur mise à jour pour {self.field_id}: '{current_value}' → '{available_values[0]}'")

            return True

        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des options dynamiques pour {self.field_id}: {e}")
            logger.error(traceback.format_exc())
            return False