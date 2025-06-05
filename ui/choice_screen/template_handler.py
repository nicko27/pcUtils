"""
Gestionnaire de templates pour l'écran de sélection.
Gère le chargement et la validation des templates de plugins.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from ruamel.yaml import YAML
from logging import getLogger

logger = getLogger('template_handler')

class TemplateHandler:
    """
    Gestionnaire de templates pour l'écran de sélection.
    
    Cette classe est responsable de:
    - Charger les templates depuis les fichiers YAML
    - Valider le format des templates
    - Appliquer les templates aux configurations de plugins
    """

    def __init__(self):
        """Initialise le gestionnaire de templates"""
        self.templates_dir = Path('templates')
        self.schema_file = self.templates_dir / 'template_schema.yml'
        self.yaml = YAML()  # Instance YAML unique pour la classe
        self.templates_cache = {}  # Cache des templates par plugin
        self.schema_cache = None   # Cache pour le schéma de validation
        
        # Créer le dossier templates s'il n'existe pas
        if not self.templates_dir.exists():
            try:
                self.templates_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Dossier de templates créé: {self.templates_dir}")
            except Exception as e:
                logger.error(f"Impossible de créer le dossier de templates: {e}")
                
        logger.debug(f"Initialisation du gestionnaire de templates")

    def get_plugin_templates(self, plugin_name: str) -> Dict[str, Any]:
        """
        Récupère tous les templates disponibles pour un plugin.
        Utilise un cache pour améliorer les performances.
        
        Args:
            plugin_name: Nom du plugin
            
        Returns:
            Dict[str, Any]: Dictionnaire des templates disponibles
        """
        # Utiliser le cache si disponible
        if plugin_name in self.templates_cache:
            logger.debug(f"Templates pour {plugin_name} trouvés dans le cache")
            return self.templates_cache[plugin_name]
            
        templates = {}
        plugin_templates_dir = self.templates_dir / plugin_name

        if not plugin_templates_dir.exists():
            logger.debug(f"Aucun dossier de templates trouvé pour {plugin_name}")
            self.templates_cache[plugin_name] = templates
            return templates

        try:
            # Charger le schéma de validation si disponible et pas déjà en cache
            schema = self._load_schema()

            # Charger les templates du plugin
            for template_file in plugin_templates_dir.glob('*.yml'):
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        template_data = self.yaml.load(f)
                        if self._validate_template(template_data, schema):
                            templates[template_file.stem] = {
                                'name': template_data.get('name', template_file.stem),
                                'description': template_data.get('description', ''),
                                'variables': template_data.get('variables', {}),
                                'conditions': template_data.get('conditions', []),
                                'messages': template_data.get('messages', {}),
                                'file_name': template_file.name
                            }
                            logger.debug(f"Template chargé: {template_file.name}")
                        else:
                            logger.warning(f"Template invalide ignoré: {template_file.name}")
                except Exception as e:
                    logger.error(f"Erreur lors du chargement du template {template_file.name}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Erreur lors du chargement des templates pour {plugin_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Mettre en cache
        self.templates_cache[plugin_name] = templates
        return templates

    def _load_schema(self) -> Optional[Dict[str, Any]]:
        """
        Charge le schéma de validation depuis le fichier.
        Utilise un cache pour éviter de relire le fichier.
        
        Returns:
            Optional[Dict[str, Any]]: Schéma de validation ou None si non disponible
        """
        if self.schema_cache is not None:
            return self.schema_cache
            
        if not self.schema_file.exists():
            logger.debug("Fichier de schéma non trouvé")
            return None
            
        try:
            with open(self.schema_file, 'r', encoding='utf-8') as f:
                schema = self.yaml.load(f)
                logger.debug("Schéma de validation chargé")
                self.schema_cache = schema
                return schema
        except Exception as e:
            logger.error(f"Erreur lors du chargement du schéma: {e}")
            return None

    def _validate_template(self, template: Any, schema: Optional[Dict[str, Any]] = None) -> bool:
        """
        Valide un template selon le schéma.
        
        Args:
            template: Données du template à valider
            schema: Schéma de validation optionnel
            
        Returns:
            bool: True si le template est valide
        """
        if not isinstance(template, dict):
            logger.warning("Le template doit être un dictionnaire")
            return False

        # Validation de base
        required_fields = ['name', 'description', 'variables']
        missing_fields = [field for field in required_fields if field not in template]
        if missing_fields:
            logger.warning(f"Champs requis manquants: {', '.join(missing_fields)}")
            return False

        if not isinstance(template.get('variables', {}), dict):
            logger.warning("Le champ 'variables' doit être un dictionnaire")
            return False

        # Validation des conditions
        if 'conditions' in template:
            if not isinstance(template['conditions'], list):
                logger.warning("Les conditions doivent être une liste")
                return False

            for i, condition in enumerate(template['conditions']):
                if not self._validate_condition(condition):
                    logger.warning(f"Condition invalide à l'index {i}")
                    return False

        # Validation des messages
        if 'messages' in template and not isinstance(template['messages'], dict):
            logger.warning("Le champ 'messages' doit être un dictionnaire")
            return False

        # Validation avec le schéma si disponible
        if schema:
            try:
                self._validate_against_schema(template, schema)
            except ValueError as e:
                logger.warning(f"Validation avec le schéma échouée: {e}")
                return False
            except Exception as e:
                logger.error(f"Erreur lors de la validation avec le schéma: {e}")
                return False

        return True

    def _validate_condition(self, condition: Any) -> bool:
        """
        Valide une condition dans un template.
        
        Args:
            condition: Condition à valider
            
        Returns:
            bool: True si la condition est valide
        """
        if not isinstance(condition, dict):
            return False
            
        required_fields = ['variable', 'operator', 'value']
        missing_fields = [field for field in required_fields if field not in condition]
        if missing_fields:
            logger.warning(f"Champs requis manquants dans la condition: {', '.join(missing_fields)}")
            return False

        valid_operators = ['==', '!=', '>', '<', '>=', '<=', 'in', 'not in']
        if condition['operator'] not in valid_operators:
            logger.warning(f"Opérateur invalide: {condition['operator']}")
            return False

        return True

    def _validate_against_schema(self, template: Dict[str, Any], schema: Dict[str, Any]) -> None:
        """
        Valide un template contre un schéma de validation.
        
        Args:
            template: Template à valider
            schema: Schéma de validation
            
        Raises:
            ValueError: Si le template ne respecte pas le schéma
        """
        if not schema or not isinstance(schema, dict):
            raise ValueError("Schéma de validation invalide")

        # Vérification des champs requis
        required_fields = schema.get('required_fields', [])
        missing_fields = [field for field in required_fields if field not in template]
        if missing_fields:
            raise ValueError(f"Champs requis manquants: {', '.join(missing_fields)}")

        # Vérification des types de champs
        field_types = schema.get('field_types', {})
        for field, expected_type in field_types.items():
            if field in template:
                value = template[field]
                type_checks = {
                    'string': lambda x: isinstance(x, str),
                    'dict': lambda x: isinstance(x, dict),
                    'list': lambda x: isinstance(x, list),
                    'bool': lambda x: isinstance(x, bool),
                    'int': lambda x: isinstance(x, int),
                    'float': lambda x: isinstance(x, (int, float))
                }
                
                if expected_type in type_checks and not type_checks[expected_type](value):
                    raise ValueError(f"Le champ {field} doit être de type {expected_type}")

        # Vérification des valeurs autorisées
        allowed_values = schema.get('allowed_values', {})
        for field, values in allowed_values.items():
            if field in template and template[field] not in values:
                raise ValueError(f"Valeur non autorisée pour {field}: {template[field]}")

        # Vérification des formats spéciaux
        format_rules = schema.get('format_rules', {})
        for field, rule in format_rules.items():
            if field in template:
                value = template[field]
                if rule == 'version' and not self._is_valid_version(value):
                    raise ValueError(f"Format de version invalide pour {field}: {value}")
                elif rule == 'path' and not self._is_valid_path(value):
                    raise ValueError(f"Format de chemin invalide pour {field}: {value}")

        logger.debug("Validation du template contre le schéma réussie")

    def _is_valid_version(self, version: str) -> bool:
        """
        Vérifie si une version est valide (format X.Y.Z).
        
        Args:
            version: Chaîne de version à vérifier
            
        Returns:
            bool: True si le format est valide
        """
        if not isinstance(version, str):
            return False
            
        try:
            parts = version.split('.')
            return len(parts) <= 3 and all(part.isdigit() for part in parts)
        except Exception:
            return False

    def _is_valid_path(self, path: str) -> bool:
        """
        Vérifie si un chemin est valide.
        
        Args:
            path: Chemin à vérifier
            
        Returns:
            bool: True si le chemin est valide
        """
        if not isinstance(path, str):
            return False
            
        try:
            return len(path) > 0 and '/' not in path and '..' not in path
        except Exception:
            return False

    def get_default_template(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        Récupère le template par défaut d'un plugin.
        
        Args:
            plugin_name: Nom du plugin
            
        Returns:
            Optional[Dict[str, Any]]: Template par défaut ou None
        """
        templates = self.get_plugin_templates(plugin_name)
        default = templates.get('default')
        if default:
            logger.debug(f"Template par défaut trouvé pour {plugin_name}")
        else:
            logger.debug(f"Aucun template par défaut trouvé pour {plugin_name}")
        return default

    def apply_template(self, plugin_name: str, template_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applique un template à une configuration de plugin.
        
        Args:
            plugin_name: Nom du plugin
            template_name: Nom du template à appliquer
            config: Configuration actuelle du plugin
            
        Returns:
            Dict[str, Any]: Configuration mise à jour avec le template
        """
        templates = self.get_plugin_templates(plugin_name)
        template = templates.get(template_name)
        
        if not template:
            logger.warning(f"Template non trouvé: {template_name}")
            return config

        # Fusionner les variables du template avec la configuration
        updated_config = config.copy()
        
        # S'assurer qu'il y a une section 'config' dans updated_config
        if 'config' not in updated_config:
            updated_config['config'] = {}
            
        # Fusionner les variables du template dans la configuration
        if isinstance(template.get('variables'), dict):
            if isinstance(updated_config.get('config'), dict):
                updated_config['config'].update(template['variables'])
            else:
                updated_config['config'] = template['variables'].copy()
        
        logger.debug(f"Template {template_name} appliqué à {plugin_name}")
        return updated_config
        
    def clear_cache(self) -> None:
        """
        Vide les caches des templates.
        Utile après des modifications ou pour les tests.
        """
        self.templates_cache.clear()
        self.schema_cache = None
        logger.debug("Caches des templates vidés")