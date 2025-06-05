import os
from ruamel.yaml import YAML
from ..utils.logging import get_logger

logger = get_logger('plugin_utils')

# Création d'une instance YAML unique
yaml = YAML()

def get_plugin_folder_name(plugin_name: str) -> str:
    """
    Retourne le nom du dossier d'un plugin à partir de son nom.
    
    Args:
        plugin_name: Nom du plugin ou identifiant avec instance
        
    Returns:
        str: Nom du dossier contenant le plugin
    """
    logger.debug(f"Recherche du dossier pour le plugin: {plugin_name}")
    
    # Cas spécial: les séquences ne sont pas des plugins standards
    if plugin_name.startswith('__sequence__'):
        logger.debug(f"Plugin {plugin_name} est une séquence, retourne '_'")
        return '_'  # Dossier spécial pour les séquences

    # Extraire le nom de base du plugin sans l'ID d'instance
    base_name = _extract_base_plugin_name(plugin_name)
    logger.debug(f"Nom de base extrait: {base_name}")
    
    # Vérifier les dossiers possibles dans l'ordre de priorité
    possible_folders = [
        f"{base_name}_test",  # Version test du plugin
        base_name,            # Version standard du plugin
        plugin_name           # Nom complet comme fallback
    ]
    
    # Parcourir les dossiers possibles et retourner le premier qui existe
    plugins_base_dir = os.path.join('plugins')
    for folder in possible_folders:
        folder_path = os.path.join(plugins_base_dir, folder)
        logger.debug(f"Vérification du chemin: {folder_path}")
        
        if os.path.exists(folder_path):
            logger.debug(f"Dossier trouvé: {folder}")
            return folder
    
    # Si aucun dossier correspondant n'est trouvé, retourner le nom tel quel
    logger.warning(f"Aucun dossier correspondant trouvé pour {plugin_name}, utilisation du nom tel quel")
    return plugin_name

def _extract_base_plugin_name(plugin_name: str) -> str:
    """
    Extrait le nom de base d'un plugin à partir de son identifiant complet.
    
    Args:
        plugin_name: Nom complet du plugin (peut inclure ID d'instance)
        
    Returns:
        str: Nom de base du plugin
    """
    # Séparation par underscore
    parts = plugin_name.split('_')
    
    # Si le plugin n'a qu'une partie, c'est déjà le nom de base
    if len(parts) == 1:
        return plugin_name
        
    # Si le plugin a deux parties ou plus, considérer les deux premières comme base
    if len(parts) >= 2:
        # Certains plugins ont un format name_type
        return f"{parts[0]}_{parts[1]}"
    
    # Fallback: retourner la première partie
    return parts[0]

def load_plugin_info(plugin_name: str, default_info=None) -> dict:
    """
    Charge les informations d'un plugin depuis son fichier settings.yml.
    
    Args:
        plugin_name: Nom ou identifiant du plugin
        default_info: Informations par défaut si le chargement échoue
        
    Returns:
        dict: Informations du plugin
    """
    logger.debug(f"Chargement des informations pour le plugin: {plugin_name}")

    # Valeurs par défaut si non fournies
    if default_info is None:
        default_info = {
            "name": plugin_name, 
            "description": "Aucune description disponible", 
            "icon": "📦"
        }

    # Cas spécial: les séquences ont un traitement différent
    if plugin_name.startswith('__sequence__'):
        logger.debug(f"Plugin {plugin_name} est une séquence, utilisation des infos par défaut")
        if 'name' not in default_info:
            default_info["name"] = plugin_name.replace('__sequence__', '')
        if 'icon' not in default_info:
            default_info["icon"] = "⚙️ "
        return default_info

    # Trouver le dossier du plugin
    folder_name = get_plugin_folder_name(plugin_name)
    settings_path = os.path.join('plugins', folder_name, 'settings.yml')

    logger.debug(f"Recherche des paramètres dans: {settings_path}")
    
    # Essayer de charger le fichier settings.yml
    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = yaml.load(f)
                logger.debug(f"Paramètres chargés avec succès pour {plugin_name}")
                return settings
        else:
            logger.warning(f"Fichier settings.yml non trouvé pour {plugin_name}")
    except Exception as e:
        logger.error(f"Erreur lors du chargement des paramètres de {plugin_name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Retourner les informations par défaut en cas d'échec
    return default_info

def get_plugins_directory() -> str:
    """
    Retourne le chemin absolu vers le répertoire des plugins.
    
    Returns:
        str: Chemin absolu vers le répertoire des plugins
    """
    # Obtenir le chemin du répertoire actuel et remonter jusqu'au répertoire des plugins
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Remonter deux niveaux (ui/choice_screen -> ui -> racine)
    root_dir = os.path.dirname(os.path.dirname(current_dir))
    plugins_dir = os.path.join(root_dir, 'plugins')
    
    return plugins_dir

def get_plugin_settings_path(plugin_name: str) -> str:
    """
    Retourne le chemin absolu vers le fichier settings.yml d'un plugin.
    
    Args:
        plugin_name: Nom ou identifiant du plugin
        
    Returns:
        str: Chemin absolu vers le fichier settings.yml
    """
    folder_name = get_plugin_folder_name(plugin_name)
    plugins_dir = get_plugins_directory()
    return os.path.join(plugins_dir, folder_name, 'settings.yml')