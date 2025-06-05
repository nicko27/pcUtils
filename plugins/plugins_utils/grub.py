# install/plugins/plugins_utils/grub.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour interagir avec le chargeur d'amorçage GRUB (GRand Unified Bootloader).
ATTENTION : Les opérations sur GRUB sont critiques pour le démarrage du système.
Utilise les commandes grub-install, update-grub, grub-mkconfig et modifie /etc/default/grub.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
# Utilise ConfigFileCommands pour éditer /etc/default/grub
try:
    from plugins_utils.config_files import ConfigFileCommands
    CONFIG_FILES_AVAILABLE = True
except ImportError:
    CONFIG_FILES_AVAILABLE = False
    class ConfigFileCommands: # Factice
         def __init__(self, logger=None, target_ip=None): self.logger = logger
         def read_file_lines(self, path, **kwargs): return None
         def _write_file_content(self, path, content, backup=True, **kwargs): return False
         def set_ini_value(self, *args, **kwargs): return False # Simule une interface pour set_default_grub_value

import os
import re
import shlex
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class GrubCommands(PluginsUtilsBase):
    """
    Classe pour gérer la configuration et l'installation de GRUB.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    DEFAULT_GRUB_CONFIG = "/etc/default/grub"
    GRUB_CFG_PATHS = ["/boot/grub/grub.cfg", "/boot/grub2/grub.cfg"]

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire GRUB."""
        super().__init__(logger, target_ip)
        self._check_commands()
        # Initialiser ConfigFileCommands s'il est disponible
        self._cfg_mgr = ConfigFileCommands(self.logger, self.target_ip) if CONFIG_FILES_AVAILABLE else None
        if not CONFIG_FILES_AVAILABLE:
            self.log_warning("Module ConfigFileCommands non trouvé. La modification de /etc/default/grub sera désactivée.", log_levels=log_levels)
        # Trouver le chemin réel de grub.cfg
        self._grub_cfg_path = self._find_grub_cfg()

    def _check_commands(self):
        """Vérifie la présence des commandes GRUB et blkid."""
        cmds = ['grub-install', 'update-grub', 'grub-mkconfig', 'blkid']
        missing = []
        for cmd in cmds:
            success, _, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if not success:
                missing.append(cmd)
        if missing:
            self.log_warning(f"Commandes GRUB/blkid manquantes: {', '.join(missing)}. Certaines opérations pourraient échouer.", log_levels=log_levels)

    def _find_grub_cfg(self) -> Optional[str]:
        """Trouve le chemin du fichier grub.cfg principal."""
        for path in self.GRUB_CFG_PATHS:
             # Utiliser run pour vérifier l'existence, peut nécessiter sudo pour /boot
             exists, _, _ = self.run(['test', '-f', path], check=False, no_output=True, error_as_warning=True, needs_sudo=True)
             if exists:
                  self.log_debug(f"Fichier grub.cfg trouvé: {path}", log_levels=log_levels)
                  return path
        self.log_warning(f"Impossible de trouver le fichier grub.cfg aux emplacements standards: {self.GRUB_CFG_PATHS}", log_levels=log_levels)
        return None

    def update_grub_config(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Met à jour le fichier de configuration principal de GRUB (/boot/grub/grub.cfg).
        Utilise `update-grub` (Debian/Ubuntu) ou `grub-mkconfig`. Nécessite root.
        """
        self.log_info("Mise à jour de la configuration GRUB (grub.cfg)...", log_levels=log_levels)
        cmd_update: Optional[List[str]] = None

        # Détecter la commande à utiliser
        update_grub_exists, _, _ = self.run(['which', 'update-grub'], check=False, no_output=True, error_as_warning=True)
        grub_mkconfig_exists, _, _ = self.run(['which', 'grub-mkconfig'], check=False, no_output=True, error_as_warning=True)

        if update_grub_exists:
             cmd_update = ['update-grub']
        elif grub_mkconfig_exists:
             if not self._grub_cfg_path:
                  self.log_error("Commande 'grub-mkconfig' trouvée mais chemin de grub.cfg inconnu.", log_levels=log_levels)
                  return False
             cmd_update = ['grub-mkconfig', '-o', self._grub_cfg_path]
        else:
             self.log_error("Ni 'update-grub' ni 'grub-mkconfig' trouvés. Impossible de mettre à jour grub.cfg.", log_levels=log_levels)
             return False

        self.log_info(f"Exécution de: {' '.join(cmd_update)}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd_update, check=False, needs_sudo=True, timeout=120) # Donner du temps pour la génération

        if success:
            self.log_success("Configuration GRUB (grub.cfg) mise à jour avec succès.", log_levels=log_levels)
            # Analyser stdout peut donner des infos sur les OS trouvés etc.
            if stdout: self.log_info(f"Sortie {cmd_update[0]}:\n{stdout}", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la mise à jour de la configuration GRUB. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie {cmd_update[0]} (échec):\n{stdout}", log_levels=log_levels)
            return False

    def install_grub(self,
                     device: str,
                     boot_directory: Optional[str] = None,
                     efi_directory: Optional[str] = None,
                     target_arch: Optional[str] = None,
                     recheck: bool = False,
                     force: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Installe le chargeur d'amorçage GRUB sur un périphérique disque (pas une partition).
        ATTENTION : Modifie le MBR (pour BIOS) ou l'ESP (pour UEFI).

        Args:
            device: Périphérique disque cible (ex: /dev/sda, /dev/nvme0n1). NE PAS mettre de partition.
            boot_directory: Répertoire racine pour GRUB (ex: /boot). Si None, GRUB essaie de deviner.
            efi_directory: Point de montage de la partition EFI (si système UEFI).
            target_arch: Architecture cible (ex: i386-pc, x86_64-efi). Si None, grub-install essaie de deviner.
            recheck: Force la ré-vérification des périphériques (-recheck).
            force: Force l'installation même si des problèmes sont détectés (--force, DANGEREUX).

        Returns:
            bool: True si succès.
        """
        self.log_warning(f"Tentative d'installation de GRUB sur {device} - OPÉRATION CRITIQUE !", log_levels=log_levels)
        cmd = ['grub-install']

        if boot_directory: cmd.extend(['--boot-directory', boot_directory])
        if efi_directory: cmd.extend(['--efi-directory', efi_directory])
        if target_arch: cmd.extend(['--target', target_arch])
        if recheck: cmd.append('--recheck')
        if force:
            cmd.append('--force')
            self.log_warning("Option --force activée pour grub-install !", log_levels=log_levels)

        cmd.append(device) # Le périphérique cible est le dernier argument

        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True, timeout=120)

        # Analyser la sortie pour confirmer le succès, car le code retour peut être 0 avec des erreurs/warnings
        output = stdout + stderr
        success_msg = "installation finished. no error reported."

        if success and success_msg in output.lower():
            self.log_success(f"GRUB installé avec succès sur {device}.", log_levels=log_levels)
            if stdout.strip(): self.log_info(f"Sortie grub-install:\n{stdout}", log_levels=log_levels)
            if stderr.strip() and success_msg not in stderr.lower(): self.log_warning(f"Sortie stderr grub-install (succès):\n{stderr}", log_levels=log_levels)
            return True
        elif success: # Code retour 0 mais message de succès absent
            self.log_warning(f"grub-install a retourné 0 pour {device} mais le message de succès est absent.", log_levels=log_levels)
            self.log_warning(f"Vérification manuelle recommandée. Sortie:\n{output}", log_levels=log_levels)
            return False # Considérer comme échec par prudence
        else: # Code retour non nul
             if "cannot find efi directory" in stderr.lower():
                  self.log_error(f"Échec: Impossible de trouver le répertoire EFI (vérifier montage ESP et option --efi-directory). Stderr: {stderr}", log_levels=log_levels)
             elif "filesystem `.* doesn't support embedding" in stderr:
                  self.log_error(f"Échec: Le système de fichiers sur {device} ne supporte pas l'intégration de GRUB (blocklists). Stderr: {stderr}", log_levels=log_levels)
             elif "will not proceed with blocklists" in stderr.lower():
                  self.log_error(f"Échec: GRUB refuse d'utiliser les blocklists (risqué). Stderr: {stderr}", log_levels=log_levels)
             else:
                  self.log_error(f"Échec de l'installation de GRUB sur {device}. Stderr: {stderr}", log_levels=log_levels)
             if stdout: self.log_info(f"Sortie grub-install (échec):\n{stdout}", log_levels=log_levels)
             return False

    def _read_default_grub(self) -> Optional[List[str]]:
        """Lit les lignes du fichier /etc/default/grub."""
        if not self._cfg_mgr:
            self.log_error("ConfigFileCommands non disponible.", log_levels=log_levels)
            return None
        # Utiliser la méthode de ConfigFileCommands pour lire (gère sudo si besoin)
        return self._cfg_mgr.read_file_lines(self.DEFAULT_GRUB_CONFIG)

    def _write_default_grub(self, lines: List[str]) -> bool:
        """Écrit les lignes dans /etc/default/grub."""
        if not self._cfg_mgr:
            self.log_error("ConfigFileCommands non disponible.", log_levels=log_levels)
            return False
        # Utiliser la méthode de ConfigFileCommands pour écrire (gère backup, sudo)
        content = "".join(lines) # read_file_lines garde les \n
        return self._cfg_mgr._write_file_content(self.DEFAULT_GRUB_CONFIG, content, backup=True)

    def _set_default_grub_value(self, key: str, value: str) -> bool:
        """Modifie ou ajoute une variable dans /etc/default/grub."""
        if not self._cfg_mgr:
            self.log_error("ConfigFileCommands non disponible.", log_levels=log_levels)
            return False

        key = key.strip()
        value = value.strip()
        self.log_info(f"Configuration de {key}='{value}' dans {self.DEFAULT_GRUB_CONFIG}", log_levels=log_levels)

        lines = self._read_default_grub()
        if lines is None:
            self.log_error(f"Impossible de lire {self.DEFAULT_GRUB_CONFIG} pour modification.", log_levels=log_levels)
            return False

        new_lines = []
        found = False
        # Regex pour trouver la ligne GRUB_KEY="valeur" ou GRUB_KEY=valeur
        # Gère les espaces, les guillemets simples ou doubles. Capture la clé et la valeur existante (avec guillemets).
        pattern = re.compile(r"^\s*(" + re.escape(key) + r")\s*=\s*(.*)\s*$", re.IGNORECASE)
        # Regex pour trouver une ligne commentée
        commented_pattern = re.compile(r"^\s*#\s*(" + re.escape(key) + r")\s*=\s*(.*)\s*$", re.IGNORECASE)

        for line in lines:
            match = pattern.match(line)
            commented_match = commented_pattern.match(line)

            if match:
                # Ligne trouvée et non commentée
                # Préserver les guillemets si la nouvelle valeur en nécessite
                if ' ' in value or not value.isalnum():
                    new_line = f'{key}="{value}"\n'
                else:
                    new_line = f'{key}={value}\n'
                new_lines.append(new_line)
                found = True
                self.log_debug(f"  Ligne existante remplacée: {line.strip()} -> {new_line.strip()}", log_levels=log_levels)
            elif commented_match:
                 # Ligne trouvée mais commentée -> décommenter et remplacer
                 if ' ' in value or not value.isalnum():
                     new_line = f'{key}="{value}"\n'
                 else:
                     new_line = f'{key}={value}\n'
                 new_lines.append(new_line)
                 found = True
                 self.log_debug(f"  Ligne commentée trouvée et activée: {line.strip()} -> {new_line.strip()}", log_levels=log_levels)
            else:
                # Garder les autres lignes
                new_lines.append(line)

        # Si la clé n'a pas été trouvée, l'ajouter à la fin
        if not found:
            if ' ' in value or not value.isalnum():
                new_line = f'{key}="{value}"\n'
            else:
                new_line = f'{key}={value}\n'
            # Ajouter un saut de ligne avant si le fichier ne se termine pas par un
            if new_lines and not new_lines[-1].endswith('\n'):
                 new_lines.append('\n')
            new_lines.append(new_line)
            self.log_debug(f"  Nouvelle ligne ajoutée: {new_line.strip()}", log_levels=log_levels)

        # Écrire le fichier modifié
        success_write = self._write_default_grub(new_lines)
        if success_write:
            # Il faut regénérer grub.cfg pour que le changement soit pris en compte
            self.log_info(f"Modification de {self.DEFAULT_GRUB_CONFIG} réussie. Lancement de update-grub...", log_levels=log_levels)
            return self.update_grub_config()
        else:
             self.log_error(f"Échec de l'écriture dans {self.DEFAULT_GRUB_CONFIG}.", log_levels=log_levels)
             return False

    def set_grub_default_entry(self, entry_spec: Union[int, str], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Définit l'entrée de démarrage par défaut dans /etc/default/grub."""
        return self._set_default_grub_value('GRUB_DEFAULT', str(entry_spec))

    def set_grub_timeout(self, seconds: int, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Définit le délai d'attente du menu GRUB dans /etc/default/grub."""
        return self._set_default_grub_value('GRUB_TIMEOUT', str(seconds))

    def add_grub_cmdline_linux_param(self, param: str, value: Optional[str] = None, default_only: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute un paramètre à la ligne de commande du noyau dans /etc/default/grub.

        Args:
            param: Nom du paramètre (ex: 'quiet', 'splash', 'cryptdevice').
            value: Valeur du paramètre (optionnel). Si None, ajoute juste le paramètre (flag).
            default_only: Si True (défaut), modifie GRUB_CMDLINE_LINUX_DEFAULT.
                          Si False, modifie GRUB_CMDLINE_LINUX.

        Returns:
            bool: True si succès.
        """
        if not self._cfg_mgr: return False
        target_key = 'GRUB_CMDLINE_LINUX_DEFAULT' if default_only else 'GRUB_CMDLINE_LINUX'
        param_to_add = f"{param}={value}" if value is not None else param

        self.log_info(f"Ajout du paramètre noyau '{param_to_add}' à {target_key}", log_levels=log_levels)

        lines = self._read_default_grub()
        if lines is None: return False

        new_lines = []
        modified = False

        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith(target_key + "="):
                parts = line.split('=', 1)
                current_values_str = parts[1].strip()
                # Enlever les guillemets existants
                if current_values_str.startswith('"') and current_values_str.endswith('"'):
                    current_values_str = current_values_str[1:-1]

                # Vérifier si le paramètre (ou sa clé) existe déjà
                current_params = shlex.split(current_values_str)
                param_key = param.split('=')[0] # Obtenir juste la clé pour la vérification
                if any(p.startswith(param_key + "=") or p == param_key for p in current_params):
                     self.log_warning(f"Le paramètre '{param}' (ou sa clé) existe déjà dans {target_key}. Ajout ignoré.", log_levels=log_levels)
                     new_lines.append(line) # Garder la ligne telle quelle
                     modified = True # Considérer comme succès car déjà présent
                else:
                     # Ajouter le nouveau paramètre
                     new_values_str = f'{current_values_str} {param_to_add}'.strip()
                     new_line = f'{target_key}="{new_values_str}"\n'
                     new_lines.append(new_line)
                     modified = True
                     self.log_debug(f"  Ligne {target_key} modifiée: -> {new_line.strip()}", log_levels=log_levels)
            else:
                new_lines.append(line)

        if not modified:
            self.log_warning(f"La ligne {target_key} n'a pas été trouvée dans {self.DEFAULT_GRUB_CONFIG}. Ajout impossible.", log_levels=log_levels)
            return False # Ou créer la ligne ? Pour l'instant, échouer.

        success_write = self._write_default_grub(new_lines)
        if success_write:
            self.log_info(f"Modification de {self.DEFAULT_GRUB_CONFIG} réussie. Lancement de update-grub...", log_levels=log_levels)
            return self.update_grub_config()
        else:
             self.log_error(f"Échec de l'écriture dans {self.DEFAULT_GRUB_CONFIG}.", log_levels=log_levels)
             return False

    def remove_grub_cmdline_linux_param(self, param_key: str, default_only: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un paramètre (par sa clé) de la ligne de commande du noyau dans /etc/default/grub."""
        if not self._cfg_mgr: return False
        target_key = 'GRUB_CMDLINE_LINUX_DEFAULT' if default_only else 'GRUB_CMDLINE_LINUX'
        self.log_info(f"Suppression du paramètre noyau '{param_key}' de {target_key}", log_levels=log_levels)

        lines = self._read_default_grub()
        if lines is None: return False

        new_lines = []
        modified = False
        found_and_removed = False

        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith(target_key + "="):
                parts = line.split('=', 1)
                current_values_str = parts[1].strip()
                if current_values_str.startswith('"') and current_values_str.endswith('"'):
                    current_values_str = current_values_str[1:-1]

                current_params = shlex.split(current_values_str)
                new_params = []
                removed = False
                for p in current_params:
                    # Supprimer si c'est le paramètre exact ou s'il commence par "param_key="
                    if p == param_key or p.startswith(param_key + "="):
                        removed = True
                        found_and_removed = True
                    else:
                        new_params.append(p)

                if removed:
                    new_values_str = ' '.join(shlex.quote(p) for p in new_params) # Recréer la chaîne
                    new_line = f'{target_key}="{new_values_str}"\n'
                    new_lines.append(new_line)
                    modified = True
                    self.log_debug(f"  Ligne {target_key} modifiée (suppression de {param_key}): -> {new_line.strip()}", log_levels=log_levels)
                else:
                    new_lines.append(line) # Pas trouvé, garder la ligne
            else:
                new_lines.append(line)

        if not found_and_removed:
            self.log_info(f"Le paramètre '{param_key}' n'a pas été trouvé dans {target_key}. Aucune modification.", log_levels=log_levels)
            return True # Pas d'erreur si déjà absent

        if modified:
            success_write = self._write_default_grub(new_lines)
            if success_write:
                self.log_info(f"Modification de {self.DEFAULT_GRUB_CONFIG} réussie. Lancement de update-grub...", log_levels=log_levels)
                return self.update_grub_config()
            else:
                 self.log_error(f"Échec de l'écriture dans {self.DEFAULT_GRUB_CONFIG}.", log_levels=log_levels)
                 return False
        else:
             return True # Pas trouvé, donc succès

    def enable_grub_cryptodisk(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Active GRUB_ENABLE_CRYPTODISK=y dans /etc/default/grub."""
        self.log_info("Activation de GRUB_ENABLE_CRYPTODISK=y", log_levels=log_levels)
        return self._set_default_grub_value('GRUB_ENABLE_CRYPTODISK', 'y')

    def configure_grub_for_luks(self, luks_uuid: str, luks_name: str = 'luks-root', default_only: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Configure GRUB pour déverrouiller un volume racine LUKS au démarrage.
        Modifie GRUB_CMDLINE_LINUX(_DEFAULT) et GRUB_ENABLE_CRYPTODISK.

        Args:
            luks_uuid: UUID du périphérique LUKS (obtenu via blkid).
            luks_name: Nom à utiliser pour le périphérique mappé (ex: luks-root, cryptroot).
            default_only: Modifier GRUB_CMDLINE_LINUX_DEFAULT ou GRUB_CMDLINE_LINUX.

        Returns:
            bool: True si la configuration et la mise à jour de grub.cfg réussissent.
        """
        self.log_warning("Configuration de GRUB pour LUKS. Assurez-vous que l'initramfs est correctement configuré avec cryptsetup !", log_levels=log_levels)

        # 1. Activer le support cryptodisk
        success_cryptodisk = self.enable_grub_cryptodisk()
        if not success_cryptodisk:
            # L'erreur est déjà logguée par enable_grub_cryptodisk/_set_default_grub_value
            return False

        # 2. Ajouter le paramètre cryptdevice
        # Format: cryptdevice=UUID=<uuid>:<mapper_name>
        # Il peut être nécessaire d'ajouter aussi 'root=/dev/mapper/<mapper_name>'
        # mais cela dépend de la configuration existante, nous ajoutons seulement cryptdevice ici.
        crypt_param = "cryptdevice"
        crypt_value = f"UUID={luks_uuid}:{luks_name}"
        success_param = self.add_grub_cmdline_linux_param(crypt_param, crypt_value, default_only=default_only)

        # Le résultat final dépend du succès de la dernière étape (add_grub_cmdline_linux_param
        # qui inclut l'appel à update_grub_config).
        if success_param:
             self.log_success(f"Paramètres GRUB pour LUKS (UUID: {luks_uuid}) configurés. Vérifiez la présence de 'root=/dev/mapper/{luks_name}' si nécessaire.", log_levels=log_levels)
        else:
             self.log_error("Échec de l'ajout du paramètre cryptdevice à la configuration GRUB.", log_levels=log_levels)

        return success_param

    def get_grub_entries(self, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Tente de parser le fichier grub.cfg pour lister les entrées de menu.
        NOTE : Le parsing de grub.cfg est complexe et peut être fragile.

        Returns:
            Liste de dictionnaires représentant les entrées de menu, ou None si erreur.
        """
        if not self._grub_cfg_path:
             self.log_error("Chemin grub.cfg inconnu, impossible de parser les entrées.", log_levels=log_levels)
             return None

        self.log_info(f"Tentative de parsing des entrées de menu depuis {self._grub_cfg_path}", log_levels=log_levels)
        # Lire le fichier (peut nécessiter sudo)
        content = self._cfg_mgr._read_file_content(self._grub_cfg_path) if self._cfg_mgr else None
        if content is None:
             self.log_error(f"Impossible de lire {self._grub_cfg_path}.", log_levels=log_levels)
             return None

        entries = []
        # Regex pour trouver les lignes 'menuentry' et capturer le titre et les options
        # Gère les guillemets simples, doubles et les options entre accolades.
        entry_pattern = re.compile(r"^\s*menuentry\s+(['\"])(.*?)\1\s*(--class\s+\S+\s*)?(\{\s*)?")

        current_entry = None
        brace_level = 0

        for line in content.splitlines():
            line_strip = line.strip()

            # Nouvelle entrée
            match = entry_pattern.match(line)
            if match and brace_level == 0:
                 if current_entry: entries.append(current_entry) # Sauver précédente
                 title = match.group(2)
                 current_entry = {'title': title, 'options': match.group(3) or '', 'content': []}
                 if match.group(4): # Si accolade ouvrante sur la même ligne
                      brace_level = 1
                 else:
                      brace_level = 0 # Attendre l'accolade sur ligne suivante? GRUB le fait parfois.

            elif current_entry is not None:
                 # Gérer les accolades pour le contenu de l'entrée
                 if '{' in line_strip and not line_strip.startswith('#'): brace_level += 1
                 # Ajouter la ligne (sauf l'accolade fermante finale)
                 if brace_level > 0 and '}' not in line_strip:
                      current_entry['content'].append(line)
                 if '}' in line_strip: brace_level -= 1
                 # Fin de l'entrée
                 if brace_level == 0:
                      # Ajouter la dernière ligne (sans l'accolade si elle est seule)
                      if line_strip != '}': current_entry['content'].append(line)
                      entries.append(current_entry)
                      current_entry = None

        # Ajouter la dernière entrée si le fichier se termine sans accolade fermante (rare)
        if current_entry: entries.append(current_entry)

        self.log_info(f"{len(entries)} entrées GRUB trouvées (parsing basique).", log_levels=log_levels)
        return entries

# Fin de la classe GrubCommands