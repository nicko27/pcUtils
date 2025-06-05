# install/plugins/plugins_utils/efi.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour gérer les variables et entrées de démarrage EFI via efibootmgr.
ATTENTION : Les modifications EFI sont critiques et peuvent empêcher le système de démarrer.
Inclut des vérifications et des considérations pour le dépannage.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import shlex
import json  # Ajout de l'import manquant
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class EfiCommands(PluginsUtilsBase):
    """
    Classe pour gérer les entrées de démarrage EFI via efibootmgr.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    ESP_MOUNT_POINTS = ["/boot/efi", "/boot", "/efi"] # Chemins courants pour l'ESP

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire EFI."""
        super().__init__(logger, target_ip)
        self._efibootmgr_path: Optional[str] = None
        self._findmnt_path: Optional[str] = None
        self._check_commands()
        self._is_efi = self._is_efi_system() # Vérifier une fois à l'initialisation

    def _check_commands(self):
        """Vérifie la présence des commandes nécessaires."""
        cmds_to_check = {
            'efibootmgr': '_efibootmgr_path',
            'findmnt': '_findmnt_path'
        }
        missing = []
        for cmd, attr_name in cmds_to_check.items():
            success, path, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if success and path.strip():
                setattr(self, attr_name, path.strip())
                self.log_debug(f"Commande '{cmd}' trouvée: {path.strip()}")
            else:
                missing.append(cmd)
                setattr(self, attr_name, None)

        if 'efibootmgr' in missing:
            self.log_error("Commande 'efibootmgr' non trouvée. Ce module ne fonctionnera pas.")
        if 'findmnt' in missing:
            self.log_warning("Commande 'findmnt' non trouvée. La détection auto de l'ESP échouera.")

    def _is_efi_system(self) -> bool:
        """Vérifie si le système a démarré en mode EFI en testant l'existence de /sys/firmware/efi."""
        is_efi, _, _ = self.run(['test', '-d', '/sys/firmware/efi'], check=False, no_output=True, needs_sudo=False)
        if not is_efi:
            self.log_warning("Le système ne semble pas démarré en mode EFI (/sys/firmware/efi absent). Les commandes efibootmgr échoueront probablement.")
        else:
            self.log_debug("Système démarré en mode EFI.")
        return is_efi

    def _get_esp_path(self) -> Optional[Path]:
        """Tente de trouver le point de montage de la partition EFI (ESP)."""
        if not self._findmnt_path:
            self.log_warning("Commande findmnt non trouvée, impossible de localiser l'ESP automatiquement.")
            # Essayer les chemins par défaut
            for p in self.ESP_MOUNT_POINTS:
                 path_obj = Path(p)
                 if path_obj.is_dir() and path_obj.is_mount():
                      self.log_info(f"ESP potentiellement trouvé sur (chemin par défaut): {p}")
                      return path_obj
            self.log_error("Impossible de deviner le chemin de l'ESP.")
            return None

        # Utiliser findmnt pour chercher le type vfat et le flag 'boot,esp' ou juste vfat sur /boot/efi etc.
        cmd = [self._findmnt_path, '-J', '-t', 'vfat', '--evaluate']
        success, stdout, stderr = self.run(cmd, check=False, no_output=True, needs_sudo=False)

        if success and stdout:
            try:
                data = json.loads(stdout)
                if 'filesystems' in data:
                    for fs in data['filesystems']:
                        # La partition ESP a souvent 'esp' dans ses options ou est montée sur un chemin standard
                        options = fs.get('options', '')
                        target = fs.get('target', '')
                        # Les options exactes peuvent varier, 'boot,esp' est courant avec systemd-boot
                        # Vérifier aussi les points de montage standards
                        if ('esp' in options and 'boot' in options) or target in self.ESP_MOUNT_POINTS:
                            self.log_info(f"Partition ESP trouvée sur: {target} (Source: {fs.get('source')})")
                            return Path(target)
            except json.JSONDecodeError:
                self.log_warning("Erreur parsing JSON de findmnt pour ESP.")
            except Exception as e:
                 self.log_warning(f"Erreur inattendue recherche ESP: {e}")

        # Fallback : vérifier les chemins standards explicitement
        for p in self.ESP_MOUNT_POINTS:
             path_obj = Path(p)
             if path_obj.is_dir() and path_obj.is_mount():
                  self.log_info(f"ESP potentiellement trouvé sur (chemin par défaut): {p}")
                  return path_obj

        self.log_error("Partition ESP (EFI System Partition) non trouvée ou non montée. Les opérations de création d'entrée peuvent échouer.")
        return None

    def _parse_efibootmgr_output(self, output: str) -> Dict[str, Any]:
        """Parse la sortie texte standard d'efibootmgr."""
        parsed_data = {'Entries': {}}
        lines = output.splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue

            try:
                if line.startswith('BootCurrent:'):
                    parsed_data['BootCurrent'] = line.split(':')[1].strip()
                elif line.startswith('Timeout:'):
                    parsed_data['Timeout'] = int(line.split(':')[1].split()[0])
                elif line.startswith('BootOrder:'):
                    parsed_data['BootOrder'] = line.split(':')[1].strip().split(',')
                elif line.startswith('Boot'):
                     # Format: BootXXXX* Label <Device Path Info> ou BootXXXX* Label File(...)
                     # Regex pour capturer numéro, flag actif, label, et le reste (chemin/fichier)
                     match = re.match(r"Boot([0-9A-F]{4})(\*?)\s+(.*?)\s+(.*)", line)
                     if match:
                          boot_num, active_flag, label, path_info = match.groups()
                          entry_data = {
                              'label': label.strip(),
                              'path_info': path_info.strip(),
                              'active': bool(active_flag),
                              'details': {} # Pour les infos verbose
                          }
                          parsed_data['Entries'][boot_num] = entry_data
                     else:
                          self.log_warning(f"Ligne d'entrée EFI non reconnue: '{line}'")
                # Gérer les lignes verbose (commencent par des espaces)
                elif line.startswith(' ') and parsed_data.get('Entries'):
                     # Trouver la dernière entrée ajoutée et y ajouter les détails
                     last_entry_num = list(parsed_data['Entries'].keys())[-1]
                     parsed_data['Entries'][last_entry_num]['details']['optional_data'] = line.strip()

            except Exception as e:
                self.log_warning(f"Erreur lors du parsing de la ligne efibootmgr '{line}': {e}")
                continue # Ignorer la ligne problématique

        return parsed_data

    def list_boot_entries(self, verbose: bool = False, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Liste les entrées de démarrage EFI. Nécessite potentiellement root.

        Args:
            verbose: Utiliser l'option -v pour plus de détails.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            Dictionnaire parsé de la sortie efibootmgr ou None si erreur.
        """
        if not self._is_efi: return None # Inutile de continuer si pas EFI
        if not self._efibootmgr_path: return None # Commande manquante

        self.log_info("Listage des entrées de démarrage EFI (efibootmgr)")
        cmd = [self._efibootmgr_path]
        if verbose: cmd.append('-v')

        # efibootmgr nécessite souvent root pour accéder aux variables EFI
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if not success:
            if "efi variables are not supported" in stderr.lower():
                self.log_warning("Le système ne semble pas supporter les variables EFI (ou module efivarfs non chargé).")
            elif "no such file or directory" in stderr.lower() and "efivars" in stderr.lower():
                 self.log_warning("Système de fichiers efivarfs non monté ou inaccessible.")
            else:
                self.log_error(f"Échec de efibootmgr. Stderr: {stderr}")
            return None

        try:
            parsed_data = self._parse_efibootmgr_output(stdout)
            self.log_info(f"{len(parsed_data.get('Entries', {}))} entrées EFI trouvées.")
            return parsed_data
        except Exception as e:
            self.log_error(f"Erreur lors du parsing de la sortie efibootmgr: {e}", exc_info=True)
            self.log_debug(f"Sortie efibootmgr brute:\n{stdout}")
            return None

    def create_boot_entry(self,
                          disk: str,
                          partition: int,
                          loader: str,
                          label: str,
                          optional_data: Optional[str] = None,
                          check_esp: bool = True,
                          check_loader: bool = True,
                          log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Crée une nouvelle entrée de démarrage EFI. Nécessite root.

        Args:
            disk: Disque contenant la partition EFI (ex: /dev/sda, /dev/nvme0n1).
            partition: Numéro de la partition EFI (ex: 1).
            loader: Chemin du chargeur EFI sur l'ESP (ex: \\EFI\\ubuntu\\grubx64.efi).
                    IMPORTANT: Utiliser des backslashes '\\' comme séparateurs.
                    Ce chemin est relatif à la racine de la partition ESP.
            label: Label pour l'entrée de démarrage (ex: "Ubuntu").
            optional_data: Données optionnelles à passer au chargeur (-u).
            check_esp: Si True, vérifie que l'ESP est montée.
            check_loader: Si True, vérifie que le fichier chargeur existe sur l'ESP montée.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si succès.
        """
        if not self._is_efi: return False
        if not self._efibootmgr_path: return False

        self.log_info(f"Tentative de création d'une entrée de démarrage EFI '{label}'")
        self.log_debug(f"  Disque: {disk}, Partition: {partition}, Loader: {loader}")
        self.log_warning("Assurez-vous que la partition EFI spécifiée est correcte et non cryptée.")
        self.log_warning("Assurez-vous que le chargeur ('loader') spécifié est capable de gérer le système (ex: déchiffrer les disques si nécessaire).")

        esp_path: Optional[Path] = None
        if check_esp or check_loader:
            esp_path = self._get_esp_path()
            if not esp_path:
                 self.log_error("Vérification ESP échouée. Impossible de continuer sans chemin ESP.")
                 return False

        if check_loader and esp_path:
             # Convertir le chemin du loader EFI (avec backslashes) en chemin système
             loader_parts = loader.strip('\\').split('\\')
             loader_system_path = esp_path.joinpath(*loader_parts)
             self.log_debug(f"Vérification de l'existence du chargeur: {loader_system_path}")
             # test -f nécessite sudo si l'ESP n'est pas lisible par l'utilisateur courant
             loader_exists, _, _ = self.run(['test', '-f', str(loader_system_path)], check=False, no_output=True, needs_sudo=True)
             if not loader_exists:
                  self.log_error(f"Le fichier chargeur spécifié '{loader}' ne semble pas exister sur l'ESP ({loader_system_path}).")
                  return False
             self.log_info(f"Fichier chargeur trouvé: {loader_system_path}")

        cmd = [self._efibootmgr_path, '-c', '-d', disk, '-p', str(partition), '-L', label, '-l', loader]
        if optional_data:
             cmd.extend(['-u', optional_data])

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
             self.log_success(f"Entrée EFI '{label}' créée avec succès.")
             if stdout: self.log_info(f"Sortie efibootmgr:\n{stdout}")
             # Suggérer de vérifier/mettre à jour l'ordre de boot
             self.log_info("Pensez à vérifier et ajuster l'ordre de démarrage (BootOrder) si nécessaire via 'set_boot_order'.")
             return True
        else:
             # Analyser les erreurs courantes
             if "could not prepare boot variable" in stderr.lower():
                  self.log_error(f"Échec création entrée EFI: Impossible de préparer la variable (problème NVRAM ou droits?). Stderr: {stderr}")
             elif "no space left on device" in stderr.lower():
                  self.log_error(f"Échec création entrée EFI: Espace insuffisant dans la NVRAM. Stderr: {stderr}")
             elif "invalid partition number" in stderr.lower():
                  self.log_error(f"Échec création entrée EFI: Numéro de partition '{partition}' invalide pour le disque '{disk}'. Stderr: {stderr}")
             else:
                  self.log_error(f"Échec de la création de l'entrée EFI '{label}'. Stderr: {stderr}")
             return False

    def delete_boot_entry(self, boot_num: Union[int, str], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime une entrée de démarrage EFI par son numéro. Nécessite root.

        Args:
            boot_num: Numéro de l'entrée EFI à supprimer.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si l'opération a réussi.
        """
        if not self._is_efi: return False
        if not self._efibootmgr_path: return False

        try:
            # Convertir en int puis en format hex 4 chiffres
            boot_num_hex = f"{int(boot_num):04X}"
        except ValueError:
            self.log_error(f"Numéro d'entrée EFI invalide: '{boot_num}'. Doit être un entier.")
            return False

        self.log_warning(f"Suppression de l'entrée de démarrage EFI Boot{boot_num_hex}")
        cmd = [self._efibootmgr_path, '-b', boot_num_hex, '-B']
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Entrée EFI Boot{boot_num_hex} supprimée.")
            if stdout: self.log_info(f"Sortie efibootmgr:\n{stdout}")
            return True
        else:
            if "could not delete" in stderr.lower() and ("no such file or directory" in stderr.lower() or "invalid argument" in stderr.lower()):
                self.log_warning(f"L'entrée EFI Boot{boot_num_hex} n'existait pas ou numéro invalide.")
                return True # Considéré comme succès car l'entrée n'est plus là
            self.log_error(f"Échec de la suppression de l'entrée EFI Boot{boot_num_hex}. Stderr: {stderr}")
            return False

    def set_boot_order(self, boot_order: List[Union[int, str]], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit l'ordre de démarrage EFI. Nécessite root.

        Args:
            boot_order: Liste des numéros d'entrées dans l'ordre souhaité.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si l'opération a réussi.
        """
        if not self._is_efi: return False
        if not self._efibootmgr_path: return False

        try:
            # Formater tous les numéros en hex 4 chiffres
            order_str = ",".join(f"{int(num):04X}" for num in boot_order)
        except ValueError:
            self.log_error(f"Ordre de démarrage invalide: {boot_order}. Contient des éléments non numériques.")
            return False

        self.log_info(f"Définition de l'ordre de démarrage EFI: {order_str}")
        cmd = [self._efibootmgr_path, '-o', order_str]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Ordre de démarrage EFI mis à jour: {order_str}.")
            if stdout: self.log_info(f"Sortie efibootmgr:\n{stdout}")
            return True
        else:
            # Gérer les numéros invalides
            if "invalid argument" in stderr.lower() or "not found" in stderr.lower():
                 self.log_error(f"Échec: Un ou plusieurs numéros dans l'ordre ({order_str}) sont invalides ou n'existent pas. Stderr: {stderr}")
            else:
                 self.log_error(f"Échec de la définition de l'ordre de démarrage EFI. Stderr: {stderr}")
            return False

    def set_boot_active(self, boot_num: Union[int, str], active: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Active ou désactive une entrée de démarrage EFI. Nécessite root.

        Args:
            boot_num: Numéro de l'entrée EFI.
            active: Si True, active l'entrée. Si False, la désactive.
            log_levels: Dictionnaire optionnel pour spécifier les niveaux de log (compatibilité).

        Returns:
            bool: True si l'opération a réussi.
        """
        if not self._is_efi: return False
        if not self._efibootmgr_path: return False

        try:
            boot_num_hex = f"{int(boot_num):04X}"
        except ValueError:
            self.log_error(f"Numéro d'entrée EFI invalide: '{boot_num}'.")
            return False

        action = "Activation" if active else "Désactivation"
        option = '-a' if active else '-A'
        self.log_info(f"{action} de l'entrée de démarrage EFI Boot{boot_num_hex}")
        cmd = [self._efibootmgr_path, '-b', boot_num_hex, option]

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Entrée EFI Boot{boot_num_hex} {'activée' if active else 'désactivée'}.")
            if stdout: self.log_info(f"Sortie efibootmgr:\n{stdout}")
            return True
        else:
            if "could not" in stderr.lower() and ("no such file or directory" in stderr.lower() or "invalid argument" in stderr.lower()):
                 self.log_error(f"Échec: L'entrée EFI Boot{boot_num_hex} n'existe pas ou est invalide.")
            else:
                 self.log_error(f"Échec de l'{action.lower()} de l'entrée EFI Boot{boot_num_hex}. Stderr: {stderr}")
            return False