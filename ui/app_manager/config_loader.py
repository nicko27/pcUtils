"""
Module de chargement des configurations.

Ce module fournit des fonctionnalités pour charger des configurations
depuis des fichiers YAML et des paramètres de ligne de commande.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from ruamel.yaml import YAML
from ..utils.logging import get_logger

logger = get_logger('config_loader')

class ConfigLoader:
    """
    Gestionnaire de chargement des configurations.
    
    Cette classe est responsable de charger les configurations depuis 
    différentes sources (fichiers YAML, paramètres de ligne de commande)
    et de les fusionner de manière cohérente.
    """
    
    # Instance YAML partagée pour toute la classe
    _yaml = YAML()
    
    # Cache des configurations chargées
    _config_cache: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def load_config(cls, config_file: Union[str, Path]) -> Dict[str, Any]:
        """
        Charge un fichier de configuration YAML.
        
        Args:
            config_file: Chemin vers le fichier de configuration
            
        Returns:
            Dict[str, Any]: Configuration chargée ou dictionnaire vide en cas d'erreur
        """
        if not config_file:
            logger.debug("Aucun fichier de configuration spécifié")
            return {}
        
        # Convertir en Path si nécessaire
        if isinstance(config_file, str):
            config_file = Path(config_file)
            
        # Vérifier si la configuration est déjà en cache
        cache_key = str(config_file)
        if cache_key in cls._config_cache:
            logger.debug(f"Configuration trouvée dans le cache: {cache_key}")
            return cls._config_cache[cache_key]
            
        # Vérifier si le fichier existe
        if not config_file.exists():
            logger.error(f"Le fichier de configuration n'existe pas: {config_file}")
            return {}
            
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = cls._yaml.load(f)
                
                # Vérifier que la configuration est un dictionnaire
                if not isinstance(config, dict):
                    logger.error(f"Format de configuration invalide dans {config_file}, dictionnaire attendu")
                    return {}
                    
                # Mettre en cache et retourner
                cls._config_cache[cache_key] = config
                logger.debug(f"Configuration chargée avec succès: {config_file}")
                return config
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la configuration: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
            
    @classmethod
    def parse_params(cls, params: Optional[List[str]]) -> Dict[str, Any]:
        """
        Parse les paramètres de ligne de commande au format key=value.
        
        Args:
            params: Liste de paramètres au format key=value
            
        Returns:
            Dict[str, Any]: Dictionnaire des paramètres parsés
        """
        if not params:
            return {}
            
        config = {}
        for param in params:
            try:
                if '=' not in param:
                    logger.warning(f"Format invalide pour le paramètre: {param}. Utilisez key=value")
                    continue
                    
                key, value = param.split('=', 1)  # Séparer uniquement sur le premier '='
                key = key.strip()
                value = value.strip()
                
                # Conversion des valeurs spéciales
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                elif value.lower() == 'null' or value.lower() == 'none':
                    value = None
                elif value.isdigit():
                    value = int(value)
                elif cls._is_float(value):
                    value = float(value)
                
                # Support des clés hiérarchiques (a.b.c=value)
                if '.' in key:
                    cls._set_nested_value(config, key, value)
                else:
                    config[key] = value
                    
            except ValueError:
                logger.error(f"Format invalide pour le paramètre: {param}. Utilisez key=value")
            except Exception as e:
                logger.error(f"Erreur lors du parsing du paramètre {param}: {e}")
                
        return config
    
    @staticmethod
    def _is_float(value: str) -> bool:
        """
        Vérifie si une chaîne peut être convertie en nombre à virgule flottante.
        
        Args:
            value: Chaîne à vérifier
            
        Returns:
            bool: True si la chaîne est un nombre à virgule flottante valide
        """
        try:
            float(value)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def _set_nested_value(config: Dict[str, Any], key_path: str, value: Any) -> None:
        """
        Définit une valeur dans un dictionnaire selon un chemin hiérarchique.
        Par exemple, 'a.b.c' = 123 définit config['a']['b']['c'] = 123
        
        Args:
            config: Dictionnaire dans lequel définir la valeur
            key_path: Chemin hiérarchique (séparé par des points)
            value: Valeur à définir
        """
        keys = key_path.split('.')
        current = config
        
        # Naviguer jusqu'au niveau le plus profond sauf le dernier
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                # Si le chemin existe mais n'est pas un dictionnaire, le remplacer
                current[key] = {}
            current = current[key]
            
        # Définir la valeur au dernier niveau
        current[keys[-1]] = value
    
    @classmethod
    def merge_configs(cls, *configs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fusionne plusieurs configurations en une seule.
        Les configurations ultérieures écrasent les précédentes en cas de conflit.
        
        Args:
            *configs: Dictionnaires de configuration à fusionner
            
        Returns:
            Dict[str, Any]: Configuration fusionnée
        """
        result = {}
        
        for config in configs:
            if not isinstance(config, dict):
                logger.warning(f"Ignoré une configuration qui n'est pas un dictionnaire: {type(config)}")
                continue
                
            # Fusion récursive
            cls._recursive_merge(result, config)
            
        return result
    
    @classmethod
    def _recursive_merge(cls, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Fusionne récursivement deux dictionnaires.
        
        Args:
            target: Dictionnaire cible (modifié en place)
            source: Dictionnaire source
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                # Fusion récursive si les deux valeurs sont des dictionnaires
                cls._recursive_merge(target[key], value)
            else:
                # Sinon, remplacer ou ajouter la valeur
                target[key] = value
    
    @classmethod
    def clear_cache(cls) -> None:
        """
        Vide le cache des configurations.
        Utile pour les tests ou après des modifications de fichiers.
        """
        cls._config_cache.clear()
        logger.debug("Cache des configurations vidé")