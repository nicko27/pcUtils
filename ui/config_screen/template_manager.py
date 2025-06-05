"""
Gestionnaire centralisé des templates de configuration.
Gère le chargement, la validation et l'application des templates.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from ruamel.yaml import YAML
from logging import getLogger

logger = getLogger('template_manager')
yaml = YAML()

class TemplateManager:
    """
    Gestionnaire centralisé des templates de configuration.
    
    Cette classe est responsable de :
    - Charger les templates depuis le répertoire templates/
    - Valider les templates selon un schéma
    - Fournir les templates disponibles pour les plugins
    - Appliquer les templates aux configurations
    """

    def __init__(self):
        """Initialise le gestionnaire de templates"""
        self.templates_dir = self._get_templates_dir()
        self.schema = self._load_schema()
        self.templates_cache = {}  # Cache des templates par plugin
        logger.debug(f"Gestionnaire de templates initialisé avec répertoire: {self.templates_dir}")
        
    def _get_templates_dir(self) -> Path:
        """
        Récupère le chemin du dossier racine des templates.
        
        Returns:
            Path: Chemin vers le dossier des templates
        """
        templates_dir = Path(__file__).parent.parent.parent / 'templates'
        logger.debug(f"Répertoire des templates: {templates_dir}")
        return templates_dir
        
    def _load_schema(self) -> dict:
        """
        Charge le schéma de validation des templates.
        
        Returns:
            dict: Schéma de validation ou dictionnaire vide si non trouvé
        """
        schema_file = self.templates_dir / 'template_schema.yml'
        try:
            if schema_file.exists():
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema = yaml.load(f)
                    logger.debug("Schéma de validation chargé avec succès")
                    return schema
            logger.debug("Aucun schéma de validation trouvé, utilisation des validations par défaut")
        except Exception as e:
            logger.error(f"Erreur lors du chargement du schéma: {e}")
        return {}

    def get_plugin_templates(self, plugin_name: str) -> Dict[str, dict]:
        """
        Récupère tous les templates disponibles pour un plugin avec mise en cache.
        
        Args:
            plugin_name: Nom du plugin
            
        Returns:
            Dict[str, dict]: Dictionnaire des templates disponibles {nom: données}
        """
        # Vérifier d'abord le cache
        if plugin_name in self.templates_cache:
            logger.debug(f"Templates pour {plugin_name} trouvés dans le cache")
            return self.templates_cache[plugin_name]
            
        templates_dir = self.templates_dir / plugin_name
        templates = {}

        if not templates_dir.exists():
            logger.debug(f"Aucun dossier de templates trouvé pour {plugin_name}")
            self.templates_cache[plugin_name] = templates
            return templates

        logger.debug(f"Chargement des templates pour {plugin_name} depuis {templates_dir}")
        for template_file in templates_dir.glob('*.yml'):
            if template_file.name == 'template_schema.yml':
                continue

            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    template_data = yaml.load(f)
                    validation_result, error_message = self._validate_template(template_data)
                    
                    if validation_result:
                        templates[template_file.stem] = template_data
                        logger.debug(f"Template chargé: {template_file.name}")
                    else:
                        logger.warning(f"Template invalide ignoré ({template_file.name}): {error_message}")
            except Exception as e:
                logger.error(f"Erreur lors du chargement du template {template_file}: {e}")

        # Mettre en cache
        self.templates_cache[plugin_name] = templates
        logger.debug(f"{len(templates)} templates chargés pour {plugin_name}")
        return templates

    def _validate_template(self, template: dict) -> Tuple[bool, str]:
        """
        Valide un template selon le schéma de validation.
        
        Args:
            template: Données du template à valider
            
        Returns:
            Tuple[bool, str]: (validité, message d'erreur)
        """
        if not isinstance(template, dict):
            return False, "Le template doit être un dictionnaire"

        # Vérifier les champs requis
        required_fields = self.schema.get('required_fields', ['name',  'variables'])
        for field in required_fields:
            if field not in template:
                return False, f"Champ requis manquant: {field}"

        # Vérifier le format des variables
        if not isinstance(template.get('variables', {}), dict):
            return False, "Le champ 'variables' doit être un dictionnaire"

        # Vérifier les types de champs
        field_types = self.schema.get('field_types', {})
        for field, expected_type in field_types.items():
            if field in template:
                value = template[field]
                if expected_type == 'string' and not isinstance(value, str):
                    return False, f"Le champ {field} doit être une chaîne"
                elif expected_type == 'dict' and not isinstance(value, dict):
                    return False, f"Le champ {field} doit être un dictionnaire"
                elif expected_type == 'list' and not isinstance(value, list):
                    return False, f"Le champ {field} doit être une liste"
                elif expected_type == 'bool' and not isinstance(value, bool):
                    return False, f"Le champ {field} doit être un booléen"

        # Vérification des formats spéciaux si définis dans le schéma
        format_rules = self.schema.get('format_rules', {})
        for field, rule in format_rules.items():
            if field in template:
                value = template[field]
                if rule == 'version' and not self._is_valid_version(value):
                    return False, f"Format de version invalide pour {field}"
                elif rule == 'path' and not self._is_valid_path(value):
                    return False, f"Format de chemin invalide pour {field}"

        logger.debug(f"Template validé: {template.get('name', 'Sans nom')}")
        return True, ""

    def _is_valid_version(self, version: str) -> bool:
        """
        Vérifie si une version est au format X.Y.Z.
        
        Args:
            version: Chaîne de version à valider
            
        Returns:
            bool: True si la version est valide
        """
        try:
            parts = version.split('.')
            return len(parts) <= 3 and all(part.isdigit() for part in parts)
        except:
            return False

    def _is_valid_path(self, path: str) -> bool:
        """
        Vérifie si un chemin est valide et sécurisé.
        
        Args:
            path: Chemin à valider
            
        Returns:
            bool: True si le chemin est valide
        """
        try:
            return len(path) > 0 and '/' not in path and '..' not in path
        except:
            return False

    def get_default_template(self, plugin_name: str) -> Optional[dict]:
        """
        Récupère le template par défaut d'un plugin.
        
        Args:
            plugin_name: Nom du plugin
            
        Returns:
            Optional[dict]: Template par défaut ou None si non trouvé
        """
        templates = self.get_plugin_templates(plugin_name)
        default = templates.get('default')
        if default:
            logger.debug(f"Template par défaut trouvé pour {plugin_name}")
        else:
            logger.debug(f"Aucun template par défaut trouvé pour {plugin_name}")
        return default

    def get_template_names(self, plugin_name: str) -> List[str]:
        """
        Liste les noms des templates disponibles pour un plugin.
        
        Args:
            plugin_name: Nom du plugin
            
        Returns:
            List[str]: Liste des noms de templates
        """
        templates = self.get_plugin_templates(plugin_name)
        names = list(templates.keys())
        
        # Trier les noms pour que "default" apparaisse en premier
        if 'default' in names:
            names.remove('default')
            names.sort()
            names.insert(0, 'default')
        else:
            names.sort()
            
        logger.debug(f"Templates disponibles pour {plugin_name}: {names}")
        return names



    def get_template_variables(self, plugin_name: str, template_name: str) -> Optional[dict]:
        """
        Récupère les variables d'un template.
        
        Args:
            plugin_name: Nom du plugin
            template_name: Nom du template
            
        Returns:
            Optional[dict]: Variables du template ou None si non trouvé
        """
        templates = self.get_plugin_templates(plugin_name)
        template = templates.get(template_name)
        if template and 'variables' in template:
            variables = template['variables']
            logger.debug(f"Variables récupérées pour {plugin_name}/{template_name}: {list(variables.keys())}")
            return variables
        logger.debug(f"Aucune variable trouvée pour {plugin_name}/{template_name}")
        return None
        
    def apply_template(self, plugin_name: str, template_name: str, current_config: dict) -> dict:
        """
        Applique un template à une configuration existante.
        
        Args:
            plugin_name: Nom du plugin
            template_name: Nom du template à appliquer
            current_config: Configuration actuelle du plugin
            
        Returns:
            dict: Configuration mise à jour avec les variables du template
        """
        templates = self.get_plugin_templates(plugin_name)
        template = templates.get(template_name)
        
        if not template:
            logger.warning(f"Template {template_name} non trouvé pour {plugin_name}")
            return current_config.copy()
            
        # Créer une copie de la configuration actuelle
        updated_config = current_config.copy()
        
        # Extraire les variables du template
        variables = template.get('variables', {})
        
        # Mettre à jour la configuration avec les variables du template
        for var_name, var_value in variables.items():
            updated_config[var_name] = var_value
            
        logger.debug(f"Template {template_name} appliqué à {plugin_name} ({len(variables)} variables)")
        return updated_config
        
    def save_template(self, plugin_name: str, template_name: str, template_data: dict) -> bool:
        """
        Sauvegarde un template dans un fichier YAML.
        
        Args:
            plugin_name: Nom du plugin
            template_name: Nom du template
            template_data: Données du template à sauvegarder
            
        Returns:
            bool: True si la sauvegarde a réussi
        """
        try:
            # Valider le template avant de le sauvegarder
            valid, error = self._validate_template(template_data)
            if not valid:
                logger.error(f"Impossible de sauvegarder un template invalide: {error}")
                return False
                
            # Créer le répertoire du plugin s'il n'existe pas
            plugin_dir = self.templates_dir / plugin_name
            plugin_dir.mkdir(parents=True, exist_ok=True)
            
            # Définir le chemin du fichier template
            template_path = plugin_dir / f"{template_name}.yml"
            
            # Sauvegarder le template
            with open(template_path, 'w', encoding='utf-8') as f:
                yaml.dump(template_data, f)
                
            # Mettre à jour le cache si nécessaire
            if plugin_name in self.templates_cache:
                self.templates_cache[plugin_name][template_name] = template_data
                
            logger.info(f"Template {template_name} sauvegardé pour {plugin_name}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du template {template_name}: {e}")
            return False