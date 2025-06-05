# install/plugins/plugins_utils/kernel.py
#!/usr/bin/env python3
"""
Module utilitaire pour interagir avec le noyau Linux.
Permet de lire/modifier les paramètres sysctl et de gérer les modules du noyau.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
from typing import Union, Optional, List, Dict, Any

class KernelCommands(PluginsUtilsBase):
    """
    Classe pour interagir avec les paramètres et modules du noyau Linux.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire du noyau."""
        super().__init__(logger, target_ip)


    def get_uname_info(self, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Récupère les informations du noyau via la commande uname.

        Returns:
            Dictionnaire contenant les informations uname (kernel_name, node_name,
            kernel_release, kernel_version, machine, operating_system).
        """
        self.log_info("Récupération des informations uname", log_levels=log_levels)
        info = {}
        options = {
            '-s': 'kernel_name',
            '-n': 'node_name',
            '-r': 'kernel_release',
            '-v': 'kernel_version',
            '-m': 'machine',
            '-o': 'operating_system',
            '-a': 'all' # Pour le debug
        }
        for flag, key in options.items():
            success, stdout, stderr = self.run(['uname', flag], check=False, no_output=True)
            if success:
                info[key] = stdout.strip()
            else:
                self.log_warning(f"Échec de 'uname {flag}'. Stderr: {stderr}", log_levels=log_levels)
                info[key] = "N/A"

        self.log_debug(f"Informations uname récupérées: {info}", log_levels=log_levels)
        return info

    def list_modules(self, log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Liste les modules du noyau actuellement chargés via lsmod.

        Returns:
            Liste de dictionnaires, chaque dict représentant un module chargé.
            Clés: 'module', 'size', 'used_by' (liste de modules).
        """
        self.log_info("Listage des modules noyau chargés (lsmod)", log_levels=log_levels)
        success, stdout, stderr = self.run(['lsmod'], check=False, no_output=True)
        modules = []
        if not success:
            self.log_error(f"Échec de la commande lsmod. Stderr: {stderr}", log_levels=log_levels)
            return modules

        # Format de sortie lsmod (l'en-tête est ignoré):
        # Module                  Size  Used by
        # module_name            12345  0
        # another_module         67890  2 module_name,some_other
        header_skipped = False
        for line in stdout.splitlines():
            if not header_skipped:
                if line.lower().startswith("module"):
                    header_skipped = True
                continue # Ignorer l'en-tête ou les lignes avant

            parts = line.split()
            if len(parts) >= 3:
                try:
                    module_name = parts[0]
                    size = int(parts[1])
                    used_count = int(parts[2]) # Le nombre après la taille
                    used_by_list = []
                    if len(parts) > 3:
                         # Les modules dépendants sont après le compte, séparés par des virgules
                         used_by_str = " ".join(parts[3:])
                         used_by_list = [mod.strip() for mod in used_by_str.split(',') if mod.strip()]

                    modules.append({
                        'module': module_name,
                        'size': size,
                        'used_by_count': used_count, # Garder le compte numérique
                        'used_by': used_by_list
                    })
                except (ValueError, IndexError) as e:
                     self.log_warning(f"Impossible de parser la ligne lsmod: '{line}'. Erreur: {e}", log_levels=log_levels)
            elif line.strip(): # Ligne non vide mais format incorrect
                 self.log_warning(f"Ligne lsmod ignorée (format inattendu): '{line}'", log_levels=log_levels)


        self.log_info(f"{len(modules)} modules noyau chargés trouvés.", log_levels=log_levels)
        self.log_debug(f"Modules chargés: {modules}", log_levels=log_levels)
        return modules

    def is_module_loaded(self, module_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si un module spécifique est chargé."""
        self.log_debug(f"Vérification si le module '{module_name}' est chargé", log_levels=log_levels)
        # Méthode 1: lsmod | grep (simple mais peut avoir des faux positifs)
        # success_grep, _, _ = self.run(f'lsmod | grep "^{module_name}\\s"', shell=True, check=False, no_output=True)
        # Méthode 2: Vérifier /sys/module (plus fiable si disponible)
        module_path = f"/sys/module/{module_name.replace('-', '_')}" # Remplacer - par _ pour le chemin sysfs
        success_test, _, _ = self.run(['test', '-d', module_path], check=False, no_output=True)

        is_loaded = success_test
        self.log_debug(f"Module '{module_name}' est chargé: {is_loaded}", log_levels=log_levels)
        return is_loaded

    def load_module(self, module_name: str, params: Optional[Dict[str, str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Charge un module noyau via modprobe. Nécessite root.

        Args:
            module_name: Nom du module à charger.
            params: Dictionnaire de paramètres à passer au module (optionnel).

        Returns:
            bool: True si le chargement a réussi ou si déjà chargé.
        """
        if self.is_module_loaded(module_name):
            self.log_info(f"Le module '{module_name}' est déjà chargé.", log_levels=log_levels)
            return True

        self.log_info(f"Chargement du module noyau: {module_name}", log_levels=log_levels)
        cmd = ['modprobe']
        cmd.append(module_name)
        param_str_list = []
        if params:
            for key, value in params.items():
                # Ajouter des guillemets si la valeur contient des espaces ou caractères spéciaux
                if isinstance(value, str) and (' ' in value or value.isalnum() is False):
                     param_str = f'{key}="{value}"'
                else:
                     param_str = f'{key}={value}'
                param_str_list.append(param_str)
            cmd.extend(param_str_list)
            self.log_info(f"  Avec paramètres: {' '.join(param_str_list)}", log_levels=log_levels)

        # modprobe nécessite root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Module '{module_name}' chargé avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du chargement du module '{module_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def unload_module(self, module_name: str, force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Décharge un module noyau via rmmod. Nécessite root.

        Args:
            module_name: Nom du module à décharger.
            force: Utiliser l'option -f (déchargement forcé, dangereux).

        Returns:
            bool: True si le déchargement a réussi ou si déjà déchargé.
        """
        if not self.is_module_loaded(module_name):
            self.log_info(f"Le module '{module_name}' n'est pas chargé, déchargement ignoré.", log_levels=log_levels)
            return True

        self.log_info(f"Déchargement du module noyau: {module_name}{' (forcé)' if force else ''}", log_levels=log_levels)
        cmd = ['rmmod']
        if force:
            cmd.append('-f')
        cmd.append(module_name)

        # rmmod nécessite root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Module '{module_name}' déchargé avec succès.", log_levels=log_levels)
            return True
        else:
             # Gérer l'erreur si le module n'existe pas (déjà déchargé)
             if "module is not loaded" in stderr.lower() or "module not found" in stderr.lower():
                  self.log_warning(f"Le module '{module_name}' n'était pas chargé (ou a été déchargé entre temps).", log_levels=log_levels)
                  return True
             # Gérer l'erreur si le module est en cours d'utilisation
             if "is in use" in stderr.lower():
                  self.log_error(f"Échec du déchargement: le module '{module_name}' est en cours d'utilisation.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec du déchargement du module '{module_name}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    def get_sysctl_value(self, parameter: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Lit la valeur d'un paramètre sysctl.

        Args:
            parameter: Nom du paramètre (ex: kernel.hostname).

        Returns:
            Valeur du paramètre sous forme de chaîne, ou None si erreur.
        """
        self.log_debug(f"Lecture du paramètre sysctl: {parameter}", log_levels=log_levels)
        # -n pour n'afficher que la valeur
        # check=False car sysctl peut retourner une erreur si le paramètre n'existe pas
        success, stdout, stderr = self.run(['sysctl', '-n', parameter], check=False, no_output=True)
        if success:
            value = stdout.strip()
            self.log_debug(f"Valeur de {parameter}: {value}", log_levels=log_levels)
            return value
        else:
            if "cannot stat" in stderr and "No such file or directory" in stderr:
                 self.log_warning(f"Le paramètre sysctl '{parameter}' n'existe pas.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la lecture de sysctl '{parameter}'. Stderr: {stderr}", log_levels=log_levels)
            return None

    def set_sysctl_value(self, parameter: str, value: Union[str, int], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Modifie la valeur d'un paramètre sysctl. Nécessite root.

        Args:
            parameter: Nom du paramètre.
            value: Nouvelle valeur.

        Returns:
            bool: True si la modification a réussi.
        """
        self.log_info(f"Modification du paramètre sysctl: {parameter} = {value}", log_levels=log_levels)
        # Utiliser le format "param=val" avec l'option -w
        cmd = ['sysctl', '-w', f"{parameter}={value}"]

        # sysctl -w nécessite root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            # sysctl -w affiche la nouvelle valeur sur stdout
            if stdout: self.log_info(f"Sortie sysctl: {stdout.strip()}", log_levels=log_levels)
            self.log_success(f"Paramètre sysctl '{parameter}' mis à jour.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la modification de sysctl '{parameter}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def get_all_sysctl(self, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Récupère tous les paramètres sysctl et leurs valeurs.

        Returns:
            Dictionnaire des paramètres {param: valeur}.
        """
        self.log_info("Récupération de tous les paramètres sysctl (sysctl -a)", log_levels=log_levels)
        # check=False car parfois des erreurs mineures peuvent apparaître
        success, stdout, stderr = self.run(['sysctl', '-a'], check=False, no_output=True)
        params = {}
        if not success:
            self.log_error(f"Échec partiel ou total de 'sysctl -a'. Stderr: {stderr}", log_levels=log_levels)
            # Continuer avec ce qui a été lu sur stdout

        for line in stdout.splitlines():
            # Format: kernel.hostname = myhost
            if " = " in line:
                try:
                    key, value = line.split(" = ", 1)
                    params[key.strip()] = value.strip()
                except ValueError:
                     self.log_warning(f"Ligne sysctl ignorée (format inattendu): '{line}'", log_levels=log_levels)

        self.log_info(f"{len(params)} paramètres sysctl récupérés.", log_levels=log_levels)
        self.log_debug(f"Paramètres sysctl: {params}", log_levels=log_levels)
        return params