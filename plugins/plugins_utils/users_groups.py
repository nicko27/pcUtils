# install/plugins/plugins_utils/users_groups.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour la gestion des utilisateurs et groupes locaux sous Linux.
Utilise les commandes système standard (useradd, usermod, userdel, groupadd, etc.).
Inclut le cryptage interne des mots de passe via le module 'crypt'.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import crypt # Pour le cryptage des mots de passe
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class UserGroupCommands(PluginsUtilsBase):
    """
    Classe pour gérer les utilisateurs et groupes locaux.
    Hérite de PluginUtilsBase pour l'exécution de commandes et la progression.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire d'utilisateurs et groupes."""
        super().__init__(logger, target_ip)
        # Vérifier la présence des commandes nécessaires


    def _encrypt_password(self, plaintext_password: str, method: Optional[Any] = None) -> Optional[str]:
        """
        Crypte un mot de passe en utilisant crypt.crypt().

        Args:
            plaintext_password: Le mot de passe en clair.
            method: Méthode de cryptage (ex: crypt.METHOD_SHA512). Si None, utilise la méthode par défaut du système (souvent SHA512 sur les systèmes modernes).

        Returns:
            Le hash du mot de passe ou None si erreur.
        """
        self.log_debug("Cryptage du mot de passe...", log_levels=log_levels)
        try:
            # Si aucune méthode spécifiée, utiliser la plus forte disponible par défaut
            # (crypt.METHOD_SHA512 est un bon choix moderne si disponible)
            if method is None and hasattr(crypt, 'METHOD_SHA512'):
                 method = crypt.METHOD_SHA512

            if method:
                 encrypted = crypt.crypt(plaintext_password, method)
            else:
                 # Utiliser la méthode par défaut du système si METHOD_SHA512 n'est pas dispo
                 encrypted = crypt.crypt(plaintext_password)

            if not encrypted:
                 self.log_error("La fonction crypt.crypt() a retourné une chaîne vide.", log_levels=log_levels)
                 return None

            self.log_debug("Mot de passe crypté avec succès.", log_levels=log_levels)
            return encrypted
        except Exception as e:
            self.log_error(f"Erreur lors du cryptage du mot de passe: {e}", exc_info=True, log_levels=log_levels)
            return None

    # --- Fonctions de Vérification ---

    def user_exists(self, username: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si un utilisateur local existe."""
        self.log_debug(f"Vérification de l'existence de l'utilisateur: {username}", log_levels=log_levels)
        success, _, _ = self.run(['getent', 'passwd', username], check=False, no_output=True)
        exists = success
        self.log_debug(f"Utilisateur '{username}' existe: {exists}", log_levels=log_levels)
        return exists

    def group_exists(self, groupname: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si un groupe local existe."""
        self.log_debug(f"Vérification de l'existence du groupe: {groupname}", log_levels=log_levels)
        success, _, _ = self.run(['getent', 'group', groupname], check=False, no_output=True)
        exists = success
        self.log_debug(f"Groupe '{groupname}' existe: {exists}", log_levels=log_levels)
        return exists

    # --- Gestion des Utilisateurs ---

    def add_user(self,
                 username: str,
                 password: Optional[str] = None, # Mot de passe en clair
                 encrypted_password: Optional[str] = None, # Ou mot de passe déjà crypté
                 uid: Optional[int] = None,
                 gid: Optional[Union[int, str]] = None,
                 gecos: Optional[str] = None,
                 home_dir: Optional[str] = None,
                 create_home: bool = True,
                 shell: Optional[str] = '/bin/bash',
                 primary_group: Optional[str] = None,
                 secondary_groups: Optional[List[str]] = None,
                 system_user: bool = False,
                 no_user_group: bool = False,
                 no_log_init: bool = False
, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute un nouvel utilisateur local. Gère le mot de passe (clair ou crypté).

        Args:
            [...] (mêmes arguments que précédemment)

        Returns:
            bool: True si l'ajout (et la définition du mot de passe si fourni) a réussi.
        """
        if self.user_exists(username):
            self.log_info(f"L'utilisateur '{username}' existe déjà.", log_levels=log_levels)
            return False

        self.log_info(f"Ajout de l'utilisateur: {username}", log_levels=log_levels)
        cmd = ['useradd']

        if system_user: cmd.append('-r')
        if uid is not None: cmd.extend(['-u', str(uid)])
        # GID initial (peut être écrasé par primary_group)
        initial_gid = gid if primary_group is None else primary_group
        if initial_gid is not None: cmd.extend(['-g', str(initial_gid)])

        if gecos: cmd.extend(['-c', gecos])

        # Gestion du home directory
        if home_dir == 'no':
            cmd.append('-M') # Ne pas créer
        elif home_dir:
            cmd.extend(['-d', home_dir])
            cmd.append('-m' if create_home else '-M')
        elif create_home:
             cmd.append('-m') # Créer par défaut
        else:
             cmd.append('-M') # Ne pas créer par défaut

        if shell: cmd.extend(['-s', shell])
        if no_user_group: cmd.append('-n')
        if no_log_init: cmd.append('-l')

        # Groupes secondaires
        if secondary_groups:
            cmd.extend(['-G', ','.join(secondary_groups)])

        # Mot de passe : on préfère utiliser chpasswd après création,
        # mais on peut passer le hash à useradd -p si fourni.
        # Si password (clair) ET encrypted_password sont fournis, encrypted_password a priorité.
        password_to_set_later = password # Garder le mot de passe clair pour plus tard
        if encrypted_password:
             cmd.extend(['-p', encrypted_password])
             self.log_info("  - Mot de passe (crypté) fourni via useradd -p.", log_levels=log_levels)
             password_to_set_later = None # Ne pas essayer de le redéfinir

        cmd.append(username)

        # Exécuter useradd
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)

        if not success:
            self.log_error(f"Échec de la commande useradd pour '{username}'. Stderr: {stderr}", log_levels=log_levels)
            return False

        self.log_success(f"Utilisateur '{username}' ajouté avec succès via useradd.", log_levels=log_levels)

        # Définir le mot de passe en clair si fourni (et si pas déjà fait via -p)
        if password_to_set_later:
            self.log_info(f"Définition du mot de passe pour {username} via chpasswd...", log_levels=log_levels)
            # set_password s'occupe du cryptage maintenant
            return self.set_password(username, password_to_set_later, is_encrypted=False)

        return True # Succès même si pas de mot de passe fourni

    def delete_user(self, username: str, remove_home: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un utilisateur local."""
        # (Code inchangé)
        if not self.user_exists(username):
            self.log_warning(f"L'utilisateur '{username}' n'existe pas, suppression ignorée.", log_levels=log_levels)
            return True
        self.log_info(f"Suppression de l'utilisateur: {username}{' (avec répertoire personnel)' if remove_home else ''}", log_levels=log_levels)
        cmd = ['userdel']
        if remove_home: cmd.append('-r')
        cmd.append(username)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Utilisateur '{username}' supprimé avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la suppression de l'utilisateur '{username}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def modify_user(self,
                    username: str,
                    new_username: Optional[str] = None,
                    uid: Optional[int] = None,
                    gid: Optional[Union[int, str]] = None,
                    gecos: Optional[str] = None,
                    home_dir: Optional[str] = None,
                    move_home: bool = False,
                    shell: Optional[str] = None,
                    append_groups: Optional[List[str]] = None,
                    set_groups: Optional[List[str]] = None,
                    lock: bool = False,
                    unlock: bool = False,
                    expire_date: Optional[str] = None
, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Modifie un utilisateur existant."""
        # (Code inchangé)
        if not self.user_exists(username):
            self.log_error(f"L'utilisateur '{username}' n'existe pas, modification impossible.", log_levels=log_levels)
            return False
        self.log_info(f"Modification de l'utilisateur: {username}", log_levels=log_levels)
        cmd = ['usermod']
        options_added = False
        if new_username: cmd.extend(['-l', new_username]); options_added = True; self.log_info(f"  - Nouveau nom: {new_username}", log_levels=log_levels)
        if uid is not None: cmd.extend(['-u', str(uid)]); options_added = True; self.log_info(f"  - Nouvel UID: {uid}", log_levels=log_levels)
        if gid is not None: cmd.extend(['-g', str(gid)]); options_added = True; self.log_info(f"  - Nouveau GID/Groupe principal: {gid}", log_levels=log_levels)
        if gecos: cmd.extend(['-c', gecos]); options_added = True; self.log_info(f"  - Nouveau GECOS: {gecos}", log_levels=log_levels)
        if home_dir:
             cmd.extend(['-d', home_dir])
             if move_home: cmd.append('-m')
             options_added = True
             self.log_info(f"  - Nouveau Home: {home_dir} (déplacer: {move_home})", log_levels=log_levels)
        if shell: cmd.extend(['-s', shell]); options_added = True; self.log_info(f"  - Nouveau Shell: {shell}", log_levels=log_levels)
        if append_groups: cmd.extend(['-a', '-G', ','.join(append_groups)]); options_added = True; self.log_info(f"  - Ajout aux groupes: {', '.join(append_groups)}", log_levels=log_levels)
        if set_groups is not None: cmd.extend(['-G', ','.join(set_groups)]); options_added = True; self.log_info(f"  - Définition des groupes: {', '.join(set_groups)}", log_levels=log_levels)
        if lock: cmd.append('-L'); options_added = True; self.log_info("  - Verrouillage du compte", log_levels=log_levels)
        if unlock: cmd.append('-U'); options_added = True; self.log_info("  - Déverrouillage du compte", log_levels=log_levels)
        if expire_date: cmd.extend(['-e', expire_date]); options_added = True; self.log_info(f"  - Date d'expiration: {expire_date}", log_levels=log_levels)
        if not options_added:
            self.log_warning("Aucune modification spécifiée pour usermod.", log_levels=log_levels)
            return True
        cmd.append(username)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Utilisateur '{username}' modifié avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la modification de l'utilisateur '{username}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def set_password(self, username: str, password: str, is_encrypted: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit ou met à jour le mot de passe d'un utilisateur via `chpasswd -e`.
        Crypte le mot de passe si `is_encrypted=False`.

        Args:
            username: Nom de l'utilisateur.
            password: Nouveau mot de passe (en clair ou déjà crypté selon is_encrypted).
            is_encrypted: Si True, le mot de passe fourni est déjà un hash.
                          Si False (défaut), le mot de passe sera crypté avant envoi.

        Returns:
            bool: True si la mise à jour a réussi.
        """
        if not self.user_exists(username):
            self.log_error(f"L'utilisateur '{username}' n'existe pas, impossible de définir le mot de passe.", log_levels=log_levels)
            return False

        self.log_info(f"Définition/Mise à jour du mot de passe pour: {username}", log_levels=log_levels)

        password_to_send = None
        if is_encrypted:
            password_to_send = password
            self.log_info("  - Utilisation d'un mot de passe déjà crypté.", log_levels=log_levels)
        else:
            # Crypter le mot de passe en clair
            password_to_send = self._encrypt_password(password)
            if not password_to_send:
                 # Erreur de cryptage déjà logguée
                 return False
            self.log_info("  - Mot de passe en clair fourni, cryptage avant envoi.", log_levels=log_levels)

        # Utiliser chpasswd avec l'option -e (encrypted)
        cmd = ['chpasswd', '-e']
        input_str = f"{username}:{password_to_send}\n"

        success, stdout, stderr = self.run(cmd, input_data=input_str, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Mot de passe pour '{username}' mis à jour avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la mise à jour du mot de passe pour '{username}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Gestion des Groupes ---
    # (Méthodes add_group, delete_group, modify_group, add_user_to_group, remove_user_from_group inchangées)
    def add_group(self, groupname: str, gid: Optional[int] = None, system: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Ajoute un nouveau groupe local."""
        if self.group_exists(groupname):
            self.log_error(f"Le groupe '{groupname}' existe déjà.", log_levels=log_levels)
            return False
        self.log_info(f"Ajout du groupe: {groupname}", log_levels=log_levels)
        cmd = ['groupadd']
        if system: cmd.append('-r')
        if gid is not None: cmd.extend(['-g', str(gid)])
        cmd.append(groupname)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Groupe '{groupname}' ajouté avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de l'ajout du groupe '{groupname}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def delete_group(self, groupname: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un groupe local."""
        if not self.group_exists(groupname):
            self.log_warning(f"Le groupe '{groupname}' n'existe pas, suppression ignorée.", log_levels=log_levels)
            return True
        self.log_info(f"Suppression du groupe: {groupname}", log_levels=log_levels)
        cmd = ['groupdel', groupname]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Groupe '{groupname}' supprimé avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la suppression du groupe '{groupname}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def modify_group(self, groupname: str, new_name: Optional[str] = None, new_gid: Optional[int] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Modifie un groupe existant (nom ou GID)."""
        if not self.group_exists(groupname):
            self.log_error(f"Le groupe '{groupname}' n'existe pas, modification impossible.", log_levels=log_levels)
            return False
        self.log_info(f"Modification du groupe: {groupname}", log_levels=log_levels)
        cmd = ['groupmod']
        options_added = False
        if new_name: cmd.extend(['-n', new_name]); options_added = True; self.log_info(f"  - Nouveau nom: {new_name}", log_levels=log_levels)
        if new_gid is not None: cmd.extend(['-g', str(new_gid)]); options_added = True; self.log_info(f"  - Nouveau GID: {new_gid}", log_levels=log_levels)
        if not options_added:
            self.log_warning("Aucune modification spécifiée pour groupmod.", log_levels=log_levels)
            return True
        cmd.append(groupname)
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            self.log_success(f"Groupe '{groupname}' modifié avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la modification du groupe '{groupname}'. Stderr: {stderr}", log_levels=log_levels)
            return False

    def add_user_to_group(self, username: str, groupname: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Ajoute un utilisateur à un groupe secondaire."""
        if not self.user_exists(username):
            self.log_error(f"L'utilisateur '{username}' n'existe pas.", log_levels=log_levels)
            return False
        if not self.group_exists(groupname):
            self.log_error(f"Le groupe '{groupname}' n'existe pas.", log_levels=log_levels)
            return False
        self.log_info(f"Ajout de l'utilisateur '{username}' au groupe '{groupname}'", log_levels=log_levels)
        cmd = ['gpasswd', '-a', username, groupname]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            if stdout: self.log_info(f"Sortie gpasswd: {stdout.strip()}", log_levels=log_levels)
            self.log_success(f"Utilisateur '{username}' ajouté au groupe '{groupname}'.", log_levels=log_levels)
            return True
        else:
             if "is already a member of group" in stderr:
                  self.log_info(f"L'utilisateur '{username}' est déjà membre du groupe '{groupname}'.", log_levels=log_levels)
                  return True
             self.log_error(f"Échec de l'ajout de '{username}' au groupe '{groupname}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    def remove_user_from_group(self, username: str, groupname: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Retire un utilisateur d'un groupe secondaire."""
        if not self.user_exists(username):
            self.log_warning(f"L'utilisateur '{username}' n'existe pas, retrait ignoré.", log_levels=log_levels)
            return True
        if not self.group_exists(groupname):
            self.log_warning(f"Le groupe '{groupname}' n'existe pas, retrait ignoré.", log_levels=log_levels)
            return True
        self.log_info(f"Retrait de l'utilisateur '{username}' du groupe '{groupname}'", log_levels=log_levels)
        cmd = ['gpasswd', '-d', username, groupname]
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True)
        if success:
            if stdout: self.log_info(f"Sortie gpasswd: {stdout.strip()}", log_levels=log_levels)
            self.log_success(f"Utilisateur '{username}' retiré du groupe '{groupname}'.", log_levels=log_levels)
            return True
        else:
             if "is not a member of group" in stderr:
                  self.log_info(f"L'utilisateur '{username}' n'était pas membre du groupe '{groupname}'.", log_levels=log_levels)
                  return True
             self.log_error(f"Échec du retrait de '{username}' du groupe '{groupname}'. Stderr: {stderr}", log_levels=log_levels)
             return False

    # --- Fonctions d'Information ---
    # (Méthodes get_user_info, get_group_info, get_user_groups inchangées)
    def get_user_info(self, username: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations d'un utilisateur via getent."""
        self.log_debug(f"Récupération des informations pour l'utilisateur: {username}", log_levels=log_levels)
        success, stdout, _ = self.run(['getent', 'passwd', username], check=False, no_output=True)
        if not success:
            self.log_debug(f"Utilisateur '{username}' non trouvé par getent.", log_levels=log_levels)
            return None
        fields = ['username', 'password_placeholder', 'uid', 'gid', 'gecos', 'home_dir', 'shell']
        values = stdout.strip().split(':')
        if len(values) == len(fields):
            info = dict(zip(fields, values))
            try: info['uid'] = int(info['uid'])
            except ValueError: pass
            try: info['gid'] = int(info['gid'])
            except ValueError: pass
            return info
        else:
            self.log_warning(f"Format de sortie inattendu de getent passwd pour '{username}': {stdout}", log_levels=log_levels)
            return None

    def get_group_info(self, groupname: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Récupère les informations d'un groupe via getent."""
        self.log_debug(f"Récupération des informations pour le groupe: {groupname}", log_levels=log_levels)
        success, stdout, _ = self.run(['getent', 'group', groupname], check=False, no_output=True)
        if not success:
            self.log_debug(f"Groupe '{groupname}' non trouvé par getent.", log_levels=log_levels)
            return None
        fields = ['groupname', 'password_placeholder', 'gid', 'members']
        values = stdout.strip().split(':')
        if len(values) == len(fields):
            info = dict(zip(fields, values))
            try: info['gid'] = int(info['gid'])
            except ValueError: pass
            info['members'] = info['members'].split(',') if info['members'] else []
            return info
        else:
            self.log_warning(f"Format de sortie inattendu de getent group pour '{groupname}': {stdout}", log_levels=log_levels)
            return None

    def get_user_groups(self, username: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        """Récupère la liste des groupes auxquels un utilisateur appartient."""
        if not self.user_exists(username):
            self.log_error(f"L'utilisateur '{username}' n'existe pas.", log_levels=log_levels)
            return None
        self.log_debug(f"Récupération des groupes pour l'utilisateur: {username}", log_levels=log_levels)
        success, stdout, stderr = self.run(['groups', username], check=False, no_output=True)
        if not success:
            self.log_error(f"Impossible de récupérer les groupes pour '{username}'. Stderr: {stderr}", log_levels=log_levels)
            return None
        try:
            groups_str = stdout.split(':', 1)[1].strip()
            groups = groups_str.split()
            self.log_debug(f"Groupes pour '{username}': {groups}", log_levels=log_levels)
            return groups
        except IndexError:
            self.log_warning(f"Format de sortie inattendu de la commande 'groups' pour '{username}': {stdout}", log_levels=log_levels)
            return []

    def get_all_user_homes(self, log_levels: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
        """
        Récupère la liste de tous les répertoires home des utilisateurs système.

        Returns:
            Liste de tuples (nom_utilisateur, chemin_home).
        """
        self.log_debug("Recherche de tous les répertoires home des utilisateurs", log_levels=log_levels)

        user_homes = []

        # Utiliser getent passwd pour obtenir tous les utilisateurs
        try:
            success, stdout, stderr = self.run(['getent', 'passwd'], check=False, no_output=True,
                                            error_as_warning=True, needs_sudo=False)
            if success:
                for line in stdout.splitlines():
                    parts = line.split(':')
                    if len(parts) >= 6:
                        username = parts[0]
                        home_dir = parts[5]
                        uid = int(parts[2]) if parts[2].isdigit() else 0

                        # Filtrer les utilisateurs système (UID < 1000) et les répertoires non standards
                        if (uid >= 1000 and
                            home_dir.startswith('/home/') and
                            Path(home_dir).exists() and
                            Path(home_dir).is_dir() and
                            username not in ['nobody', 'guest']):
                            user_homes.append((username, home_dir))
                            self.log_debug(f"Utilisateur trouvé: {username} -> {home_dir}", log_levels=log_levels)
        except Exception as e:
            self.log_warning(f"Erreur lors de la lecture de getent passwd: {str(e)}", log_levels=log_levels)

        # Méthode alternative: parcourir /home/ directement si la première méthode échoue
        if not user_homes:
            self.log_debug("Méthode getent échouée, parcours direct de /home/", log_levels=log_levels)
            try:
                if Path('/home/').exists():
                    for item in Path('/home/').iterdir():
                        if item.is_dir() and not item.name.startswith('.'):
                            user_homes.append((item.name, str(item)))
                            self.log_debug(f"Répertoire home trouvé: {item.name} -> {item}", log_levels=log_levels)
            except Exception as e:
                self.log_error(f"Impossible de parcourir /home/: {str(e)}", log_levels=log_levels)

        self.log_info(f"Trouvé {len(user_homes)} utilisateur(s) avec répertoire home", log_levels=log_levels)
        return user_homes

    def get_user_home_path(self, username: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Obtient le chemin du répertoire home d'un utilisateur spécifique.

        Args:
            username: Nom de l'utilisateur.
            log_levels: Niveaux de log personnalisés (optionnel).

        Returns:
            str: Chemin du répertoire home ou None si non trouvé.
        """
        user_info = self.get_user_info(username, log_levels)
        if user_info and 'home_dir' in user_info:
            home_dir = Path(user_info['home_dir'])
            if home_dir.exists():
                return str(home_dir)
            else:
                self.log_warning(f"Le répertoire home {home_dir} n'existe pas pour l'utilisateur {username}", log_levels=log_levels)
        return None

    def get_user_uid(self, username: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[int]:
        """
        Obtient l'UID d'un utilisateur.

        Args:
            username: Nom de l'utilisateur.
            log_levels: Niveaux de log personnalisés (optionnel).

        Returns:
            int: UID de l'utilisateur ou None si non trouvé.
        """
        user_info = self.get_user_info(username, log_levels)
        if user_info and 'uid' in user_info:
            return user_info['uid']

        # Méthode alternative avec id
        try:
            success, stdout, _ = self.run(['id', '-u', username], check=False, no_output=True,
                                        error_as_warning=True, needs_sudo=False)
            if success and stdout.strip().isdigit():
                return int(stdout.strip())
        except Exception:
            pass

        self.log_warning(f"Impossible d'obtenir l'UID pour l'utilisateur {username}", log_levels=log_levels)
        return None

    def clean_user_configs(self, username: str, config_paths: List[str],
                        log_levels: Optional[Dict[str, str]] = None) -> Tuple[bool, int, int]:
        """
        Supprime des fichiers/dossiers de configuration pour un utilisateur spécifique.
        Fonction utilitaire générique pour nettoyer les configurations utilisateur.

        Args:
            username: Nom de l'utilisateur.
            config_paths: Liste des chemins de configuration à supprimer.
            log_levels: Niveaux de log personnalisés (optionnel).

        Returns:
            Tuple (succès: bool, nb_trouvés: int, nb_supprimés: int).
        """
        user_home = self.get_user_home_path(username, log_levels)
        if not user_home:
            self.log_error(f"Impossible d'obtenir le répertoire home pour {username}", log_levels=log_levels)
            return False, 0, 0

        self.log_debug(f"Nettoyage des configurations pour {username} dans {user_home}", log_levels=log_levels)

        success_count = 0
        total_found = 0

        for config_path in config_paths:
            # Remplacer les placeholders si nécessaire et créer un objet Path
            full_path = Path(config_path.replace('{HOME}', user_home))

            if full_path.exists():
                total_found += 1
                self.log_debug(f"Suppression de: {full_path}", log_levels=log_levels)

                try:
                    if full_path.is_file():
                        success, stdout, stderr = self.run(['rm', '-f', str(full_path)],
                                                        check=False, no_output=True,
                                                        error_as_warning=True, needs_sudo=False)
                    elif full_path.is_dir():
                        success, stdout, stderr = self.run(['rm', '-rf', str(full_path)],
                                                        check=False, no_output=True,
                                                        error_as_warning=True, needs_sudo=False)
                    else:
                        self.log_warning(f"Type de fichier non reconnu: {full_path}", log_levels=log_levels)
                        continue

                    if success:
                        success_count += 1
                        self.log_debug(f"Supprimé avec succès: {full_path}", log_levels=log_levels)
                    else:
                        self.log_warning(f"Échec de suppression de {full_path}. Stderr: {stderr}", log_levels=log_levels)

                except Exception as e:
                    self.log_error(f"Exception lors de la suppression de {full_path}: {str(e)}", log_levels=log_levels)
            else:
                self.log_debug(f"Chemin non trouvé (ignoré): {full_path}", log_levels=log_levels)

        final_success = success_count == total_found if total_found > 0 else True
        self.log_debug(f"Nettoyage terminé pour {username}: {success_count}/{total_found} éléments supprimés", log_levels=log_levels)

        return final_success, total_found, success_count