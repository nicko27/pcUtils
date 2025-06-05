# install/plugins/plugins_utils/services.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour la gestion des services systemd.
Permet de démarrer, arrêter, redémarrer, recharger, activer, désactiver
et vérifier l'état des services du système.
"""

# Import de la classe de base et des types
from plugins_utils.plugins_utils_base import PluginsUtilsBase
import json # Pour parser la sortie de systemctl show
import time # Pour les délais potentiels
from typing import Union, Optional, List, Dict, Any, Tuple

class ServiceCommands(PluginsUtilsBase):
    """
    Classe pour gérer les services systemd via systemctl.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """
        Initialise le gestionnaire de services systemd.

        Args:
            logger: Instance de PluginLogger (optionnel).
            target_ip: IP cible pour les logs (optionnel).
        """
        super().__init__(logger, target_ip)
        self._systemctl_path = self._find_systemctl()

    def _find_systemctl(self, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Trouve le chemin de l'exécutable systemctl."""
        # Vérifier les emplacements courants
        for path in ['/bin/systemctl', '/usr/bin/systemctl', '/sbin/systemctl', '/usr/sbin/systemctl']:
            success, _, _ = self.run(['test', '-x', path], check=False, no_output=True, error_as_warning=True)
            if success:
                self.log_debug(f"Exécutable systemctl trouvé: {path}", log_levels=log_levels)
                return path
        # Si non trouvé, essayer 'which'
        success_which, path_which, _ = self.run(['which', 'systemctl'], check=False, no_output=True, error_as_warning=True)
        if success_which and path_which.strip():
             path_str = path_which.strip()
             self.log_debug(f"Exécutable systemctl trouvé via which: {path_str}", log_levels=log_levels)
             return path_str

        # Retourner 'systemctl' quand même, peut être dans le PATH mais non trouvé par les vérifications
        return 'systemctl'

    def _run_systemctl(self, args: List[str], check: bool = False, needs_sudo: bool = True, log_levels: Optional[Dict[str, str]] = None, **kwargs) -> Tuple[bool, str, str]:
        """Exécute une commande systemctl avec gestion sudo."""
        if not self._systemctl_path:
            # Tenter avec 'systemctl' au cas où il serait dans le PATH mais non trouvé par _find_systemctl
            cmd = ['systemctl'] + args
            self.log_warning("Chemin systemctl non trouvé, tentative d'exécution directe.", log_levels=log_levels)
        else:
             cmd = [self._systemctl_path] + args
        # La plupart des commandes systemctl nécessitent root
        return self.run(cmd, check=check, needs_sudo=needs_sudo, **kwargs)

    def start(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Démarre un service systemd via `systemctl start`.

        Args:
            service_name: Nom du service (ex: 'sshd', 'apache2.service').

        Returns:
            bool: True si le démarrage a réussi (ou si le service tournait déjà).
        """
        self.log_info(f"Démarrage du service: {service_name}", log_levels=log_levels)
        success, stdout, stderr = self._run_systemctl(['start', service_name], check=False)
        if success:
            self.log_info(f"Service {service_name} démarré.", log_levels=log_levels)
            return True
        else:
            # Vérifier si l'erreur est due au fait qu'il tournait déjà
            # Les messages peuvent varier selon la version de systemd et la locale
            if "already running" in stderr.lower() or "job is running" in stderr.lower() or "service is already active" in stderr.lower():
                 self.log_info(f"Le service {service_name} était déjà en cours d'exécution.", log_levels=log_levels)
                 # Vérifier l'état actif pour être sûr
                 return self.is_active(service_name)
            self.log_error(f"Échec du démarrage du service {service_name}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def stop(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Arrête un service systemd via `systemctl stop`.

        Args:
            service_name: Nom du service.

        Returns:
            bool: True si l'arrêt a réussi (ou si le service était déjà arrêté).
        """
        self.log_info(f"Arrêt du service: {service_name}", log_levels=log_levels)
        success, stdout, stderr = self._run_systemctl(['stop', service_name], check=False)
        if success:
            self.log_info(f"Service {service_name} arrêté.", log_levels=log_levels)
            return True
        else:
            # Vérifier si l'erreur est due au fait qu'il était déjà arrêté ou non chargé
            if "not running" in stderr.lower() or "not loaded" in stderr.lower() or "inactive" in stderr.lower():
                 self.log_info(f"Le service {service_name} était déjà arrêté ou non chargé.", log_levels=log_levels)
                 # Vérifier l'état inactif
                 return not self.is_active(service_name)
            self.log_error(f"Échec de l'arrêt du service {service_name}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def restart(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Redémarre un service systemd via `systemctl restart`.

        Args:
            service_name: Nom du service.

        Returns:
            bool: True si le redémarrage a réussi.
        """
        self.log_info(f"Redémarrage du service: {service_name}", log_levels=log_levels)
        # restart retourne généralement 0 même si le service n'existait pas,
        # mais peut échouer si la configuration est mauvaise.
        success, stdout, stderr = self._run_systemctl(['restart', service_name], check=False)
        if success:
            # Attendre un court instant pour laisser le service démarrer et vérifier son état
            time.sleep(1)
            if self.is_active(service_name):
                 self.log_info(f"Service {service_name} redémarré avec succès.", log_levels=log_levels)
                 return True
            else:
                 self.log_error(f"Service {service_name} redémarré (code 0) mais n'est pas actif. Vérifier les logs du service.", log_levels=log_levels)
                 self.log_error(f"Stderr (restart): {stderr}", log_levels=log_levels) # Afficher stderr même si code 0
                 return False
        else:
            self.log_error(f"Échec du redémarrage du service {service_name}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def reload(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Recharge la configuration d'un service sans l'arrêter via `systemctl reload`.
        Si 'reload' échoue, tente `systemctl reload-or-restart`.

        Args:
            service_name: Nom du service.

        Returns:
            bool: True si le rechargement (ou rechargement/redémarrage) a réussi.
        """
        self.log_info(f"Rechargement de la configuration du service: {service_name}", log_levels=log_levels)
        success, stdout, stderr = self._run_systemctl(['reload', service_name], check=False)
        if success:
            self.log_info(f"Configuration du service {service_name} rechargée.", log_levels=log_levels)
            return True
        else:
            # Si reload échoue (ex: service ne supporte pas reload), essayer reload-or-restart
            self.log_warning(f"Échec du rechargement simple de {service_name}, tentative avec 'reload-or-restart'. Stderr: {stderr}", log_levels=log_levels)
            success_ror, _, stderr_ror = self._run_systemctl(['reload-or-restart', service_name], check=False)
            if success_ror:
                self.log_info(f"Service {service_name} rechargé ou redémarré avec succès.", log_levels=log_levels)
                return True
            else:
                # Logguer l'erreur initiale de reload et l'erreur de reload-or-restart
                self.log_error(f"Échec initial de reload pour {service_name}. Stderr: {stderr}", log_levels=log_levels)
                self.log_error(f"Échec de reload-or-restart pour {service_name}. Stderr: {stderr_ror}", log_levels=log_levels)
                return False

    def enable(self, service_name: str, now: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Active un service systemd au démarrage via `systemctl enable`.

        Args:
            service_name: Nom du service.
            now: Si True, démarre aussi le service immédiatement (`--now`). Défaut: False.

        Returns:
            bool: True si l'activation a réussi (ou si déjà activé).
                  Si `now=True`, inclut le succès du démarrage.
        """
        action = "Activation et démarrage" if now else "Activation"
        self.log_info(f"{action} du service au démarrage: {service_name}", log_levels=log_levels)
        cmd = ['enable']
        if now:
            cmd.append('--now')
        cmd.append(service_name)
        success, stdout, stderr = self._run_systemctl(cmd, check=False)

        # systemctl enable peut créer des liens symboliques et afficher des infos, même si déjà activé
        # Le code retour 0 indique le succès de l'opération demandée (ou que c'était déjà fait)
        if stdout: self.log_info(f"Sortie de systemctl enable:\n{stdout}", log_levels=log_levels)

        if success:
            # Vérifier si déjà activé (le code retour est 0 dans ce cas aussi)
            if "already enabled" in stderr.lower():
                 self.log_info(f"Le service {service_name} était déjà activé.", log_levels=log_levels)
                 # Si --now était demandé, vérifier qu'il est actif
                 if now: return self.is_active(service_name)
                 return True
            self.log_info(f"Service {service_name} activé{' et démarré' if now else ''} avec succès.", log_levels=log_levels)
            return True
        else:
             self.log_error(f"Échec de l'{action.lower()} du service {service_name}. Stderr: {stderr}", log_levels=log_levels)
             return False

    def disable(self, service_name: str, now: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Désactive un service systemd au démarrage via `systemctl disable`.

        Args:
            service_name: Nom du service.
            now: Si True, arrête aussi le service immédiatement (`--now`). Défaut: False.

        Returns:
            bool: True si la désactivation a réussi (ou si déjà désactivé).
                  Si `now=True`, inclut le succès de l'arrêt.
        """
        action = "Désactivation et arrêt" if now else "Désactivation"
        self.log_info(f"{action} du service au démarrage: {service_name}", log_levels=log_levels)
        cmd = ['disable']
        if now:
            cmd.append('--now')
        cmd.append(service_name)
        success, stdout, stderr = self._run_systemctl(cmd, check=False)

        if stdout: self.log_info(f"Sortie de systemctl disable:\n{stdout}", log_levels=log_levels)

        if success:
            # Vérifier si déjà désactivé (code retour 0)
            if "removed" in stdout.lower(): # systemd > v2?? utilise stdout pour confirmer la suppression du lien
                 self.log_info(f"Service {service_name} désactivé{' et arrêté' if now else ''} avec succès (lien supprimé).", log_levels=log_levels)
                 return True
            elif "does not exist" in stderr.lower(): # Service non trouvé
                 self.log_warning(f"Le service {service_name} n'existe pas.", log_levels=log_levels)
                 return True # Considérer comme succès car état désiré atteint
            else:
                 # Peut retourner 0 même si déjà désactivé sans message clair
                 self.log_info(f"Service {service_name} désactivé{' et arrêté' if now else ''} (ou était déjà désactivé).", log_levels=log_levels)
                 return True
        else:
             self.log_error(f"Échec de la {action.lower()} du service {service_name}. Stderr: {stderr}", log_levels=log_levels)
             return False

    def is_active(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un service est actuellement actif (running) via `systemctl is-active --quiet`.

        Args:
            service_name: Nom du service.

        Returns:
            bool: True si le service est actif (code retour 0).
        """
        # --quiet supprime la sortie texte, on se base sur le code retour
        success, _, _ = self._run_systemctl(['is-active', '--quiet', service_name], check=False, no_output=True)
        is_act = success # Le code de retour 0 indique 'active'
        self.log_debug(f"Service {service_name} est actif: {is_act}", log_levels=log_levels)
        return is_act

    def is_enabled(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un service est activé au démarrage via `systemctl is-enabled --quiet`.

        Args:
            service_name: Nom du service.

        Returns:
            bool: True si le service est activé (code retour 0).
                  False s'il est désactivé, statique, masqué, ou si erreur.
        """
        # --quiet supprime la sortie texte ('enabled', 'disabled', etc.)
        # Le code retour 0 signifie 'enabled', 1 signifie autre chose ('disabled', 'static', 'masked', etc.)
        success, _, stderr = self._run_systemctl(['is-enabled', '--quiet', service_name], check=False, no_output=True, error_as_warning=True)
        is_enb = success # Le code de retour 0 indique 'enabled'
        self.log_debug(f"Service {service_name} est activé au démarrage: {is_enb}", log_levels=log_levels)
        # Logguer l'erreur si ce n'est pas juste "disabled" ou "static"
        if not success and stderr and not re.search(r'(disabled|static|masked)', stderr, re.IGNORECASE):
             self.log_warning(f"Erreur lors de la vérification de l'état enabled pour {service_name}: {stderr.strip()}", log_levels=log_levels)
        return is_enb

    def get_status(self, service_name: str, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Récupère le statut détaillé d'un service via `systemctl show --output=json --all`.

        Args:
            service_name: Nom du service.

        Returns:
            Dictionnaire contenant les informations du statut (clés normalisées comme
            'name', 'description', 'load_state', 'active_state', 'sub_state', 'enabled',
            'pid', 'memory', 'tasks', etc.), ou un dict vide si erreur.
        """
        self.log_debug(f"Récupération du statut détaillé du service: {service_name}", log_levels=log_levels)
        # Utiliser --output=json pour un parsing facile
        # --all pour inclure toutes les propriétés
        cmd = ['show', service_name, '--output=json', '--all']
        # Pas besoin de sudo pour 'show' généralement
        success, stdout, stderr = self._run_systemctl(cmd, check=False, no_output=True, needs_sudo=False)

        if not success:
            # Essayer avec 'status' si 'show' échoue (peut donner plus d'infos sur l'erreur)
            status_success, status_stdout, status_stderr = self._run_systemctl(['status', service_name, '--no-pager', '-n', '0'], check=False, no_output=True, needs_sudo=False)
            self.log_error(f"Impossible d'obtenir le statut détaillé de {service_name}.", log_levels=log_levels)
            # Afficher les deux erreurs si disponibles
            if stderr: self.log_error(f"Stderr (show): {stderr}", log_levels=log_levels)
            if status_stderr: self.log_error(f"Stderr (status): {status_stderr}", log_levels=log_levels)
            return {} # Retourner dict vide en cas d'erreur

        try:
            # La sortie de 'systemctl show --output=json' est un JSON *par ligne*
            # Il faut parser chaque ligne et les combiner
            status_data = {}
            for line in stdout.splitlines():
                 if line.strip(): # Ignorer les lignes vides
                      try:
                           # Chaque ligne est un dict JSON, on les fusionne
                           status_data.update(json.loads(line))
                      except json.JSONDecodeError:
                           self.log_warning(f"Impossible de parser la ligne JSON du statut: {line}", log_levels=log_levels)
                           continue # Ignorer la ligne mal formée

            # Simplifier les noms de clés et extraire les infos utiles
            # Convertir les valeurs numériques si possible
            def parse_value(v, log_levels: Optional[Dict[str, str]] = None):
                if isinstance(v, str) and v.isdigit(): return int(v)
                if isinstance(v, str) and v.lower() == 'yes': return True
                if isinstance(v, str) and v.lower() == 'no': return False
                return v

            info = {
                'name': status_data.get('Id'),
                'description': status_data.get('Description'),
                'load_state': status_data.get('LoadState'), # loaded, not-found, masked, error
                'active_state': status_data.get('ActiveState'), # active, inactive, activating, deactivating, failed
                'sub_state': status_data.get('SubState'), # running, dead, exited, mounted, plugged, etc.
                'enabled': status_data.get('UnitFileState') == 'enabled', # Comparaison directe
                'unit_file_state': status_data.get('UnitFileState'), # Garder l'état brut (enabled, disabled, static, masked)
                'pid': parse_value(status_data.get('MainPID')),
                'memory_bytes': parse_value(status_data.get('MemoryCurrent')), # En octets si ControlGroup v2
                'tasks_current': parse_value(status_data.get('TasksCurrent')),
                'state_change_timestamp': status_data.get('StateChangeTimestamp'),
                'active_enter_timestamp': status_data.get('ActiveEnterTimestamp'),
                'active_exit_timestamp': status_data.get('ActiveExitTimestamp'),
                'inactive_enter_timestamp': status_data.get('InactiveEnterTimestamp'),
                'inactive_exit_timestamp': status_data.get('InactiveExitTimestamp'),
                # Ajouter d'autres champs pertinents si nécessaire
                'exec_start': status_data.get('ExecStart'),
                'exec_reload': status_data.get('ExecReload'),
                'exec_stop': status_data.get('ExecStop'),
            }
            # Filtrer les valeurs None pour un résultat plus propre
            info = {k: v for k, v in info.items() if v is not None}

            self.log_debug(f"Statut détaillé pour {service_name}: {info}", log_levels=log_levels)
            return info

        except ImportError:
             self.log_error("Le module 'json' est nécessaire pour parser la sortie de systemctl show.", log_levels=log_levels)
             return {}
        except Exception as e:
             self.log_error(f"Erreur lors du parsing du statut détaillé de {service_name}: {e}", exc_info=True, log_levels=log_levels)
             self.log_debug(f"Sortie systemctl show brute:\n{stdout}", log_levels=log_levels)
             return {}
