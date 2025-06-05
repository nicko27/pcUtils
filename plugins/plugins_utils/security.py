# install/plugins/plugins_utils/security.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour les tâches de sécurité courantes.
Gestion des clés SSH, permissions, propriétaires, interaction fail2ban, et ACLs POSIX.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import pwd # Pour trouver le home directory d'un utilisateur
import grp # Pour trouver le groupe d'un utilisateur
import stat # Pour interpréter les modes de permission
import re
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class SecurityCommands(PluginsUtilsBase):
    """
    Classe pour effectuer des opérations de sécurité courantes, y compris la gestion des ACLs.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de sécurité."""
        super().__init__(logger, target_ip)


    def _get_user_home_ssh_dir(self, username: str) -> Optional[Path]:
        """Trouve le chemin du dossier .ssh pour un utilisateur."""
        # (Code inchangé)
        try:
            user_info = pwd.getpwnam(username)
            home_dir = Path(user_info.pw_dir)
            ssh_dir = home_dir / ".ssh"
            return ssh_dir
        except KeyError:
            self.log_error(f"Utilisateur '{username}' non trouvé.", log_levels=log_levels)
            return None
        except Exception as e:
            self.log_error(f"Erreur lors de la récupération du dossier .ssh pour {username}: {e}", log_levels=log_levels)
            return None

    def _ensure_ssh_dir(self, username: str, ssh_dir: Path) -> bool:
        """S'assure que le dossier .ssh existe avec les bonnes permissions (700)."""
        # (Code inchangé)
        try:
            user_info = pwd.getpwnam(username)
            uid = user_info.pw_uid
            gid = user_info.pw_gid
            if not ssh_dir.exists():
                self.log_debug(f"Création du dossier {ssh_dir}", log_levels=log_levels)
                success_mkdir, _, err_mkdir = self.run(['mkdir', '-p', str(ssh_dir)], needs_sudo=True)
                if not success_mkdir:
                     self.log_error(f"Impossible de créer {ssh_dir}. Stderr: {err_mkdir}", log_levels=log_levels)
                     return False
            else:
                 self.log_debug(f"Le dossier {ssh_dir} existe déjà.", log_levels=log_levels)
            success_chown, _, err_chown = self.run(['chown', f"{uid}:{gid}", str(ssh_dir)], needs_sudo=True)
            success_chmod, _, err_chmod = self.run(['chmod', '700', str(ssh_dir)], needs_sudo=True)
            if not success_chown or not success_chmod:
                 self.log_error(f"Échec de la définition des permissions/propriétaire pour {ssh_dir}. Chown stderr: {err_chown}, Chmod stderr: {err_chmod}", log_levels=log_levels)
                 return False
            return True
        except KeyError:
            self.log_error(f"Utilisateur '{username}' non trouvé lors de la configuration de {ssh_dir}.", log_levels=log_levels)
            return False
        except Exception as e:
            self.log_error(f"Erreur lors de la configuration de {ssh_dir}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def generate_ssh_key(self,
                         key_path: Union[str, Path],
                         key_type: str = 'rsa',
                         bits: int = 4096,
                         passphrase: str = '',
                         comment: str = '',
overwrite: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Génère une nouvelle paire de clés SSH via ssh-keygen."""
        # (Code inchangé)
        key_path_obj = Path(key_path)
        key_pub_path = key_path_obj.with_suffix('.pub')
        self.log_debug(f"Génération de la clé SSH ({key_type}, {bits} bits) vers: {key_path_obj}", log_levels=log_levels)
        if key_path_obj.exists() and not overwrite:
            self.log_error(f"Le fichier de clé privée {key_path_obj} existe déjà. Utiliser overwrite=True pour écraser.", log_levels=log_levels)
            return False
        elif key_path_obj.exists() or key_pub_path.exists():
             self.log_warning(f"Écrasement des fichiers de clé existants: {key_path_obj} / {key_pub_path}", log_levels=log_levels)
             try:
                  if key_path_obj.exists(): key_path_obj.unlink()
                  if key_pub_path.exists(): key_pub_path.unlink()
             except Exception as e_del:
                  self.log_error(f"Impossible de supprimer les anciennes clés: {e_del}", log_levels=log_levels)
                  return False
        try:
            key_path_obj.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e_mkdir:
            self.log_error(f"Impossible de créer le dossier parent {key_path_obj.parent}: {e_mkdir}", log_levels=log_levels)
            return False
        cmd = ['ssh-keygen', '-t', key_type, '-b', str(bits), '-f', str(key_path_obj), '-N', passphrase, '-C', comment]
        yes_cmd = ['yes', 'y', '|'] + cmd
        success, stdout, stderr = self.run(" ".join(yes_cmd), shell=True, check=False)
        if success and key_path_obj.exists() and key_pub_path.exists():
            self.log_debug(f"Clé SSH générée avec succès: {key_path_obj}", log_levels=log_levels)
            self.set_permissions(key_path_obj, mode="600")
            return True
        else:
            self.log_error(f"Échec de la génération de la clé SSH. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_debug(f"Sortie ssh-keygen (échec):\n{stdout}", log_levels=log_levels)
            if key_path_obj.exists(): key_path_obj.unlink()
            if key_pub_path.exists(): key_pub_path.unlink()
            return False

    def add_authorized_key(self, username: str, public_key_content: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Ajoute une clé publique au fichier authorized_keys d'un utilisateur."""
        # (Code inchangé)
        self.log_debug(f"Ajout d'une clé publique autorisée pour l'utilisateur: {username}", log_levels=log_levels)
        ssh_dir = self._get_user_home_ssh_dir(username)
        if not ssh_dir: return False
        if not self._ensure_ssh_dir(username, ssh_dir): return False
        auth_keys_path = ssh_dir / "authorized_keys"
        key_to_add = public_key_content.strip()
        key_exists = False
        if auth_keys_path.exists():
            try:
                cmd_grep = ['grep', '-qFx', key_to_add, str(auth_keys_path)]
                success_grep, _, _ = self.run(cmd_grep, check=False, needs_sudo=True, no_output=True)
                key_exists = success_grep
            except Exception as e_grep:
                 self.log_warning(f"Erreur lors de la vérification de l'existence de la clé: {e_grep}", log_levels=log_levels)
        if key_exists:
            self.log_debug(f"La clé publique existe déjà dans {auth_keys_path}.", log_levels=log_levels)
            return True
        self.log_debug(f"Ajout de la clé à {auth_keys_path}", log_levels=log_levels)
        cmd_add = ['tee', '-a', str(auth_keys_path)]
        success_add, _, stderr_add = self.run(cmd_add, input_data=key_to_add + "\n", check=False, needs_sudo=True)
        if not success_add:
            self.log_error(f"Échec de l'ajout de la clé à {auth_keys_path}. Stderr: {stderr_add}", log_levels=log_levels)
            return False
        try:
            user_info = pwd.getpwnam(username)
            uid = user_info.pw_uid
            gid = user_info.pw_gid
            success_chown, _, err_chown = self.run(['chown', f"{uid}:{gid}", str(auth_keys_path)], needs_sudo=True)
            success_chmod, _, err_chmod = self.run(['chmod', '600', str(auth_keys_path)], needs_sudo=True)
            if not success_chown or not success_chmod:
                 self.log_error(f"Échec de la définition des permissions/propriétaire pour {auth_keys_path}. Chown stderr: {err_chown}, Chmod stderr: {err_chmod}", log_levels=log_levels)
                 return False
            self.log_debug(f"Clé publique ajoutée et permissions définies pour {username}.", log_levels=log_levels)
            return True
        except KeyError:
             self.log_error(f"Utilisateur '{username}' non trouvé lors de la définition des permissions finales.", log_levels=log_levels)
             return False
        except Exception as e_perm:
             self.log_error(f"Erreur lors de la définition des permissions finales: {e_perm}", log_levels=log_levels)
             return False

    def remove_authorized_key(self, username: str, key_identifier: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime une clé publique du fichier authorized_keys d'un utilisateur."""
        # (Code inchangé)
        self.log_debug(f"Suppression de la clé publique autorisée pour '{username}' identifiée par '{key_identifier[:30]}...'", log_levels=log_levels)
        ssh_dir = self._get_user_home_ssh_dir(username)
        if not ssh_dir: return False
        auth_keys_path = ssh_dir / "authorized_keys"
        if not auth_keys_path.exists():
            self.log_warning(f"Le fichier {auth_keys_path} n'existe pas.", log_levels=log_levels)
            return True
        escaped_identifier = key_identifier.replace('/', '\\/').replace('&', '\\&').replace('"', '\\"').replace("'", "\\'")
        cmd_sed = ['sed', '-i', f"/{escaped_identifier}/d", str(auth_keys_path)]
        self.log_debug(f"Exécution de sed pour supprimer la clé: {' '.join(cmd_sed)}", log_levels=log_levels)
        success, stdout, stderr = self.run(cmd_sed, check=False, needs_sudo=True)
        if success:
            self.log_debug(f"Clé(s) correspondant à '{key_identifier[:30]}...' supprimée(s) de {auth_keys_path} (si elle existait).", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la suppression de la clé dans {auth_keys_path}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def set_permissions(self, path: Union[str, Path], mode: Union[str, int], recursive: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Modifie les permissions d'un fichier ou d'un dossier."""
        # (Code inchangé)
        target_path = Path(path)
        mode_str = str(mode)
        self.log_debug(f"Modification des permissions de {target_path} en {mode_str}{' (récursif)' if recursive else ''}", log_levels=log_levels)
        if not target_path.exists():
             # Vérifier avec sudo si l'utilisateur courant n'a pas les droits de voir
             s_exists, _, _ = self.run(['test', '-e', str(target_path)], check=False, needs_sudo=True)
             if not s_exists:
                  self.log_error(f"Le chemin n'existe pas: {target_path}", log_levels=log_levels)
                  return False
        cmd = ['chmod']
        if recursive: cmd.append('-R')
        cmd.append(mode_str)
        cmd.append(str(target_path))
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_debug(f"Permissions de {target_path} mises à jour.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de chmod sur {target_path}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def set_ownership(self, path: Union[str, Path], user: Optional[str] = None, group: Optional[str] = None, recursive: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Modifie le propriétaire et/ou le groupe d'un fichier ou dossier."""
        # (Code inchangé)
        target_path = Path(path)
        if not user and not group:
            self.log_warning("Aucun utilisateur ou groupe spécifié pour set_ownership.", log_levels=log_levels)
            return True
        owner_spec = ""
        if user: owner_spec += str(user)
        if group: owner_spec += f":{str(group)}"
        elif user: owner_spec += ":"
        if not owner_spec or owner_spec == ":":
             self.log_error("Spécification propriétaire/groupe invalide.", log_levels=log_levels)
             return False
        self.log_debug(f"Modification du propriétaire/groupe de {target_path} en {owner_spec}{' (récursif)' if recursive else ''}", log_levels=log_levels)
        if not target_path.exists():
             s_exists, _, _ = self.run(['test', '-e', str(target_path)], check=False, needs_sudo=True)
             if not s_exists:
                  self.log_error(f"Le chemin n'existe pas: {target_path}", log_levels=log_levels)
                  return False
        cmd = ['chown']
        if recursive: cmd.append('-R')
        cmd.append(owner_spec)
        cmd.append(str(target_path))
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_debug(f"Propriétaire/groupe de {target_path} mis à jour.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de chown sur {target_path}. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Fonctions Fail2Ban ---

    def fail2ban_ban_ip(self, jail: str, ip_address: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Bannit une IP dans une jail fail2ban."""
        # (Code inchangé)
        self.log_debug(f"Bannissement de l'IP {ip_address} dans la jail '{jail}' (fail2ban)", log_levels=log_levels)
        cmd = ['fail2ban-client', 'set', jail, 'banip', ip_address]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            if stdout: self.log_debug(f"Sortie fail2ban-client: {stdout.strip()}", log_levels=log_levels)
            self.log_debug(f"IP {ip_address} bannie dans la jail '{jail}'.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du bannissement de {ip_address}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def fail2ban_unban_ip(self, jail: str, ip_address: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Débannit une IP d'une jail fail2ban."""
        # (Code inchangé)
        self.log_debug(f"Débannissement de l'IP {ip_address} de la jail '{jail}' (fail2ban)", log_levels=log_levels)
        cmd = ['fail2ban-client', 'set', jail, 'unbanip', ip_address]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            if stdout: self.log_debug(f"Sortie fail2ban-client: {stdout.strip()}", log_levels=log_levels)
            self.log_debug(f"IP {ip_address} débannie de la jail '{jail}'.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec du débannissement de {ip_address}. Stderr: {stderr}", log_levels=log_levels)
            return False

    def fail2ban_status(self, jail: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Récupère le statut de fail2ban ou d'une jail spécifique."""
        # (Code inchangé)
        target = f"de la jail '{jail}'" if jail else "global"
        self.log_debug(f"Récupération du statut fail2ban {target}", log_levels=log_levels)
        cmd = ['fail2ban-client', 'status']
        if jail: cmd.append(jail)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_debug(f"Statut fail2ban ({target}):\n{stdout}", log_levels=log_levels)
            return stdout
        else:
            self.log_error(f"Échec de la récupération du statut fail2ban {target}. Stderr: {stderr}", log_levels=log_levels)
            return None

    # --- Fonctions ACL (Nouvelles) ---

    def parse_acl(self, acl_output: str, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Parse la sortie texte de getfacl.

        Args:
            acl_output: La sortie brute de la commande getfacl.

        Returns:
            Dictionnaire structuré représentant les ACLs.
            Ex: {'owner': 'user', 'group': 'group', 'flags': '...',
                 'access': [{'type':'user', 'name':'', 'perms':'rwx'}, ...],
                 'default': [{'type':'user', 'name':'', 'perms':'rwx'}, ...]}
        """
        acl_data: Dict[str, Any] = {'access': [], 'default': []}
        current_section = 'access' # Commence par les ACLs d'accès

        for line in acl_output.splitlines():
            line = line.strip()
            if not line: continue

            # Ignorer les lignes d'en-tête
            if line.startswith('# file:'):
                acl_data['file'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('# owner:'):
                acl_data['owner'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('# group:'):
                acl_data['group'] = line.split(':', 1)[1].strip()
                continue
            if line.startswith('# flags:'):
                acl_data['flags'] = line.split(':', 1)[1].strip()
                continue

            # Détecter le début de la section default
            if line.startswith('default:'):
                 current_section = 'default'
                 line = line[len('default:'):].strip() # Enlever le préfixe pour le parsing suivant
                 if not line: continue # Si la ligne était juste "default:"

            # Parser les entrées ACL (user::rwx, user:name:r-x, group::r-x, mask::r-x, other::r--)
            parts = line.split(':')
            if len(parts) == 3:
                 acl_type, acl_name, acl_perms = parts
                 # Nettoyer les permissions (ex: rwx -> rwx, r-x -> r-x)
                 acl_perms_clean = acl_perms.replace('-', '')
                 entry = {'type': acl_type, 'name': acl_name, 'perms': acl_perms_clean}
                 acl_data[current_section].append(entry)
            elif line: # Si la ligne n'est pas vide mais ne correspond pas
                 self.log_warning(f"Ligne ACL non reconnue ignorée: '{line}'", log_levels=log_levels)

        self.log_debug(f"ACLs parsées: {acl_data}", log_levels=log_levels)
        return acl_data

    def get_acl(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Récupère les ACLs POSIX d'un fichier ou dossier via `getfacl`.

        Args:
            path: Chemin du fichier ou dossier.

        Returns:
            Dictionnaire structuré représentant les ACLs, ou None si erreur.
        """
        target_path = Path(path)
        self.log_debug(f"Récupération des ACLs pour: {target_path}", log_levels=log_levels)

        if not target_path.exists():
             # Vérifier avec sudo
             s_exists, _, _ = self.run(['test', '-e', str(target_path)], check=False, needs_sudo=True)
             if not s_exists:
                  self.log_error(f"Le chemin n'existe pas: {target_path}", log_levels=log_levels)
                  return None

        # Utiliser -p pour les chemins absolus dans la sortie (plus facile à parser si récursif)
        # Utiliser -E pour ne pas afficher les permissions effectives (moins de bruit)
        cmd = ['getfacl', '-pE', str(target_path)]
        # getfacl peut nécessiter root selon les permissions
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if not success:
            # Gérer le cas où les ACLs ne sont pas supportées/activées
            if "operation not supported" in stderr.lower():
                 self.log_warning(f"Les ACLs ne semblent pas supportées ou activées pour {target_path}.", log_levels=log_levels)
                 # Retourner les permissions de base ? Pour l'instant None.
                 return None
            self.log_error(f"Échec de getfacl pour {target_path}. Stderr: {stderr}", log_levels=log_levels)
            return None

        try:
            return self.parse_acl(stdout)
        except Exception as e:
             self.log_error(f"Erreur lors du parsing de la sortie getfacl: {e}", exc_info=True, log_levels=log_levels)
             self.log_debug(f"Sortie getfacl brute:\n{stdout}", log_levels=log_levels)
             return None

    def set_acl(self,
                path: Union[str, Path],
                acl_spec: str,
                recursive: bool = False,
                modify: bool = True, # Par défaut, modifie (-m, log_levels: Optional[Dict[str, str]] = None)
                remove: bool = False, # Utiliser -x
                remove_default: bool = False, # Utiliser -k
                clear: bool = False, # Utiliser -b
                use_default_prefix: bool = False # Ajouter 'd:' pour ACLs par défaut
                ) -> bool:
        """
        Modifie ou définit les ACLs POSIX d'un fichier ou dossier via `setfacl`.

        Args:
            path: Chemin du fichier ou dossier.
            acl_spec: Spécification ACL (ex: "u:user:rwx", "g:group:r-x", "d:u:other:rw").
                      Peut contenir plusieurs spécifications séparées par des virgules.
            recursive: Appliquer récursivement (-R).
            modify: Modifier les ACLs existantes (-m). C'est l'action par défaut si
                    remove, remove_default et clear sont False.
            remove: Supprimer les ACLs spécifiées (-x acl_spec).
            remove_default: Supprimer les ACLs par défaut (-k). acl_spec est ignoré.
            clear: Supprimer toutes les ACLs étendues (-b). acl_spec est ignoré.
            use_default_prefix: Si True, préfixe automatiquement 'd:' à acl_spec pour
                                définir les ACLs par défaut.

        Returns:
            bool: True si succès.
        """
        target_path = Path(path)
        action = "Modification/Définition"
        cmd = ['setfacl']

        if recursive: cmd.append('-R')

        # Déterminer l'option principale (-m, -x, -b, -k)
        if clear:
            cmd.append('-b')
            action = "Suppression de toutes les ACLs étendues"
            acl_spec = "" # Ignoré par -b
        elif remove_default:
            cmd.append('-k')
            action = "Suppression des ACLs par défaut"
            acl_spec = "" # Ignoré par -k
        elif remove:
            cmd.append('-x')
            action = "Suppression des ACLs spécifiées"
        elif modify: # Action par défaut
             cmd.append('-m')
             action = "Modification/Ajout des ACLs"
        else: # Si modify=False et aucune autre action, c'est une erreur
             self.log_error("Aucune action spécifiée pour set_acl (modify, remove, remove_default, clear).", log_levels=log_levels)
             return False

        # Ajouter la spécification ACL si nécessaire
        if acl_spec:
             spec_to_use = acl_spec
             if use_default_prefix and not acl_spec.startswith('d:'):
                  # Ajouter 'd:' à chaque partie si séparées par virgule
                  parts = [f"d:{p}" if not p.startswith('d:') else p for p in acl_spec.split(',')]
                  spec_to_use = ','.join(parts)
                  action += " (par défaut)"
             cmd.append(spec_to_use)

        cmd.append(str(target_path))
        self.log_debug(f"{action} sur: {target_path}", log_levels=log_levels)
        if acl_spec: self.log_debug(f"  Spécification: {spec_to_use}", log_levels=log_levels)

        # setfacl nécessite root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if success:
            self.log_debug(f"ACLs mises à jour avec succès pour {target_path}.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de setfacl sur {target_path}. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_debug(f"Sortie setfacl (échec):\n{stdout}", log_levels=log_levels)
            return False