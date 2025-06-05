import sys
import os
import glob

# Configure logging first
from ui.utils.logging import get_logger

logger = get_logger('main')

# Utiliser le chemin absolu du script comme base
pkg_dir = os.path.dirname(os.path.abspath(__file__))
logger.debug(f"Répertoire de base de l'application: {pkg_dir}")

# Ajouter le répertoire principal au path en priorité
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)
    logger.debug(f"Ajout de {pkg_dir} au sys.path")

# Ajouter tous les sous-répertoires pertinents
for subdir in glob.glob(os.path.join(pkg_dir, '*')):
    if os.path.isdir(subdir) and (
        subdir.endswith('.dist-info') or
        os.path.exists(os.path.join(subdir, '__init__.py')) or
        subdir.endswith('.data')
    ):
        logger.debug(f"Sous-répertoire trouvé: {subdir}")
        # Ajouter le répertoire parent si nécessaire
        parent_dir = os.path.dirname(subdir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            logger.debug(f"Ajout de {parent_dir} au sys.path")

# Ajouter explicitement le dossier libs au chemin de recherche
libs_dir = os.path.join(pkg_dir, 'libs')
if os.path.exists(libs_dir) and os.path.isdir(libs_dir):
    # Ajouter tous les sous-répertoires de libs qui contiennent des packages Python
    for lib_path in glob.glob(os.path.join(libs_dir, '*')):
        if os.path.isdir(lib_path):
            # Vérifier si c'est un package Python
            if lib_path not in sys.path:
                sys.path.insert(0, lib_path)
                logger.debug(f"Ajout de la bibliothèque: {lib_path} au sys.path")

# Afficher le sys.path complet pour le débogage
logger.debug(f"sys.path complet: {sys.path}")

# Essayer d'importer ruamel.yaml pour vérifier que ça fonctionne
try:
    import ruamel.yaml
    logger.debug(f"ruamel.yaml importé avec succès depuis {ruamel.yaml.__file__}")
except ImportError as e:
    logger.error(f"Erreur lors de l'importation de ruamel.yaml: {e}")
    print(f"Erreur critique: Impossible d'importer ruamel.yaml. Vérifiez que le package est installé.")
    sys.exit(1)

from ui.app_manager import AppManager

if __name__ == "__main__":
    app_manager = AppManager()
    app_manager.run()
