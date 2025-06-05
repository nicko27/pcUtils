# install/plugins/plugins_utils/ldap.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour interagir avec des annuaires LDAP via les commandes système.
Utilise ldapsearch, ldapadd, ldapmodify, ldapdelete, ldappasswd.
NOTE: Le parsing de la sortie LDIF peut être fragile. Nécessite le paquet 'ldap-utils'.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import tempfile
import shutil
import shlex # Pour échapper les arguments
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple, Generator

# Regex pour parser une entrée LDIF simple retournée par ldapsearch
# Capture les lignes "clé: valeur" et gère les lignes continuées (commençant par un espace)
LDIF_LINE_RE = re.compile(r'^([^:]+):\s?(.*)$')
# Regex pour détecter le début d'une nouvelle entrée (ligne "dn:")
DN_LINE_RE = re.compile(r'^dn:\s?(.*)$', re.IGNORECASE)

class LdapCommands(PluginsUtilsBase):
    """
    Classe pour interagir avec LDAP via les commandes ldap-utils.
    Hérite de PluginUtilsBase pour l'exécution de commandes et la journalisation.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire LDAP."""
        super().__init__(logger, target_ip)
        # Vérifier la présence des commandes nécessaires
        self._cmd_paths: Dict[str, Optional[str]] = {}

    def _get_cmd_path(self, tool_name: str) -> Optional[str]:
        """Récupère le chemin d'une commande LDAP, loggue une erreur si absente."""
        path = shutil.which(tool_name)
        if not path:
             self.log_error(f"Commande '{tool_name}' non trouvée ou non initialisée.", log_levels=log_levels)
        return path

    def _build_auth_args(self, bind_dn: Optional[str], password: Optional[str]) -> List[str]:
        """Construit les arguments d'authentification pour les commandes LDAP."""
        args = []
        if bind_dn:
            args.extend(['-D', bind_dn])
            if password:
                # ATTENTION: Mot de passe visible dans la liste des processus !
                self.log_warning("Utilisation de l'option -w : le mot de passe peut être visible.", log_levels=log_levels)
                args.extend(['-w', password])
            else:
                 # Utiliser -x pour simple bind anonyme si pas de mot de passe mais un bind_dn
                 args.append('-x')
                 self.log_warning(f"Authentification simple anonyme demandée pour {bind_dn} (pas de mot de passe fourni).", log_levels=log_levels)
        else:
            # Simple bind anonyme par défaut si pas de bind_dn
            args.append('-x')
        return args

    def _build_common_args(self, server: Optional[str], port: int = 389, use_tls: bool = False, use_starttls: bool = False) -> List[str]:
        """Construit les arguments communs (serveur, port, TLS/StartTLS)."""
        args = []
        if server:
            proto = "ldap://"
            conn_port = port
            if use_tls:
                proto = "ldaps://"
                conn_port = 636 # Port LDAPS par défaut
            uri = f"{proto}{server}:{conn_port}"
            args.extend(['-H', uri])
        # L'option pour STARTTLS est -Z (double Z) pour ldapsearch/modify/etc.
        if use_starttls and not use_tls:
             args.append('-ZZ') # Double Z pour exiger StartTLS réussi
             # Alternative: -Z pour essayer StartTLS mais continuer si échec (moins sûr)
        return args

    def parse_ldif(self, ldif_output: str, log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Parse une sortie LDIF multiligne (typiquement de ldapsearch) en une liste de dictionnaires.
        Gère les attributs multivalués et les lignes continuées. Moins robuste qu'une vraie bibliothèque LDAP.
        """
        entries = []
        current_entry: Optional[Dict[str, Any]] = None
        current_key: Optional[str] = None
        current_values: List[str] = []
        # Utiliser un buffer pour reconstruire les lignes continuées
        line_buffer = ""

        for line in ldif_output.splitlines():
            # Gestion des lignes continuées (commencent par un espace)
            if line.startswith(" "):
                line_buffer += line[1:]
                continue
            else:
                # Traiter la ligne précédente (complète) si elle était dans le buffer
                if line_buffer:
                    if current_key and current_entry is not None:
                        # Ajouter la valeur reconstituée à la liste des valeurs pour la clé courante
                        current_values.append(line_buffer)
                    line_buffer = "" # Réinitialiser le buffer

            # Ignorer les commentaires et lignes vides entre les entrées
            line_strip = line.strip()
            if not line_strip or line_strip.startswith("#"):
                continue

            # Détecter une nouvelle entrée via la ligne "dn:"
            dn_match = DN_LINE_RE.match(line)
            if dn_match:
                # Sauvegarder l'entrée précédente si elle existe et a une clé en cours
                if current_entry is not None and current_key is not None:
                     if len(current_values) == 1:
                         current_entry[current_key] = current_values[0]
                     elif len(current_values) > 1:
                         current_entry[current_key] = current_values # Garder comme liste si multivalué
                # Sauvegarder l'entrée complète précédente
                if current_entry is not None:
                    entries.append(current_entry)

                # Commencer une nouvelle entrée
                current_entry = {'dn': dn_match.group(1)}
                current_key = None
                current_values = []
                self.log_debug(f"Nouvelle entrée LDIF détectée: {current_entry['dn']}", log_levels=log_levels)
                continue # Passer à la ligne suivante

            # Parser les lignes attribut: valeur
            line_match = LDIF_LINE_RE.match(line)
            if line_match and current_entry is not None:
                key = line_match.group(1).strip()
                value = line_match.group(2) # Garder les espaces initiaux potentiels pour le buffer
                line_buffer = value # Mettre la valeur dans le buffer au cas où elle continue

                # Si la clé change, sauvegarder les valeurs précédentes
                if key != current_key:
                    if current_key is not None:
                        if len(current_values) == 1:
                            current_entry[current_key] = current_values[0]
                        elif len(current_values) > 1:
                            current_entry[current_key] = current_values
                    current_key = key
                    current_values = [] # Nouvelle liste pour la nouvelle clé

        # Traiter la toute dernière ligne dans le buffer
        if line_buffer and current_key and current_entry is not None:
             current_values.append(line_buffer)

        # Sauvegarder les dernières valeurs de la dernière entrée
        if current_entry is not None and current_key is not None:
             if len(current_values) == 1:
                 current_entry[current_key] = current_values[0]
             elif len(current_values) > 1:
                 current_entry[current_key] = current_values
        # Ajouter la toute dernière entrée
        if current_entry is not None:
            entries.append(current_entry)

        self.log_debug(f"Parsing LDIF terminé, {len(entries)} entrées trouvées.", log_levels=log_levels)
        return entries

    def search(self,
               base_dn: str,
               scope: str = 'sub', # sub, base, one
               filter_str: str = '(objectClass=*, log_levels: Optional[Dict[str, str]] = None)',
               attributes: Optional[List[str]] = None,
               bind_dn: Optional[str] = None,
               password: Optional[str] = None,
               server: Optional[str] = None,
               port: int = 389,
               use_tls: bool = False,
               use_starttls: bool = False,
               timeout: int = 10) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Effectue une recherche LDAP via la commande `ldapsearch`.

        Args:
            base_dn: DN de base pour la recherche.
            scope: Étendue de la recherche ('sub', 'base', 'one').
            filter_str: Filtre LDAP (doit être correctement échappé si nécessaire par l'appelant).
            attributes: Liste des attributs à retourner (None pour tous).
            bind_dn: DN pour l'authentification (optionnel).
            password: Mot de passe pour l'authentification (optionnel).
            server: Adresse du serveur LDAP (optionnel, utilise la conf locale sinon).
            port: Port du serveur LDAP.
            use_tls: Utiliser LDAPS.
            use_starttls: Utiliser STARTTLS (via -ZZ).
            timeout: Timeout pour la commande ldapsearch (via -l).

        Returns:
            Tuple (succès: bool, résultats: List[Dict[str, Any]]).
            Les résultats sont une liste de dictionnaires représentant les entrées trouvées.
        """
        tool_path = self._get_cmd_path('ldapsearch')
        if not tool_path: return False, []

        self.log_info(f"Recherche LDAP: base='{base_dn}', scope='{scope}', filter='{filter_str}'", log_levels=log_levels)
        cmd = [tool_path]
        cmd.extend(self._build_common_args(server, port, use_tls, use_starttls))
        cmd.extend(self._build_auth_args(bind_dn, password))
        cmd.extend(['-b', base_dn])
        cmd.extend(['-s', scope])
        cmd.extend(['-l', str(timeout)]) # Timeout ldapsearch

        # Ajouter le filtre et les attributs en derniers arguments
        cmd.append(filter_str)
        if attributes:
            cmd.extend(attributes)

        # Exécuter ldapsearch
        # no_output=True car on parse stdout nous-mêmes
        success, stdout, stderr = self.run(cmd, check=False, timeout=(timeout + 5), no_output=True,needs_sudo= False) # Timeout global un peu plus long

        if not success:
            # Gérer les erreurs courantes
            if "no such object" in stderr.lower():
                 self.log_info(f"La base de recherche '{base_dn}' n'existe pas ou aucun résultat trouvé.", log_levels=log_levels)
                 return True, [] # Pas une erreur fatale
            elif "invalid credentials" in stderr.lower():
                 self.log_error(f"Échec de l'authentification LDAP pour {bind_dn or 'anonyme'}.", log_levels=log_levels)
            elif "can't contact ldap server" in stderr.lower():
                 self.log_error(f"Impossible de contacter le serveur LDAP.", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de ldapsearch. Stderr: {stderr}", log_levels=log_levels)
            # Logguer stdout si contient des infos utiles
            if stdout: self.log_info(f"Sortie ldapsearch (échec):\n{stdout}", log_levels=log_levels)
            return False, []

        # Parser la sortie LDIF
        try:
            results = self.parse_ldif(stdout)
            self.log_info(f"Recherche LDAP réussie, {len(results)} entrée(s) trouvée(s).", log_levels=log_levels)
            return True, results
        except Exception as e:
            self.log_error(f"Erreur lors du parsing de la sortie LDIF de ldapsearch: {e}", exc_info=True, log_levels=log_levels)
            self.log_debug(f"Sortie LDIF brute:\n{stdout}", log_levels=log_levels)
            return False, []

    def _run_ldap_modify_tool(self, tool_name: str, ldif_content: str,
                             bind_dn: Optional[str] = None, password: Optional[str] = None,
                             server: Optional[str] = None, port: int = 389, use_tls: bool = False, use_starttls: bool = False,
                             continue_on_error: bool = False, timeout: int = 30) -> bool:
        """Fonction interne pour exécuter ldapadd ou ldapmodify."""
        tool_path = self._get_cmd_path(tool_name)
        if not tool_path: return False

        self.log_info(f"Exécution de {tool_name}...", log_levels=log_levels)
        cmd = [tool_path]
        cmd.extend(self._build_common_args(server, port, use_tls, use_starttls))
        cmd.extend(self._build_auth_args(bind_dn, password))
        if continue_on_error:
             cmd.append('-c') # Continuer même si des erreurs se produisent

        # Passer le contenu LDIF via stdin
        # Utiliser un timeout global légèrement plus long que celui de la commande
        success, stdout, stderr = self.run(cmd, input_data=ldif_content, check=False, timeout=(timeout + 5))

        if not success:
            self.log_error(f"Échec de {tool_name}. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie {tool_name} (échec):\n{stdout}", log_levels=log_levels)
            return False

        self.log_success(f"{tool_name} exécuté avec succès.", log_levels=log_levels)
        if stdout: self.log_info(f"Sortie {tool_name} (succès):\n{stdout}", log_levels=log_levels)
        return True

    def add(self, ldif_content: str, **conn_kwargs) -> bool:
        """
        Ajoute des entrées via `ldapadd` en utilisant du contenu LDIF.

        Args:
            ldif_content: Chaîne contenant une ou plusieurs entrées au format LDIF.
            **conn_kwargs: Arguments pour la connexion (bind_dn, password, server, etc.).

        Returns:
            bool: True si succès.
        """
        return self._run_ldap_modify_tool('ldapadd', ldif_content, **conn_kwargs)

    def modify(self, ldif_content: str, **conn_kwargs) -> bool:
        """
        Modifie des entrées via `ldapmodify` en utilisant du contenu LDIF.

        Args:
            ldif_content: Chaîne contenant une ou plusieurs modifications au format LDIF.
            **conn_kwargs: Arguments pour la connexion.

        Returns:
            bool: True si succès.
        """
        return self._run_ldap_modify_tool('ldapmodify', ldif_content, **conn_kwargs)

    def delete(self, dn: str, recursive: bool = False,
               bind_dn: Optional[str] = None, password: Optional[str] = None,
               server: Optional[str] = None, port: int = 389, use_tls: bool = False, use_starttls: bool = False,
               continue_on_error: bool = False, timeout: int = 30) -> bool:
        """
        Supprime une entrée LDAP via `ldapdelete`.

        Args:
            dn: DN de l'entrée à supprimer.
            recursive: Si True, tente une suppression récursive (-r). ATTENTION: peut être dangereux.
            **conn_kwargs: Autres arguments pour la connexion.

        Returns:
            bool: True si succès ou si l'entrée n'existait pas.
        """
        tool_path = self._get_cmd_path('ldapdelete')
        if not tool_path: return False

        self.log_info(f"Suppression de l'entrée LDAP: {dn}{' (récursivement)' if recursive else ''}", log_levels=log_levels)
        cmd = [tool_path]
        cmd.extend(self._build_common_args(server, port, use_tls, use_starttls))
        cmd.extend(self._build_auth_args(bind_dn, password))
        if recursive:
             cmd.append('-r')
             self.log_warning("Option de suppression récursive activée.", log_levels=log_levels)
        if continue_on_error:
             cmd.append('-c')
        # Le DN à supprimer est un argument pour ldapdelete
        cmd.append(dn)

        success, stdout, stderr = self.run(cmd, check=False, timeout=(timeout + 5))

        if not success:
            # Gérer l'erreur "No such object" comme un succès potentiel (déjà supprimé)
            if "no such object" in stderr.lower():
                 self.log_warning(f"L'entrée '{dn}' n'existe pas (ou plus). Considéré comme succès.", log_levels=log_levels)
                 return True
            elif "subtree delete requires" in stderr.lower() and not recursive:
                 self.log_error(f"Échec: Impossible de supprimer '{dn}' car elle contient des enfants (utiliser recursive=True?).", log_levels=log_levels)
            else:
                 self.log_error(f"Échec de ldapdelete pour {dn}. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie ldapdelete (échec):\n{stdout}", log_levels=log_levels)
            return False

        self.log_success(f"Entrée LDAP '{dn}' supprimée avec succès.", log_levels=log_levels)
        if stdout: self.log_info(f"Sortie ldapdelete (succès):\n{stdout}", log_levels=log_levels)
        return True

    def change_password(self, user_dn: str,
                        new_password: str,
                        old_password: Optional[str] = None,
                        bind_dn: Optional[str] = None, # DN utilisé pour le bind (peut être user_dn ou admin)
                        bind_password: Optional[str] = None,
                        server: Optional[str] = None, port: int = 389, use_tls: bool = False, use_starttls: bool = False,
                        timeout: int = 15) -> bool:
        """
        Change le mot de passe d'un utilisateur LDAP via `ldappasswd`.

        Args:
            user_dn: DN de l'utilisateur dont le mot de passe doit être changé (-S user_dn).
            new_password: Nouveau mot de passe en clair (-s new_password).
            old_password: Ancien mot de passe en clair (requis si non admin, -a old_password).
            bind_dn: DN pour s'authentifier (-D bind_dn, si None, utilise user_dn).
            bind_password: Mot de passe pour l'authentification (-w bind_password).
            **conn_kwargs: Autres arguments pour la connexion (server, port, etc.).

        Returns:
            bool: True si succès.
        """
        tool_path = self._get_cmd_path('ldappasswd')
        if not tool_path: return False

        # Utiliser user_dn pour le bind si bind_dn n'est pas fourni
        auth_dn = bind_dn if bind_dn else user_dn
        auth_pass = bind_password # Le mot de passe pour le bind

        if not auth_pass:
             self.log_error("Mot de passe requis pour l'authentification (bind_password).", log_levels=log_levels)
             return False

        self.log_info(f"Tentative de changement de mot de passe pour: {user_dn}", log_levels=log_levels)
        cmd = [tool_path]
        cmd.extend(self._build_common_args(server, port, use_tls, use_starttls))
        # Authentification
        cmd.extend(self._build_auth_args(auth_dn, auth_pass))
        # Spécifier l'utilisateur cible
        cmd.extend(['-S', user_dn])
        # Ancien mot de passe
        if old_password:
             cmd.extend(['-a', old_password])
        # Nouveau mot de passe
        cmd.extend(['-s', new_password])

        # ldappasswd peut être interactif s'il manque des infos, mais on fournit tout ici.
        success, stdout, stderr = self.run(cmd, check=False, timeout=(timeout + 5))

        if not success:
            if "invalid credentials" in stderr.lower():
                 self.log_error(f"Échec du changement de mot de passe pour {user_dn}: Identifiants invalides (bind ou ancien mot de passe?).", log_levels=log_levels)
            elif "constraint violation" in stderr.lower():
                 self.log_error(f"Échec du changement de mot de passe pour {user_dn}: Violation de contrainte (vérifier politique de mot de passe).", log_levels=log_levels)
            else:
                 self.log_error(f"Échec du changement de mot de passe pour {user_dn}. Stderr: {stderr}", log_levels=log_levels)
            if stdout: self.log_info(f"Sortie ldappasswd (échec):\n{stdout}", log_levels=log_levels)
            return False

        self.log_success(f"Mot de passe pour {user_dn} changé avec succès.", log_levels=log_levels)
        if stdout: self.log_info(f"Sortie ldappasswd (succès):\n{stdout}", log_levels=log_levels)
        return True

    # --- Fonctions de commodité ---

    def get_user(self, username: str, user_base_dn: str, user_attr: str = 'uid', attributes: Optional[List[str]] = None, **conn_kwargs) -> Optional[Dict[str, Any]]:
        """Recherche un utilisateur par son nom d'utilisateur (ou autre attribut) et retourne ses informations."""
        # Échapper les caractères spéciaux pour le filtre LDAP
        safe_attr = re.sub(r'[*()\\]', r'\\\g<0>', user_attr)
        safe_username = re.sub(r'[*()\\]', r'\\\g<0>', username)
        filter_str = f"({safe_attr}={safe_username})"
        attrs_to_fetch = attributes # None signifie '*' par défaut dans ldapsearch
        success, results = self.search(base_dn=user_base_dn, scope='sub', filter_str=filter_str, attributes=attrs_to_fetch, **conn_kwargs)
        if success and results:
            if len(results) > 1:
                 self.log_warning(f"Plusieurs utilisateurs trouvés pour {username}, retourne le premier.", log_levels=log_levels)
            return results[0]
        self.log_info(f"Utilisateur '{username}' non trouvé dans '{user_base_dn}'.", log_levels=log_levels)
        return None

    def check_user_exists(self, username: str, user_base_dn: str, user_attr: str = 'uid', **conn_kwargs) -> bool:
        """Vérifie si un utilisateur existe en cherchant son DN."""
        # Recherche juste le DN, plus rapide
        return self.get_user(username, user_base_dn, user_attr, attributes=['dn'], **conn_kwargs) is not None

    def add_user_to_group(self, user_dn: str, group_dn: str, member_attr: str = 'member', **conn_kwargs) -> bool:
        """Ajoute un utilisateur (par son DN) à un groupe LDAP via ldapmodify."""
        self.log_info(f"Ajout de '{user_dn}' au groupe '{group_dn}' (attribut: {member_attr})", log_levels=log_levels)
        # Construire le LDIF pour ajouter l'attribut membre
        ldif = f"dn: {group_dn}\n"
        ldif += "changetype: modify\n"
        ldif += f"add: {member_attr}\n"
        ldif += f"{member_attr}: {user_dn}\n"
        # Utiliser continue_on_error=True car ldapmodify peut échouer si l'utilisateur est déjà membre
        return self.modify(ldif, continue_on_error=True, **conn_kwargs)

    def remove_user_from_group(self, user_dn: str, group_dn: str, member_attr: str = 'member', **conn_kwargs) -> bool:
        """Supprime un utilisateur (par son DN) d'un groupe LDAP via ldapmodify."""
        self.log_info(f"Suppression de '{user_dn}' du groupe '{group_dn}' (attribut: {member_attr})", log_levels=log_levels)
        ldif = f"dn: {group_dn}\n"
        ldif += "changetype: modify\n"
        ldif += f"delete: {member_attr}\n"
        ldif += f"{member_attr}: {user_dn}\n"
        # Utiliser continue_on_error=True car ldapmodify échoue si l'utilisateur n'est pas membre
        return self.modify(ldif, continue_on_error=True, **conn_kwargs)