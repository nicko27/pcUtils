# install/plugins/plugins_utils/storage.py
#!/usr/bin/env python3
"""
Module utilitaire pour obtenir des informations sur le stockage :
systèmes de fichiers, points de montage, utilisation disque.
Utilise les commandes lsblk, findmnt, df.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import json
from typing import Union, Optional, List, Dict, Any, Tuple

class StorageCommands(PluginsUtilsBase):
    """
    Classe pour récupérer des informations sur le stockage (FS, montage, df).
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de stockage."""
        super().__init__(logger, target_ip)
        self._check_commands()

    def _check_commands(self):
        """Vérifie la présence des commandes nécessaires."""
        cmds = ['lsblk', 'findmnt', 'df']
        missing = []
        for cmd in cmds:
            success, _, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if not success:
                missing.append(cmd)
        if missing:
            self.log_warning(f"Commandes de stockage potentiellement manquantes: {', '.join(missing)}.", log_levels=log_levels)

    def get_filesystem_info(self, device: str, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Récupère le type de système de fichiers, UUID et label pour un périphérique.

        Args:
            device: Chemin du périphérique (ex: /dev/sda1, /dev/mapper/vg-lv).

        Returns:
            Dictionnaire avec les clés 'TYPE', 'UUID', 'LABEL' ou vide si erreur/non trouvé.
        """
        self.log_debug(f"Récupération des infos FS pour: {device}", log_levels=log_levels)
        # lsblk -f fournit FSTYPE, UUID, LABEL, FSVER, MOUNTPOINTS
        # -n : pas d'en-tête, -o : colonnes spécifiques, --json : sortie JSON
        cmd = ['lsblk', '-f', '-n', '-o', 'FSTYPE,UUID,LABEL', '--json', device]
        success, stdout, stderr = self.run(cmd, check=False, no_output=True)

        info = {}
        if not success:
            # Gérer le cas où lsblk échoue car device n'existe pas
            if "no such file or directory" in stderr.lower():
                 self.log_warning(f"Le périphérique {device} n'a pas été trouvé par lsblk.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de lsblk -f pour {device}. Stderr: {stderr}", log_levels=log_levels)
            return info

        try:
            data = json.loads(stdout)
            # La sortie JSON contient 'blockdevices' qui est une liste
            if data and 'blockdevices' in data and data['blockdevices']:
                # Prendre le premier périphérique (normalement un seul retourné)
                dev_info = data['blockdevices'][0]
                # lsblk retourne null pour les champs vides, les convertir en None ou str vide
                info = {
                    'TYPE': dev_info.get('fstype') or "",
                    'UUID': dev_info.get('uuid') or "",
                    'LABEL': dev_info.get('label') or ""
                }
                # Filtrer les valeurs None si nécessaire, mais les garder peut être utile
                # info = {k: v for k, v in info.items() if v is not None}
                self.log_debug(f"Infos FS pour {device}: {info}", log_levels=log_levels)
            else:
                 self.log_warning(f"Aucune information de blockdevice retournée par lsblk pour {device}.", log_levels=log_levels)

        except json.JSONDecodeError:
            self.log_error(f"Erreur de parsing JSON pour la sortie lsblk de {device}.", log_levels=log_levels)
        except Exception as e:
            self.log_error(f"Erreur inattendue lors du traitement lsblk JSON: {e}", exc_info=True, log_levels=log_levels)

        return info

    def get_mount_info(self, source_or_target: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
        """
        Récupère les informations de montage pour un périphérique ou point de montage spécifique, ou tous.
        Utilise findmnt pour obtenir des informations structurées.

        Args:
            source_or_target: Périphérique (ex: /dev/sda1) ou point de montage (ex: /home)
                              ou None pour lister tous les points de montage.

        Returns:
            Liste de dictionnaires, chaque dict représentant un point de montage.
            Clés typiques: 'TARGET', 'SOURCE', 'FSTYPE', 'OPTIONS'.
        """
        target_log = f"pour '{source_or_target}'" if source_or_target else "pour tous les points de montage"
        self.log_debug(f"Récupération des informations de montage {target_log}", log_levels=log_levels)
        # findmnt -J : sortie JSON, -n : pas d'en-tête (implicite avec JSON)
        cmd = ['findmnt', '-J']
        if source_or_target:
            cmd.append(source_or_target)

        success, stdout, stderr = self.run(cmd, check=False, no_output=True)
        mounts = []

        if not success:
            # findmnt retourne un code d'erreur si source_or_target n'est pas trouvé/monté
            if source_or_target and ("not found" in stderr or "nothing was found" in stderr):
                 self.log_debug(f"Aucun point de montage trouvé pour '{source_or_target}'.", log_levels=log_levels)
                 return []
            self.log_error(f"Échec de findmnt. Stderr: {stderr}", log_levels=log_levels)
            return mounts

        try:
            data = json.loads(stdout)
            if 'filesystems' in data:
                mounts = data['filesystems']
                self.log_debug(f"{len(mounts)} point(s) de montage trouvé(s) {target_log}.", log_levels=log_levels)
            else:
                 self.log_warning("Format JSON inattendu de findmnt (clé 'filesystems' manquante).", log_levels=log_levels)
        except json.JSONDecodeError:
            self.log_error("Erreur de parsing JSON pour la sortie findmnt.", log_levels=log_levels)
        except Exception as e:
            self.log_error(f"Erreur inattendue lors du traitement findmnt JSON: {e}", exc_info=True, log_levels=log_levels)

        return mounts

    def is_mounted(self, source_or_target: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un périphérique ou un point de montage est actuellement monté.

        Args:
            source_or_target: Périphérique ou point de montage.

        Returns:
            bool: True si monté, False sinon.
        """
        mount_info = self.get_mount_info(source_or_target)
        is_mnt = bool(mount_info) # Si la liste n'est pas vide, c'est monté
        self.log_debug(f"'{source_or_target}' est monté: {is_mnt}", log_levels=log_levels)
        return is_mnt

    def get_disk_usage(self, path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
        """
        Récupère l'utilisation disque via `df`.

        Args:
            path: Chemin spécifique pour vérifier l'utilisation (optionnel).
                  Si None, retourne l'utilisation de tous les systèmes de fichiers montés.

        Returns:
            Liste de dictionnaires, chaque dict représentant une ligne de `df`.
            Clés basées sur les en-têtes de `df` (normalisées en minuscules).
        """
        target_log = f"pour '{path}'" if path else "pour tous les FS"
        self.log_debug(f"Récupération de l'utilisation disque {target_log}", log_levels=log_levels)
        # df options:
        # -P : Utiliser le format POSIX (évite coupure lignes)
        # --output=... : Spécifier les colonnes (plus robuste que le parsing par défaut)
        # --block-size=1 : Afficher tailles en octets pour éviter parsing d'unités
        # Note: --output n'est pas dispo partout, utiliser -P comme fallback
        # Vérifier si --output est supporté
        output_supported = False
        df_help_success, df_help_stdout, _ = self.run(['df', '--help'], check=False, no_output=True, error_as_warning=True)
        if df_help_success and '--output' in df_help_stdout:
            output_supported = True

        cmd = ['df']
        if output_supported:
            # Source, FSType, Size, Used, Avail, Use%, Target
            cmd.extend(['--output=source,fstype,size,used,avail,pcent,target'])
        else:
             cmd.append('-P') # Format POSIX standard

        if path:
            cmd.append(path)

        success, stdout, stderr = self.run(cmd, check=False, no_output=True)
        usage = []

        if not success:
            # Gérer le cas où le chemin n'existe pas
            if path and "no such file or directory" in stderr.lower():
                 self.log_error(f"Chemin non trouvé pour df: {path}", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la commande df. Stderr: {stderr}", log_levels=log_levels)
            return usage

        lines = stdout.strip().splitlines()
        if not lines:
            return usage

        # Obtenir les en-têtes (première ligne) et normaliser
        header_raw = lines[0].split()
        if output_supported:
             # Les noms sont déjà ceux demandés
             header = [h.lower() for h in header_raw]
        else:
             # Noms POSIX standard
             header_map = {
                 'Filesystem': 'source',
                 'Type': 'fstype',
                 '1K-blocks': 'size_1k', # Sera converti plus tard si possible
                 'Size': 'size',
                 'Used': 'used',
                 'Available': 'avail',
                 'Avail': 'avail', # Autre forme
                 'Use%': 'pcent',
                 'Mounted': 'target', # 'Mounted on' -> 'target'
                 'on': None # Ignorer la particule 'on'
             }
             header = [header_map.get(h) for h in header_raw if header_map.get(h)]

        # Parser les lignes de données
        for line in lines[1:]:
            parts = line.split(None, len(header) - 1) # Split seulement N-1 fois
            if len(parts) == len(header):
                row_dict = dict(zip(header, parts))
                # Nettoyer le % de pcent
                if 'pcent' in row_dict:
                     row_dict['pcent'] = row_dict['pcent'].replace('%', '')
                # Convertir les tailles si possible (si non déjà en octets)
                # Pour l'instant, on garde les chaînes retournées par df
                usage.append(row_dict)
            else:
                 self.log_warning(f"Ligne df ignorée (format inattendu): '{line}'", log_levels=log_levels)

        self.log_debug(f"{len(usage)} entrée(s) d'utilisation disque trouvée(s).", log_levels=log_levels)
        return usage