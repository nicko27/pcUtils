# install/plugins/plugins_utils/raid.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour la gestion avancée des tableaux RAID logiciels Linux (mdadm).
Permet de créer, gérer, surveiller et réparer les dispositifs RAID.
"""

# Import de la classe de base et des types
from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import time
import tempfile
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class RaidCommands(PluginsUtilsBase):
    """
    Classe pour gérer les tableaux RAID Linux (mdadm).
    Hérite de PluginUtilsBase pour l'exécution de commandes et la progression.
    """

    def __init__(self, logger=None, target_ip=None):
        """
        Initialise le gestionnaire de commandes RAID.

        Args:
            logger: Instance de PluginLogger (optionnel).
            target_ip: IP cible pour les logs (optionnel).
        """
        super().__init__(logger, target_ip)
        self._mdadm_path = self._find_mdadm()

    def _find_mdadm(self) -> Optional[str]:
        """Trouve le chemin de l'exécutable mdadm."""
        # Vérifier les emplacements courants
        for path in ['/sbin/mdadm', '/usr/sbin/mdadm', '/bin/mdadm', '/usr/bin/mdadm']:
            success, _, _ = self.run(['test', '-x', path], check=False, no_output=True, error_as_warning=True)
            if success:
                self.log_debug(f"Exécutable mdadm trouvé: {path}", log_levels=log_levels)
                return path
        # Si non trouvé, essayer 'which'
        success_which, path_which, _ = self.run(['which', 'mdadm'], check=False, no_output=True, error_as_warning=True)
        if success_which and path_which.strip():
            path_str = path_which.strip()
            self.log_debug(f"Exécutable mdadm trouvé via which: {path_str}", log_levels=log_levels)
            return path_str

        self.log_error("Exécutable 'mdadm' introuvable. Les opérations RAID échoueront. Installer le paquet 'mdadm'.", log_levels=log_levels)
        return None

    def _run_mdadm(self, args: List[str], check: bool = False, needs_sudo: bool = True, **kwargs) -> Tuple[bool, str, str]:
        """Exécute une commande mdadm avec gestion sudo."""
        if not self._mdadm_path:
            return False, "", "Exécutable mdadm non trouvé."
        cmd = [self._mdadm_path] + args
        # La plupart des commandes mdadm nécessitent root
        return self.run(cmd, check=check, needs_sudo=needs_sudo, **kwargs)

    def _get_available_md_device(self) -> str:
        """Trouve le prochain nom de périphérique /dev/mdX disponible."""
        md_num = 0
        while True:
            dev_path = f"/dev/md{md_num}"
            # Utiliser une commande pour vérifier l'existence du bloc device
            # Pas besoin de sudo pour 'test -b' généralement
            success, _, _ = self.run(['test', '-b', dev_path], check=False, no_output=True, error_as_warning=True, needs_sudo=False)
            if not success:
                self.log_debug(f"Prochain périphérique md disponible: {dev_path}", log_levels=log_levels)
                return dev_path
            md_num += 1
            if md_num > 128: # Limite de sécurité raisonnable
                self.log_error("Impossible de trouver un périphérique /dev/mdX disponible (limite atteinte?).", log_levels=log_levels)
                raise RuntimeError("Limite de périphériques md atteinte")

    def create_raid_array(self,
                          raid_level: Union[int, str],
                          devices: List[str],
                          array_path: Optional[str] = None,
                          spare_devices: Optional[List[str]] = None,
                          chunk_size: Optional[int] = None, # en KB
                          metadata: str = "1.2", # Défaut moderne
                          force: bool = False,
                          assume_clean: bool = False,
task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Crée un nouveau tableau RAID via `mdadm --create`.

        Args:
            raid_level: Niveau RAID (0, 1, 4, 5, 6, 10).
            devices: Liste des chemins des périphériques à inclure (ex: /dev/sda1).
            array_path: Chemin du périphérique RAID à créer (ex: /dev/md0). Si None, auto-détecté.
            spare_devices: Liste des périphériques de secours (optionnel).
            chunk_size: Taille de chunk en KiloOctets (optionnel).
            metadata: Version des métadonnées (ex: "1.2", "0.90"). Défaut: "1.2".
            force: Forcer la création même si des superblocks existent (`--force`).
            assume_clean: Supposer que les disques sont synchronisés (`--assume-clean`, accélère RAID1/10).
            task_id: ID de tâche pour la progression (optionnel).

        Returns:
            Chemin du périphérique RAID créé (ex: /dev/md0) ou None si échec.
            La fonction attend la fin de la synchro initiale et met à jour mdadm.conf.
        """
        spare_devices = spare_devices or []
        # Valider le nombre de disques
        min_disks = self._min_devices_for_level(raid_level)
        if not devices or len(devices) < min_disks:
            self.log_error(f"Nombre insuffisant de périphériques ({len(devices)}) pour RAID {raid_level}. Minimum requis: {min_disks}.", log_levels=log_levels)
            return None

        # Déterminer le chemin du tableau
        target_array_path = array_path
        if not target_array_path:
            try:
                target_array_path = self._get_available_md_device()
            except RuntimeError as e:
                self.log_error(str(e), log_levels=log_levels)
                return None
        elif not target_array_path.startswith('/dev/md'):
            self.log_error(f"Chemin de tableau invalide: {target_array_path}. Doit commencer par /dev/md.", log_levels=log_levels)
            return None

        array_name = os.path.basename(target_array_path)
        self.log_info(f"Création du tableau RAID {raid_level} '{array_name}' sur {target_array_path}", log_levels=log_levels)
        self.log_info(f"  Périphériques: {', '.join(devices)}", log_levels=log_levels)
        if spare_devices:
            self.log_info(f"  Secours: {', '.join(spare_devices)}", log_levels=log_levels)

        current_task_id = task_id or f"raid_create_{array_name}_{int(time.time())}"
        # Étapes: 1 (commande create) + 1 (attente sync/rebuild) + 1 (update conf)
        self.start_task(3, description=f"Création RAID {array_name} - Étape 1/3: Commande mdadm", task_id=current_task_id)

        # Construire la commande mdadm --create
        cmd = ['--create', target_array_path, f'--level={raid_level}', f'--raid-devices={len(devices)}']
        if spare_devices:
            cmd.append(f'--spare-devices={len(spare_devices)}')
        if chunk_size:
            cmd.append(f'--chunk={chunk_size}')
        if metadata:
            cmd.append(f'--metadata={metadata}')
        if assume_clean:
             # Attention: à utiliser seulement si on est sûr que les données sont identiques (ex: nouveaux disques)
             self.log_warning("Utilisation de --assume-clean : suppose les disques synchronisés.", log_levels=log_levels)
             cmd.append('--assume-clean')

        cmd.extend(devices)
        cmd.extend(spare_devices)

        # Exécuter avec --run pour démarrer immédiatement après création
        cmd.append('--run')
        # Ajouter --force si demandé explicitement
        if force:
            cmd.append('--force')
            self.log_info("  Option --force activée.", log_levels=log_levels)

        # Exécuter la commande mdadm --create
        # Utiliser un timeout très long ou None, car la création peut prendre du temps
        # check=False pour analyser stderr en cas d'erreur (ex: superblocs existants)
        create_success, stdout_create, stderr_create = self._run_mdadm(cmd, check=False, timeout=None)

        # Gérer le cas où la création échoue à cause de superblocs existants sans --force
        if not create_success and not force and \
           re.search(r'(blocks found on|contains a .* filesystem|member device)', stderr_create, re.IGNORECASE):
            self.log_warning("Superblocs ou systèmes de fichiers existants détectés. Relance avec --force.", log_levels=log_levels)
            cmd_force = cmd + ['--force'] # Ajouter --force à la commande précédente
            create_success, stdout_create, stderr_create = self._run_mdadm(cmd_force, check=False, timeout=None)

        # Si toujours en échec après la relance potentielle
        if not create_success:
            self.log_error(f"Échec de la création du tableau RAID '{array_name}'.", log_levels=log_levels)
            self.log_error(f"Stderr: {stderr_create}", log_levels=log_levels)
            if stdout_create: self.log_info(f"Stdout: {stdout_create}", log_levels=log_levels)
            self.complete_task(success=False, message="Échec création mdadm")
            return None

        self.log_success(f"Commande de création pour {array_name} réussie.", log_levels=log_levels)
        self.update_task(description=f"Création RAID {array_name} - Étape 2/3: Attente Synchro")

        # Attendre la fin de la synchro/reconstruction initiale
        # (mdadm --create --run retourne souvent avant la fin)
        sync_success = self.wait_for_raid_sync(target_array_path, task_id=current_task_id) # Utilise le même task_id
        if not sync_success:
             self.log_warning(f"La synchronisation initiale de {array_name} a échoué ou a dépassé le timeout.", log_levels=log_levels)
             # Continuer quand même pour mettre à jour la conf ? Ou retourner échec ? Retourner échec.
             self.complete_task(success=False, message="Échec/Timeout synchro RAID")
             return None

        self.update_task(description=f"Création RAID {array_name} - Étape 3/3: Mise à jour config")
        # Mettre à jour mdadm.conf pour l'assemblage au démarrage
        conf_updated = self._update_mdadm_conf()
        if not conf_updated:
             self.log_warning("La mise à jour de mdadm.conf a échoué, le RAID pourrait ne pas être assemblé au démarrage.", log_levels=log_levels)

        self.complete_task(success=True, message=f"RAID {array_name} créé")
        return target_array_path

    def stop_raid_array(self, array_path: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Arrête (désactive) un tableau RAID via `mdadm --stop`.
        Le tableau ne doit pas être monté ou utilisé.

        Args:
            array_path: Chemin du périphérique RAID à arrêter (ex: /dev/md0).

        Returns:
            bool: True si succès (ou si déjà arrêté).
        """
        array_name = os.path.basename(array_path)
        self.log_info(f"Arrêt du tableau RAID: {array_name} ({array_path})", log_levels=log_levels)

        # Vérifier si le tableau existe (en tant que block device)
        if not self._check_array_exists(array_path):
             # _check_array_exists loggue déjà l'erreur
             return False # Ne pas essayer d'arrêter un device inexistant

        # Vérifier si monté (optionnel, mais recommandé)
        try:
             from .storage import StorageCommands # Import local
             storage = StorageCommands(self.logger, self.target_ip)
             if storage.is_mounted(array_path):
                  self.log_error(f"Impossible d'arrêter {array_name}: le périphérique est monté.", log_levels=log_levels)
                  return False
        except ImportError:
             self.log_warning("Module StorageCommands non trouvé, impossible de vérifier si le RAID est monté.", log_levels=log_levels)
        except Exception as e_mount_check:
             self.log_warning(f"Erreur lors de la vérification du montage de {array_path}: {e_mount_check}", log_levels=log_levels)

        # Exécuter mdadm --stop
        success, stdout, stderr = self._run_mdadm(['--stop', array_path], check=False)
        if success:
            self.log_success(f"Tableau RAID '{array_name}' arrêté.", log_levels=log_levels)
            return True
        else:
            # Gérer l'erreur "not active" ou "No such file" comme un succès potentiel
            if re.search(r'(not active|no such file or directory)', stderr, re.IGNORECASE):
                 self.log_warning(f"Le tableau RAID '{array_name}' n'était déjà pas actif.", log_levels=log_levels)
                 return True
            # Gérer l'erreur "device or resource busy"
            elif "device or resource busy" in stderr.lower():
                 self.log_error(f"Échec de l'arrêt: Le périphérique {array_name} est occupé (probablement monté).", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de l'arrêt du tableau RAID '{array_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def check_raid_status(self, array_path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """
        Vérifie l'état d'un ou tous les tableaux RAID.

        Args:
            array_path: Chemin du périphérique RAID spécifique (ex: /dev/md0).
                        Si None, lit `/proc/mdstat` pour tous les arrays.

        Returns:
            - Si `array_path` fourni: Dictionnaire détaillé parsé depuis `mdadm --detail` ou None si erreur.
            - Si `array_path` est None: Liste de dictionnaires parsés depuis `/proc/mdstat`
              (peut être enrichie avec `mdadm --detail`) ou None si erreur de lecture `/proc/mdstat`.
        """
        if array_path:
            array_name = os.path.basename(array_path)
            self.log_info(f"Vérification de l'état du tableau RAID '{array_name}' ({array_path})", log_levels=log_levels)
            if not self._check_array_exists(array_path): return None

            # Utiliser --detail pour un array spécifique
            success, stdout, stderr = self._run_mdadm(['--detail', array_path], check=False, no_output=True)
            if not success:
                # Gérer le cas où l'array n'est pas actif
                if "does not appear to be an md device" in stderr or "No such file or directory" in stderr:
                     self.log_warning(f"Le périphérique '{array_path}' n'est pas un array mdadm actif.", log_levels=log_levels)
                     return {'device': array_path, 'state': 'inactive'}
                self.log_error(f"Échec de la récupération des détails de {array_name}. Stderr: {stderr}", log_levels=log_levels)
                return None
            return self._parse_mdadm_detail(stdout)
        else:
            # Lire /proc/mdstat pour tous les arrays
            self.log_info("Vérification de l'état de tous les tableaux RAID actifs (/proc/mdstat)", log_levels=log_levels)
            # Pas besoin de sudo pour lire /proc/mdstat
            success, stdout, stderr = self.run(['cat', '/proc/mdstat'], check=False, no_output=True, needs_sudo=False)
            if not success:
                self.log_error(f"Impossible de lire /proc/mdstat. Stderr: {stderr}", log_levels=log_levels)
                return None
            return self._parse_mdstat(stdout)

    def wait_for_raid_sync(self, array_path: str, timeout: int = 3600, task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Attend la fin de la synchronisation/reconstruction/reshape d'un array
        en surveillant `/proc/mdstat`. Met à jour une tâche de progression si `task_id` est fourni.

        Args:
            array_path: Chemin du périphérique RAID (ex: /dev/md0).
            timeout: Temps maximum d'attente en secondes. Défaut: 3600 (1 heure).
            task_id: ID de tâche existant à mettre à jour avec la progression en pourcentage (0-100).
                     Si None, aucune progression n'est rapportée par cette fonction.

        Returns:
            bool: True si la synchronisation est terminée dans le délai imparti, False sinon.
        """
        array_name = os.path.basename(array_path)
        self.log_info(f"Attente de la fin de la synchronisation/reconstruction pour {array_name}...", log_levels=log_levels)
        start_time = time.monotonic()
        last_pct_reported = -1

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                self.log_error(f"Timeout ({timeout}s) dépassé en attendant la synchronisation de {array_name}.", log_levels=log_levels)
                # Mettre à jour la tâche à 100% avec un message d'erreur ? Ou laisser tel quel ?
                if task_id: self.update_task(description=f"Timeout Synchro {array_name}", task_id=task_id)
                return False

            # Lire /proc/mdstat pour vérifier l'état
            success, mdstat_out, _ = self.run(['cat', '/proc/mdstat'], check=False, no_output=True, error_as_warning=True, needs_sudo=False)
            if not success:
                 self.log_warning("Impossible de lire /proc/mdstat pour vérifier la synchro. Réessai dans 10s.", log_levels=log_levels)
                 time.sleep(10)
                 continue

            sync_line = None
            in_array_section = False
            # Trouver la section de l'array concerné et la ligne de synchro
            for line in mdstat_out.splitlines():
                line_strip = line.strip()
                if line_strip.startswith(f"{array_name} :"):
                    in_array_section = True
                elif in_array_section and line_strip.startswith("md"): # Début d'un autre array
                    in_array_section = False
                    break # Sortir si on passe à un autre array
                elif in_array_section and ("recovery" in line or "resync" in line or "reshape" in line or "check" in line):
                    sync_line = line_strip
                    break # Trouvé la ligne de synchro/recovery/check

            if sync_line:
                # Extraire le pourcentage
                match = re.search(r'=\s*([\d\.]+)%', sync_line)
                percentage = -1.0
                if match:
                    try:
                        percentage = float(match.group(1))
                    except ValueError: pass

                # Mettre à jour la progression si un task_id est fourni et le pourcentage a changé
                if task_id and int(percentage) > last_pct_reported:
                    current_step = int(percentage) # Barre de 0 à 100
                    # Extraire le temps restant si possible
                    time_match = re.search(r'finish=([\d\.]+)min', sync_line)
                    eta = f"ETA: {time_match.group(1)}min" if time_match else ""
                    # Mettre à jour la description de la tâche
                    self.update_task(advance=0, # Ne pas avancer l'étape globale ici
                                     description=f"Synchro {array_name}: {percentage:.1f}% {eta}",
                                     task_id=task_id)
                    # Mettre à jour la barre visuelle si activée
                    if self.use_visual_bars:
                         self.logger.update_bar(task_id, current_step, 100, post_text=f"{percentage:.1f}% {eta}")
                    last_pct_reported = int(percentage)

                self.log_debug(f"Progression synchro {array_name}: {sync_line}", log_levels=log_levels)
                # Continuer d'attendre
                time.sleep(5) # Intervalle de vérification
            else:
                # Aucune ligne de synchro/recovery/reshape/check trouvée pour cet array
                self.log_info(f"Synchronisation/Reconstruction de {array_name} terminée (ou non en cours).", log_levels=log_levels)
                # Mettre à jour la tâche à 100% si elle était suivie
                if task_id:
                     self.update_task(advance=0, description=f"Synchro {array_name}: Terminé", task_id=task_id)
                     if self.use_visual_bars:
                          self.logger.update_bar(task_id, 100, 100, post_text="Terminé")
                return True # Terminé

    # --- Méthodes Privées ---

    def _check_array_exists(self, array_path: str) -> bool:
        """Vérifie si un périphérique bloc md existe."""
        success, _, _ = self.run(['test', '-b', array_path], check=False, no_output=True, error_as_warning=True, needs_sudo=False)
        if not success:
            self.log_error(f"Le tableau RAID '{os.path.basename(array_path)}' ({array_path}) n'existe pas ou n'est pas un périphérique bloc.", log_levels=log_levels)
            return False
        return True

    def _min_devices_for_level(self, level: Union[int, str]) -> int:
        """Retourne le nombre minimum de disques pour un niveau RAID."""
        level_str = str(level).lower().replace('raid','')
        if level_str == '0': return 1 # mdadm permet RAID0 avec 1 disque
        if level_str == '1': return 2
        if level_str == '4': return 2 # Techniquement 3 recommandé (2 data + 1 parité)
        if level_str == '5': return 3
        if level_str == '6': return 4
        if level_str == '10': return 2 # Minimum 2 pour un miroir, 4 pour miroir de stripes
        self.log_warning(f"Niveau RAID inconnu: {level_str}, suppose minimum 2 disques.", log_levels=log_levels)
        return 2

    def _parse_mdadm_detail(self, detail_output: str) -> Dict[str, Any]:
        """Parse la sortie de mdadm --detail."""
        info: Dict[str, Any] = {'devices': []}
        device_section = False
        key_map = { # Mapper les noms verbeux en clés normalisées
            'Version': 'metadata_version', 'Creation Time': 'creation_time',
            'Raid Level': 'raid_level', 'Array Size': 'array_size',
            'Used Dev Size': 'used_dev_size', 'Raid Devices': 'raid_devices',
            'Total Devices': 'total_devices', 'Persistence': 'persistence',
            'Update Time': 'update_time', 'State': 'state',
            'Active Devices': 'active_devices', 'Working Devices': 'working_devices',
            'Failed Devices': 'failed_devices', 'Spare Devices': 'spare_devices',
            'Layout': 'layout', 'Chunk Size': 'chunk_size',
            'Consistency Policy': 'consistency_policy', 'Name': 'name', 'UUID': 'uuid',
            'Events': 'events',
            # Pour la section device
            'Number': 'number', 'Major': 'major', 'Minor': 'minor',
            'RaidDevice': 'raid_device_slot', 'State': 'device_state', # Renommer pour éviter conflit
        }

        for line in detail_output.splitlines():
            line_strip = line.strip()
            if not line_strip:
                device_section = False # Fin de section potentielle
                continue

            # Détecter le début de la section des devices
            if line_strip.startswith('Number') and 'Major' in line_strip and 'Minor' in line_strip:
                device_section = True
                continue

            if device_section:
                # Format: Number Major Minor RaidDevice State Device
                parts = line_strip.split()
                if len(parts) >= 5: # Au moins 5 colonnes attendues
                    try:
                        device_info = {
                            'number': int(parts[0]),
                            'major': int(parts[1]),
                            'minor': int(parts[2]),
                            'raid_device_slot': int(parts[3]),
                            'device_state': " ".join(parts[4:-1]), # L'état peut contenir des espaces
                            'device': parts[-1] # Le chemin est toujours le dernier
                        }
                        info['devices'].append(device_info)
                    except (ValueError, IndexError):
                         self.log_warning(f"Impossible de parser la ligne device mdadm: '{line_strip}'", log_levels=log_levels)
            elif ':' in line_strip:
                # Parser les informations générales clé: valeur
                key, value = line_strip.split(':', 1)
                key_strip = key.strip()
                value_strip = value.strip()
                # Utiliser le mapping ou une clé normalisée
                key_norm = key_map.get(key_strip, key_strip.lower().replace(' ', '_').replace('-', '_'))
                # Essayer de convertir les tailles en octets
                if key_norm.endswith('_size') and '(' in value_strip:
                     size_match = re.match(r'(\d+)\s*\((\d+\.\d+)\s*(\w+)B\)', value_strip)
                     if size_match:
                          info[key_norm + '_bytes'] = int(size_match.group(1)) * 1024 # Taille en Ko * 1024
                          info[key_norm + '_gib'] = float(size_match.group(2)) # Taille en GiB/MiB
                          info[key_norm + '_unit'] = size_match.group(3) + 'B'
                          info[key_norm] = value_strip # Garder aussi la chaîne originale
                     else:
                          info[key_norm] = value_strip
                # Convertir les nombres si possible
                elif value_strip.isdigit():
                     info[key_norm] = int(value_strip)
                else:
                     info[key_norm] = value_strip
        return info

    def _parse_mdstat(self, mdstat_output: str) -> List[Dict[str, Any]]:
        """Parse la sortie de /proc/mdstat."""
        arrays = []
        current_array: Optional[Dict[str, Any]] = None
        lines = mdstat_output.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if line.startswith('Personalities :'): continue
            if line.startswith('unused devices:'): continue
            if not line: continue

            # Début d'un nouvel array: mdX : active raidY sdb1[1] sda1[0]
            match_md = re.match(r'^(md\d+)\s*:\s*(active|inactive|clean|degraded|recovering|resyncing|reshape)\s*(?:(raid\d+|linear|multipath|faulty)\s*)?(.*)', line)
            if match_md:
                # Sauvegarder l'array précédent s'il existe
                if current_array: arrays.append(current_array)

                name, state, level, devices_str = match_md.groups()
                current_array = {'name': name, 'state': state, 'raid_level': level.replace('raid','') if level else None, 'devices': [], 'status_line': line}
                # Parser les devices sur la même ligne
                dev_matches = re.findall(r'(\w+\[\d+\](?:\(.\))?)', devices_str) # Ex: sda1[0](F)
                for dev_match in dev_matches:
                    dev_name_match = re.match(r'(\w+)\[\d+\]', dev_match) # Ex: sda1
                    dev_state_match = re.search(r'\((.)\)', dev_match) # Ex: (F)
                    if dev_name_match:
                        dev_state = 'active' # Par défaut
                        if dev_state_match:
                             state_code = dev_state_match.group(1)
                             if state_code == 'F': dev_state = 'faulty'
                             if state_code == 'S': dev_state = 'spare'
                        # Construire le chemin /dev/XXX (suppose que c'est un nom de base comme sda1, nvme0n1p1)
                        device_path = f"/dev/{dev_name_match.group(1)}"
                        current_array['devices'].append({'device': device_path, 'state': dev_state})

            # Ligne de configuration (blocks, level, chunk size)
            elif current_array and re.match(r'^\d+\s+blocks', line):
                current_array['config_line'] = line
                # Essayer d'extraire la taille et le chunk
                size_match = re.search(r'(\d+)\s+blocks', line)
                if size_match: current_array['size_blocks'] = int(size_match.group(1))
                chunk_match = re.search(r'(\d+k)\s+chunks', line)
                if chunk_match: current_array['chunk_size'] = chunk_match.group(1)

            # Ligne de statut de bitmap ou synchro/recovery
            elif current_array and (line.startswith('[') or 'bitmap:' in line or 'resync =' in line or 'recovery =' in line or 'reshape =' in line or 'check =' in line):
                current_array['sync_line'] = line
                # Essayer d'extraire le pourcentage et l'ETA
                pct_match = re.search(r'=\s*([\d\.]+)%', line)
                if pct_match: current_array['sync_percent'] = float(pct_match.group(1))
                eta_match = re.search(r'finish=([\d\.]+)min', line)
                if eta_match: current_array['sync_eta_min'] = float(eta_match.group(1))
                speed_match = re.search(r'speed=(\d+K/sec)', line)
                if speed_match: current_array['sync_speed'] = speed_match.group(1)

        # Ajouter le dernier array parsé
        if current_array: arrays.append(current_array)

        # Optionnel: Enrichir avec les détails mdadm pour chaque array trouvé
        # for arr in arrays:
        #     details = self.check_raid_status(f"/dev/{arr['name']}")
        #     if details: arr.update(details) # Fusionner les détails

        self.log_info(f"{len(arrays)} array(s) RAID trouvés dans /proc/mdstat.", log_levels=log_levels)
        return arrays

    def _update_mdadm_conf(self) -> bool:
        """Met à jour /etc/mdadm/mdadm.conf ou /etc/mdadm.conf via `mdadm --detail --scan`."""
        self.log_info("Mise à jour de la configuration mdadm (/etc/mdadm/mdadm.conf)", log_levels=log_levels)
        # Déterminer le chemin du fichier de conf
        conf_path = "/etc/mdadm/mdadm.conf"
        alt_path = "/etc/mdadm.conf"
        target_conf_path = None
        if os.path.exists(conf_path):
             target_conf_path = conf_path
        elif os.path.exists(alt_path):
             target_conf_path = alt_path
        else:
             # Si aucun n'existe, créer celui dans /etc/mdadm/
             target_conf_path = conf_path
             self.log_info(f"Fichier {target_conf_path} non trouvé, il sera créé.", log_levels=log_levels)
             mdadm_dir = os.path.dirname(target_conf_path)
             if not os.path.exists(mdadm_dir):
                  # Créer le dossier avec sudo
                  self.run(['mkdir', '-p', mdadm_dir], check=False, needs_sudo=True)

        # Sauvegarde de l'ancien fichier si existant
        if os.path.exists(target_conf_path):
            backup_path = f"{target_conf_path}.bak_{int(time.time())}"
            self.log_info(f"Sauvegarde de la configuration existante dans {backup_path}", log_levels=log_levels)
            # Utiliser cp -a via self.run pour gérer sudo et préserver les permissions
            cp_success, _, cp_stderr = self.run(['cp', '-a', target_conf_path, backup_path], check=False, needs_sudo=True)
            if not cp_success:
                 self.log_warning(f"Échec de la sauvegarde de {target_conf_path}: {cp_stderr}", log_levels=log_levels)

        # Générer la nouvelle configuration via mdadm --detail --scan
        # Exécuter avec sudo car peut nécessiter de lire les superblocs
        scan_success, scan_stdout, scan_stderr = self._run_mdadm(['--detail', '--scan'], check=False, no_output=True, needs_sudo=True)

        if not scan_success:
            self.log_error(f"Impossible de générer la configuration mdadm via '--detail --scan'. Stderr: {scan_stderr}", log_levels=log_levels)
            return False

        # Construire le contenu final du fichier
        conf_content = f"# mdadm.conf generated by pcUtils plugin on {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        conf_content += "# See mdadm.conf(5) for more information.\n\n"
        # Ajouter la directive DEVICE (importante)
        conf_content += "DEVICE partitions\n\n"
        # Ajouter la sortie de scan qui contient les lignes ARRAY
        conf_content += scan_stdout.strip() + "\n\n"
        # Ajouter une ligne MAILADDR si configuré (à implémenter si besoin)
        # conf_content += "MAILADDR admin@example.com\n"

        # Écrire la nouvelle configuration en utilisant _write_file_content pour gérer sudo/backup
        from .config_files import ConfigFileCommands # Import local
        cfg_writer = ConfigFileCommands(self.logger, self.target_ip)
        # Ne pas faire de backup ici car on l'a déjà fait au début
        success_write = cfg_writer._write_file_content(target_conf_path, conf_content, backup=False)

        if success_write:
            self.log_success(f"Fichier {target_conf_path} mis à jour avec succès.", log_levels=log_levels)
            # Recommander la mise à jour de l'initramfs
            self.log_info("Il est fortement recommandé de mettre à jour l'initramfs (ex: update-initramfs -u) pour assurer l'assemblage au démarrage.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de l'écriture dans {target_conf_path}.", log_levels=log_levels)
            return False