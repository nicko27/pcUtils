# install/plugins/plugins_utils/webserver.py
#!/usr/bin/env python3
"""
Module utilitaire pour la gestion des serveurs web Apache2 et Nginx.
Utilise les commandes système spécifiques (apachectl/httpd, a2en*/a2dis*, nginx).
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import glob
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

# Essayer d'importer ServiceCommands pour la gestion des services
try:
    from .services import ServiceCommands
    SERVICES_AVAILABLE = True
except ImportError:
    SERVICES_AVAILABLE = False

class WebServerCommands(PluginsUtilsBase):
    """
    Classe pour gérer les serveurs web Apache2 et Nginx.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    SERVER_APACHE = "apache"
    SERVER_NGINX = "nginx"
    SERVER_UNKNOWN = "unknown"

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de serveur web."""
        super().__init__(logger, target_ip)
        self._apache_cmd = None
        self._nginx_cmd = None
        self._apache_service_name = None
        self._nginx_service_name = "nginx" # Nom standard
        self._check_commands()
        # Initialiser ServiceCommands si disponible
        self._service_manager = ServiceCommands(logger, target_ip) if SERVICES_AVAILABLE else None

    def _check_commands(self):
        """Vérifie si les commandes serveur web sont disponibles."""
        # Apache: chercher apache2ctl, apachectl, httpd
        for cmd_name in ['apache2ctl', 'apachectl', 'httpd']:
            success, path, _ = self.run(['which', cmd_name], check=False, no_output=True, error_as_warning=True)
            if success:
                self._apache_cmd = path.strip()
                # Déterminer le nom du service associé
                if 'apache2ctl' in self._apache_cmd:
                    self._apache_service_name = 'apache2'
                elif 'httpd' in self._apache_cmd:
                     self._apache_service_name = 'httpd'
                else:
                     # Fallback
                     self._apache_service_name = 'apache2' if os.path.exists('/etc/init.d/apache2') else 'httpd'
                self.log_debug(f"Commande Apache trouvée: {self._apache_cmd} (service: {self._apache_service_name})", log_levels=log_levels)
                break
        if not self._apache_cmd:
            self.log_debug("Aucune commande Apache (apache2ctl, apachectl, httpd) trouvée.", log_levels=log_levels)

        # Nginx
        success_nginx, path_nginx, _ = self.run(['which', 'nginx'], check=False, no_output=True, error_as_warning=True)
        if success_nginx:
            self._nginx_cmd = path_nginx.strip()
            self.log_debug(f"Commande Nginx trouvée: {self._nginx_cmd}", log_levels=log_levels)
        else:
             self.log_debug("Commande Nginx non trouvée.", log_levels=log_levels)

        # Outils Apache Debian/Ubuntu
        for cmd_name in ['a2ensite', 'a2dissite', 'a2enmod', 'a2dismod']:
             success, _, _ = self.run(['which', cmd_name], check=False, no_output=True, error_as_warning=True)
             if not success:
                  self.log_debug(f"Commande Apache '{cmd_name}' non trouvée (peut être normal sur non-Debian).", log_levels=log_levels)


    def detect_webserver(self, log_levels: Optional[Dict[str, str]] = None) -> str:
        """
        Tente de détecter quel serveur web est principal (installé et potentiellement actif).
        Donne la priorité à Apache si les deux sont trouvés.

        Returns:
            'apache', 'nginx', ou 'unknown'.
        """
        apache_present = bool(self._apache_cmd)
        nginx_present = bool(self._nginx_cmd)

        # Vérifier les services si possible
        apache_active = False
        nginx_active = False
        if self._service_manager:
            if apache_present and self._apache_service_name:
                 apache_active = self._service_manager.is_active(self._apache_service_name)
            if nginx_present:
                 nginx_active = self._service_manager.is_active(self._nginx_service_name)

        if apache_active:
             self.log_info("Serveur web détecté: Apache (actif)", log_levels=log_levels)
             return self.SERVER_APACHE
        if nginx_active:
             self.log_info("Serveur web détecté: Nginx (actif)", log_levels=log_levels)
             return self.SERVER_NGINX

        # Si services non actifs ou non vérifiables, se baser sur la présence des commandes
        if apache_present:
             self.log_info("Serveur web détecté: Apache (commande présente)", log_levels=log_levels)
             return self.SERVER_APACHE
        if nginx_present:
             self.log_info("Serveur web détecté: Nginx (commande présente)", log_levels=log_levels)
             return self.SERVER_NGINX

        self.log_info("Aucun serveur web principal (Apache/Nginx) détecté.", log_levels=log_levels)
        return self.SERVER_UNKNOWN

    # --- Opérations Apache ---

    def apache_check_config(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie la syntaxe de la configuration Apache."""
        if not self._apache_cmd:
            self.log_error("Commande Apache (apachectl/httpd) non trouvée.", log_levels=log_levels)
            return False
        self.log_info("Vérification de la configuration Apache (configtest)", log_levels=log_levels)
        # Utiliser 'configtest' ou '-t'
        cmd = [self._apache_cmd, 'configtest']
        # La sortie va sur stderr, même en cas de succès ("Syntax OK")
        # check=False car retourne non-zéro si erreur de syntaxe
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True) # Nécessite sudo pour lire tous les fichiers inclus

        if "syntax is ok" in stderr.lower():
            self.log_success("Syntaxe de configuration Apache OK.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Erreur de syntaxe dans la configuration Apache. Stderr:\n{stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Stdout:\n{stdout}", log_levels=log_levels) # Parfois des infos utiles sur stdout aussi
            return False

    def _run_apache_tool(self, tool: str, target: str, action_verb: str) -> bool:
        """Exécute un outil Apache comme a2ensite, a2dissite, etc."""
        cmd_path = None
        # Trouver le chemin de l'outil
        success_which, path, _ = self.run(['which', tool], check=False, no_output=True, error_as_warning=True)
        if not success:
             self.log_error(f"Commande Apache '{tool}' non trouvée.", log_levels=log_levels)
             return False
        cmd_path = path.strip()

        self.log_info(f"{action_verb.capitalize()} Apache '{target}' via {tool}", log_levels=log_levels)
        cmd = [cmd_path, '-q', target] # -q pour quiet
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        # Analyser stdout/stderr pour le résultat réel car le code retour n'est pas toujours fiable
        output = stdout + stderr
        action_past = action_verb.replace('er', 'é') # Activer -> Activé
        if f"{target} {action_past}" in output or "run systemctl reload apache2" in output:
             self.log_success(f"Apache: {target} {action_past} avec succès.", log_levels=log_levels)
             self.log_info("Un rechargement/redémarrage d'Apache est nécessaire pour appliquer les changements.", log_levels=log_levels)
             return True
        elif f"{target} already enabled" in output or f"{target} déjà activé" in output:
             self.log_info(f"Apache: {target} est déjà {action_past}.", log_levels=log_levels)
             return True
        elif f"{target} does not exist" in output or f"n'existe pas" in output:
             self.log_error(f"Apache: {target} n'existe pas.", log_levels=log_levels)
             return False
        else:
             self.log_error(f"Échec de '{tool} {target}'. Sortie:\n{output}", log_levels=log_levels)
             return False

    def apache_enable_site(self, site_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Active un site Apache (ex: '000-default' ou 'my-site.conf')."""
        return self._run_apache_tool('a2ensite', site_name, 'activer site')

    def apache_disable_site(self, site_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Désactive un site Apache."""
        return self._run_apache_tool('a2dissite', site_name, 'désactiver site')

    def apache_enable_module(self, module_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Active un module Apache."""
        return self._run_apache_tool('a2enmod', module_name, 'activer module')

    def apache_disable_module(self, module_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Désactive un module Apache."""
        return self._run_apache_tool('a2dismod', module_name, 'désactiver module')

    def apache_reload(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Recharge la configuration Apache."""
        if not self._apache_service_name:
            self.log_error("Nom du service Apache inconnu, impossible de recharger.", log_levels=log_levels)
            return False
        if not self._service_manager:
            self.log_error("Gestionnaire de services non disponible, impossible de recharger Apache.", log_levels=log_levels)
            return False
        self.log_info(f"Rechargement du service Apache ({self._apache_service_name})", log_levels=log_levels)
        # Utiliser 'reload' qui est plus gracieux que 'restart'
        return self._service_manager.reload(self._apache_service_name)

    def apache_restart(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Redémarre le service Apache."""
        if not self._apache_service_name:
            self.log_error("Nom du service Apache inconnu, impossible de redémarrer.", log_levels=log_levels)
            return False
        if not self._service_manager:
            self.log_error("Gestionnaire de services non disponible, impossible de redémarrer Apache.", log_levels=log_levels)
            return False
        self.log_info(f"Redémarrage du service Apache ({self._apache_service_name})", log_levels=log_levels)
        return self._service_manager.restart(self._apache_service_name)

    # --- Opérations Nginx ---

    def nginx_check_config(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie la syntaxe de la configuration Nginx."""
        if not self._nginx_cmd:
            self.log_error("Commande Nginx non trouvée.", log_levels=log_levels)
            return False
        self.log_info("Vérification de la configuration Nginx (nginx -t)", log_levels=log_levels)
        # nginx -t écrit sur stderr
        cmd = [self._nginx_cmd, '-t']
        # check=False car retourne non-zéro si erreur de syntaxe
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True) # Souvent besoin de sudo pour lire les includes

        # Le succès est indiqué par "syntax is ok" ET "test is successful" sur stderr
        stderr_lower = stderr.lower()
        if "syntax is ok" in stderr_lower and "test is successful" in stderr_lower:
            self.log_success("Syntaxe de configuration Nginx OK.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Erreur de syntaxe dans la configuration Nginx. Stderr:\n{stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Stdout:\n{stdout}", log_levels=log_levels)
            return False

    def _get_nginx_sites_dirs(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Trouve les répertoires sites-available et sites-enabled pour Nginx."""
        common_paths = ['/etc/nginx']
        # Ajouter d'autres chemins si nécessaire (ex: /usr/local/nginx/conf)
        for base_path in common_paths:
            available = Path(base_path) / "sites-available"
            enabled = Path(base_path) / "sites-enabled"
            if available.is_dir() and enabled.is_dir():
                 self.log_debug(f"Répertoires Nginx trouvés: {available}, {enabled}", log_levels=log_levels)
                 return available, enabled
        self.log_error("Impossible de trouver les répertoires 'sites-available' et 'sites-enabled' pour Nginx.", log_levels=log_levels)
        return None, None

    def nginx_enable_site(self, site_config_filename: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Active un site Nginx en créant un lien symbolique."""
        available_dir, enabled_dir = self._get_nginx_sites_dirs()
        if not available_dir or not enabled_dir:
            return False

        site_available_path = available_dir / site_config_filename
        site_enabled_path = enabled_dir / site_config_filename

        self.log_info(f"Activation du site Nginx: {site_config_filename}", log_levels=log_levels)

        if not site_available_path.is_file():
            self.log_error(f"Fichier de configuration '{site_config_filename}' non trouvé dans {available_dir}.", log_levels=log_levels)
            return False

        if site_enabled_path.is_symlink() or site_enabled_path.exists():
            # Vérifier si le lien pointe vers le bon fichier
            if site_enabled_path.is_symlink() and os.readlink(str(site_enabled_path)) == str(site_available_path):
                 self.log_info(f"Site Nginx '{site_config_filename}' déjà activé.", log_levels=log_levels)
                 return True
            else:
                 self.log_warning(f"Un fichier/lien existe déjà pour '{site_config_filename}' dans {enabled_dir}. Tentative de remplacement.", log_levels=log_levels)
                 # Supprimer l'ancien lien/fichier avant de créer le nouveau
                 rm_success, _, rm_stderr = self.run(['rm', '-f', str(site_enabled_path)], check=False, needs_sudo=True)
                 if not rm_success:
                      self.log_error(f"Impossible de supprimer l'ancien lien/fichier '{site_enabled_path}'. Stderr: {rm_stderr}", log_levels=log_levels)
                      return False

        # Créer le lien symbolique
        cmd = ['ln', '-s', str(site_available_path), str(site_enabled_path)]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if success:
            self.log_success(f"Site Nginx '{site_config_filename}' activé.", log_levels=log_levels)
            self.log_info("Un rechargement/redémarrage de Nginx est nécessaire.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de l'activation du site Nginx '{site_config_filename}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def nginx_disable_site(self, site_config_filename: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Désactive un site Nginx en supprimant le lien symbolique."""
        available_dir, enabled_dir = self._get_nginx_sites_dirs()
        if not available_dir or not enabled_dir:
            return False

        site_enabled_path = enabled_dir / site_config_filename
        self.log_info(f"Désactivation du site Nginx: {site_config_filename}", log_levels=log_levels)

        if not site_enabled_path.is_symlink() and not site_enabled_path.exists():
            self.log_info(f"Site Nginx '{site_config_filename}' déjà désactivé ou inexistant.", log_levels=log_levels)
            return True

        # Supprimer le lien/fichier
        cmd = ['rm', '-f', str(site_enabled_path)]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if success:
            self.log_success(f"Site Nginx '{site_config_filename}' désactivé.", log_levels=log_levels)
            self.log_info("Un rechargement/redémarrage de Nginx est nécessaire.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la désactivation du site Nginx '{site_config_filename}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def nginx_reload(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Recharge la configuration Nginx."""
        if not self._nginx_service_name:
            self.log_error("Nom du service Nginx inconnu, impossible de recharger.", log_levels=log_levels)
            return False
        if not self._service_manager:
            self.log_error("Gestionnaire de services non disponible, impossible de recharger Nginx.", log_levels=log_levels)
            return False
        # Vérifier la config avant de recharger
        if not self.nginx_check_config():
            self.log_error("Rechargement annulé en raison d'erreurs de configuration Nginx.", log_levels=log_levels)
            return False
        self.log_info(f"Rechargement du service Nginx ({self._nginx_service_name})", log_levels=log_levels)
        return self._service_manager.reload(self._nginx_service_name)

    def nginx_restart(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Redémarre le service Nginx."""
        if not self._nginx_service_name:
            self.log_error("Nom du service Nginx inconnu, impossible de redémarrer.", log_levels=log_levels)
            return False
        if not self._service_manager:
            self.log_error("Gestionnaire de services non disponible, impossible de redémarrer Nginx.", log_levels=log_levels)
            return False
        # Vérifier la config avant de redémarrer
        if not self.nginx_check_config():
            self.log_error("Redémarrage annulé en raison d'erreurs de configuration Nginx.", log_levels=log_levels)
            return False
        self.log_info(f"Redémarrage du service Nginx ({self._nginx_service_name})", log_levels=log_levels)
        return self._service_manager.restart(self._nginx_service_name)