# install/plugins/plugins_utils/lvm.py
#!/usr/bin/env python3
"""
Module utilitaire pour la gestion avancée de LVM (Logical Volume Manager) sous Linux.
Utilise les commandes pvs, vgs, lvs, pvcreate, vgcreate, lvcreate, lvresize, vgrename etc.
Privilégie la sortie JSON lorsque disponible (--reportformat json).
Inclut la gestion des snapshots, du thin provisioning, des tags et plus encore.
"""

# Import des dépendances internes et standard
from plugins_utils.plugins_utils_base import PluginsUtilsBase
try:
    # Importation réelle si storage.py existe
    from plugins_utils.storage import StorageCommands
    STORAGE_CMD_AVAILABLE = True
except ImportError:
    STORAGE_CMD_AVAILABLE = False
    # Classe factice pour éviter les erreurs si storage.py manque
    class StorageCommands:
        def __init__(self, logger=None, target_ip=None): pass
        def get_filesystem_info(self, device: str) -> Dict[str, str]: return {}
        def get_mount_info(self, device: str) -> List[Dict[str, str]]: return []
        def is_mounted(self, device: str) -> bool: return False
        # Ajouter des méthodes factices si d'autres sont appelées
        def umount(self, target: str, force: bool = False) -> bool: return False
        def mount(self, source: str, target: str, options: Optional[str] = None, fs_type: Optional[str] = None) -> bool: return False

import os
import re
import json
import time
import shlex
from typing import Union, Optional, List, Dict, Any, Tuple

# Unités de taille LVM courantes
LVM_UNITS = {'k', 'm', 'g', 't', 'p', 'e'} # Kilo, Mega, Giga, Tera, Peta, Exa (puissances de 1024)

