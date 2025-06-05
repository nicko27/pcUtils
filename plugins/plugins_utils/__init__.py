import os
import sys
import importlib
from pathlib import Path

# Obtenir le répertoire du module actuel
current_dir = Path(__file__).parent

# Liste des modules à ignorer pour éviter les imports circulaires
_IGNORE_MODULES = {'__init__', 'main'}

# Liste des modules disponibles
__all__ = [
    f.stem for f in current_dir.glob("*.py") 
    if f.is_file() 
    and not f.stem.startswith('__') 
    and f.stem not in _IGNORE_MODULES
]

# Dictionnaire pour stocker les modules importés
_imported_modules = {}

def __getattr__(name):
    """
    Import dynamique avec protection contre les imports circulaires.
    
    Appelé uniquement quand un attribut n'est pas trouvé dans l'espace de noms.
    """
    # Vérifier si le module est dans __all__ et pas déjà importé
    if name in __all__ and name not in _imported_modules:
        try:
            # Vérifier s'il n'y a pas déjà un import en cours pour ce module
            if name in sys.modules:
                return sys.modules[name]
            
            # Importer le module
            module = importlib.import_module(f".{name}", package="plugins_utils")
            
            # Stocker le module
            _imported_modules[name] = module
            return module
        
        except ImportError as e:
            # Log de l'erreur sans interrompre le processus
            print(f"Impossible d'importer {name}: {e}")
            raise AttributeError(f"Module {name} not found")
    
    # Si le module n'est pas dans __all__, lever une erreur standard
    raise AttributeError(f"module {name} not found in plugins_utils")