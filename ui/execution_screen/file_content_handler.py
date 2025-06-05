"""
Module pour gérer le contenu des fichiers de configuration.
"""

import os
from ruamel.yaml import YAML

from ..utils.logging import get_logger

logger = get_logger('file_content_handler')

class FileContentHandler:
    """Classe pour gérer le contenu des fichiers de configuration."""
    
    @staticmethod
    def process_file_content(plugin_settings, plugin_config, plugin_dir):
        """
        Traite le contenu des fichiers de configuration.
        
        Args:
            plugin_settings (dict): Les paramètres du plugin depuis settings.yml
            plugin_config (dict): La configuration du plugin
            plugin_dir (str): Le chemin vers le répertoire du plugin
            
        Returns:
            dict: Un dictionnaire contenant le contenu des fichiers
        """
        file_content = {}
        
        # Vérifier si la configuration files_content existe
        if 'files_content' in plugin_settings and isinstance(plugin_settings['files_content'], dict):
            file_config = plugin_settings['files_content']
            logger.info(f"Configuration files_content trouvée: {file_config}")
            
            # Traiter chaque entrée de file_content
            for param_name, file_path in file_config.items():
                logger.info(f"Traitement du fichier pour {param_name}: {file_path}")
                
                # Remplacer les variables dans le chemin du fichier
                # D'abord chercher dans la configuration racine
                for key, value in plugin_config.items():
                    if isinstance(value, str):
                        placeholder = f"{{{key}}}"
                        if placeholder in file_path:
                            # Vérifier si on va ajouter une extension en double
                            if '.yml' in file_path and value.endswith('.yml'):
                                # Si le chemin contient déjà .yml et que la valeur se termine par .yml,
                                # retirer l'extension .yml de la valeur pour éviter la double extension
                                value = value[:-4]  # Retirer les 4 derniers caractères (.yml)
                                logger.info(f"Extension .yml retirée de la valeur {value+'.yml'} pour éviter la double extension")
                            file_path = file_path.replace(placeholder, value)
                            logger.info(f"Variable {placeholder} remplacée par {value} dans le chemin")
                
                # Ensuite chercher dans le sous-dictionnaire config si présent
                if 'config' in plugin_config and isinstance(plugin_config['config'], dict):
                    for key, value in plugin_config['config'].items():
                        if isinstance(value, str):
                            placeholder = f"{{{key}}}"
                            if placeholder in file_path:
                                # Vérifier si on va ajouter une extension en double
                                if '.yml' in file_path and value.endswith('.yml'):
                                    # Si le chemin contient déjà .yml et que la valeur se termine par .yml,
                                    # retirer l'extension .yml de la valeur pour éviter la double extension
                                    value = value[:-4]  # Retirer les 4 derniers caractères (.yml)
                                    logger.info(f"Extension .yml retirée de la valeur {value+'.yml'} pour éviter la double extension")
                                file_path = file_path.replace(placeholder, value)
                                logger.info(f"Variable {placeholder} (depuis config) remplacée par {value} dans le chemin")
                
                # Construire le chemin complet
                full_path = os.path.join(plugin_dir, file_path)
                logger.info(f"Chemin complet du fichier: {full_path}")
                
                # Vérifier si le fichier existe
                if os.path.exists(full_path):
                    try:
                        # Lire le contenu du fichier
                        with open(full_path, 'r', encoding='utf-8') as f:
                            file_content_str = f.read()
                            logger.info(f"Contenu du fichier lu avec succès pour {param_name}")
                            
                            # Essayer de parser le contenu comme YAML pour le convertir en dictionnaire
                            try:
                                parsed_content = YAML().load(file_content_str)
                                logger.info(f"Contenu YAML parsé avec succès pour {param_name}: {type(parsed_content)}")
                            except Exception as yaml_error:
                                logger.warning(f"Impossible de parser le contenu comme YAML: {yaml_error}")
                                parsed_content = file_content_str
                            
                            # Ajouter le contenu au dictionnaire
                            file_content[param_name] = parsed_content
                    except Exception as e:
                        logger.error(f"Erreur lors de la lecture du fichier {full_path}: {str(e)}")
                else:
                    logger.warning(f"Fichier introuvable: {full_path}")
        else:
            logger.info("Aucune configuration files_content trouvée")
        
        return file_content