class LvmCommands(PluginsUtilsBase):
    """
    Classe pour gérer LVM (Physical Volumes, Volume Groups, Logical Volumes)
    avec des fonctionnalités avancées.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire LVM."""
        super().__init__(logger, target_ip)
        self._check_commands()
        self._storage_cmd = StorageCommands(self.logger, self.target_ip) if STORAGE_CMD_AVAILABLE else None
        if not STORAGE_CMD_AVAILABLE:
            self.log_warning("Module StorageCommands non trouvé. La détection FS/Montage sera désactivée.", log_levels=log_levels)

    def _check_commands(self):
        """Vérifie si les commandes LVM/FS/Montage sont disponibles."""
        cmds = [
            'pvs', 'vgs', 'lvs', 'pvcreate', 'vgcreate', 'lvcreate', 'vgextend', 'vgrename',
            'lvextend', 'lvreduce', 'lvresize', 'lvremove', 'vgremove', 'pvremove',
            'lvconvert', 'lvchange', 'vgchange', 'pvchange', 'pvmove', 'pvresize',
            'vgsplit', 'vgmerge', 'vgcfgbackup', 'vgcfgrestore', 'lvsdisplay',
            'resize2fs', 'xfs_growfs', 'btrfs', # Commandes FS
            'mount', 'umount', 'findmnt', 'lsblk', 'e2fsck' # Commandes Montage/Stockage/FS Check
        ]
        missing = []
        for cmd in cmds:
            success, _, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if not success:
                missing.append(cmd)
        if missing:
            self.log_warning(f"Commandes LVM/FS/Montage potentiellement manquantes: {', '.join(missing)}. "
                             f"Installer 'lvm2', 'e2fsprogs', 'xfsprogs', 'btrfs-progs', 'util-linux' ou équivalent.", log_levels=log_levels)

    def _run_lvm_report_json(self, command: List[str], expect_list: bool = True) -> Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]:
        """Exécute une commande LVM avec sortie JSON et la parse."""
        # --binary pour tailles en octets, +all pour toutes les colonnes
        cmd = command + ['-o', '+all', '--binary', '--reportformat', 'json']
        success, stdout, stderr = self.run(cmd, check=False, no_output=True, needs_sudo=True)

        if not success:
            if "not found" in stderr.lower():
                self.log_info(f"Aucun objet LVM trouvé par '{' '.join(command)}'.", log_levels=log_levels)
                return [] if expect_list else {}
            if "failed to find" in stderr.lower() or "does not exist" in stderr.lower():
                self.log_info(f"Aucun objet LVM correspondant au filtre '{' '.join(command)}' trouvé.", log_levels=log_levels)
                return [] if expect_list else {}
            self.log_error(f"Échec de la commande LVM '{' '.join(command)}'. Stderr: {stderr}", log_levels=log_levels)
            return None

        try:
            data = json.loads(stdout)
            report = data.get('report', [])
            if not report or not isinstance(report, list):
                self.log_warning(f"Format JSON inattendu (pas de 'report') pour '{' '.join(command)}'.", log_levels=log_levels)
                return [] if expect_list else {}

            report_key = command[0][:-1] # 'pvs' -> 'pv', etc.
            items_data = report[0].get(report_key)
            if items_data is None:
                self.log_debug(f"Clé '{report_key}' non trouvée dans JSON pour '{' '.join(command)}'.", log_levels=log_levels)
                return [] if expect_list else {}

            items = items_data if isinstance(items_data, list) else [items_data]

            for item in items:
                if isinstance(item, dict):
                    self._convert_binary_sizes(item)

            if not expect_list:
                return items[0] if items else {}
            return items

        except json.JSONDecodeError as e:
            self.log_error(f"Erreur parsing JSON pour '{' '.join(command)}': {e}", log_levels=log_levels)
            self.log_debug(f"Sortie LVM brute:\n{stdout}", log_levels=log_levels)
            return None
        except Exception as e:
            self.log_error(f"Erreur inattendue traitement LVM JSON: {e}", exc_info=True, log_levels=log_levels)
            return None

    def _convert_binary_sizes(self, item: Dict[str, Any]):
        """Convertit les tailles LVM (obtenues via --binary) en entiers."""
        keys_to_convert = [k for k, v in item.items() if isinstance(v, str) and v.isdigit()]
        for key in keys_to_convert:
            try:
                item[key] = int(item[key])
            except (ValueError, TypeError): pass

    def _lvm_size_to_bytes(self, size_str: str) -> int:
        """Convertit une taille LVM (ex: '10.00g', '512k') en octets."""
        size_str_orig = size_str
        size_str = size_str.lower().strip()
        if not size_str: raise ValueError("Chaîne de taille vide.")
        if size_str.isdigit(): return int(size_str)

        unit = size_str[-1]
        if unit == 'b': # Octets
            if size_str[:-1].isdigit(): return int(size_str[:-1])
            raise ValueError(f"Format octet invalide dans '{size_str_orig}'")
        if unit not in LVM_UNITS:
            raise ValueError(f"Unité LVM inconnue: {unit} dans '{size_str_orig}'")

        value_part = size_str[:-1].replace(',', '.')
        try:
            value = float(value_part)
        except ValueError:
            raise ValueError(f"Partie numérique invalide: {value_part} dans '{size_str_orig}'")

        multipliers = {'k': 1024, 'm': 1024**2, 'g': 1024**3, 't': 1024**4, 'p': 1024**5, 'e': 1024**6}
        return int(value * multipliers[unit])

    def _format_lvm_size(self, size: Union[str, int], default_units: str = 'G') -> str:
        """Formate une taille pour les commandes LVM (ex: '10G', '512M', '1024k')."""
        size_str = str(size).strip().upper()
        if not size_str: raise ValueError("Taille vide fournie.")

        # Si déjà formaté avec unité LVM valide
        if size_str[-1] in 'KMGTP' and size_str[:-1].replace('.', '', 1).replace(',', '', 1).isdigit():
            num_part = size_str[:-1].replace(',', '.')
            unit = size_str[-1]
            return f"{num_part}{'k' if unit == 'K' else unit}"

        # Si c'est un nombre (peut être octets ou avec unité par défaut)
        num_part = size_str.replace(',', '.')
        if num_part.replace('.', '', 1).isdigit():
            unit = default_units.upper()
            if unit == 'B': return num_part # Octets -> pas d'unité pour LVM
            if unit == 'K': unit = 'k'
            if unit not in 'KMGTP': unit = 'G' # Défaut si unité invalide
            return f"{num_part}{unit}"

        raise ValueError(f"Format de taille invalide pour LVM: {size}")

    # --- Commandes de Listage/Information ---

    def list_pvs(self, vg_name: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[Dict[str, Any]]]:
        """Liste les Physical Volumes (PVs)."""
        # ... (identique) ...
        self.log_info(f"Listage des PVs {'dans VG ' + vg_name if vg_name else ''}", log_levels=log_levels)
        cmd = ['pvs']
        if vg_name: cmd.append(vg_name)
        return self._run_lvm_report_json(cmd, expect_list=True)


    def list_vgs(self, vg_name: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[Dict[str, Any]]]:
        """Liste les Volume Groups (VGs)."""
        # ... (identique) ...
        target = f"VG {vg_name}" if vg_name else "tous les VGs"
        self.log_info(f"Listage de {target}", log_levels=log_levels)
        cmd = ['vgs']
        if vg_name: cmd.append(vg_name)
        return self._run_lvm_report_json(cmd, expect_list=True)

    def list_lvs(self, vg_or_lv_path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[Dict[str, Any]]]:
        """Liste les Logical Volumes (LVs)."""
        # ... (identique) ...
        target = f"dans '{vg_or_lv_path}'" if vg_or_lv_path else "tous"
        self.log_info(f"Listage des LVs {target}", log_levels=log_levels)
        cmd = ['lvs']
        if vg_or_lv_path: cmd.append(vg_or_lv_path)
        return self._run_lvm_report_json(cmd, expect_list=True)

    def get_pv_info(self, pv_device: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations détaillées d'un PV."""
        # ... (identique) ...
        self.log_debug(f"Récupération des informations pour PV {pv_device}", log_levels=log_levels)
        cmd = ['pvs', pv_device]
        result = self._run_lvm_report_json(cmd, expect_list=True)
        return result[0] if result else None

    def get_vg_info(self, vg_name: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations détaillées d'un VG."""
        # ... (identique) ...
        self.log_debug(f"Récupération des informations pour VG {vg_name}", log_levels=log_levels)
        cmd = ['vgs', vg_name]
        result = self._run_lvm_report_json(cmd, expect_list=True)
        return result[0] if result else None

    def get_lv_info(self, lv_path_or_name: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations détaillées d'un LV."""
        # ... (identique) ...
        full_lv_path = self._resolve_lv_path(lv_path_or_name)
        if not full_lv_path: return None
        self.log_debug(f"Récupération des informations pour LV {full_lv_path}", log_levels=log_levels)
        cmd = ['lvs', full_lv_path]
        result = self._run_lvm_report_json(cmd, expect_list=True)
        return result[0] if result else None

    # --- Commandes de Création ---

    def create_pv(self, device: str, force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Initialise un disque ou une partition comme Physical Volume (PV)."""
        # ... (amélioration gestion erreur "already exists") ...
        self.log_info(f"Initialisation du PV sur: {device}{' (forcé)' if force else ''}", log_levels=log_levels)
        if force:
            self.log_warning(f"Utilisation de l'option force pour pvcreate sur {device} - RISQUE DE PERTE DE DONNÉES !", log_levels=log_levels)
        cmd = ['pvcreate', '-y']
        if force: cmd.append('-ff')
        cmd.append(device)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"PV créé avec succès sur {device}.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie pvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "already exists" in stderr.lower() or "physical volume belongs to a volume group" in stderr.lower():
                self.log_warning(f"Le périphérique {device} est déjà un PV ou appartient à un VG.", log_levels=log_levels)
                return True # Succès si déjà PV
            self.log_error(f"Échec de la création du PV sur {device}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def create_vg(self, vg_name: str, devices: List[str], tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un Volume Group (VG) à partir d'un ou plusieurs PVs."""
        # ... (amélioration gestion erreur "already exists") ...
        if not devices:
            self.log_error("Au moins un périphérique PV est requis pour créer un VG.", log_levels=log_levels)
            return False
        self.log_info(f"Création du VG '{vg_name}' avec les PVs: {', '.join(devices)}", log_levels=log_levels)
        cmd = ['vgcreate', vg_name] + devices
        if tags:
            cmd.extend(['--addtag', ",".join(tags)])
            self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"VG '{vg_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie vgcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "already exists" in stderr.lower():
                self.log_warning(f"Le VG '{vg_name}' existe déjà.", log_levels=log_levels)
                return True # Succès si existe déjà
            # Gérer le cas où un PV n'est pas valide
            if "Cannot use device" in stderr or "not a valid physical volume" in stderr.lower():
                 self.log_error(f"Échec: Un ou plusieurs périphériques ne sont pas des PV valides ou ne peuvent être utilisés. Stderr: {stderr}", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la création du VG '{vg_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def create_lv_linear(self, vg_name: str, lv_name: str, size: Union[str, int],
                         units: str = 'G', tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un Logical Volume (LV) linéaire de taille fixe."""
        # ... (amélioration gestion erreur "already exists") ...
        try:
            size_str = self._format_lvm_size(size, units)
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False
        self.log_info(f"Création du LV linéaire '{lv_name}' dans VG '{vg_name}' (taille: {size_str})", log_levels=log_levels)
        cmd = ['lvcreate', '-L', size_str, '-n', lv_name, vg_name]
        if tags:
            cmd.extend(['--addtag', ",".join(tags)])
            self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"LV '{lv_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "already exists" in stderr.lower():
                self.log_warning(f"Le LV '{lv_name}' dans VG '{vg_name}' existe déjà.", log_levels=log_levels)
                return True
            # Gérer espace insuffisant
            if "insufficient free space" in stderr.lower() or "not enough free extents" in stderr.lower():
                 self.log_error(f"Échec: Espace insuffisant dans le VG '{vg_name}' pour créer le LV '{lv_name}' de taille {size_str}.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la création du LV '{lv_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def create_lv_percent(self, vg_name: str, lv_name: str, percent: int,
                          pool: str = 'VG', tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un LV en utilisant un pourcentage de l'espace disponible."""
        # ... (amélioration gestion erreur "already exists") ...
        if not 1 <= percent <= 100:
            self.log_error("Le pourcentage doit être entre 1 et 100.", log_levels=log_levels)
            return False
        pool_upper = pool.upper()
        if pool_upper not in ['VG', 'FREE']:
            self.log_error("Le pool doit être 'VG' ou 'FREE'.", log_levels=log_levels)
            return False

        self.log_info(f"Création du LV '{lv_name}' dans VG '{vg_name}' ({percent}% de {pool_upper})", log_levels=log_levels)
        cmd = ['lvcreate', '-l', f"{percent}%{pool_upper}", '-n', lv_name, vg_name]
        if tags:
            cmd.extend(['--addtag', ",".join(tags)])
            self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"LV '{lv_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "already exists" in stderr.lower():
                self.log_warning(f"Le LV '{lv_name}' dans VG '{vg_name}' existe déjà.", log_levels=log_levels)
                return True
            if "insufficient free space" in stderr.lower() or "not enough free extents" in stderr.lower():
                 self.log_error(f"Échec: Espace insuffisant dans le VG '{vg_name}' pour créer le LV '{lv_name}' ({percent}% {pool_upper}).", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la création du LV '{lv_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Commandes de Modification ---

    def extend_vg(self, vg_name: str, devices: List[str], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Ajoute un ou plusieurs PVs à un VG existant."""
        # ... (identique, mais erreurs gérées) ...
        if not devices:
            self.log_error("Aucun périphérique PV spécifié pour étendre le VG.", log_levels=log_levels)
            return False
        self.log_info(f"Extension du VG '{vg_name}' avec les PVs: {', '.join(devices)}", log_levels=log_levels)
        cmd = ['vgextend', vg_name] + devices
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"VG '{vg_name}' étendu avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie vgextend:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "not found" in stderr.lower() and f"'{vg_name}'" in stderr.lower():
                self.log_error(f"Échec: Le VG '{vg_name}' n'a pas été trouvé.", log_levels=log_levels)
            elif "already in volume group" in stderr.lower():
                self.log_warning(f"Un ou plusieurs PVs sont déjà dans le VG '{vg_name}'.", log_levels=log_levels)
                return True
            elif "not a valid physical volume" in stderr.lower():
                self.log_error(f"Échec: Un ou plusieurs périphériques ne sont pas des PV valides. Stderr: {stderr}", log_levels=log_levels)
            else:
                self.log_error(f"Échec de l'extension du VG '{vg_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def extend_lv(self, lv_path_or_name: str, size_increase: Union[str, int],
                  units: str = 'G', resize_fs: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Étend un LV et optionnellement son système de fichiers."""
        # ... (amélioration : utilise --resizefs, gestion erreurs) ...
        try:
            size_str = self._format_lvm_size(size_increase, units)
            if not size_str.startswith('+'): size_str = f"+{size_str}"
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False

        full_lv_path = self._resolve_lv_path(lv_path_or_name)
        if not full_lv_path: return False

        self.log_info(f"Extension du LV '{full_lv_path}' de {size_str}", log_levels=log_levels)
        opt = '-L' # Taille absolue (avec +)
        # Si l'utilisateur a passé un pourcentage explicite
        if '%' in size_str: opt = '-l'
        cmd_extend = ['lvextend', opt, size_str, full_lv_path]

        use_integrated_resizefs = False
        if resize_fs:
            # Vérifier si le FS est supporté par lvextend --resizefs (principalement ext* et xfs monté)
            fs_type = self._storage_cmd.get_filesystem_info(full_lv_path).get('TYPE') if self._storage_cmd else None
            is_mounted = self._storage_cmd.is_mounted(full_lv_path) if self._storage_cmd else False
            if fs_type and (fs_type.startswith('ext') or (fs_type == 'xfs' and is_mounted)):
                cmd_extend.append('--resizefs')
                use_integrated_resizefs = True
                self.log_info("  Utilisation de l'option --resizefs.", log_levels=log_levels)
            else:
                 self.log_info("  --resizefs non utilisé (FS non supporté ou non monté pour XFS). Redimensionnement manuel tenté après.", log_levels=log_levels)

        success, stdout, stderr = self.run(cmd_extend, check=False, needs_sudo=True)

        if not success:
            if "insufficient free space" in stderr.lower() or "not enough free extents" in stderr.lower():
                 self.log_error(f"Échec: Espace insuffisant dans le VG pour étendre {full_lv_path}.", log_levels=log_levels)
            elif "failed to find" in stderr.lower() or "not found" in stderr.lower():
                 self.log_error(f"Échec: Le LV '{full_lv_path}' n'a pas été trouvé.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de l'extension du LV '{full_lv_path}'. Stderr: {stderr}", log_levels=log_levels)
            return False

        self.log_success(f"LV '{full_lv_path}' étendu avec succès.", log_levels=log_levels)
        if stdout: self.log_info(f"Sortie lvextend:\n{stdout}", log_levels=log_levels)

        # Si l'option --resizefs n'a pas été utilisée mais resize_fs=True, tenter manuellement
        if resize_fs and not use_integrated_resizefs:
            return self.resize_filesystem(full_lv_path)
        elif use_integrated_resizefs and "fsadm failed" in stderr.lower():
             self.log_error("L'option --resizefs intégrée a échoué. Vérifier manuellement le système de fichiers.", log_levels=log_levels)
             return False # Échec du redimensionnement FS
        else:
             return True # Extension LV réussie, FS non demandé ou fait par --resizefs


    def resize_filesystem(self, lv_path: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Redimensionne le FS sur un LV. Dépend de StorageCommands."""
        # ... (identique mais gère la dépendance optionnelle) ...
        if not self._storage_cmd:
            self.log_error("StorageCommands non disponible, impossible de redimensionner le FS.", log_levels=log_levels)
            return False

        self.log_info(f"Tentative de redimensionnement du système de fichiers sur {lv_path}", log_levels=log_levels)
        fs_info = self._storage_cmd.get_filesystem_info(lv_path)
        fs_type = fs_info.get('TYPE') if fs_info else None

        if not fs_type:
            self.log_error(f"Impossible de détecter le type de système de fichiers sur {lv_path}.", log_levels=log_levels)
            return False

        self.log_info(f"Système de fichiers détecté: {fs_type}", log_levels=log_levels)

        resize_cmd: Optional[List[str]] = None
        mount_point = None # Initialiser
        mount_info = self._storage_cmd.get_mount_info(lv_path)
        if mount_info:
             mount_point = mount_info[0].get('TARGET')

        if fs_type.startswith('ext'):
            resize_cmd = ['resize2fs', lv_path]
        elif fs_type == 'xfs':
            if mount_point:
                resize_cmd = ['xfs_growfs', mount_point]
            else:
                self.log_error(f"Impossible de trouver le point de montage pour {lv_path} (requis pour xfs_growfs).", log_levels=log_levels)
                return False
        elif fs_type == 'btrfs':
            if mount_point:
                resize_cmd = ['btrfs', 'filesystem', 'resize', 'max', mount_point]
            else:
                self.log_error(f"Impossible de trouver le point de montage pour {lv_path} (requis pour btrfs resize).", log_levels=log_levels)
                return False

        if not resize_cmd:
            self.log_warning(f"Le redimensionnement pour le FS '{fs_type}' n'est pas supporté automatiquement.", log_levels=log_levels)
            return True # Considérer comme succès partiel (LV étendu)

        self.log_info(f"Exécution: {' '.join(resize_cmd)}", log_levels=log_levels)
        success, stdout, stderr = self.run(resize_cmd, check=False, needs_sudo=True)

        if success:
            self.log_success(f"Système de fichiers sur {lv_path} redimensionné avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie redimensionnement:\n{stdout}", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du redimensionnement du FS sur {lv_path}. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie redimensionnement (échec):\n{stdout}", log_levels=log_levels)
            return False

    def reduce_lv(self, lv_path_or_name: str, new_size: Union[str, int],
                  units: str = 'G', resize_fs: bool = True,
                  unmount_required: bool = True, force_fsck: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Réduit la taille d'un LV et de son FS. DANGEREUX."""
        # ... (identique) ...
        full_lv_path = self._resolve_lv_path(lv_path_or_name)
        if not full_lv_path: return False
        try:
            new_size_str = self._format_lvm_size(new_size, units)
            new_size_bytes = self._lvm_size_to_bytes(new_size_str)
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False

        self.log_warning(f"Réduction du LV '{full_lv_path}' à {new_size_str} - OPÉRATION RISQUÉE !", log_levels=log_levels)

        lv_info = self.get_lv_info(full_lv_path)
        if not lv_info or 'lv_size' not in lv_info:
            self.log_error(f"Impossible d'obtenir la taille actuelle de {full_lv_path}", log_levels=log_levels)
            return False
        # lv_size est déjà en octets
        current_size_bytes = int(lv_info.get('lv_size', 0))

        if new_size_bytes >= current_size_bytes:
            self.log_error(f"La nouvelle taille ({new_size_str}) doit être inférieure à la taille actuelle.", log_levels=log_levels)
            return False

        mount_point = None
        fs_type = None
        needs_umount = unmount_required
        was_mounted = False # Pour savoir s'il faut remonter

        if self._storage_cmd:
            mount_info = self._storage_cmd.get_mount_info(full_lv_path)
            if mount_info:
                was_mounted = True
                mount_point = mount_info[0].get('TARGET')
                fs_info = self._storage_cmd.get_filesystem_info(full_lv_path)
                fs_type = fs_info.get('TYPE') if fs_info else None
                self.log_info(f"LV est monté sur {mount_point} (FS: {fs_type or 'inconnu'})", log_levels=log_levels)

                if fs_type == 'btrfs': needs_umount = False
                if fs_type == 'xfs':
                     self.log_error("XFS ne supporte PAS la réduction de taille.", log_levels=log_levels)
                     return False

                if needs_umount and mount_point:
                    self.log_info(f"Démontage de {mount_point} nécessaire...")
                    # Utiliser la commande umount de storage si disponible, sinon fallback
                    if hasattr(self._storage_cmd, 'umount'):
                         success_umount = self._storage_cmd.umount(mount_point)
                    else:
                         success_umount, _, _ = self.run(['umount', mount_point], check=False, needs_sudo=True)
                    if not success_umount:
                        self.log_error(f"Échec du démontage de {mount_point}. Annulation.", log_levels=log_levels)
                        return False
                elif not needs_umount:
                    self.log_info("Réduction online supportée (ou pas de démontage requis).", log_levels=log_levels)
            else:
                needs_umount = False
                fs_info = self._storage_cmd.get_filesystem_info(full_lv_path)
                fs_type = fs_info.get('TYPE') if fs_info else None
                if fs_type == 'xfs':
                     self.log_error("XFS ne supporte PAS la réduction de taille.", log_levels=log_levels)
                     return False
        else:
             self.log_warning("StorageCommands indisponible, impossible de vérifier montage/FS. Poursuite risquée...", log_levels=log_levels)
             if resize_fs:
                  self.log_error("Impossible de réduire le FS car StorageCommands est manquant.", log_levels=log_levels)
                  return False

        success_fs_reduce = True
        if resize_fs and fs_type:
            self.log_info(f"Réduction du système de fichiers ({fs_type}) sur {full_lv_path} à {new_size_str}...")
            reduce_fs_cmd: Optional[List[str]] = None
            # Passer la taille cible au FS (souvent la même que le LV)
            fs_size_arg = new_size_str

            if fs_type.startswith('ext'):
                if force_fsck:
                    self.log_info("Exécution de e2fsck -f...")
                    success_fsck, _, err_fsck = self.run(['e2fsck', '-f', '-y', full_lv_path], check=False, needs_sudo=True)
                    if not success_fsck:
                        self.log_error(f"e2fsck a échoué sur {full_lv_path}. Stderr: {err_fsck}. Annulation.", log_levels=log_levels)
                        success_fs_reduce = False
                    else:
                        reduce_fs_cmd = ['resize2fs', full_lv_path, fs_size_arg]
                else:
                     reduce_fs_cmd = ['resize2fs', full_lv_path, fs_size_arg]
            elif fs_type == 'btrfs':
                if mount_point: # BTRFS resize nécessite le point de montage
                    reduce_fs_cmd = ['btrfs', 'filesystem', 'resize', new_size_str, mount_point]
                else: # Doit être monté pour btrfs resize
                    self.log_error("BTRFS doit être monté pour être réduit (même si online).", log_levels=log_levels)
                    success_fs_reduce = False
            else:
                self.log_warning(f"La réduction auto du FS '{fs_type}' n'est pas supportée.", log_levels=log_levels)
                success_fs_reduce = False

            if reduce_fs_cmd and success_fs_reduce:
                success_fs, _, err_fs = self.run(reduce_fs_cmd, check=False, needs_sudo=True)
                if not success_fs:
                    self.log_error(f"Échec de la réduction du FS sur {full_lv_path}. Stderr: {err_fs}", log_levels=log_levels)
                    success_fs_reduce = False

        elif resize_fs and not fs_type:
            self.log_warning("Impossible de redimensionner le FS : type inconnu.", log_levels=log_levels)
            success_fs_reduce = False

        success_lv_reduce = False
        if success_fs_reduce:
            self.log_info(f"Réduction du LV '{full_lv_path}' à {new_size_str}...")
            cmd_reduce = ['lvreduce', '-L', new_size_str, '-f', full_lv_path]
            success_lv, stdout_lv, err_lv = self.run(cmd_reduce, check=False, needs_sudo=True)
            if success_lv:
                self.log_success(f"LV '{full_lv_path}' réduit à {new_size_str}.", log_levels=log_levels)
                if stdout_lv: self.log_info(f"Sortie lvreduce:\n{stdout_lv}", log_levels=log_levels)
                success_lv_reduce = True
            else:
                self.log_error(f"Échec de la réduction du LV '{full_lv_path}'. Stderr: {err_lv}", log_levels=log_levels)
        else:
            self.log_error("Annulation de la réduction LV car la réduction FS a échoué ou n'était pas possible/demandée.", log_levels=log_levels)

        # Remonter le FS si on l'a démonté
        if was_mounted and needs_umount and mount_point:
            self.log_info(f"Remontage de {mount_point}...")
            time.sleep(1)
            # Utiliser la commande mount de storage si disponible
            if hasattr(self._storage_cmd, 'mount'):
                 success_mount = self._storage_cmd.mount(full_lv_path, mount_point)
            else:
                 success_mount, _, err_mount = self.run(['mount', mount_point], check=False, needs_sudo=True)
            if not success_mount:
                 self.log_warning(f"Échec du remontage de {mount_point}. Vérification manuelle requise.", log_levels=log_levels)

        return success_lv_reduce

    def rename_vg(self, old_vg_name: str, new_vg_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Renomme un Volume Group."""
        # ... (identique) ...
        self.log_info(f"Renommage du VG '{old_vg_name}' en '{new_vg_name}'", log_levels=log_levels)
        cmd = ['vgrename', old_vg_name, new_vg_name]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"VG renommé avec succès de '{old_vg_name}' en '{new_vg_name}'.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie vgrename:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "not found" in stderr.lower():
                 self.log_error(f"Échec: Le VG source '{old_vg_name}' n'existe pas.", log_levels=log_levels)
            elif "already exists" in stderr.lower():
                 self.log_error(f"Échec: Le nom de VG destination '{new_vg_name}' existe déjà.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec du renommage du VG '{old_vg_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Commandes de Suppression ---

    def remove_lv(self, lv_path_or_name: str, force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un Logical Volume."""
        # ... (amélioration gestion erreur "not found") ...
        full_lv_path = self._resolve_lv_path(lv_path_or_name)
        if not full_lv_path: return False

        if self._storage_cmd and self._storage_cmd.is_mounted(full_lv_path):
            self.log_error(f"Le LV '{full_lv_path}' est monté. Veuillez le démonter d'abord.", log_levels=log_levels)
            return False

        self.log_warning(f"Suppression du LV: {full_lv_path} - OPÉRATION DESTRUCTIVE !", log_levels=log_levels)
        cmd = ['lvremove']
        if force: cmd.append('-f')
        cmd.append(full_lv_path)

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"LV '{full_lv_path}' supprimé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvremove:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "y/n" in stderr and not force:
                self.log_error(f"Échec suppression LV '{full_lv_path}': Confirmation requise. Utiliser force=True.", log_levels=log_levels)
            elif "failed to find" in stderr.lower() or "not found" in stderr.lower():
                self.log_warning(f"LV '{full_lv_path}' non trouvé (déjà supprimé?).", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Échec de la suppression du LV '{full_lv_path}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def remove_vg(self, vg_name: str, force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un Volume Group (doit être vide)."""
        # ... (amélioration gestion erreur "not found") ...
        self.log_warning(f"Suppression du VG: {vg_name} - OPÉRATION DESTRUCTIVE !", log_levels=log_levels)
        cmd = ['vgremove']
        if force: cmd.append('-f')
        cmd.append(vg_name)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"VG '{vg_name}' supprimé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie vgremove:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "still contains" in stderr and "logical volume" in stderr:
                self.log_error(f"Échec: Le VG '{vg_name}' contient encore des LVs. Supprimez-les d'abord.", log_levels=log_levels)
            elif "not found" in stderr.lower():
                self.log_warning(f"VG '{vg_name}' non trouvé (déjà supprimé?).", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Échec de la suppression du VG '{vg_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def remove_pv(self, device: str, force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un Physical Volume (ne doit appartenir à aucun VG)."""
        # ... (amélioration gestion erreur "not found") ...
        self.log_warning(f"Suppression du PV: {device} - OPÉRATION DESTRUCTIVE !", log_levels=log_levels)
        cmd = ['pvremove', '-y']
        if force: cmd.append('-ff')
        cmd.append(device)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"PV '{device}' supprimé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie pvremove:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "used by volume group" in stderr.lower():
                self.log_error(f"Échec: Le PV '{device}' est encore utilisé par un VG.", log_levels=log_levels)
            elif "cannot physical volume" in stderr.lower() and "not found" in stderr.lower():
                self.log_warning(f"PV '{device}' non trouvé (déjà supprimé?).", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Échec de la suppression du PV '{device}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Gestion des Snapshots ---

    def create_lv_snapshot(self, lv_path_or_name: str, snapshot_name: str, size: Union[str, int],
                           units: str = 'G', tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un snapshot LVM."""
        # ... (ajout tags) ...
        origin_lv_path = self._resolve_lv_path(lv_path_or_name)
        if not origin_lv_path: return False
        try:
            size_str = self._format_lvm_size(size, units)
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False

        self.log_info(f"Création du snapshot '{snapshot_name}' pour LV '{origin_lv_path}' (taille: {size_str})", log_levels=log_levels)
        cmd = ['lvcreate', '--snapshot', '-L', size_str, '--name', snapshot_name, origin_lv_path]
        if tags:
             cmd.extend(['--addtag', ",".join(tags)])
             self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Snapshot '{snapshot_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
             if "already exists" in stderr.lower():
                  self.log_warning(f"Le snapshot '{snapshot_name}' existe déjà.", log_levels=log_levels)
                  return True
             elif "insufficient free space" in stderr.lower():
                  self.log_error(f"Échec: Espace insuffisant pour créer le snapshot '{snapshot_name}' de taille {size_str}.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec de la création du snapshot '{snapshot_name}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    def remove_lv_snapshot(self, snapshot_path_or_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un snapshot LVM."""
        # ... (identique) ...
        self.log_warning(f"Suppression du snapshot : {snapshot_path_or_name}", log_levels=log_levels)
        return self.remove_lv(snapshot_path_or_name, force=True)

    def merge_lv_snapshot(self, snapshot_path_or_name: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Fusionne un snapshot actif dans son volume d'origine."""
        # ... (identique) ...
        snapshot_path = self._resolve_lv_path(snapshot_path_or_name)
        if not snapshot_path: return False

        lv_info = self.get_lv_info(snapshot_path)
        if not lv_info or 'O' not in lv_info.get('lv_attr', '') or lv_info.get('origin') is None:
             self.log_error(f"'{snapshot_path}' n'est pas un snapshot LVM valide ou n'a pas d'origine.", log_levels=log_levels)
             return False

        self.log_info(f"Fusion du snapshot '{snapshot_path}' dans son origine '{lv_info.get('origin')}'...", log_levels=log_levels)
        cmd = ['lvconvert', '--merge', snapshot_path]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True, timeout=7200)
        if success:
            if "Merging of snapshot" in stdout and "will occur on next activation" in stdout:
                 self.log_warning(f"La fusion du snapshot '{snapshot_path}' est programmée pour la prochaine activation.", log_levels=log_levels)
            else:
                 self.log_success(f"Snapshot '{snapshot_path}' fusionné (ou programmé pour fusion).", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvconvert --merge:\n{stdout}", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la fusion du snapshot '{snapshot_path}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Gestion Thin Provisioning ---

    def create_thin_pool(self, vg_name: str, pool_name: str, size: Union[str, int],
                         units: str = 'G', metadata_size: Optional[Union[str, int]] = None,
                         metadata_units: str = 'M', tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un Thin Pool LVM."""
        # ... (ajout tags, meilleure gestion erreurs taille) ...
        try:
            size_str = self._format_lvm_size(size, units)
        except ValueError as e:
            self.log_error(f"Erreur format taille pool: {e}", log_levels=log_levels)
            return False

        pool_lv_name = pool_name
        self.log_info(f"Création du Thin Pool '{pool_lv_name}' dans VG '{vg_name}' (taille: {size_str})", log_levels=log_levels)
        cmd = ['lvcreate', '--type', 'thin-pool', '-L', size_str, '--name', pool_lv_name, vg_name]

        if metadata_size:
             try:
                  meta_size_str = self._format_lvm_size(metadata_size, metadata_units)
                  cmd.extend(['--poolmetadatasize', meta_size_str])
                  self.log_info(f"  Taille métadonnées: {meta_size_str}", log_levels=log_levels)
             except ValueError as e:
                  self.log_warning(f"Format taille métadonnées invalide ('{metadata_size}'), ignoré: {e}", log_levels=log_levels)
        if tags:
             cmd.extend(['--addtag', ",".join(tags)])
             self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Thin Pool '{pool_lv_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
             if "already exists" in stderr.lower():
                  self.log_warning(f"Le Thin Pool '{pool_lv_name}' existe déjà.", log_levels=log_levels)
                  return True
             elif "insufficient free space" in stderr.lower():
                  self.log_error(f"Échec: Espace insuffisant dans VG '{vg_name}' pour créer le pool '{pool_lv_name}'.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec de la création du Thin Pool '{pool_lv_name}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    def create_thin_lv(self, vg_name: str, pool_name: str, lv_name: str, size: Union[str, int],
                       units: str = 'G', tags: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un Thin Logical Volume dans un Thin Pool."""
        # ... (ajout tags, meilleure gestion erreurs taille) ...
        try:
            size_str = self._format_lvm_size(size, units)
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False

        pool_path = f"{vg_name}/{pool_name}"
        self.log_info(f"Création du Thin LV '{lv_name}' dans Pool '{pool_path}' (taille virtuelle: {size_str})", log_levels=log_levels)
        # Utiliser -V pour taille virtuelle
        cmd = ['lvcreate', '-V', size_str, '--thin', '--name', lv_name, pool_path]
        if tags:
             cmd.extend(['--addtag', ",".join(tags)])
             self.log_info(f"  Avec tags: {tags}", log_levels=log_levels)

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Thin LV '{lv_name}' créé avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvcreate:\n{stdout}", log_levels=log_levels)
            return True
        else:
            if "already exists" in stderr.lower():
                 self.log_warning(f"Le Thin LV '{lv_name}' existe déjà dans {pool_path}.", log_levels=log_levels)
                 return True
            elif "does not exist" in stderr.lower() and f"'{pool_path}'" in stderr.lower():
                 self.log_error(f"Échec: Le Thin Pool '{pool_path}' n'existe pas.", log_levels=log_levels)
            elif "pool is low on space" in stderr.lower():
                 self.log_error(f"Échec: Le Thin Pool '{pool_path}' manque d'espace physique (ou metadata).", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de la création du Thin LV '{lv_name}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def extend_thin_pool(self, vg_name: str, pool_name: str, size_increase: Union[str, int],
                         units: str = 'G', resize_metadata: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Étend un Thin Pool existant."""
        try:
            size_str = self._format_lvm_size(size_increase, units)
            if not size_str.startswith('+'): size_str = f"+{size_str}"
        except ValueError as e:
            self.log_error(f"Erreur de format de taille : {e}", log_levels=log_levels)
            return False

        pool_path = f"{vg_name}/{pool_name}"
        self.log_info(f"Extension du Thin Pool '{pool_path}' de {size_str}", log_levels=log_levels)
        cmd = ['lvextend', '-L', size_str, pool_path]
        # Pas d'option directe pour redimensionner les métadonnées en même temps avec lvextend,
        # LVM le fait souvent automatiquement ou c'est géré par des vérifications périodiques.
        # Si resize_metadata est True, on pourrait ajouter un check de l'état des métadonnées après.
        if resize_metadata:
            self.log_debug("La taille des métadonnées est généralement gérée automatiquement.", log_levels=log_levels)

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Thin Pool '{pool_path}' étendu avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie lvextend:\n{stdout}", log_levels=log_levels)
            return True
        else:
             if "insufficient free space" in stderr.lower() or "not enough free extents" in stderr.lower():
                  self.log_error(f"Échec: Espace insuffisant dans VG '{vg_name}' pour étendre le pool '{pool_name}'.", log_levels=log_levels)
             elif "not found" in stderr.lower():
                  self.log_error(f"Échec: Le Thin Pool '{pool_path}' n'existe pas.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec de l'extension du Thin Pool '{pool_path}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    # --- Gestion des Tags ---

    def add_tag(self, lvm_object_path: str, tag: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Ajoute un tag à un PV, VG ou LV."""
        # ... (identique) ...
        self.log_info(f"Ajout du tag '{tag}' à {lvm_object_path}", log_levels=log_levels)
        cmd: List[str] = []
        # Identifier le type d'objet pour choisir la bonne commande
        if os.path.exists(lvm_object_path) and os.path.isblock(lvm_object_path): # Probablement un PV
            cmd = ['pvchange', '--addtag', tag, lvm_object_path]
        else:
            # Essayer de résoudre comme LV, sinon supposer VG
            full_path = self._resolve_lv_path(lvm_object_path)
            if full_path: # C'est un LV
                cmd = ['lvchange', '--addtag', tag, full_path]
            else: # Supposer que c'est un VG
                # Vérifier si le VG existe
                vg_info = self.get_vg_info(lvm_object_path)
                if vg_info:
                     cmd = ['vgchange', '--addtag', tag, lvm_object_path]
                else:
                     self.log_error(f"Impossible de déterminer le type ou trouver l'objet LVM: '{lvm_object_path}'", log_levels=log_levels)
                     return False

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Tag '{tag}' ajouté à {lvm_object_path}.", log_levels=log_levels)
            return True
        else:
            # Gérer erreur si tag existe déjà (souvent code 0 mais message stderr)
            if "already exists" in stderr.lower():
                 self.log_warning(f"Le tag '{tag}' existe déjà sur {lvm_object_path}.", log_levels=log_levels)
                 return True
            self.log_error(f"Échec de l'ajout du tag '{tag}' à {lvm_object_path}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def remove_tag(self, lvm_object_path: str, tag: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un tag d'un PV, VG ou LV."""
        # ... (identique) ...
        self.log_info(f"Suppression du tag '{tag}' de {lvm_object_path}", log_levels=log_levels)
        cmd: List[str] = []
        if os.path.exists(lvm_object_path) and os.path.isblock(lvm_object_path):
            cmd = ['pvchange', '--deltag', tag, lvm_object_path]
        else:
            full_path = self._resolve_lv_path(lvm_object_path)
            if full_path:
                cmd = ['lvchange', '--deltag', tag, full_path]
            else:
                vg_info = self.get_vg_info(lvm_object_path)
                if vg_info:
                     cmd = ['vgchange', '--deltag', tag, lvm_object_path]
                else:
                     self.log_error(f"Impossible de déterminer le type ou trouver l'objet LVM: '{lvm_object_path}'", log_levels=log_levels)
                     return False

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Tag '{tag}' supprimé de {lvm_object_path}.", log_levels=log_levels)
            return True
        else:
            if "not found" in stderr.lower() and f"'{tag}'" in stderr:
                 self.log_warning(f"Le tag '{tag}' n'existait pas sur {lvm_object_path}.", log_levels=log_levels)
                 return True
            self.log_error(f"Échec de la suppression du tag '{tag}' de {lvm_object_path}. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Autres opérations avancées ---

    def move_pv_extents(self, source_pv: str, dest_pv: Optional[str] = None,
                        lv_path_or_name: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Déplace les extents d'un PV vers d'autres PVs dans le même VG."""
        # ... (renommé lv_path en lv_path_or_name) ...
        action_log = f"Déplacement des extents de {source_pv}"
        if dest_pv: action_log += f" vers {dest_pv}"
        if lv_path_or_name:
             full_lv_path = self._resolve_lv_path(lv_path_or_name)
             if not full_lv_path: return False
             action_log += f" pour LV {full_lv_path}"
        self.log_info(action_log, log_levels=log_levels)
        self.log_warning("L'opération pvmove peut être longue !", log_levels=log_levels)

        cmd = ['pvmove']
        # Ajouter -i N pour intervalle de rapport (ex: -i 10 pour toutes les 10s)
        cmd.extend(['-i', '10'])
        if lv_path_or_name:
            full_lv_path = self._resolve_lv_path(lv_path_or_name) # Re-résoudre au cas où
            if not full_lv_path: return False
            cmd.extend(['-n', full_lv_path])

        cmd.append(source_pv)
        if dest_pv: cmd.append(dest_pv)

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True, timeout=None, real_time_output=True, show_progress=True)

        if success:
            self.log_success(f"Extents de {source_pv} déplacés avec succès.", log_levels=log_levels)
            return True
        else:
             if "check required" in stderr.lower():
                  self.log_error(f"Échec pvmove: Problème de cohérence détecté pour {source_pv}. Vérification VG/LV nécessaire.", log_levels=log_levels)
             elif "sufficient free space" in stderr.lower():
                  self.log_error(f"Échec pvmove: Espace insuffisant sur le(s) PV(s) de destination.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec du déplacement des extents de {source_pv}. Stderr: {stderr}", log_levels=log_levels)
             return False

    def resize_pv(self, pv_device: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Redimensionne un PV après agrandissement du périphérique sous-jacent."""
        # ... (identique) ...
        self.log_info(f"Redimensionnement du PV {pv_device} pour utiliser l'espace disponible", log_levels=log_levels)
        cmd = ['pvresize', pv_device]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"PV {pv_device} redimensionné avec succès.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie pvresize:\n{stdout}", log_levels=log_levels)
            return True
        else:
             if "nothing to resize" in stderr.lower():
                  self.log_info(f"Aucun espace supplémentaire détecté pour redimensionner PV {pv_device}.", log_levels=log_levels)
                  return True # Pas une erreur
             self.log_error(f"Échec du redimensionnement du PV {pv_device}. Stderr: {stderr}", log_levels=log_levels)
             return False

    def reduce_vg(self, vg_name: str, pv_device: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un PV d'un VG (le PV doit être vide d'extents LVM)."""
        # ... (identique) ...
        self.log_info(f"Suppression du PV {pv_device} du VG {vg_name}", log_levels=log_levels)
        pv_info = self.get_pv_info(pv_device)
        # pv_used est en octets
        if pv_info and int(pv_info.get('pv_used', 1)) > 0:
             pv_used_mb = int(pv_info.get('pv_used', 1)) / (1024*1024)
             self.log_error(f"Le PV {pv_device} n'est pas vide (utilisé: {pv_used_mb:.2f} Mo). Utiliser pvmove d'abord.", log_levels=log_levels)
             return False

        cmd = ['vgreduce', vg_name, pv_device]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"PV {pv_device} retiré du VG {vg_name}.", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie vgreduce:\n{stdout}", log_levels=log_levels)
            return True
        else:
             if "Cannot remove final" in stderr:
                  self.log_error(f"Échec: Impossible de retirer le dernier PV ({pv_device}) du VG {vg_name}.", log_levels=log_levels)
             elif "not found" in stderr.lower() and f"'{pv_device}'" in stderr.lower():
                  self.log_error(f"Échec: Le PV '{pv_device}' n'appartient pas au VG '{vg_name}' ou n'existe pas.", log_levels=log_levels)
             else:
                  self.log_error(f"Échec de la suppression du PV {pv_device} du VG {vg_name}. Stderr: {stderr}", log_levels=log_levels)
             return False

    # --- Fonctions Helper ---

    def _resolve_lv_path(self, lv_path_or_name: str) -> Optional[str]:
        """Tente de résoudre un nom de LV (relatif ou absolu) en chemin complet."""
        # ... (identique) ...
        if not lv_path_or_name: return None

        if lv_path_or_name.startswith('/dev/'):
            success, _, _ = self.run(['test', '-b', lv_path_or_name], check=False, no_output=True, error_as_warning=True, needs_sudo=False)
            if success:
                 return lv_path_or_name
            else:
                 self.log_warning(f"Chemin absolu LV '{lv_path_or_name}' invalide. Tentative résolution...", log_levels=log_levels)
                 # Continuer pour essayer comme vg/lv

        cmd = ['lvs', '--noheadings', '-o', 'lv_path', lv_path_or_name]
        success_lvs, stdout_lvs, stderr_lvs = self.run(cmd, check=False, no_output=True)

        if success_lvs and stdout_lvs.strip():
            full_path = stdout_lvs.strip().splitlines()[0]
            self.log_debug(f"Chemin LV résolu pour '{lv_path_or_name}' -> '{full_path}'", log_levels=log_levels)
            return full_path
        else:
            self.log_error(f"Impossible de trouver le LV '{lv_path_or_name}'. Stderr lvs: {stderr_lvs}", log_levels=log_levels)
            return None

# Fin de la classe LvmCommands