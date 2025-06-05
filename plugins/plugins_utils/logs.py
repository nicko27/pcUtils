#!/usr/bin/env python3
"""
Module utilitaire pour la gestion et l'analyse des fichiers journaux système.
Combine la gestion de logrotate, journald et l'analyse de contenu/taille.
Utilise logrotate, journalctl, find, du, grep, sort, uniq (via des appels systèmes).
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import time
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple, Generator
import shlex  # Pour sécuriser les commandes shell

# Essayer d'importer ArchiveCommands si disponible
try:
    from .archive import ArchiveCommands
    ARCHIVE_AVAILABLE = True
except ImportError:
    ARCHIVE_AVAILABLE = False

class LogCommands(PluginsUtilsBase):
    """
    Classe pour la gestion et l'analyse des logs système.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    DEFAULT_LOG_DIRS = ["/var/log"]
    COMMON_ERROR_PATTERNS = [
        "error", "failed", "failure", "critical", "exception", "traceback",
        "segfault", "denied", "refused", "timeout", "unable to", "cannot"
    ]

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de logs."""
        super().__init__(logger, target_ip)
        self._archive_manager = ArchiveCommands(logger, target_ip) if ARCHIVE_AVAILABLE else None

    def _read_file_lines(self, file_path: Union[str, Path]) -> Generator[str, None, None]:
        """Générateur pour lire les lignes d'un fichier."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    yield line.strip()
        except FileNotFoundError:
            self.log_warning(f"Fichier non trouvé: {file_path}", log_levels=log_levels)
        except Exception as e:
            self.log_error(f"Erreur lors de la lecture de {file_path}: {e}", log_levels=log_levels)

    def check_logrotate_config(self, service_or_logpath: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Vérifie la configuration logrotate pour un service ou un chemin de log.

        Args:
            service_or_logpath: Nom du service (ex: 'nginx') ou chemin du fichier log
                                (ex: '/var/log/nginx/access.log').

        Returns:
            Dictionnaire contenant les directives trouvées ou None si aucune config trouvée.
        """
        config_file = None
        logrotate_d = "/etc/logrotate.d"
        self.log_info(f"Recherche de la configuration logrotate pour: {service_or_logpath}", log_levels=log_levels)

        # 1. Essayer de trouver par nom de service/fichier dans /etc/logrotate.d
        if os.path.isdir(logrotate_d):
            potential_config = Path(logrotate_d) / service_or_logpath.split('/')[-1] # Utiliser le nom de base
            if potential_config.is_file():
                config_file = potential_config
            else:
                 # Essayer de trouver un fichier contenant le chemin
                 try:
                      # Utiliser grep pour chercher le chemin dans les fichiers de conf
                      cmd_grep = ['grep', '-l', '-F', service_or_logpath, f'{logrotate_d}/'] # -l: liste fichiers, -F: chaîne fixe
                      success_grep, stdout_grep, _ = self.run(cmd_grep, check=False, no_output=True, error_as_warning=True)
                      if success_grep and stdout_grep.strip():
                           # Prendre le premier fichier trouvé
                           config_file = Path(stdout_grep.strip().splitlines()[0])
                 except Exception as e_grep:
                      self.log_warning(f"Erreur lors de la recherche du fichier logrotate: {e_grep}", log_levels=log_levels)

        if not config_file or not config_file.is_file():
            self.log_warning(f"Aucun fichier de configuration logrotate trouvé explicitement pour '{service_or_logpath}'. "
                             "La rotation peut être gérée par /etc/logrotate.conf.", log_levels=log_levels)
            # On pourrait parser /etc/logrotate.conf mais c'est plus complexe
            return None

        self.log_info(f"Fichier de configuration logrotate trouvé: {config_file}", log_levels=log_levels)

        # 2. Parser le fichier de configuration (simpliste)
        config_data: Dict[str, Any] = {'config_file': str(config_file), 'directives': {}}
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Extraire les directives globales ou spécifiques au logpath
                # Regex simple pour directives communes (peut être améliorée)
                pattern = re.compile(r'^\s*(\w+)\s*(.*)')
                # Chercher le bloc spécifique s'il existe
                log_block_match = re.search(r'^\s*' + re.escape(service_or_logpath) + r'\s*{([^}]*)}', content, re.MULTILINE | re.DOTALL)
                target_content = log_block_match.group(1) if log_block_match else content

                for line in target_content.splitlines():
                    match = pattern.match(line)
                    if match:
                        key = match.group(1).lower()
                        value = match.group(2).strip()
                        config_data['directives'][key] = value if value else True # Ex: 'compress' a une valeur True implicite

            self.log_debug(f"Directives logrotate trouvées: {config_data['directives']}", log_levels=log_levels)
            return config_data
        except Exception as e:
            self.log_error(f"Erreur lors du parsing de {config_file}: {e}", log_levels=log_levels)
            return None

    def force_logrotate(self, config_file: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Force l'exécution de logrotate. Nécessite root.

        Args:
            config_file: Chemin vers un fichier de configuration logrotate spécifique (optionnel).
                         Si None, utilise la configuration système globale.

        Returns:
            bool: True si succès.
        """
        action = f"fichier {config_file}" if config_file else "configuration globale"
        self.log_info(f"Forçage de l'exécution de logrotate pour {action}", log_levels=log_levels)
        cmd = ['logrotate', '-f'] # -f pour forcer
        if config_file:
            if not os.path.exists(config_file):
                 self.log_error(f"Fichier de configuration logrotate introuvable: {config_file}", log_levels=log_levels)
                 return False
            cmd.append(config_file)
        else:
             # Forcer pour la configuration système (/etc/logrotate.conf)
             cmd.append('/etc/logrotate.conf')

        # logrotate -f nécessite root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if stdout: self.log_info(f"Sortie logrotate:\n{stdout}", log_levels=log_levels) # logrotate peut être verbeux

        if success:
            self.log_success(f"Exécution forcée de logrotate réussie pour {action}.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de l'exécution forcée de logrotate. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Gestion des Fichiers Logs ---

    def list_log_files(self,
                       directories: Optional[List[str]] = None,
                       min_size_mb: Optional[float] = None,
                       older_than_days: Optional[int] = None,
pattern: str = "*.log*", log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Liste les fichiers journaux selon des critères de taille et d'âge (incluant les sous-dossiers).

        Args:
            directories: Liste de répertoires à scanner (défaut: ['/var/log']).
            min_size_mb: Taille minimale en Mo pour lister un fichier.
            older_than_days: Lister seulement les fichiers plus vieux que N jours (basé sur mtime).
            pattern: Motif de nom de fichier (glob style, ex: "*.log", "syslog*").

        Returns:
            Liste des chemins complets des fichiers trouvés.
        """
        dirs_to_scan = directories or self.DEFAULT_LOG_DIRS
        found_files = []
        criteria_log = []
        self.log_info(f"Recherche de fichiers logs dans {', '.join(dirs_to_scan)} (et leurs sous-dossiers)", log_levels=log_levels)
        if pattern != "*.log*": criteria_log.append(f"pattern='{pattern}'")
        if min_size_mb is not None: criteria_log.append(f"taille >= {min_size_mb} Mo")
        if older_than_days is not None: criteria_log.append(f"plus vieux que {older_than_days} jours")
        if criteria_log: self.log_info(f"  Critères: {', '.join(criteria_log)}", log_levels=log_levels)

        for log_dir in dirs_to_scan:
            log_path = Path(log_dir)
            if log_path.is_dir():
                for item in log_path.rglob(pattern): # Use rglob to include subdirectories
                    if item.is_file():
                        include = True
                        if min_size_mb is not None and item.stat().st_size < min_size_mb * 1024 * 1024:
                            include = False
                        if older_than_days is not None:
                            cutoff_timestamp = time.time() - (older_than_days * 24 * 3600)
                            if item.stat().st_mtime >= cutoff_timestamp:
                                include = False
                        if include:
                            found_files.append(str(item.resolve()))
            else:
                self.log_warning(f"Répertoire non trouvé: {log_path}", log_levels=log_levels)

        self.log_info(f"{len(found_files)} fichier(s) log(s) trouvé(s) correspondant aux critères.", log_levels=log_levels)
        return found_files

    def archive_logs(self, log_files: List[str], output_archive: Union[str, Path], compression: str = 'gz', log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Crée une archive contenant les fichiers journaux spécifiés.

        Args:
            log_files: Liste des chemins complets des fichiers logs à archiver.
            output_archive: Chemin du fichier archive à créer (ex: /tmp/logs.tar.gz).
            compression: Type de compression ('gz', 'bz2', 'xz', 'zst').

        Returns:
            bool: True si l'archivage a réussi.
        """
        if not log_files:
            self.log_warning("Aucun fichier log spécifié pour l'archivage.", log_levels=log_levels)
            return False
        if not self._archive_manager:
            self.log_error("Le module ArchiveCommands n'est pas disponible pour créer l'archive.", log_levels=log_levels)
            # Fallback possible avec tar directement?
            if 'tar' not in self._cmd_paths:
                 self.log_error("Commande 'tar' non trouvée, impossible d'archiver.", log_levels=log_levels)
                 return False
            # Utiliser tar directement si ArchiveCommands n'est pas là
            self.log_warning("Utilisation de la commande 'tar' directe car ArchiveCommands n'est pas disponible.", log_levels=log_levels)
            output_path = Path(output_archive)
            cmd = ['tar']
            comp_map = {'gz': '-z', 'bz2': '-j', 'xz': '-J', 'zst': '--zstd'}
            comp_flag = comp_map.get(compression)
            if not comp_flag:
                 self.log_error(f"Type de compression tar non supporté: {compression}", log_levels=log_levels)
                 return False
            # c=create, f=file + compression flag
            cmd.extend([f'-c{comp_flag[1]}f' if comp_flag.startswith('-') else f'-cf {comp_flag}', str(output_path)])
            cmd.extend(log_files)
            # Archiver nécessite potentiellement root pour lire les logs
            success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
            if success:
                 self.log_success(f"Logs archivés avec succès dans {output_path} (via tar).", log_levels=log_levels)
                 return True
            else:
                 self.log_error(f"Échec de l'archivage des logs via tar. Stderr: {stderr}", log_levels=log_levels)
                 return False
        else:
            # Utiliser ArchiveCommands
            return self._archive_manager.create_tar(output_archive, log_files, compression=compression, needs_sudo=True)

    def purge_old_logs(self,
                       directories: Optional[List[str]] = None,
                       older_than_days: int = 30,
                       pattern: str = "*.log*",
dry_run: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime les fichiers journaux plus vieux qu'un certain nombre de jours (incluant les sous-dossiers).
        ATTENTION: Opération destructive ! Utiliser dry_run=False avec prudence.

        Args:
            directories: Liste de répertoires à scanner (défaut: ['/var/log']).
            older_than_days: Supprimer les fichiers plus vieux que N jours (mtime).
            pattern: Motif de nom de fichier à cibler.
            dry_run: Si True (défaut), simule seulement la suppression. Si False, supprime réellement.

        Returns:
            bool: True si l'opération (ou la simulation) a réussi.
        """
        dirs_to_scan = directories or self.DEFAULT_LOG_DIRS
        action = "Simulation de la suppression" if dry_run else "Suppression"
        self.log_warning(f"{action} des logs plus vieux que {older_than_days} jours dans {', '.join(dirs_to_scan)} (et leurs sous-dossiers, pattern: '{pattern}')", log_levels=log_levels)
        if not dry_run:
            self.log_warning("!!! OPÉRATION DESTRUCTIVE ACTIVÉE !!!", log_levels=log_levels)

        files_to_delete = self.list_log_files(directories=dirs_to_scan, older_than_days=older_than_days, pattern=pattern)
        total_size_to_delete = sum(Path(f).stat().st_size for f in files_to_delete if Path(f).is_file())

        if dry_run:
            if files_to_delete:
                size_mb = total_size_to_delete / (1024 * 1024)
                self.log_info(f"Simulation: {len(files_to_delete)} fichier(s) seraient supprimé(s), libérant environ {size_mb:.2f} Mo.", log_levels=log_levels)
                for f in files_to_delete[:10]:
                    self.log_info(f"  - {f}", log_levels=log_levels)
                if len(files_to_delete) > 10:
                    self.log_info("  - ... et autres.", log_levels=log_levels)
            else:
                self.log_info("Simulation: Aucun fichier à supprimer trouvé.", log_levels=log_levels)
            return True
        else:
            success = True
            deleted_size = 0
            for file_path in files_to_delete:
                try:
                    file_size = Path(file_path).stat().st_size
                    os.remove(file_path)
                    deleted_size += file_size
                    self.log_debug(f"Supprimé: {file_path}", log_levels=log_levels)
                except OSError as e:
                    self.log_error(f"Erreur lors de la suppression de {file_path}: {e}", log_levels=log_levels)
                    success = False
            if success:
                deleted_size_mb = deleted_size / (1024 * 1024)
                self.log_success(f"Vieux fichiers logs supprimés avec succès (si trouvés), libérant {deleted_size_mb:.2f} Mo.", log_levels=log_levels)
                return True
            else:
                self.log_error("Des erreurs sont survenues lors de la suppression des vieux logs.", log_levels=log_levels)
                return False

    def purge_large_logs(self,
                          patterns: List[str],
                          directories: Optional[List[str]] = None,
                          size_threshold_mb: int = 100,
dry_run: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime les fichiers journaux dépassant une certaine taille et correspondant à un des motifs (incluant les sous-dossiers).
        ATTENTION: Opération destructive ! Utiliser dry_run=False avec prudence.

        Args: patterns: Liste de motifs de nom de fichier à cibler (glob style, ex: ["*.log", "access.log*"]).
            directories: Liste de répertoires à scanner (défaut: ['/var/log']).
            size_threshold_mb: Taille minimale en Mo pour considérer la suppression.
            dry_run: Si True (défaut), simule seulement la suppression.

        Returns:
            bool: True si l'opération (ou la simulation) a réussi.
        """
        dirs_to_scan = directories or self.DEFAULT_LOG_DIRS
        action = "Simulation de la suppression" if dry_run else "Suppression"
        self.log_warning(f"{action} des logs de plus de {size_threshold_mb} Mo dans {', '.join(dirs_to_scan)} "
                         f"(et leurs sous-dossiers) correspondant aux motifs: {patterns}", log_levels=log_levels)
        if not dry_run:
            self.log_warning("!!! OPÉRATION DESTRUCTIVE ACTIVÉE !!!", log_levels=log_levels)

        files_to_delete = []
        for pattern in patterns:
            log_dir_paths = [Path(d) for d in dirs_to_scan if Path(d).is_dir()]
            for log_path in log_dir_paths:
                for item in log_path.rglob(pattern): # Use rglob here as well
                    if item.is_file() and item.stat().st_size >= size_threshold_mb * 1024 * 1024:
                        files_to_delete.append(str(item.resolve()))

        # Supprimer les doublons si un fichier correspond à plusieurs motifs
        files_to_delete = list(set(files_to_delete))
        total_size_to_delete = sum(Path(f).stat().st_size for f in files_to_delete if Path(f).is_file())

        if dry_run:
            if files_to_delete:
                size_mb = total_size_to_delete / (1024 * 1024)
                self.log_info(f"Simulation: {len(files_to_delete)} fichier(s) seraient supprimé(s) (taille >= {size_threshold_mb} Mo), "
                              f"libérant environ {size_mb:.2f} Mo.", log_levels=log_levels)
                for f in files_to_delete[:10]:
                    self.log_info(f"  - {f}", log_levels=log_levels)
                if len(files_to_delete) > 10:
                    self.log_info("  - ... et autres.", log_levels=log_levels)
            else:
                self.log_info(f"Simulation: Aucun fichier de plus de {size_threshold_mb} Mo correspondant aux motifs trouvé.", log_levels=log_levels)
            return True
        else:
            success = True
            deleted_size = 0
            for file_path in files_to_delete:
                try:
                    file_size = Path(file_path).stat().st_size
                    os.remove(file_path)
                    deleted_size += file_size
                    self.log_debug(f"Supprimé (large): {file_path}", log_levels=log_levels)
                except OSError as e:
                    self.log_error(f"Erreur lors de la suppression (large) de {file_path}: {e}", log_levels=log_levels)
                    success = False
            if success:
                deleted_size_mb = deleted_size / (1024 * 1024)
                self.log_success(f"Fichiers logs de plus de {size_threshold_mb} Mo supprimés avec succès (si trouvés), "
                                 f"libérant {deleted_size_mb:.2f} Mo.", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Des erreurs sont survenues lors de la suppression des fichiers logs volumineux.", log_levels=log_levels)
                return False

    # --- Gestion Journald ---

    def journald_vacuum_size(self, max_size_mb: int, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Réduit la taille des logs journald à une taille maximale."""
        size_str = f"{max_size_mb}M"
        self.log_info(f"Réduction de la taille des logs journald à {size_str} (journalctl --vacuum-size)", log_levels=log_levels)
        cmd = ['journalctl', f"--vacuum-size={size_str}"]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True, no_output=True)
        if stdout: self.log_info(f"Sortie journalctl vacuum-size:\n{stdout}", log_levels=log_levels)
        if success:
            self.log_info("Nettoyage journald par taille réussi.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du nettoyage journald par taille. Stderr: {stderr}", log_levels=log_levels)
            return False

    def journald_vacuum_time(self, time_spec: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime les entrées journald plus anciennes qu'une date/durée."""
        if not self._cmd_paths.get('journalctl'):
            self.log_error("Commande 'journalctl' non trouvée.", log_levels=log_levels)
            return False
        self.log_info(f"Suppression des entrées journald antérieures à '{time_spec}' (journalctl --vacuum-time)", log_levels=log_levels)
        cmd = [self._cmd_paths['journalctl'], f"--vacuum-time={time_spec}"]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if stdout: self.log_info(f"Sortie journalctl vacuum-time:\n{stdout}", log_levels=log_levels)
        if success:
            self.log_success("Nettoyage journald par temps réussi.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du nettoyage journald par temps. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Analyse de Logs ---

    def find_large_logs(self, directories: Optional[List[str]] = None, size_threshold_mb: int = 100, log_levels: Optional[Dict[str, str]] = None) -> List[Tuple[str, int]]:
        """Trouve les fichiers logs dépassant une certaine taille (incluant les sous-dossiers)."""
        found_files = self.list_log_files(directories=directories, min_size_mb=size_threshold_mb, pattern="*") # Chercher tous types de fichiers
        results = []
        if found_files:
             self.log_info(f"Analyse de la taille des {len(found_files)} fichier(s) trouvé(s)...", log_levels=log_levels)
             for file_path_str in found_files:
                  file_path = Path(file_path_str)
                  try:
                       size_mb = file_path.stat().st_size / (1024 * 1024)
                       if size_mb >= size_threshold_mb:
                            results.append((file_path_str, int(size_mb)))
                  except OSError as e:
                       self.log_warning(f"Impossible d'obtenir la taille de {file_path}: {e}", log_levels=log_levels)
             # Trier par taille décroissante
             results.sort(key=lambda x: x[1], reverse=True)
             self.log_info(f"{len(results)} fichier(s) log(s) dépassant {size_threshold_mb} Mo trouvés.", log_levels=log_levels)
        else:
             self.log_info(f"Aucun fichier trouvé dépassant {size_threshold_mb} Mo.", log_levels=log_levels)

        return results

    def find_frequent_lines(self, log_file: Union[str, Path], top_n: int = 10, patterns_to_ignore: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> List[Tuple[int, str]]:
        """
        Identifie les lignes les plus fréquentes dans un fichier log.

        Args:
            log_file: Chemin du fichier log.
            top_n: Nombre de lignes les plus fréquentes à retourner.
            patterns_to_ignore: Liste d'expressions régulières pour ignorer certaines lignes.

        Returns:
            Liste de tuples (count, line) triée par fréquence décroissante.
        """
        log_path = Path(log_file)
        if not log_path.is_file():
            self.log_error(f"Fichier log introuvable: {log_path}", log_levels=log_levels)
            return []

        self.log_info(f"Recherche des {top_n} lignes les plus fréquentes dans {log_path}", log_levels=log_levels)
        line_counts: Dict[str, int] = {}
        ignored_patterns = [re.compile(p) for p in patterns_to_ignore] if patterns_to_ignore else []

        for line in self._read_file_lines(log_path):
            if not any(pattern.search(line) for pattern in ignored_patterns):
                line_counts[line] = line_counts.get(line, 0) + 1

        sorted_lines = sorted(line_counts.items(), key=lambda item: item[1], reverse=True)
        top_frequent = [(count, line) for line, count in sorted_lines[:top_n]]

        self.log_info(f"{len(top_frequent)} ligne(s) fréquente(s) identifiée(s).", log_levels=log_levels)
        return top_frequent

    def search_log_errors(self,
                          log_file: Union[str, Path],
                          error_patterns: Optional[List[str]] = None,
                          time_since: Optional[str] = None, # Ex: '1 hour ago', 'yesterday'
max_lines: int = 100, log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Recherche des erreurs ou motifs spécifiques dans un fichier log ou journald.

        Args:
            log_file: Chemin du fichier log OU 'journald' pour chercher dans le journal systemd.
            error_patterns: Liste d'expressions régulières à rechercher. Si None, utilise COMMON_ERROR_PATTERNS.
            time_since: Ne chercher que les entrées depuis ce moment (format 'journalctl --since').
                        Uniquement applicable si log_file='journald'.
            max_lines: Nombre maximum de lignes d'erreur à retourner.

        Returns:
            Liste des lignes contenant les erreurs trouvées.
        """
        target = str(log_file)
        is_journald = (target.lower() == 'journald')
        self.log_info(f"Recherche d'erreurs dans: {target}", log_levels=log_levels)

        patterns = error_patterns or self.COMMON_ERROR_PATTERNS
        if not patterns:
            self.log_warning("Aucun motif d'erreur spécifié pour la recherche.", log_levels=log_levels)
            return []

        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        error_lines = []

        if is_journald:
            if not self._cmd_paths.get('journalctl'):
                 self.log_error("Commande 'journalctl' non trouvée.", log_levels=log_levels)
                 return []
            cmd = [self._cmd_paths['journalctl'], '--no-pager', '-p', 'err..alert']
            if time_since:
                 cmd.extend(['--since', time_since])
            success, stdout, stderr = self.run(cmd, check=False, no_output=True, needs_sudo=True)
            if success:
                for line in stdout.splitlines():
                    if any(pattern.search(line) for pattern in compiled_patterns):
                        error_lines.append(line)
                        if len(error_lines) >= max_lines:
                            break
            else:
                self.log_error(f"Erreur lors de la lecture du journald: {stderr}", log_levels=log_levels)
        else:
            log_path = Path(target)
            if not log_path.is_file():
                self.log_error(f"Fichier log introuvable: {log_path}", log_levels=log_levels)
                return []
            for line in self._read_file_lines(log_path):
                if any(pattern.search(line) for pattern in compiled_patterns):
                    error_lines.append(line)
                    if len(error_lines) >= max_lines:
                        break

        self.log_info(f"{len(error_lines)} ligne(s) d'erreur trouvée(s) dans {target}.", log_levels=log_levels)
        return error_lines[:max_lines]