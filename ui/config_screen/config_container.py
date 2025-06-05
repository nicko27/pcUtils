from textual.app import ComposeResult
from textual.containers import VerticalGroup, HorizontalGroup
from textual.widgets import Label, Input, Select, Button, Checkbox
from textual.reactive import reactive
from textual.widget import Widget
from typing import Dict, List, Any, Optional, Set, Type

from .text_field import TextField
from .directory_field import DirectoryField
from .ip_field import IPField
from .checkbox_field import CheckboxField
from .select_field import SelectField
from .checkbox_group_field import CheckboxGroupField
from .password_field import PasswordField

from ..utils.logging import get_logger

logger = get_logger('config_container')

class ConfigContainer(VerticalGroup):
    """
    Conteneur de base pour les champs de configuration.

    Gère à la fois les configurations de plugins et les configurations globales,
    avec les dépendances entre champs.
    """

    # Définition des attributs réactifs
    source_id = reactive("")       # Identifiant de la source (plugin ou config globale)
    title = reactive("")           # Titre d'affichage
    icon = reactive("")            # Icône d'affichage
    description = reactive("")     # Description du conteneur
    is_global = reactive(False)    # Si True, c'est une configuration globale

    # Mapping des types de champs
    FIELD_TYPES = {
        'text': TextField,
        'directory': DirectoryField,
        'ip': IPField,
        'checkbox': CheckboxField,
        'select': SelectField,
        'checkbox_group': CheckboxGroupField,
        'password': PasswordField
    }

    def __init__(self, source_id: str, title: str, icon: str, description: str,
                 fields_by_id: Dict[str, Any], config_fields: List[Dict[str, Any]],
                 is_global: bool = False, **kwargs):
        """
        Initialise un conteneur de configuration.

        Args:
            source_id: Identifiant de la source (plugin ou config globale)
            title: Titre d'affichage
            icon: Icône d'affichage
            description: Description du conteneur
            fields_by_id: Dictionnaire des champs par ID
            config_fields: Liste des configurations de champs
            is_global: Si True, c'est une configuration globale
            **kwargs: Arguments supplémentaires pour le VerticalGroup
        """
        # Ajouter la classe CSS du conteneur
        if "classes" in kwargs:
            if "config-container" not in kwargs["classes"]:
                kwargs["classes"] += " config-container"
        else:
            kwargs["classes"] = "config-container"

        super().__init__(**kwargs)

        # Définir les attributs réactifs
        self.source_id = source_id
        self.title = title
        self.icon = icon
        self.description = description
        self.is_global = is_global

        # Attributs non réactifs
        self.fields_by_id = fields_by_id            # Tous les champs référencés par ID
        self.config_fields = config_fields          # Configurations des champs

        # Structures de dépendances (mappings directs)
        self.enabled_if_map = {}     # {field_id: {dep_field_id: required_value}}
        self.value_deps_map = {}     # {field_id: dep_field_id}
        self.dynamic_options_map = {}  # {field_id: {dep_fields: [field_ids], args: [arg_configs]}}

        # Structures miroirs (mappings inversés)
        self.mirror_enabled_if = {}    # {field_id: [fields qui dépendent de field_id pour enabled_if]}
        self.mirror_value_deps = {}    # {field_id: [fields qui dépendent de field_id pour leur valeur]}
        self.mirror_dynamic_options = {} # {field_id: [fields qui dépendent de field_id pour leurs options]}

        # État interne
        self._updating_dependencies = False  # Flag pour éviter les cycles
        self._fields_to_remove = set()  # Champs à supprimer lors de la prochaine mise à jour

    def compose(self) -> ComposeResult:
        """
        Compose le conteneur avec ses champs de configuration.

        Returns:
            ComposeResult: Résultat de la composition
        """
        # En-tête: titre et description
        with VerticalGroup(classes="config-header"):
            yield Label(f"{self.icon} {self.title}", classes="config-title")
            if self.description:
                yield Label(self.description, classes="config-description")

        # Si aucun champ, afficher un message
        if not self.config_fields:
            with VerticalGroup(classes="no-config"):
                with HorizontalGroup(classes="no-config-content"):
                    yield Label("ℹ️", classes="no-config-icon")
                    yield Label(f"Rien à configurer pour ce plugin", classes="no-config-label")
                return

        # Créer les champs de configuration
        with VerticalGroup(classes="config-fields"):
            # Création des champs
            for field_config in self.config_fields:
                field = self._create_field(field_config)
                if field:
                    yield field

        # Après la création de tous les champs, analyser leurs dépendances
        # L'analyse est déplacée après la création pour avoir tous les champs disponibles
        self._analyze_field_dependencies()

    def _create_field(self, field_config: Dict[str, Any]) -> Optional[Widget]:
        """
        Crée un champ de configuration à partir de sa configuration.

        Args:
            field_config: Configuration du champ

        Returns:
            Optional[Widget]: Champ créé ou None en cas d'erreur
        """
        field_id = field_config.get('id')
        if not field_id:
            logger.warning(f"Champ sans ID dans {self.source_id}")
            return None

        # Utiliser l'ID unique s'il est disponible pour éviter les conflits entre instances
        unique_id = field_config.get('unique_id', field_id)

        field_type = field_config.get('type', 'text')
        logger.debug(f"Création du champ {field_id} (unique_id: {unique_id}) de type {field_type}")

        # Déterminer la classe du champ
        field_class = self.FIELD_TYPES.get(field_type, TextField)

        try:
            # Créer le champ avec accès aux autres champs
            field = field_class(
                self.source_id,
                field_id,
                field_config,
                self.fields_by_id,
                is_global=self.is_global
            )

            # Enregistrer le champ dans le dictionnaire global
            self.fields_by_id[unique_id] = field

            return field

        except Exception as e:
            logger.error(f"Erreur lors de la création du champ {field_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _analyze_field_dependencies(self) -> None:
        """
        Analyse les dépendances entre tous les champs du conteneur.
        Cette méthode construit les dictionnaires de dépendances directes et inversées.
        """
        logger.debug(f"DÉBUT _analyze_field_dependencies pour {self.source_id} avec {len(self.fields_by_id)} champs")
        
        # Afficher les champs disponibles pour le débogage
        field_ids = list(self.fields_by_id.keys())
        logger.debug(f"Champs disponibles: {field_ids}")

        # Réinitialiser les dictionnaires de dépendances
        self.enabled_if_map = {}
        self.value_deps_map = {}
        self.dynamic_options_map = {}
        self.mirror_enabled_if = {}
        self.mirror_value_deps = {}
        self.mirror_dynamic_options = {}

        # Parcourir tous les champs pour collecter les dépendances
        for field_id, field in self.fields_by_id.items():
            # Ignorer les champs qui n'appartiennent pas à ce conteneur
            if not hasattr(field, 'source_id') or field.source_id != self.source_id:
                continue

            # Vérifier les dépendances de type 'enabled_if'
            if hasattr(field, 'dependencies') and field.dependencies['enabled_if']:
                enabled_if = field.dependencies['enabled_if']
                
                # Vérifier si c'est l'ancien format (compatible) ou le nouveau format avec conditions multiples
                if 'conditions' in enabled_if:
                    # Nouveau format avec conditions multiples
                    conditions = enabled_if['conditions']
                    operator = enabled_if.get('operator', 'AND')
                    
                    # Enregistrer chaque condition
                    for condition in conditions:
                        dep_field_id = condition['field_id']
                        required_value = condition['required_value']
                        
                        # Enregistrer la dépendance directe
                        if field_id not in self.enabled_if_map:
                            self.enabled_if_map[field_id] = {}
                        
                        # Stocker la condition avec l'opérateur
                        if 'conditions' not in self.enabled_if_map[field_id]:
                            self.enabled_if_map[field_id]['conditions'] = []
                            self.enabled_if_map[field_id]['operator'] = operator
                        
                        self.enabled_if_map[field_id]['conditions'].append({
                            'field_id': dep_field_id,
                            'required_value': required_value
                        })
                        
                        # Enregistrer aussi la valeur directement pour la rétro-compatibilité
                        self.enabled_if_map[field_id][dep_field_id] = required_value
                        
                        # Enregistrer la dépendance inverse (miroir)
                        if dep_field_id not in self.mirror_enabled_if:
                            self.mirror_enabled_if[dep_field_id] = []
                        if field_id not in self.mirror_enabled_if[dep_field_id]:
                            self.mirror_enabled_if[dep_field_id].append(field_id)
                    
                    logger.debug(f"Dépendance enabled_if multiple: {field_id} dépend de {len(conditions)} conditions avec opérateur {operator}")
                    
                elif 'field_id' in enabled_if and 'required_value' in enabled_if:
                    # Ancien format (compatible)
                    dep_field_id = enabled_if['field_id']
                    required_value = enabled_if['required_value']

                    # Enregistrer la dépendance directe
                    if field_id not in self.enabled_if_map:
                        self.enabled_if_map[field_id] = {}
                    self.enabled_if_map[field_id][dep_field_id] = required_value
                    
                    # Ajouter également au nouveau format pour uniformité
                    self.enabled_if_map[field_id]['conditions'] = [{
                        'field_id': dep_field_id,
                        'required_value': required_value
                    }]
                    self.enabled_if_map[field_id]['operator'] = 'AND'

                    # Enregistrer la dépendance inverse (miroir)
                    if dep_field_id not in self.mirror_enabled_if:
                        self.mirror_enabled_if[dep_field_id] = []
                    if field_id not in self.mirror_enabled_if[dep_field_id]:
                        self.mirror_enabled_if[dep_field_id].append(field_id)

                    logger.debug(f"Dépendance enabled_if simple: {field_id} dépend de {dep_field_id}={required_value}")

            # Vérifier les dépendances de type 'depends_on' (valeur)
            if hasattr(field, 'dependencies') and field.dependencies['depends_on']:
                depends_on = field.dependencies['depends_on']
                
                # Vérifier si c'est l'ancien format (chaîne simple) ou le nouveau format (dictionnaire avec fields)
                if isinstance(depends_on, dict) and 'fields' in depends_on:
                    # Nouveau format avec plusieurs champs
                    fields = depends_on['fields']
                    operator = depends_on.get('operator', 'AND')
                    
                    # Créer une entrée pour ce champ s'il n'existe pas déjà
                    if field_id not in self.value_deps_map:
                        self.value_deps_map[field_id] = {}
                    
                    # Stocker la configuration complète
                    self.value_deps_map[field_id]['fields'] = fields
                    self.value_deps_map[field_id]['operator'] = operator
                    
                    # Enregistrer aussi chaque champ individuellement pour rétro-compatibilité
                    for dep_field_id in fields:
                        # Stocker aussi le champ directement pour la rétro-compatibilité
                        if isinstance(self.value_deps_map[field_id], dict) and 'direct' not in self.value_deps_map[field_id]:
                            self.value_deps_map[field_id]['direct'] = dep_field_id
                        
                        # Enregistrer la dépendance inverse (miroir)
                        if dep_field_id not in self.mirror_value_deps:
                            self.mirror_value_deps[dep_field_id] = []
                        if field_id not in self.mirror_value_deps[dep_field_id]:
                            self.mirror_value_deps[dep_field_id].append(field_id)
                    
                    logger.debug(f"Dépendance depends_on multiple: {field_id} dépend de {len(fields)} champs avec opérateur {operator}")
                else:
                    # Ancien format (chaîne simple) ou format de transition (liste)
                    dep_field_id = depends_on[0] if isinstance(depends_on, list) and depends_on else depends_on
                    
                    # Enregistrer la dépendance directe
                    self.value_deps_map[field_id] = dep_field_id
                    
                    # Enregistrer la dépendance inverse (miroir)
                    if dep_field_id not in self.mirror_value_deps:
                        self.mirror_value_deps[dep_field_id] = []
                    if field_id not in self.mirror_value_deps[dep_field_id]:
                        self.mirror_value_deps[dep_field_id].append(field_id)
                    
                    logger.debug(f"Dépendance de valeur: {field_id} dépend de {dep_field_id}")

            # Vérifier les dépendances de type 'dynamic_options'
            if hasattr(field, 'dependencies') and field.dependencies['dynamic_options']:
                dynamic_options = field.dependencies['dynamic_options']

                # Initialiser la structure pour ce champ
                self.dynamic_options_map[field_id] = {
                    'dep_fields': [],
                    'args': dynamic_options.get('args', [])
                }

                # Collecter tous les champs dont dépendent les options
                for arg in dynamic_options.get('args', []):
                    # Support du format avec 'field_id' (converti depuis 'field' dans _init_dependencies)
                    if 'field_id' in arg:
                        dep_field_id = arg['field_id']
                        
                        # S'assurer que l'ID du champ est une chaîne
                        dep_field_id = str(dep_field_id)

                        # Ajouter à la liste des dépendances
                        if dep_field_id not in self.dynamic_options_map[field_id]['dep_fields']:
                            self.dynamic_options_map[field_id]['dep_fields'].append(dep_field_id)

                        # Enregistrer la dépendance inverse (miroir)
                        if dep_field_id not in self.mirror_dynamic_options:
                            self.mirror_dynamic_options[dep_field_id] = []
                        if field_id not in self.mirror_dynamic_options[dep_field_id]:
                            self.mirror_dynamic_options[dep_field_id].append(field_id)

                        logger.debug(f"Dépendance dynamic_options: {field_id} dépend de {dep_field_id}")
                    # Support de l'ancien format avec 'field_id'
                    elif 'field_id' in arg:
                        dep_field_id = arg['field_id']
                        
                        # S'assurer que l'ID du champ est une chaîne
                        dep_field_id = str(dep_field_id)

                        # Ajouter à la liste des dépendances
                        if dep_field_id not in self.dynamic_options_map[field_id]['dep_fields']:
                            self.dynamic_options_map[field_id]['dep_fields'].append(dep_field_id)

                        # Enregistrer la dépendance inverse (miroir)
                        if dep_field_id not in self.mirror_dynamic_options:
                            self.mirror_dynamic_options[dep_field_id] = []
                        if field_id not in self.mirror_dynamic_options[dep_field_id]:
                            self.mirror_dynamic_options[dep_field_id].append(field_id)

                            
                        # Enregistrer aussi avec l'ID unique du champ source
                        dep_unique_id = f"{dep_field_id}_{self.source_id}"
                        if dep_unique_id != dep_field_id:
                            if dep_unique_id not in self.mirror_dynamic_options:
                                self.mirror_dynamic_options[dep_unique_id] = []
                            if field_id not in self.mirror_dynamic_options[dep_unique_id]:
                                self.mirror_dynamic_options[dep_unique_id].append(field_id)

                        logger.debug(f"Dépendance dynamic_options: {field_id} dépend de {dep_field_id} ({dep_unique_id}) (via field_id)")

        # Afficher le contenu des dictionnaires miroirs pour le débogage
        logger.debug(f"Analyse des dépendances terminée: {len(self.enabled_if_map)} enabled_if, " +
                   f"{len(self.value_deps_map)} value_deps, {len(self.dynamic_options_map)} dynamic_options")
        
        # Afficher le contenu des dictionnaires miroirs
        logger.debug(f"mirror_enabled_if: {self.mirror_enabled_if}")
        logger.debug(f"mirror_value_deps: {self.mirror_value_deps}")
        logger.debug(f"mirror_dynamic_options: {self.mirror_dynamic_options}")

    def update_dependent_fields(self, source_field: Widget) -> None:
        """
        Met à jour les champs qui dépendent du champ source.

        Args:
            source_field: Champ source dont la valeur a changé
        """
        # Éviter les cycles de mise à jour
        if self._updating_dependencies:
            return

        try:
            # Marquer le début de la mise à jour
            self._updating_dependencies = True
            
            # S'assurer que les dépendances sont correctement analysées
            logger.debug("Dépendances réanalysées avant la mise à jour")

            # Récupérer les identifiants du champ source
            source_field_id = getattr(source_field, 'field_id', None)
            source_unique_id = getattr(source_field, 'unique_id', source_field_id)

            if not source_field_id:
                logger.warning("Impossible de mettre à jour les dépendances: champ source sans field_id")
                return

            logger.debug(f"Mise à jour des champs dépendant de {source_field_id} (unique_id: {source_unique_id})")

            # 1. METTRE À JOUR LES OPTIONS DYNAMIQUES
            self._update_dynamic_options_dependencies(source_field_id, source_unique_id, source_field)

            # 2. METTRE À JOUR LES VALEURS DÉPENDANTES
            self._update_value_dependencies(source_field_id, source_unique_id, source_field)

            # 3. METTRE À JOUR LES ÉTATS ENABLED/DISABLED
            self._update_enabled_if_dependencies(source_field_id, source_unique_id, source_field)

            # 4. TRAITER LES SUPPRESSIONS DE CHAMPS SI NÉCESSAIRE
            self.process_fields_to_remove()

            logger.debug(f"Mise à jour des dépendances terminée pour {source_field_id}")

        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des dépendances: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # CRUCIAL: Toujours réinitialiser le flag pour permettre des mises à jour futures
            self._updating_dependencies = False

    def process_fields_to_remove(self) -> None:
        """
        Traite les champs à supprimer suite aux mises à jour de dépendances.
        """
        if not hasattr(self, '_fields_to_remove') or not self._fields_to_remove:
            return

        logger.debug(f"Traitement de {len(self._fields_to_remove)} champs à supprimer")

        # Copier la liste pour éviter les problèmes de modification pendant l'itération
        fields_to_remove = set(self._fields_to_remove)

        # Parcourir les champs à supprimer
        for field_id in fields_to_remove:
            # Vérifier si le champ existe encore
            if field_id in self.fields_by_id:
                field = self.fields_by_id[field_id]

                # Supprimer des structures de dépendances
                if field_id in self.enabled_if_map:
                    del self.enabled_if_map[field_id]
                if field_id in self.value_deps_map:
                    del self.value_deps_map[field_id]
                if field_id in self.dynamic_options_map:
                    del self.dynamic_options_map[field_id]

                # Supprimer des structures miroirs
#                for mirror_dict in [self.mirror_enabled_if, self.mirror_value_deps, self.mirror_dynamic_options]:
#                    for dep_id, deps in list(mirror_dict.items()):
#                        if field_id in deps:
#                            deps.remove(field_id)

                # Supprimer du dictionnaire des champs
                del self.fields_by_id[field_id]

                # Supprimer de l'interface si le champ est un enfant direct
                if field in self.children:
                    field.remove()

                logger.debug(f"Champ {field_id} supprimé")

        # Réinitialiser la liste des champs à supprimer
        self._fields_to_remove.clear()

    def _normalize_value_for_comparison(self, value: Any) -> Any:
        """
        Normalise une valeur pour la comparaison dans le cadre des dépendances.
        Convertit les valeurs en types comparables et gère les cas spéciaux.
        
        Args:
            value: Valeur à normaliser
            
        Returns:
            Any: Valeur normalisée pour la comparaison
        """
        # Conversion des chaînes booléennes en booléens
        if isinstance(value, str):
            # Conversion des chaînes booléennes en minuscules
            value_lower = value.lower()
            if value_lower in ('true', 'yes', 'oui', '1'):
                return True
            elif value_lower in ('false', 'no', 'non', '0'):
                return False
        
        # Conversion des nombres en chaînes pour les comparaisons
        # (utile quand on compare des valeurs de champs texte avec des nombres)
        if isinstance(value, (int, float)):
            return str(value)
            
        # Retourner la valeur telle quelle pour les autres types
        return value
        
    def _update_enabled_if_dependencies(self, source_field_id: str, source_unique_id: str, source_field: Widget) -> None:
        """
        Met à jour l'état enabled/disabled des champs dont l'activation dépend du champ source.
        Supporte plusieurs conditions avec opérateurs logiques (AND/OR).

        Args:
            source_field_id: Identifiant du champ source
            source_unique_id: Identifiant unique du champ source
            source_field: Widget du champ source
        """
        # Utiliser les dictionnaires miroirs pour une recherche directe
        dependent_fields = []

        # Chercher dans le dictionnaire miroir avec l'ID du champ
        if source_field_id in self.mirror_enabled_if:
            dependent_fields.extend(self.mirror_enabled_if[source_field_id])

        # Chercher aussi avec l'ID unique si différent
        if source_unique_id != source_field_id and source_unique_id in self.mirror_enabled_if:
            dependent_fields.extend(self.mirror_enabled_if[source_unique_id])

        # Si aucun champ dépendant trouvé, sortir rapidement
        if not dependent_fields:
            return

        # Récupérer la valeur actuelle du champ source
        source_value = self._get_field_value(source_field)
        logger.debug(f"Mise à jour de {len(dependent_fields)} champs enabled_if dépendant de {source_field_id}={source_value}")

        # Mettre à jour chaque champ dépendant
        for dep_field_id in dependent_fields:
            # Récupérer le champ dépendant
            dependent_field = self.fields_by_id.get(dep_field_id)
            if not dependent_field:
                continue

            # Vérifier si le champ utilise le nouveau format avec conditions multiples
            if dep_field_id in self.enabled_if_map and 'conditions' in self.enabled_if_map[dep_field_id]:
                # Nouveau format avec conditions multiples
                conditions = self.enabled_if_map[dep_field_id]['conditions']
                operator = self.enabled_if_map[dep_field_id].get('operator', 'AND')
                
                # Évaluer toutes les conditions
                condition_results = []
                for condition in conditions:
                    condition_field_id = condition['field_id']
                    required_value = condition['required_value']
                    
                    # Si la condition concerne le champ source actuel
                    if condition_field_id == source_field_id or condition_field_id == source_unique_id:
                        # Normaliser les valeurs pour la comparaison
                        normalized_source_value = self._normalize_value_for_comparison(source_value)
                        normalized_required_value = self._normalize_value_for_comparison(required_value)
                        
                        # Ajouter le résultat de cette condition
                        condition_results.append(normalized_source_value == normalized_required_value)
                        logger.debug(f"Condition pour {dep_field_id}: {condition_field_id}={required_value} vs {source_value} -> {normalized_source_value == normalized_required_value}")
                    else:
                        # Pour les autres champs, récupérer leur valeur actuelle
                        other_field = self.fields_by_id.get(condition_field_id)
                        if other_field:
                            other_value = self._get_field_value(other_field)
                            normalized_other_value = self._normalize_value_for_comparison(other_value)
                            normalized_required_value = self._normalize_value_for_comparison(required_value)
                            
                            # Ajouter le résultat de cette condition
                            condition_results.append(normalized_other_value == normalized_required_value)
                            logger.debug(f"Condition pour {dep_field_id}: {condition_field_id}={required_value} vs {other_value} -> {normalized_other_value == normalized_required_value}")
                
                # Déterminer si le champ doit être activé selon l'opérateur
                if condition_results:
                    if operator.upper() == 'AND':
                        should_enable = all(condition_results)
                    elif operator.upper() == 'OR':
                        should_enable = any(condition_results)
                    else:
                        # Opérateur non reconnu, utiliser AND par défaut
                        should_enable = all(condition_results)
                    
                    # Mettre à jour l'état du champ
                    self._update_field_enabled_state(dependent_field, should_enable)
                    
                    logger.debug(f"Champ {dep_field_id} {'' if should_enable else 'dés'}activé avec opérateur {operator} ({len(condition_results)} conditions évaluées)")
            else:
                # Ancien format (rétro-compatibilité)
                # Récupérer la valeur requise pour l'activation
                required_value = None
                if dep_field_id in self.enabled_if_map and source_field_id in self.enabled_if_map[dep_field_id]:
                    required_value = self.enabled_if_map[dep_field_id][source_field_id]
                elif dep_field_id in self.enabled_if_map and source_unique_id in self.enabled_if_map[dep_field_id]:
                    required_value = self.enabled_if_map[dep_field_id][source_unique_id]

                if required_value is None:
                    continue

                # Normaliser les valeurs pour la comparaison
                normalized_source_value = self._normalize_value_for_comparison(source_value)
                normalized_required_value = self._normalize_value_for_comparison(required_value)

                # Déterminer si le champ doit être activé
                should_enable = normalized_source_value == normalized_required_value

                # Mettre à jour l'état du champ
                self._update_field_enabled_state(dependent_field, should_enable)

                logger.debug(f"Champ {dep_field_id} {'' if should_enable else 'dés'}activé (requis: {required_value}, actuel: {source_value})")

    def _update_dynamic_options_dependencies(self, source_field_id: str, source_unique_id: str, source_field: Widget) -> None:
        """
        Met à jour les options dynamiques des champs qui dépendent du champ source.

        Args:
            source_field_id: Identifiant du champ source
            source_unique_id: Identifiant unique du champ source
            source_field: Widget du champ source
        """
        # Utiliser les dictionnaires miroirs pour une recherche directe
        dependent_fields = []

        # Déboguer le contenu du dictionnaire miroir
        logger.debug(f"Vérification des dépendances pour {source_field_id} (unique: {source_unique_id})")
        logger.debug(f"mirror_dynamic_options contient {len(self.mirror_dynamic_options)} clés: {list(self.mirror_dynamic_options.keys())}")
        
        # Chercher dans le dictionnaire miroir avec l'ID du champ
        if source_field_id in self.mirror_dynamic_options:
            logger.debug(f"Trouvé {len(self.mirror_dynamic_options[source_field_id])} dépendances pour {source_field_id}: {self.mirror_dynamic_options[source_field_id]}")
            dependent_fields.extend(self.mirror_dynamic_options[source_field_id])
        else:
            logger.debug(f"Aucune dépendance trouvée pour {source_field_id} dans mirror_dynamic_options")

        # Chercher aussi avec l'ID unique si différent
        if source_unique_id != source_field_id and source_unique_id in self.mirror_dynamic_options:
            logger.debug(f"Trouvé {len(self.mirror_dynamic_options[source_unique_id])} dépendances pour {source_unique_id}: {self.mirror_dynamic_options[source_unique_id]}")
            dependent_fields.extend(self.mirror_dynamic_options[source_unique_id])
        elif source_unique_id != source_field_id:
            logger.debug(f"Aucune dépendance trouvée pour {source_unique_id} dans mirror_dynamic_options")

        # Si aucun champ dépendant trouvé, sortir rapidement
        if not dependent_fields:
            logger.debug(f"Aucun champ dépendant trouvé pour {source_field_id} ou {source_unique_id}")
            return

        logger.debug(f"Mise à jour de {len(dependent_fields)} champs avec options dynamiques dépendant de {source_field_id}: {dependent_fields}")

        # Préparer les valeurs des arguments pour les options dynamiques
        source_value = self._get_field_value(source_field)

        # Mettre à jour chaque champ dépendant
        for dep_field_id in dependent_fields:
            # Récupérer le champ dépendant
            dependent_field = self.fields_by_id.get(dep_field_id)
            if not dependent_field or not hasattr(dependent_field, 'update_dynamic_options'):
                continue

            # Vérifier si le champ est activé (ne pas mettre à jour les options des champs désactivés)
            if hasattr(dependent_field, 'disabled') and dependent_field.disabled:
                logger.debug(f"Champ {dep_field_id} désactivé, options non mises à jour")
                continue

            # Préparer les arguments pour la mise à jour des options
            update_kwargs = self._prepare_dynamic_options_args(dependent_field, dep_field_id, source_field_id, source_value)

            # Mettre à jour les options
            try:
                result = dependent_field.update_dynamic_options(**update_kwargs)
                logger.debug(f"Options mises à jour pour {dep_field_id}: {result}")

                # Vérifier s'il faut supprimer le champ (cas spécial: groupe de cases à cocher sans options)
                if not result and hasattr(dependent_field, 'field_config') and dependent_field.field_config.get('type') == 'checkbox_group':
                    logger.debug(f"Le champ {dep_field_id} n'a plus d'options, planifié pour suppression")
                    self._fields_to_remove.add(dep_field_id)
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour des options pour {dep_field_id}: {e}")

    def _prepare_dynamic_options_args(self, field: Widget, field_id: str, source_field_id: str, source_value: Any) -> Dict[str, Any]:
        """
        Prépare les arguments pour la mise à jour des options dynamiques.

        Args:
            field: Champ dont les options doivent être mises à jour
            field_id: Identifiant du champ
            source_field_id: Identifiant du champ qui a déclenché la mise à jour
            source_value: Valeur du champ source

        Returns:
            Dict[str, Any]: Arguments à passer à update_dynamic_options
        """
        kwargs = {}

        # Si le champ n'est pas dans notre mapping d'options dynamiques, retourner un dict vide
        if field_id not in self.dynamic_options_map:
            return kwargs

        # Récupérer la configuration des options dynamiques
        dynamic_config = self.dynamic_options_map[field_id]

        # Parcourir tous les arguments définis
        for arg in dynamic_config.get('args', []):
            # Support du nouveau format avec 'field' et 'param'
            if 'field' in arg and 'param_name' in arg:
                dep_field_id = arg['field']
                param_name = arg['param_name']
                
                # Si c'est le champ source qui a déclenché la mise à jour, utiliser sa valeur
                if dep_field_id == source_field_id:
                    kwargs[param_name] = source_value
                # Sinon, chercher la valeur dans les champs existants
                elif dep_field_id in self.fields_by_id:
                    dep_field = self.fields_by_id[dep_field_id]
                    # Ne pas inclure les valeurs des champs désactivés
                    if not (hasattr(dep_field, 'disabled') and dep_field.disabled):
                        kwargs[param_name] = self._get_field_value(dep_field)
                        
                logger.debug(f"Argument dynamique: {param_name}={kwargs.get(param_name)} depuis {dep_field_id}")
            # Support de l'ancien format avec 'field_id' et 'param_name'
            elif 'field_id' in arg and 'param_name' in arg:
                dep_field_id = arg['field_id']
                param_name = arg['param_name']

                # Si c'est le champ source qui a déclenché la mise à jour, utiliser sa valeur
                if dep_field_id == source_field_id:
                    kwargs[param_name] = source_value
                # Sinon, chercher la valeur dans les champs existants
                elif dep_field_id in self.fields_by_id:
                    dep_field = self.fields_by_id[dep_field_id]
                    # Ne pas inclure les valeurs des champs désactivés
                    if not (hasattr(dep_field, 'disabled') and dep_field.disabled):
                        kwargs[param_name] = self._get_field_value(dep_field)
                        
                logger.debug(f"Argument dynamique: {param_name}={kwargs.get(param_name)} depuis {dep_field_id}")

        return kwargs

    def _update_value_dependencies(self, source_field_id: str, source_unique_id: str, source_field: Widget) -> None:
        """
        Met à jour les valeurs des champs qui dépendent du champ source.
        Supporte les dépendances multiples avec opérateurs logiques (AND/OR).

        Args:
            source_field_id: Identifiant du champ source
            source_unique_id: Identifiant unique du champ source
            source_field: Widget du champ source
        """
        # Utiliser les dictionnaires miroirs pour une recherche directe
        dependent_fields = []

        # Chercher dans le dictionnaire miroir avec l'ID du champ
        if source_field_id in self.mirror_value_deps:
            dependent_fields.extend(self.mirror_value_deps[source_field_id])

        # Chercher aussi avec l'ID unique si différent
        if source_unique_id != source_field_id and source_unique_id in self.mirror_value_deps:
            dependent_fields.extend(self.mirror_value_deps[source_unique_id])

        # Si aucun champ dépendant trouvé, sortir rapidement
        if not dependent_fields:
            return

        # Récupérer la valeur actuelle du champ source
        source_value = self._get_field_value(source_field)
        logger.debug(f"Mise à jour de {len(dependent_fields)} champs dont la valeur dépend de {source_field_id}={source_value}")

        # Mettre à jour chaque champ dépendant
        for dep_field_id in dependent_fields:
            # Récupérer le champ dépendant
            dependent_field = self.fields_by_id.get(dep_field_id)
            if not dependent_field:
                continue

            # Vérifier si le champ utilise le nouveau format avec dépendances multiples
            if dep_field_id in self.value_deps_map and isinstance(self.value_deps_map[dep_field_id], dict) and 'fields' in self.value_deps_map[dep_field_id]:
                # Nouveau format avec dépendances multiples
                fields = self.value_deps_map[dep_field_id]['fields']
                operator = self.value_deps_map[dep_field_id].get('operator', 'AND')
                
                # Vérifier si le champ source fait partie des dépendances
                if source_field_id in fields or source_unique_id in fields:
                    # Pour les dépendances multiples, nous devons vérifier l'état de tous les champs dépendants
                    all_fields_valid = True
                    any_field_valid = False
                    
                    # Vérifier chaque champ dépendant
                    for field_id in fields:
                        field = self.fields_by_id.get(field_id)
                        if field:
                            # Un champ est considéré valide s'il est activé et a une valeur non vide
                            field_value = self._get_field_value(field)
                            field_valid = not (hasattr(field, 'disabled') and field.disabled) and field_value
                            
                            all_fields_valid = all_fields_valid and field_valid
                            any_field_valid = any_field_valid or field_valid
                        else:
                            # Si un champ est manquant, il est considéré comme non valide
                            all_fields_valid = False
                    
                    # Déterminer si le champ doit être activé selon l'opérateur
                    should_enable = (operator.upper() == 'AND' and all_fields_valid) or \
                                   (operator.upper() == 'OR' and any_field_valid)
                    
                    # Activer ou désactiver le champ selon l'état des dépendances
                    if should_enable:
                        # Activer le champ s'il était désactivé
                        if hasattr(dependent_field, 'disabled') and dependent_field.disabled:
                            self._update_field_enabled_state(dependent_field, True)
                            
                        # Déterminer la nouvelle valeur selon le type de dépendance
                        new_value = self._compute_dependent_value(dependent_field, source_value)
                        logger.debug(f"Mise à jour de {dep_field_id} avec dépendances multiples suite au changement de {source_field_id}")
                    else:
                        # Désactiver le champ
                        if not hasattr(dependent_field, 'disabled') or not dependent_field.disabled:
                            self._update_field_enabled_state(dependent_field, False)
                        continue
                else:
                    # Le champ source ne fait pas partie des dépendances, ignorer
                    continue
            else:
                # Ancien format (rétro-compatibilité)
                # Vérifier si le champ source a une valeur valide
                source_valid = source_value is not None and source_value != ''
                
                # Activer ou désactiver le champ selon l'état du champ source
                if source_valid:
                    # Activer le champ s'il était désactivé
                    if hasattr(dependent_field, 'disabled') and dependent_field.disabled:
                        self._update_field_enabled_state(dependent_field, True)
                        
                    # Déterminer la nouvelle valeur selon le type de dépendance
                    new_value = self._compute_dependent_value(dependent_field, source_value)
                else:
                    # Désactiver le champ
                    if not hasattr(dependent_field, 'disabled') or not dependent_field.disabled:
                        self._update_field_enabled_state(dependent_field, False)
                    continue

            # Mettre à jour la valeur
            if new_value is not None:
                success = self._update_field_value(dependent_field, new_value)
                logger.debug(f"Valeur mise à jour pour {dep_field_id}: {new_value} (succès: {success})")

    def _compute_dependent_value(self, field: Widget, source_value: Any) -> Any:
        """
        Calcule la nouvelle valeur d'un champ dépendant.

        Args:
            field: Champ dont la valeur doit être calculée
            source_value: Valeur du champ source

        Returns:
            Any: Nouvelle valeur calculée ou None si pas de calcul possible
        """
                # Vérifier si le champ a un mapping de valeurs
        if hasattr(field, 'field_config') and 'values' in field.field_config:
            values_map = field.field_config['values']
            if source_value in values_map:
                return values_map[source_value]

        # Si le champ a une méthode pour calculer sa valeur basée sur une source
        if hasattr(field, '_get_default_value'):
            try:
                return field._get_default_value(source_value)
            except TypeError:
                # Si la méthode ne prend pas d'argument source_value
                pass

        # Par défaut, utiliser la source directement
        return source_value

    def _update_field_enabled_state(self, field: Widget, enabled: bool) -> None:
        """
        Met à jour l'état activé/désactivé d'un champ.

        Args:
            field: Champ à mettre à jour
            enabled: True pour activer, False pour désactiver
        """
        # Vérifier si l'état change réellement
        current_state = not (hasattr(field, 'disabled') and field.disabled)
        if current_state == enabled:
            return

        # Cas spécial: Si le champ a une méthode set_disabled
        if hasattr(field, 'set_disabled'):
            try:
                field.set_disabled(not enabled)
                logger.debug(f"État du champ {field.field_id} mis à jour via set_disabled: enabled={enabled}")
                return
            except Exception as e:
                logger.error(f"Erreur lors de l'appel à set_disabled pour {field.field_id}: {e}")

        # Cas général: Mettre à jour directement les attributs
        field.disabled = not enabled

        if enabled:
            field.remove_class('disabled')
            
            # Forcer l'affichage du label et des éléments du champ
            if hasattr(field, 'field_id') and hasattr(field, 'field_config'):
                try:
                    # Forcer l'affichage du header
                    header = None
                    try:
                        header = field.query_one(f"#header_{field.field_id}")
                    except Exception:
                        # Le header n'existe pas, on va le créer plus tard si nécessaire
                        pass
                        
                    if header:
                        header.display = True
                        
                        # Vérifier si le header est vide et le recréer si nécessaire
                        if not header.children:
                            label_text = field.field_config.get('label', field.field_id)
                            from textual.widgets import Label
                            
                            if field.field_config.get('required', False):
                                header.mount(Label(label_text, classes="field-label"))
                                header.mount(Label(" *", classes="required-field"))
                            else:
                                header.mount(Label(label_text, classes="field-label"))
                                
                            logger.debug(f"Label recréé pour {field.field_id}: {label_text}")
                except Exception as e:
                    logger.error(f"Erreur lors de la gestion du header pour {field.field_id}: {e}")
            
            # Réactiver les widgets internes
            self._enable_field_widgets(field)
            
            # Restaurer la valeur sauvegardée si disponible
            if hasattr(field, '_saved_value'):
                try:
                    saved_value = field._saved_value
                    
                    # Restaurer directement dans l'input si disponible
                    if hasattr(field, 'input') and field.input:
                        # Récupérer aussi la valeur sauvegardée de l'input si disponible
                        if hasattr(field, '_saved_input_value'):
                            field.input.value = field._saved_input_value
                            delattr(field, '_saved_input_value')
                            logger.debug(f"Valeur d'input restaurée pour {field.field_id}: {field.input.value}")
                        else:
                            field.input.value = str(saved_value) if saved_value is not None else ""
                    
                    # Utiliser set_value si disponible pour restaurer la valeur interne
                    if hasattr(field, 'set_value'):
                        field.set_value(saved_value, update_input=True, update_dependencies=True)
                        logger.debug(f"Valeur restaurée via set_value pour {field.field_id}: {saved_value}")
                    
                    # Pour les champs spéciaux comme CheckboxGroupField, appeler restore_display si disponible
                    if hasattr(field, 'restore_display') and callable(field.restore_display):
                        field.restore_display(saved_value)
                        logger.debug(f"Méthode restore_display appelée pour {field.field_id}")
                        
                    logger.debug(f"Valeur restaurée pour {field.field_id}: {saved_value}")
                    delattr(field, '_saved_value')
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de la valeur pour {field.field_id}: {e}")
            else:
                # Appeler _restore_field_value pour gérer les cas spéciaux
                self._restore_field_value(field)
        else:
            field.add_class('disabled')
            
            # Sauvegarder la valeur actuelle
            try:
                if not hasattr(field, '_saved_value'):
                    field._saved_value = self._get_field_value(field)
                    logger.debug(f"Valeur sauvegardée pour {field.field_id}: {field._saved_value}")
                    
                # Vider le contenu visuel du champ, mais ne pas modifier la valeur interne
                # Nous sauvegardons la valeur interne dans _saved_value, mais nous vidons juste l'affichage
                if hasattr(field, 'input') and field.input:
                    # Sauvegarder la valeur actuelle de l'input avant de la vider
                    if not hasattr(field, '_saved_input_value'):
                        field._saved_input_value = field.input.value
                        logger.debug(f"Valeur d'input sauvegardée pour {field.field_id}: {field._saved_input_value}")
                    
                    # Vider l'affichage uniquement
                    field.input.value = ""
                    logger.debug(f"Contenu visuel vidé pour {field.field_id}")
                    
                # Pour les champs spéciaux comme CheckboxGroupField, appeler une méthode spécifique si disponible
                if hasattr(field, 'clear_display') and callable(field.clear_display):
                    field.clear_display()
                    logger.debug(f"Méthode clear_display appelée pour {field.field_id}")
            except Exception as e:
                logger.error(f"Erreur lors de la sauvegarde/vidage pour {field.field_id}: {e}")
            
            # Désactiver les widgets internes
            self._disable_field_widgets(field)

            # Vérifier s'il faut supprimer le champ
            if hasattr(field, 'dependencies') and 'enabled_if' in field.dependencies and field.dependencies['enabled_if']:
                try:
                    remove_if_disabled = field.dependencies['enabled_if'].get('remove_if_disabled', False)
                    if remove_if_disabled:
                        self._fields_to_remove.add(field.field_id)
                        logger.debug(f"Champ {field.field_id} marqué pour suppression")
                except Exception as e:
                    logger.error(f"Erreur lors de la vérification de remove_if_disabled pour {field.field_id}: {e}")

        logger.debug(f"État du champ {field.field_id} mis à jour: enabled={enabled}")

    def _enable_field_widgets(self, field: Widget) -> None:
        """
        Active tous les widgets internes d'un champ.

        Args:
            field: Champ dont les widgets doivent être activés
        """
        # Activer le widget input
        if hasattr(field, 'input'):
            field.input.disabled = False
            field.input.remove_class('disabled')

        # Activer le widget select
        if hasattr(field, 'select'):
            field.select.disabled = False
            field.select.remove_class('disabled')

        # Activer le widget checkbox
        if hasattr(field, 'checkbox'):
            field.checkbox.disabled = False
            field.checkbox.remove_class('disabled')

        # Activer le bouton browse des champs de répertoire
        if hasattr(field, '_browse_button'):
            field._browse_button.disabled = False
            field._browse_button.remove_class('disabled')

    def _disable_field_widgets(self, field: Widget) -> None:
        """
        Désactive tous les widgets internes d'un champ.

        Args:
            field: Champ dont les widgets doivent être désactivés
        """
        # Désactiver le widget input
        if hasattr(field, 'input'):
            field.input.disabled = True
            field.input.add_class('disabled')

        # Désactiver le widget select
        if hasattr(field, 'select'):
            field.select.disabled = True
            field.select.add_class('disabled')

        # Désactiver le widget checkbox
        if hasattr(field, 'checkbox'):
            field.checkbox.disabled = True
            field.checkbox.add_class('disabled')

        # Désactiver le bouton browse des champs de répertoire
        if hasattr(field, '_browse_button'):
            field._browse_button.disabled = True
            field._browse_button.add_class('disabled')

    def _restore_field_value(self, field: Widget) -> None:
        """
        Restaure la valeur sauvegardée d'un champ et s'assure que son label est visible.

        Args:
            field: Champ dont la valeur doit être restaurée
        """
        # S'assurer que le label est visible (problème avec les champs réactivés)
        if hasattr(field, 'field_id') and hasattr(field, 'field_config'):
            # Forcer la recréation du label pour s'assurer qu'il est visible
            try:
                # Récupérer le header du champ
                header = None
                try:
                    header = field.query_one(f"#header_{field.field_id}")
                except Exception:
                    # Le header n'existe pas
                    logger.debug(f"Header introuvable pour {field.field_id}")
                
                if header:
                    # Récupérer le label depuis la configuration
                    label_text = field.field_config.get('label', field.field_id)
                    
                    # Vider le header existant
                    header.remove_children()
                    
                    # Recréer les labels
                    from textual.widgets import Label
                    
                    if field.field_config.get('required', False):
                        header.mount(Label(label_text, classes="field-label"))
                        header.mount(Label(" *", classes="required-field"))
                    else:
                        header.mount(Label(label_text, classes="field-label"))
                    
                    # S'assurer que le header est visible
                    header.display = True
                    logger.debug(f"Label recréé pour le champ {field.field_id}: {label_text}")
            except Exception as e:
                logger.error(f"Erreur lors de la recréation du label pour {field.field_id}: {e}")
        
        # Restaurer la valeur sauvegardée
        if hasattr(field, '_saved_value'):
            # Récupérer la valeur sauvegardée
            saved_value = field._saved_value
            
            # Restaurer la valeur si le champ a une méthode set_value
            if hasattr(field, 'set_value'):
                try:
                    # Restaurer la valeur dans l'input
                    if hasattr(field, 'input') and field.input:
                        field.input.value = str(saved_value) if saved_value is not None else ""
                    
                    # Appeler set_value pour mettre à jour la valeur interne
                    field.set_value(saved_value, update_input=True)
                    logger.debug(f"Valeur restaurée pour {field.field_id}: {saved_value}")
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de la valeur pour {field.field_id}: {e}")
            
            # Supprimer l'attribut pour éviter les conflits
            delattr(field, '_saved_value')

    def _get_field_value(self, field: Widget) -> Any:
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