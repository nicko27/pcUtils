# install/plugins/plugins_utils/dependency_checker.py
#!/usr/bin/env python3
"""
Module utilitaire pour vérifier les dépendances et prérequis d'un plugin.
Vérifie la présence de commandes, paquets, modules Python, fichiers, etc.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import importlib.util
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

# Essayer d'importer AptCommands pour la vérification des paquets
try:
    from .apt import AptCommands
    APT_AVAILABLE = True
except ImportError:
    APT_AVAILABLE = False
    class AptCommands: pass # Factice si non disponible

class DependencyChecker(PluginsUtilsBase):
    """
    Classe pour vérifier les prérequis d'exécution d'un plugin.
    Hérite de PluginUtilsBase pour l'exécution de commandes et la journalisation.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le vérificateur de dépendances."""
        super().__init__(logger, target_ip)
        # Instancier AptCommands si disponible
        self._apt = AptCommands(logger, target_ip) if APT_AVAILABLE else None
        if not APT_AVAILABLE:
             self.log_warning("Module AptCommands non trouvé. La vérification des paquets sera désactivée.", log_levels=log_levels)

    def check_command(self, command_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si une commande externe est disponible dans le PATH.

        Args:
            command_name: Nom de la commande à vérifier.

        Returns:
            bool: True si la commande est trouvée, False sinon.
        """
        self.log_debug(f"Vérification de la présence de la commande: {command_name}", log_levels=log_levels)
        # Utiliser 'which' ou 'command -v' via self.run
        success, stdout, _ = self.run(['which', command_name], check=False, no_output=True, error_as_warning=True)
        if success and stdout.strip():
            self.log_info(f"Commande '{command_name}' trouvée: {stdout.strip()}", log_levels=log_levels)
            return True
        else:
            self.log_warning(f"Commande '{command_name}' non trouvée dans le PATH.", log_levels=log_levels)
            return False

    def check_package(self, package_name: str, min_version: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un paquet système (Debian/Ubuntu) est installé.

        Args:
            package_name: Nom du paquet (ex: 'openssh-server').
            min_version: Version minimale requise (optionnel).

        Returns:
            bool: True si le paquet est installé et satisfait la version minimale.
        """
        if not self._apt:
            self.log_error("Vérification de paquet impossible: AptCommands non disponible.", log_levels=log_levels)
            return False # Ne peut pas vérifier

        self.log_debug(f"Vérification de l'installation du paquet: {package_name} (version min: {min_version or 'N/A'})", log_levels=log_levels)
        installed = self._apt.is_installed(package_name)

        if not installed:
            self.log_warning(f"Paquet requis '{package_name}' non installé.", log_levels=log_levels)
            return False

        if min_version:
            current_version = self._apt.get_version(package_name)
            if not current_version:
                 self.log_warning(f"Paquet '{package_name}' installé mais impossible de récupérer sa version.", log_levels=log_levels)
                 # Considérer comme échec si une version minimale est requise
                 return False
            # Comparer les versions (nécessite une logique de comparaison robuste)
            # Utiliser dpkg --compare-versions via self.run
            cmd_compare = ['dpkg', '--compare-versions', current_version, 'ge', min_version] # ge = greater or equal
            success_cmp, _, _ = self.run(cmd_compare, check=False, no_output=True, error_as_warning=True)
            if not success_cmp:
                 self.log_warning(f"Paquet '{package_name}' installé (version {current_version}) mais ne satisfait pas la version minimale requise ({min_version}).", log_levels=log_levels)
                 return False
            self.log_info(f"Paquet '{package_name}' (version {current_version}) satisfait la version minimale ({min_version}).", log_levels=log_levels)
        else:
            self.log_info(f"Paquet '{package_name}' est installé.", log_levels=log_levels)

        return True

    def check_python_module(self, module_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un module Python peut être importé.

        Args:
            module_name: Nom du module (ex: 'requests', 'ldap').

        Returns:
            bool: True si le module est trouvable.
        """
        self.log_debug(f"Vérification de la disponibilité du module Python: {module_name}", log_levels=log_levels)
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is not None:
                self.log_info(f"Module Python '{module_name}' trouvé.", log_levels=log_levels)
                return True
            else:
                self.log_warning(f"Module Python requis '{module_name}' non trouvé.", log_levels=log_levels)
                return False
        except ModuleNotFoundError:
             self.log_warning(f"Module Python requis '{module_name}' non trouvé (ModuleNotFoundError).", log_levels=log_levels)
             return False
        except Exception as e:
             self.log_error(f"Erreur lors de la vérification du module Python '{module_name}': {e}", log_levels=log_levels)
             return False

    def check_file_exists(self, path: Union[str, Path], check_is_file: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie l'existence d'un fichier.

        Args:
            path: Chemin complet du fichier.
            check_is_file: Si True (défaut), vérifie aussi que c'est un fichier et non un dossier.

        Returns:
            bool: True si le fichier existe (et est un fichier si check_is_file=True).
        """
        target_path = Path(path)
        self.log_debug(f"Vérification de l'existence du fichier: {target_path}", log_levels=log_levels)
        exists = target_path.exists()
        is_file = target_path.is_file() if exists else False

        if not exists:
            self.log_warning(f"Fichier requis non trouvé: {target_path}", log_levels=log_levels)
            return False
        elif check_is_file and not is_file:
            self.log_warning(f"Le chemin requis {target_path} existe mais n'est pas un fichier.", log_levels=log_levels)
            return False
        elif check_is_file and is_file:
             self.log_info(f"Fichier requis trouvé: {target_path}", log_levels=log_levels)
             return True
        else: # exists and not check_is_file
             self.log_info(f"Chemin requis trouvé: {target_path}", log_levels=log_levels)
             return True

    def check_directory_exists(self, path: Union[str, Path], check_is_dir: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie l'existence d'un répertoire.

        Args:
            path: Chemin complet du répertoire.
            check_is_dir: Si True (défaut), vérifie aussi que c'est un répertoire.

        Returns:
            bool: True si le répertoire existe (et est un répertoire si check_is_dir=True).
        """
        target_path = Path(path)
        self.log_debug(f"Vérification de l'existence du répertoire: {target_path}", log_levels=log_levels)
        exists = target_path.exists()
        is_dir = target_path.is_dir() if exists else False

        if not exists:
            self.log_warning(f"Répertoire requis non trouvé: {target_path}", log_levels=log_levels)
            return False
        elif check_is_dir and not is_dir:
            self.log_warning(f"Le chemin requis {target_path} existe mais n'est pas un répertoire.", log_levels=log_levels)
            return False
        elif check_is_dir and is_dir:
             self.log_info(f"Répertoire requis trouvé: {target_path}", log_levels=log_levels)
             return True
        else: # exists and not check_is_dir
             self.log_info(f"Chemin requis trouvé: {target_path}", log_levels=log_levels)
             return True

    def check_all(self,
                  commands: Optional[List[str]] = None,
                  packages: Optional[Union[List[str], Dict[str, Optional[str]]]] = None,
                  python_modules: Optional[List[str]] = None,
                  files: Optional[List[str]] = None,
                  directories: Optional[List[str]] = None
, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Exécute une série de vérifications de dépendances.

        Args:
            commands: Liste de noms de commandes à vérifier.
            packages: Liste de noms de paquets OU dictionnaire {nom_paquet: version_min}.
            python_modules: Liste de noms de modules Python à vérifier.
            files: Liste de chemins de fichiers dont l'existence doit être vérifiée.
            directories: Liste de chemins de répertoires dont l'existence doit être vérifiée.

        Returns:
            Dictionnaire résumant les résultats:
            {
                'overall_status': 'OK' | 'MISSING_DEPENDENCIES',
                'missing': {
                    'commands': [...],
                    'packages': [...],
                    'python_modules': [...],
                    'files': [...],
                    'directories': [...]
                },
                'details': { # Statut détaillé pour chaque élément vérifié
                    'commands': {'cmd1': True, 'cmd2': False, ...},
                    'packages': {'pkg1': True, 'pkg2': False, ...},
                    ...
                }
            }
        """
        self.log_info("Vérification des dépendances requises...", log_levels=log_levels)
        results: Dict[str, Any] = {
            'overall_status': 'OK',
            'missing': {'commands': [], 'packages': [], 'python_modules': [], 'files': [], 'directories': []},
            'details': {'commands': {}, 'packages': {}, 'python_modules': {}, 'files': {}, 'directories': {}}
        }
        all_ok = True

        # Vérifier les commandes
        if commands:
            self.log_info(f"Vérification des commandes: {', '.join(commands)}", log_levels=log_levels)
            for cmd in commands:
                found = self.check_command(cmd)
                results['details']['commands'][cmd] = found
                if not found:
                    results['missing']['commands'].append(cmd)
                    all_ok = False

        # Vérifier les paquets
        if packages:
            pkg_list = []
            pkg_versions = {}
            if isinstance(packages, list):
                pkg_list = packages
            elif isinstance(packages, dict):
                pkg_list = list(packages.keys())
                pkg_versions = packages

            self.log_info(f"Vérification des paquets: {', '.join(pkg_list)}", log_levels=log_levels)
            if not self._apt:
                 self.log_error("Impossible de vérifier les paquets: AptCommands non disponible.", log_levels=log_levels)
                 results['overall_status'] = 'ERROR' # Erreur de vérification
                 # Marquer tous comme manquants ? Ou juste logguer l'erreur ? Logguer.
            else:
                 for pkg in pkg_list:
                     min_version = pkg_versions.get(pkg)
                     installed = self.check_package(pkg, min_version=min_version)
                     results['details']['packages'][pkg] = installed
                     if not installed:
                         results['missing']['packages'].append(f"{pkg}{' (version>=' + min_version + ')' if min_version else ''}")
                         all_ok = False

        # Vérifier les modules Python
        if python_modules:
            self.log_info(f"Vérification des modules Python: {', '.join(python_modules)}", log_levels=log_levels)
            for mod in python_modules:
                found = self.check_python_module(mod)
                results['details']['python_modules'][mod] = found
                if not found:
                    results['missing']['python_modules'].append(mod)
                    all_ok = False

        # Vérifier les fichiers
        if files:
            self.log_info(f"Vérification des fichiers: {', '.join(files)}", log_levels=log_levels)
            for f in files:
                found = self.check_file_exists(f)
                results['details']['files'][f] = found
                if not found:
                    results['missing']['files'].append(f)
                    all_ok = False

        # Vérifier les répertoires
        if directories:
            self.log_info(f"Vérification des répertoires: {', '.join(directories)}", log_levels=log_levels)
            for d in directories:
                found = self.check_directory_exists(d)
                results['details']['directories'][d] = found
                if not found:
                    results['missing']['directories'].append(d)
                    all_ok = False

        # Mettre à jour le statut global
        if not all_ok:
            results['overall_status'] = 'MISSING_DEPENDENCIES'
            self.log_warning("Certaines dépendances sont manquantes.", log_levels=log_levels)
            # Logguer les dépendances manquantes
            for dep_type, missing_list in results['missing'].items():
                 if missing_list:
                      self.log_warning(f"  - Manquants ({dep_type}): {', '.join(missing_list)}", log_levels=log_levels)
        else:
            self.log_success("Toutes les dépendances vérifiées sont présentes.", log_levels=log_levels)

        return results