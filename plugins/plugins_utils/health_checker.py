# install/plugins/plugins_utils/health_checker.py
#!/usr/bin/env python3
"""
Module utilitaire pour effectuer des vérifications de l'état général du système.
Vérifie l'espace disque, la mémoire, la charge CPU, la connectivité, les services critiques, etc.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import time
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

# Patterns courants d'erreurs à rechercher dans dmesg
COMMON_ERROR_PATTERNS = [
    r'error',
    r'fail',
    r'warning',
    r'critical',
    r'panic',
    r'oops',
    r'segfault',
    r'killed',
    r'timeout',
    r'corruption',
    r'I/O error',
    r'hardware error',
    r'kernel BUG',
    r'call trace'
]

# Importer d'autres utilitaires nécessaires
try:
    from .storage import StorageCommands
    from .network import NetworkCommands
    from .services import ServiceCommands
    UTILS_AVAILABLE = True
except ImportError:
    UTILS_AVAILABLE = False
    # Définir des classes factices si les imports échouent
    class StorageCommands: pass
    class NetworkCommands: pass
    class ServiceCommands: pass

class HealthChecker(PluginsUtilsBase):
    """
    Classe pour effectuer des vérifications de santé système.
    Hérite de PluginUtilsBase et utilise d'autres commandes utilitaires.
    """

    # Seuils par défaut
    DEFAULT_DISK_THRESHOLD_PERCENT = 90
    DEFAULT_MEMORY_THRESHOLD_PERCENT = 90
    DEFAULT_LOAD_THRESHOLD_FACTOR = 2.0 # Ex: charge > 2.0 * nb_coeurs

    def __init__(self, logger=None, target_ip=None):
        """Initialise le vérificateur de santé."""
        super().__init__(logger, target_ip)
        if not UTILS_AVAILABLE:
            self.log_error("Certains modules utilitaires (Storage, Network, Services) sont manquants. "
                           "Les vérifications de santé seront limitées.")
            self._storage = None
            self._network = None
            self._services = None
        else:
            # Instancier les autres utilitaires
            self._storage = StorageCommands(logger, target_ip)
            self._network = NetworkCommands(logger, target_ip)
            self._services = ServiceCommands(logger, target_ip)
        self._cpu_cores = self._get_cpu_cores()

    def _get_cpu_cores(self) -> int:
        """Récupère le nombre de cœurs CPU."""
        try:
            # Méthode 1: /proc/cpuinfo
            success, stdout, _ = self.run(['grep', '-c', '^processor', '/proc/cpuinfo'], check=False, no_output=True)
            if success and stdout.strip().isdigit():
                cores = int(stdout.strip())
                self.log_debug(f"Nombre de coeurs CPU trouvés (cpuinfo): {cores}")
                return cores if cores > 0 else 1
            # Méthode 2: nproc
            success, stdout, _ = self.run(['nproc'], check=False, no_output=True)
            if success and stdout.strip().isdigit():
                cores = int(stdout.strip())
                self.log_debug(f"Nombre de coeurs CPU trouvés (nproc): {cores}")
                return cores if cores > 0 else 1
        except Exception as e:
            self.log_warning(f"Impossible de déterminer le nombre de coeurs CPU: {e}")
        return 1 # Retourner 1 par défaut

    def check_disk_space(self, threshold_percent: int = DEFAULT_DISK_THRESHOLD_PERCENT,
                        paths: Optional[List[str]] = None,
                        log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Vérifie l'espace disque utilisé sur les systèmes de fichiers montés.

        Args:
            threshold_percent: Seuil d'utilisation (en %) au-delà duquel une alerte est générée.
            paths: Liste de points de montage spécifiques à vérifier (None pour tous).
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Liste de dictionnaires pour les FS dépassant le seuil. Chaque dict contient
            'filesystem', 'size', 'used', 'avail', 'use_pct', 'mounted_on'.
        """
        if not self._storage: return [{"error": "StorageCommands non disponible"}]
        self.log_info(f"Vérification de l'utilisation disque (seuil: >{threshold_percent}%)")
        alerts = []
        try:
            usage_data = self._storage.get_disk_usage(path=paths[0] if paths and len(paths)==1 else None)
            if not usage_data:
                 self.log_warning("Aucune donnée d'utilisation disque obtenue.")
                 return alerts

            # Filtrer les données pour ne garder que les chemins demandés si spécifié
            if paths:
                 target_paths_set = set(paths)
                 filtered_data = [u for u in usage_data if u.get('MountedOn') in target_paths_set]
                 usage_data = filtered_data

            for fs_usage in usage_data:
                use_pct_str = fs_usage.get('UsePct', '0%').replace('%', '')
                mounted_on = fs_usage.get('MountedOn', 'N/A')
                filesystem = fs_usage.get('Filesystem', 'N/A')

                # Ignorer les systèmes de fichiers temporaires ou spéciaux
                if filesystem.startswith(('tmpfs', 'devtmpfs', 'squashfs', '/dev/loop')) or mounted_on.startswith('/run'):
                    continue

                try:
                    use_pct = int(use_pct_str)
                    if use_pct > threshold_percent:
                        alert_info = {
                            'filesystem': filesystem,
                            'size': fs_usage.get('Size', 'N/A'),
                            'used': fs_usage.get('Used', 'N/A'),
                            'avail': fs_usage.get('Avail', 'N/A'),
                            'use_pct': use_pct,
                            'mounted_on': mounted_on
                        }
                        alerts.append(alert_info)
                        self.log_warning(f"Utilisation disque élevée sur {mounted_on} ({filesystem}): {use_pct}%")
                except (ValueError, TypeError):
                     self.log_warning(f"Impossible de parser le pourcentage d'utilisation pour {mounted_on}: '{use_pct_str}'")

            if not alerts:
                 self.log_info("Utilisation disque OK.")

        except Exception as e:
            self.log_error(f"Erreur lors de la vérification de l'espace disque: {e}", exc_info=True)
            alerts.append({"error": f"Erreur lors de la vérification: {e}"})

        return alerts

    def check_memory_usage(self, threshold_percent: int = DEFAULT_MEMORY_THRESHOLD_PERCENT,
                          log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Vérifie l'utilisation de la mémoire RAM et Swap.

        Args:
            threshold_percent: Seuil d'utilisation (en %) au-delà duquel une alerte est générée.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Dictionnaire avec l'état ('OK', 'WARNING') et les détails, ou None si erreur.
        """
        self.log_info(f"Vérification de l'utilisation mémoire (seuil: >{threshold_percent}%)")
        mem_info = {'status': 'ERROR', 'message': 'Impossible de lire /proc/meminfo'}
        try:
            # Lire /proc/meminfo
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()

            mem_data = {}
            for line in lines:
                parts = line.split(':')
                if len(parts) == 2:
                    key = parts[0].strip()
                    value_str = parts[1].strip().split()[0] # Prendre la valeur numérique
                    if value_str.isdigit():
                        mem_data[key] = int(value_str) # Stocker en Ko

            # Calculer l'utilisation RAM
            total_ram = mem_data.get('MemTotal')
            free_ram = mem_data.get('MemFree')
            buffers = mem_data.get('Buffers', 0)
            cached = mem_data.get('Cached', 0)
            sreclaimable = mem_data.get('SReclaimable', 0) # Cache réutilisable (noyaux > 2.6.19)

            if total_ram is None or free_ram is None:
                 raise ValueError("MemTotal ou MemFree non trouvé dans /proc/meminfo")

            # Mémoire réellement disponible (approche Linux moderne)
            # MemAvailable est la meilleure métrique si disponible
            available_ram = mem_data.get('MemAvailable')
            if available_ram is None:
                 # Estimation fallback: Free + Buffers + Cached (partie réutilisable)
                 available_ram = free_ram + buffers + cached + sreclaimable
                 self.log_debug("MemAvailable non trouvé, estimation de la mémoire disponible.")
            else:
                 self.log_debug("Utilisation de MemAvailable pour la mémoire disponible.")

            used_ram = total_ram - available_ram
            used_ram_pct = int((used_ram / total_ram) * 100) if total_ram > 0 else 0

            mem_info['ram_total_kb'] = total_ram
            mem_info['ram_available_kb'] = available_ram
            mem_info['ram_used_kb'] = used_ram
            mem_info['ram_used_pct'] = used_ram_pct

            # Calculer l'utilisation Swap
            total_swap = mem_data.get('SwapTotal')
            free_swap = mem_data.get('SwapFree')
            used_swap = -1
            used_swap_pct = 0

            if total_swap is not None and free_swap is not None:
                 if total_swap > 0:
                      used_swap = total_swap - free_swap
                      used_swap_pct = int((used_swap / total_swap) * 100)
                 mem_info['swap_total_kb'] = total_swap
                 mem_info['swap_free_kb'] = free_swap
                 mem_info['swap_used_kb'] = used_swap
                 mem_info['swap_used_pct'] = used_swap_pct

            # Déterminer le statut global
            if used_ram_pct > threshold_percent or (total_swap is not None and total_swap > 0 and used_swap_pct > threshold_percent):
                 mem_info['status'] = 'WARNING'
                 mem_info['message'] = f"Utilisation mémoire élevée: RAM={used_ram_pct}%, Swap={used_swap_pct}%"
                 self.log_warning(mem_info['message'])
            else:
                 mem_info['status'] = 'OK'
                 mem_info['message'] = f"Utilisation mémoire OK: RAM={used_ram_pct}%, Swap={used_swap_pct}%"
                 self.log_info(mem_info['message'])

        except FileNotFoundError:
             self.log_error("Fichier /proc/meminfo introuvable.")
             mem_info['message'] = "/proc/meminfo introuvable"
        except Exception as e:
            self.log_error(f"Erreur lors de la vérification de la mémoire: {e}", exc_info=True)
            mem_info['message'] = f"Erreur: {e}"

        return mem_info

    def check_cpu_load(self, threshold_factor: float = DEFAULT_LOAD_THRESHOLD_FACTOR,
                      log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Vérifie la charge moyenne du CPU (load average).

        Args:
            threshold_factor: Facteur multiplicateur pour le seuil d'alerte.
                              Une alerte est générée si loadavg (1m, 5m ou 15m)
                              dépasse threshold_factor * nombre_de_coeurs.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Dictionnaire avec l'état ('OK', 'WARNING') et les valeurs, ou None si erreur.
        """
        self.log_info(f"Vérification de la charge CPU (seuil: > {threshold_factor} * nb_coeurs)")
        load_info = {'status': 'ERROR', 'message': 'Impossible de lire /proc/loadavg'}
        try:
            with open('/proc/loadavg', 'r') as f:
                load_str = f.read()

            parts = load_str.split()
            if len(parts) < 3:
                 raise ValueError(f"Format /proc/loadavg inattendu: {load_str}")

            load_1m, load_5m, load_15m = map(float, parts[:3])
            load_info['load_1m'] = load_1m
            load_info['load_5m'] = load_5m
            load_info['load_15m'] = load_15m
            load_info['cpu_cores'] = self._cpu_cores

            # Calculer le seuil basé sur le nombre de coeurs
            threshold = threshold_factor * self._cpu_cores
            load_info['threshold'] = threshold

            # Vérifier si un des load average dépasse le seuil
            high_load = False
            if load_1m > threshold: high_load = True; self.log_warning(f"Charge CPU (1m) élevée: {load_1m:.2f} (seuil: {threshold:.2f})")
            if load_5m > threshold: high_load = True; self.log_warning(f"Charge CPU (5m) élevée: {load_5m:.2f} (seuil: {threshold:.2f})")
            if load_15m > threshold: high_load = True; self.log_warning(f"Charge CPU (15m) élevée: {load_15m:.2f} (seuil: {threshold:.2f})")

            if high_load:
                 load_info['status'] = 'WARNING'
                 load_info['message'] = f"Charge CPU élevée détectée (1m={load_1m:.2f}, 5m={load_5m:.2f}, 15m={load_15m:.2f}, seuil={threshold:.2f})"
            else:
                 load_info['status'] = 'OK'
                 load_info['message'] = f"Charge CPU OK (1m={load_1m:.2f}, 5m={load_5m:.2f}, 15m={load_15m:.2f})"
                 self.log_info(load_info['message'])

        except FileNotFoundError:
             self.log_error("Fichier /proc/loadavg introuvable.")
             load_info['message'] = "/proc/loadavg introuvable"
        except Exception as e:
            self.log_error(f"Erreur lors de la vérification de la charge CPU: {e}", exc_info=True)
            load_info['message'] = f"Erreur: {e}"

        return load_info

    def check_network_connectivity(self, hosts_to_ping: Optional[List[str]] = None,
                                  log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie la connectivité réseau de base en pinguant des hôtes essentiels.

        Args:
            hosts_to_ping: Liste d'hôtes/IPs à pinguer. Si None, essaie de pinguer
                           la passerelle par défaut et un serveur DNS externe (ex: 8.8.8.8).
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si tous les hôtes essentiels répondent.
        """
        if not self._network:
             self.log_error("NetworkCommands non disponible, impossible de vérifier la connectivité.")
             return False

        targets = []
        if hosts_to_ping:
            targets = hosts_to_ping
        else:
            # Ajouter la passerelle par défaut
            gateway = self._network.get_default_gateway()
            if gateway:
                 targets.append(gateway)
            # Ajouter un DNS public
            targets.append("8.8.8.8") # Google DNS comme test externe standard

        if not targets:
             self.log_warning("Aucune cible spécifiée ou trouvée pour le test de connectivité.")
             return False # Ne peut pas tester

        self.log_info(f"Vérification de la connectivité réseau vers: {', '.join(targets)}")
        all_ok = True
        for host in targets:
            if not self._network.ping(host, count=1, timeout=2): # Ping court
                 self.log_warning(f"Échec du ping vers {host}.")
                 all_ok = False

        if all_ok:
             self.log_success("Connectivité réseau de base OK.")
        else:
             self.log_error("Problème de connectivité réseau détecté.")

        return all_ok

    def check_critical_services(self, service_names: List[str],
                               log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si une liste de services système critiques sont actifs.

        Args:
            service_names: Liste des noms de services à vérifier.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si tous les services sont actifs.
        """
        if not self._services:
             self.log_error("ServiceCommands non disponible, impossible de vérifier les services.")
             return False
        if not service_names:
             self.log_warning("Aucun service critique spécifié pour la vérification.")
             return True # Pas d'échec si rien à vérifier

        self.log_info(f"Vérification du statut des services critiques: {', '.join(service_names)}")
        all_ok = True
        for service in service_names:
            if not self._services.is_active(service):
                 self.log_error(f"Service critique '{service}' n'est pas actif !")
                 all_ok = False

        if all_ok:
             self.log_success("Tous les services critiques vérifiés sont actifs.")
        else:
             self.log_error("Un ou plusieurs services critiques ne sont pas actifs.")

        return all_ok

    def check_dmesg_errors(self, patterns: Optional[List[str]] = None, time_since: str = "1 hour ago",
                          log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Recherche les erreurs récentes dans la sortie de dmesg. Nécessite root.

        Args:
            patterns: Liste d'expressions régulières supplémentaires à rechercher (en plus des erreurs/warnings par défaut).
            time_since: Ne chercher que les messages depuis ce moment (ex: '10 min ago', 'yesterday').
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Liste des lignes d'erreur/warning trouvées.
        """
        self.log_info(f"Recherche d'erreurs/warnings dans dmesg (depuis {time_since})")
        # -T pour l'horodatage lisible
        cmd = ['dmesg', '-T']
        # Filtrer par temps
        cmd.extend(['--since', time_since])

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        errors = []
        if not success:
            self.log_error(f"Échec de la lecture de dmesg. Stderr: {stderr}")
            return errors

        # Combiner les patterns par défaut et ceux fournis
        search_patterns = COMMON_ERROR_PATTERNS + (patterns or [])
        # Créer une regex combinée (insensible à la casse)
        regex = re.compile('|'.join(f"({p})" for p in search_patterns), re.IGNORECASE)

        for line in stdout.splitlines():
            if regex.search(line):
                errors.append(line)

        if errors:
             self.log_warning(f"{len(errors)} erreur(s)/warning(s) potentiel(s) trouvé(s) dans dmesg récemment.")
             # Logguer les premières erreurs trouvées
             for err_line in errors[:5]:
                  self.log_warning(f"  - {err_line}")
             if len(errors) > 5: self.log_warning("  - ... et autres.")
        else:
             self.log_info("Aucune erreur/warning récent trouvé dans dmesg.")

        return errors

    def run_all_checks(self,
                       disk_threshold: int = DEFAULT_DISK_THRESHOLD_PERCENT,
                       mem_threshold: int = DEFAULT_MEMORY_THRESHOLD_PERCENT,
                       load_factor: float = DEFAULT_LOAD_THRESHOLD_FACTOR,
                       ping_hosts: Optional[List[str]] = None,
                       critical_services: Optional[List[str]] = None,
                       dmesg_since: str = "1 hour ago",
                       log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Exécute une série de vérifications de santé et retourne un rapport.

        Args:
            disk_threshold: Seuil pour l'alerte d'espace disque.
            mem_threshold: Seuil pour l'alerte mémoire.
            load_factor: Facteur pour l'alerte de charge CPU.
            ping_hosts: Hôtes à pinguer pour la connectivité.
            critical_services: Services dont l'état actif doit être vérifié.
            dmesg_since: Période pour la recherche d'erreurs dmesg.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Dictionnaire contenant les résultats de chaque vérification.
            La clé 'overall_status' indique 'OK' ou 'WARNING'/'ERROR'.
        """
        self.log_info("Exécution des vérifications de santé système...")
        results: Dict[str, Any] = {'checks_performed': []}
        overall_ok = True

        # Disk Space
        disk_alerts = self.check_disk_space(disk_threshold)
        results['disk_space'] = {'status': 'WARNING' if disk_alerts else 'OK', 'alerts': disk_alerts}
        results['checks_performed'].append('disk_space')
        if disk_alerts: overall_ok = False

        # Memory Usage
        mem_info = self.check_memory_usage(mem_threshold)
        results['memory_usage'] = mem_info if mem_info else {'status': 'ERROR', 'message': 'Check failed'}
        results['checks_performed'].append('memory_usage')
        if mem_info and mem_info.get('status') != 'OK': overall_ok = False

        # CPU Load
        load_info = self.check_cpu_load(load_factor)
        results['cpu_load'] = load_info if load_info else {'status': 'ERROR', 'message': 'Check failed'}
        results['checks_performed'].append('cpu_load')
        if load_info and load_info.get('status') != 'OK': overall_ok = False

        # Network Connectivity
        conn_ok = self.check_network_connectivity(ping_hosts)
        results['network_connectivity'] = {'status': 'OK' if conn_ok else 'ERROR'}
        results['checks_performed'].append('network_connectivity')
        if not conn_ok: overall_ok = False

        # Critical Services
        if critical_services:
            services_ok = self.check_critical_services(critical_services)
            results['critical_services'] = {'status': 'OK' if services_ok else 'ERROR', 'services_checked': critical_services}
            results['checks_performed'].append('critical_services')
            if not services_ok: overall_ok = False

        # Dmesg Errors
        dmesg_errors = self.check_dmesg_errors(time_since=dmesg_since)
        results['dmesg_errors'] = {'status': 'WARNING' if dmesg_errors else 'OK', 'errors_found': len(dmesg_errors), 'details': dmesg_errors[:10]} # Limiter les détails
        results['checks_performed'].append('dmesg_errors')
        if dmesg_errors: overall_ok = False # Considérer les erreurs dmesg comme un warning/error global

        # Statut global
        results['overall_status'] = 'OK' if overall_ok else 'WARNING/ERROR'
        self.log_info(f"Vérifications de santé terminées. Statut global: {results['overall_status']}")

        return results
