from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.widgets import Label, Select
import os
from typing import Dict, Any, Optional, Tuple, List, Set, Union, Callable
import importlib.util
import sys
import traceback

from ..utils.logging import get_logger

logger = get_logger('config_field')

class ConfigField(VerticalGroup):
    """
    Classe de base pour tous les champs de configuration.

    Cette classe fournit les fonctionnalités communes à tous les champs
    et doit être sous-classée par des types de champs spécifiques.
    """

    def __init__(self, source_id: str, field_id: str, field_config: Dict[str, Any],
                fields_by_id: Optional[Dict[str, Any]] = None, is_global: bool = False):
        """
        Initialise un champ de configuration.

        Args:
            source_id: ID de la source (plugin ou config globale)
            field_id: ID du champ
            field_config: Configuration du champ
            fields_by_id: Dictionnaire des champs indexés par ID (pour les dépendances)
            is_global: Indique si c'est un champ global ou spécifique à un plugin
        """
        super().__init__()
        # Attributs d'identification
        self.source_id = source_id                 # ID de la source (plugin ou config globale)
        self.field_id = field_id                   # ID du champ
        self.unique_id = field_config.get('unique_id', field_id)  # ID unique pour ce champ

        # Configuration et références
        self.field_config = field_config           # Configuration du champ
        self.fields_by_id = fields_by_id or {}     # Champs indexés par ID pour les dépendances
        self.is_global = is_global                 # Indique si c'est un champ global ou plugin
        self.variable_name = field_config.get('variable', field_id)  # Nom de la variable pour l'export

        # Définition des dictionnaires de dépendances
        self.dependencies = {
            # Activation conditionnelle: ce champ est activé si un autre champ a une certaine valeur
            'enabled_if': None,           # {field_id: required_value} ou None

            # Valeur dépendante: la valeur de ce champ dépend d'un autre champ
            'depends_on': None,           # field_id ou None

            # Options dynamiques: les options de ce champ dépendent d'autres champs
            'dynamic_options': None,      # {script, function, args: [{field, param_name},...]}

            # Champs qui dépendent de celui-ci (rempli par le conteneur parent)
            'dependent_fields': {
                'enabled': set(),          # Champs dont l'activation dépend de celui-ci
                'value': set(),            # Champs dont la valeur dépend de celui-ci
                'options': set()           # Champs dont les options dépendent de celui-ci
            }
        }

        # Initialiser les dépendances à partir de la configuration
        self._init_dependencies()

        # Valeur actuelle
        self.value = self._get_default_value()
        logger.debug(f"Champ {self.field_id} initialisé avec valeur: {self.value}")

    def _init_dependencies(self) -> None:
        """
        Initialise toutes les dépendances à partir de la configuration.
        """
        # === ENABLED_IF ===
        if 'enabled_if' in self.field_config:
            enabled_if = self.field_config['enabled_if']
            
            # Stocker l'état initial pour restauration plus tard si nécessaire
            self._original_default = self.field_config.get('default')
            
            # Vérifier si c'est une structure simple ou multiple
            if isinstance(enabled_if, dict):
                # Détecter si c'est une structure simple (field+value) ou une structure avec plusieurs conditions
                if 'field' in enabled_if and 'value' in enabled_if:
                    # Structure simple - un seul champ et une seule valeur
                    conditions = [{
                        'field_id': enabled_if['field'],
                        'required_value': enabled_if['value']
                    }]
                    remove_if_disabled = enabled_if.get('remove_if_disabled', False)
                    logger.debug(f"Dépendance enabled_if simple définie pour {self.field_id}: "
                                f"activé si {enabled_if['field']} = {enabled_if['value']}")
                elif 'conditions' in enabled_if:
                    # Structure explicite avec plusieurs conditions
                    conditions = enabled_if['conditions']
                    remove_if_disabled = enabled_if.get('remove_if_disabled', False)
                    logger.debug(f"Dépendance enabled_if multiple explicite définie pour {self.field_id}: "
                                f"{len(conditions)} conditions")
                else:
                    # Structure implicite - chaque clé qui n'est pas 'remove_if_disabled' ou 'operator' est un champ
                    conditions = []
                    for field_id, value in enabled_if.items():
                        if field_id not in ['remove_if_disabled', 'operator']:
                            conditions.append({
                                'field_id': field_id,
                                'required_value': value
                            })
                    remove_if_disabled = enabled_if.get('remove_if_disabled', False)
                    logger.debug(f"Dépendance enabled_if multiple implicite définie pour {self.field_id}: "
                                f"{len(conditions)} conditions")
                
                # Structure normalisée pour enabled_if avec support de plusieurs conditions
                self.dependencies['enabled_if'] = {
                    'conditions': conditions,
                    'operator': enabled_if.get('operator', 'AND'),  # AND ou OR
                    'remove_if_disabled': remove_if_disabled
                }
            elif isinstance(enabled_if, list):
                # Liste de conditions (format alternatif)
                conditions = []
                for condition in enabled_if:
                    if isinstance(condition, dict) and 'field' in condition and 'value' in condition:
                        conditions.append({
                            'field_id': condition['field'],
                            'required_value': condition['value']
                        })
                
                self.dependencies['enabled_if'] = {
                    'conditions': conditions,
                    'operator': 'AND',  # Par défaut, toutes les conditions doivent être vraies
                    'remove_if_disabled': False
                }
                logger.debug(f"Dépendance enabled_if multiple (liste) définie pour {self.field_id}: "
                            f"{len(conditions)} conditions")

        # === DEPENDS_ON ===
        if 'depends_on' in self.field_config:
            depends_on = self.field_config['depends_on']
            
            # Vérifier si c'est une chaîne simple, une liste ou un dictionnaire
            if isinstance(depends_on, str):
                # Format simple : une seule dépendance sous forme de chaîne
                self.dependencies['depends_on'] = {
                    'fields': [depends_on],
                    'operator': 'AND'  # Par défaut, tous les champs doivent changer
                }
                logger.debug(f"Dépendance depends_on simple définie pour {self.field_id}: "
                           f"valeur dépend de {depends_on}")
            elif isinstance(depends_on, list):
                # Format liste : plusieurs dépendances sous forme de liste
                self.dependencies['depends_on'] = {
                    'fields': depends_on,
                    'operator': 'AND'  # Par défaut, tous les champs doivent changer
                }
                logger.debug(f"Dépendance depends_on multiple (liste) définie pour {self.field_id}: "
                           f"valeur dépend de {', '.join(depends_on)}")
            elif isinstance(depends_on, dict):
                # Format dictionnaire : configuration avancée
                if 'fields' in depends_on:
                    # Format explicite avec liste de champs
                    fields = depends_on['fields']
                    operator = depends_on.get('operator', 'AND')
                    self.dependencies['depends_on'] = {
                        'fields': fields if isinstance(fields, list) else [fields],
                        'operator': operator
                    }
                    logger.debug(f"Dépendance depends_on avancée définie pour {self.field_id}: "
                               f"valeur dépend de {fields} avec opérateur {operator}")
                else:
                    # Format implicite - chaque clé qui n'est pas 'operator' est un champ
                    fields = []
                    for field_id, include in depends_on.items():
                        if field_id != 'operator' and include:
                            fields.append(field_id)
                    
                    self.dependencies['depends_on'] = {
                        'fields': fields,
                        'operator': depends_on.get('operator', 'AND')
                    }
                    logger.debug(f"Dépendance depends_on implicite définie pour {self.field_id}: "
                               f"valeur dépend de {', '.join(fields)}")
            else:
                # Type non reconnu, utiliser comme une seule dépendance
                self.dependencies['depends_on'] = {
                    'fields': [str(depends_on)],
                    'operator': 'AND'
                }
                logger.debug(f"Dépendance depends_on de type non reconnu pour {self.field_id}: "
                           f"valeur dépend de {depends_on}")

        # === DYNAMIC_OPTIONS ===
        if 'dynamic_options' in self.field_config:
            dynamic_config = self.field_config['dynamic_options']

            # Structure normalisée pour dynamic_options
            self.dependencies['dynamic_options'] = {
                'script': dynamic_config.get('script'),
                'function': dynamic_config.get('function'),
                'global': dynamic_config.get('global', False),
                'path': dynamic_config.get('path'),
                'args': [],
                'value_key': dynamic_config.get('value'),
                'description_key': dynamic_config.get('description')
            }

            # Traiter les arguments qui font référence à d'autres champs
            if 'args' in dynamic_config:
                for arg in dynamic_config['args']:
                    if 'field' in arg:
                        self.dependencies['dynamic_options']['args'].append({
                            'field_id': arg['field'],
                            'param_name': arg.get('param_name', arg['field'])
                        })
                        logger.debug(f"Argument dynamic_options ajouté pour {self.field_id}: "
                                   f"utilise {arg['field']} comme {arg.get('param_name', arg['field'])}")

            logger.debug(f"Dépendance dynamic_options définie pour {self.field_id}")

    def _get_default_value(self, source_value=None) -> Any:
        """
        Détermine la valeur par défaut du champ, optionnellement basée sur une valeur source.

        Args:
            source_value: Valeur optionnelle du champ source dans le cas d'une dépendance

        Returns:
            Any: Valeur par défaut du champ
        """
        # Cas 1: Dépendance sur un autre champ avec mapping de valeurs
        if self.dependencies['depends_on'] and 'values' in self.field_config:
            # Si une valeur source est fournie, l'utiliser directement
            if source_value is not None:
                values_map = self.field_config['values']
                if source_value in values_map:
                    logger.debug(f"Valeur pour {self.field_id} basée sur valeur source {source_value}: {values_map[source_value]}")
                    return values_map[source_value]
            # Sinon, utiliser la méthode standard
            return self._get_dependent_value()

        # Cas 2: Valeur par défaut dynamique via script
        if 'dynamic_default' in self.field_config:
            dynamic_value = self._get_dynamic_default()
            if dynamic_value is not None:
                return dynamic_value

        # Cas 3: Valeur par défaut statique dans la configuration
        if 'default' in self.field_config:
            return self.field_config.get('default')

        # Cas 4: Aucune valeur par défaut spécifiée
        return None

    def _get_dependent_value(self) -> Any:
        """
        Récupère la valeur en fonction d'un autre champ.

        Returns:
            Any: Valeur basée sur le champ dont dépend celui-ci
        """
        depends_on = self.dependencies['depends_on']
        if not depends_on or depends_on not in self.fields_by_id:
            return self.field_config.get('default')

        dependent_field = self.fields_by_id[depends_on]
        dependent_value = dependent_field.get_value()
        values_map = self.field_config['values']

        if dependent_value in values_map:
            logger.debug(f"Valeur pour {self.field_id} basée sur {depends_on}={dependent_value}: {values_map[dependent_value]}")
            return values_map[dependent_value]

        # Si pas de correspondance, utiliser la valeur par défaut standard
        return self.field_config.get('default')

    def _get_dynamic_default(self) -> Any:
        """
        Récupère une valeur par défaut dynamique via un script.

        Returns:
            Any: Valeur obtenue dynamiquement ou None en cas d'échec
        """
        try:
            if 'dynamic_default' not in self.field_config or 'script' not in self.field_config['dynamic_default']:
                return None

            dynamic_config = self.field_config['dynamic_default']
            script_name = dynamic_config['script']
            logger.debug(f"Chargement de valeur dynamique pour {self.field_id} via script: {script_name}")

            # Déterminer le chemin du script
            script_path = self._resolve_script_path(dynamic_config)
            if not os.path.exists(script_path):
                logger.error(f"Script non trouvé: {script_path}")
                return None

            # Importer le script
            module = self._import_script_module(script_path)
            if not module:
                return None

            # Déterminer la fonction à appeler
            function_name = dynamic_config.get('function', 'get_default_value')
            if not hasattr(module, function_name):
                logger.error(f"Fonction {function_name} non trouvée dans {script_name}")
                return None

            # Préparer les arguments
            function_args = self._prepare_function_args(dynamic_config)

            # Appeler la fonction
            result = getattr(module, function_name)(**function_args)
            logger.debug(f"Résultat obtenu du script: {result}")

            # Traiter le résultat
            return self._process_dynamic_result(result, dynamic_config)

        except Exception as e:
            logger.error(f"Erreur lors de l'obtention de la valeur dynamique: {e}")
            logger.error(traceback.format_exc())
            return None

    def _resolve_script_path(self, dynamic_config: Dict[str, Any]) -> str:
        """
        Résout le chemin d'un script dynamique.

        Args:
            dynamic_config: Configuration pour la valeur dynamique

        Returns:
            str: Chemin complet vers le script
        """
        script_name = dynamic_config['script']

        # Cas 1: Chemin personnalisé spécifié
        if 'path' in dynamic_config:
            path = dynamic_config['path']

            # Syntaxe @[directory]
            if path.startswith('@[') and path.endswith(']'):
                dir_name = path[2:-1]  # Extraire le nom du répertoire entre @[ et ]
                if dir_name == 'scripts':
                    return os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', script_name)
                return os.path.join(os.path.dirname(__file__), '..', '..', dir_name, script_name)

            # Chemin absolu ou relatif directement spécifié
            return os.path.join(path, script_name) if not os.path.isabs(path) else os.path.join(path, script_name)

        # Cas 2: Script global
        if dynamic_config.get('global', False):
            return os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', script_name)

        # Cas 3: Script dans le dossier du plugin
        return os.path.join(os.path.dirname(__file__), '..', '..', 'plugins', self.source_id, script_name)

    def _import_script_module(self, script_path: str) -> Optional[Any]:
        """
        Importe un module Python depuis un chemin de fichier.

        Args:
            script_path: Chemin vers le script à importer

        Returns:
            Optional[Any]: Module importé ou None en cas d'échec
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

    def _prepare_function_args(self, dynamic_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prépare les arguments à passer à la fonction dynamique.

        Args:
            dynamic_config: Configuration pour la valeur dynamique

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
                if field_id in self.fields_by_id:
                    field_value = self.fields_by_id[field_id].get_value()
                    param_name = arg_config.get('param_name', field_id)
                    args[param_name] = field_value

            # Argument avec valeur directe
            elif 'value' in arg_config:
                param_name = arg_config.get('param_name')
                if param_name:
                    args[param_name] = arg_config['value']

        return args

    def _process_dynamic_result(self, result: Any, dynamic_config: Dict[str, Any]) -> Any:
        """
        Traite le résultat d'une fonction dynamique.

        Args:
            result: Résultat retourné par la fonction
            dynamic_config: Configuration pour la valeur dynamique

        Returns:
            Any: Valeur extraite du résultat
        """
        # Cas 1: Résultat au format (success, value)
        if isinstance(result, tuple) and len(result) == 2:
            success, value = result

            if not success:
                logger.warning(f"Fonction dynamique a échoué: {value}")
                return None

            # Extraire la valeur du dictionnaire si nécessaire
            if isinstance(value, dict):
                value_key = dynamic_config.get('value')
                if value_key and value_key in value:
                    return value[value_key]
                elif value:
                    return next(iter(value.values()))

            return value

        # Cas 2: Résultat est un dictionnaire
        if isinstance(result, dict):
            value_key = dynamic_config.get('value')
            if value_key and value_key in result:
                return result[value_key]
            elif result:
                return next(iter(result.values()))

        # Cas 3: Tout autre type de résultat
        return result

    def compose(self) -> ComposeResult:
        """
        Compose l'interface du champ de configuration.

        Returns:
            ComposeResult: Résultat de la composition
        """
        label = self.field_config.get('label', self.field_id)

        # Création de l'en-tête avec le libellé
        with HorizontalGroup(classes="field-header", id=f"header_{self.field_id}"):
            if self.field_config.get('required', False):
                # Combiner le label et l'astérisque dans un seul Label pour éviter les sauts de ligne
                yield Label(f"{label} *", classes="field-label required-field-container")
            else:
                yield Label(label, classes="field-label")

        # Vérifier si le champ doit être activé ou non selon les dépendances
        self._check_initial_enabled_state()

    def _check_initial_enabled_state(self) -> None:
        """
        Vérifie si le champ doit être initialement activé ou désactivé selon ses dépendances.
        Supporte les dépendances multiples avec opérateurs logiques (AND/OR).
        """
        if not self.dependencies['enabled_if']:
            return

        # Récupérer les informations de dépendance
        dep_info = self.dependencies['enabled_if']
        
        # Vérifier si nous avons la nouvelle structure avec conditions multiples
        if 'conditions' in dep_info:
            # Nouvelle structure avec conditions multiples
            conditions = dep_info['conditions']
            operator = dep_info.get('operator', 'AND')
            condition_results = []
            
            for condition in conditions:
                dep_field_id = condition['field_id']
                required_value = condition['required_value']
                
                # Chercher le champ dépendant
                dep_field = self.fields_by_id.get(dep_field_id)
                
                if dep_field:
                    # Récupérer la valeur actuelle
                    field_value = dep_field.get_value()
                    
                    # Normaliser les valeurs booléennes si nécessaire
                    if isinstance(required_value, bool) and not isinstance(field_value, bool):
                        field_value = str(field_value).lower() in ('true', '1', 'yes', 'y', 'oui', 'o')
                    
                    # Comparer les valeurs
                    condition_results.append(field_value == required_value)
                else:
                    # Si le champ dépendant n'est pas trouvé, considérer la condition comme fausse
                    condition_results.append(False)
            
            # Appliquer l'opérateur logique
            if operator.upper() == 'AND':
                should_enable = all(condition_results)
            elif operator.upper() == 'OR':
                should_enable = any(condition_results)
            else:
                # Opérateur non reconnu, utiliser AND par défaut
                should_enable = all(condition_results)
                
            # Appliquer l'état activé/désactivé
            self.disabled = not should_enable
            
            # Gérer remove_if_disabled si nécessaire
            if self.disabled and dep_info.get('remove_if_disabled', False):
                self.display = False
            else:
                self.display = True
        else:
            # Ancienne structure (rétro-compatibilité)
            dep_field_id = dep_info['field_id']
            required_value = dep_info['required_value']

            # Chercher le champ dépendant
            dep_field = self.fields_by_id.get(dep_field_id)

            if dep_field:
                # Récupérer la valeur actuelle
                field_value = dep_field.get_value()

                # Normaliser les valeurs booléennes si nécessaire
                if isinstance(required_value, bool) and not isinstance(field_value, bool):
                    field_value = self._normalize_bool_value(field_value)

                logger.debug(f"État initial pour {self.field_id}: {field_value} == {required_value}")

                # Définir l'état initial
                self.disabled = field_value != required_value
                if self.disabled:
                    self.add_class('disabled')
                else:
                    self.remove_class('disabled')
            else:
                # Par défaut, désactiver si le champ dépendant n'est pas résolu
                logger.debug(f"Champ dépendant {dep_field_id} non trouvé pour {self.field_id}, désactivé par défaut")
                self.disabled = True
                self.add_class('disabled')

    def _normalize_bool_value(self, value: Any) -> bool:
        """
        Normalise une valeur en booléen.

        Args:
            value: Valeur à normaliser

        Returns:
            bool: Valeur normalisée
        """
        if isinstance(value, str):
            return value.lower() in ('true', 't', 'yes', 'y', '1')
        return bool(value)

    def get_value(self) -> Any:
        """
        Récupère la valeur actuelle du champ.
        Renvoie None si le champ est désactivé.

        Returns:
            Any: Valeur du champ ou None si désactivé
        """
        if hasattr(self, 'disabled') and self.disabled:
            return None
        return self.value

    def set_value(self, value: Any, update_input: bool = True, update_dependencies: bool = True) -> bool:
        """
        Définit la valeur du champ.

        Args:
            value: Nouvelle valeur
            update_input: Si True, met à jour le widget d'entrée
            update_dependencies: Si True, notifie les champs dépendants

        Returns:
            bool: True si la mise à jour a réussi
        """
        # À implémenter par les sous-classes
        self.value = value

        # Notifier les containers parents si nécessaire
        if update_dependencies:
            self._notify_parent_containers()

        return True

    def _notify_parent_containers(self) -> None:
        """
        Notifie les containers parents du changement pour mettre à jour les dépendances.
        """
        logger.debug(f"Notification des changements aux parents pour {self.field_id}")
        parent = self.parent
        while parent:
            if hasattr(parent, 'update_dependent_fields'):
                logger.debug(f"Mise à jour des champs dépendants via {parent}")
                parent.update_dependent_fields(self)
                break
            parent = parent.parent

    def update_dynamic_options(self, **kwargs) -> bool:
        """
        Met à jour les options dynamiques du champ.
        Cette méthode est destinée à être surchargée par les classes filles.

        Args:
            **kwargs: Arguments dynamiques pour l'actualisation des options

        Returns:
            bool: True si les options ont été mises à jour avec succès
        """
        return False

    def restore_default(self) -> bool:
        """
        Réinitialise le champ à sa valeur par défaut définie dans la configuration.
        Prend en compte les valeurs par défaut dynamiques définies via des scripts.
        
        Returns:
            bool: True si la réinitialisation a réussi
        """
        try:
            # Vérifier si une valeur par défaut dynamique est définie
            if 'dynamic_default' in self.field_config:
                logger.debug(f"Récupération de la valeur par défaut dynamique pour {self.field_id}")
                dynamic_value = self._get_dynamic_default()
                
                if dynamic_value is not None:
                    logger.debug(f"Réinitialisation de {self.field_id} à la valeur dynamique: '{dynamic_value}'")
                    return self.set_value(dynamic_value, update_input=True, update_dependencies=True)
                else:
                    logger.warning(f"Valeur dynamique non disponible pour {self.field_id}, utilisation de la valeur par défaut statique")
            
            # Sinon, utiliser la valeur par défaut statique
            default_value = self.field_config.get('default')
            
            if default_value is not None:
                logger.debug(f"Réinitialisation de {self.field_id} à la valeur par défaut statique: {default_value}")
                return self.set_value(default_value, update_input=True, update_dependencies=True)
            else:
                logger.debug(f"Pas de valeur par défaut définie pour {self.field_id}")
                # Pour les champs sans valeur par défaut, on peut définir une valeur vide
                return self.set_value("", update_input=True, update_dependencies=True)
        except Exception as e:
            logger.error(f"Erreur lors de la réinitialisation de {self.field_id}: {e}")
            return False

    def validate_input(self, value: Any) -> Tuple[bool, str]:
        """
        Valide une valeur d'entrée.

        Args:
            value: Valeur à valider

        Returns:
            Tuple[bool, str]: (validité, message d'erreur)
        """
        return True, ""

    def on_select_changed(self, event: Select.Changed) -> None:
        """
        Gère les changements de valeur pour les champs de type select.

        Args:
            event: Événement de changement du select
        """
        if not hasattr(self, 'field_id') or not event.select.id.endswith(self.field_id):
            return

        # Mettre à jour la valeur
        self.value = str(event.value) if event.value is not None else ""
        logger.debug(f"Valeur de {self.field_id} changée à {self.value}")

        # Notifier les containers parents du changement
        self._notify_parent_containers()