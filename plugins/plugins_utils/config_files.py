#!/usr/bin/env python3
"""
Module utilitaire pour lire et écrire différents formats de fichiers de configuration
(INI, JSON, fichiers à blocs) et manipuler des fichiers texte ligne par ligne.
Utilise principalement les fonctionnalités natives de Python.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import json
import configparser
import tempfile
import shutil
import io
import stat
import time
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple, Generator

class ConfigFileCommands(PluginsUtilsBase):
    """
    Classe pour lire et écrire des fichiers de configuration (INI, JSON, blocs)
    et manipuler des fichiers texte.
    Hérite de PluginUtilsBase pour la journalisation.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de fichiers de configuration."""
        super().__init__(logger, target_ip)
        self._sudo_mode = False  # Mode sudo par défaut (sera détecté à la demande)

    def _check_sudo_required(self, path: Union[str, Path]) -> bool:
        """
        Vérifie si les privilèges sudo sont nécessaires pour accéder à un fichier.

        Args:
            path: Chemin du fichier à vérifier

        Returns:
            bool: True si sudo est nécessaire, False sinon
        """
        file_path = Path(path)

        # Si le fichier n'existe pas, vérifier les permissions du répertoire parent
        if not file_path.exists():
            parent_dir = file_path.parent
            # Vérifier si le répertoire parent existe
            if not parent_dir.exists():
                return True  # Probablement besoin de sudo pour créer des répertoires système

            # Vérifier si on peut écrire dans le répertoire parent
            if not os.access(parent_dir, os.W_OK):
                return True
            return False

        # Vérifier les permissions de lecture/écriture sur le fichier existant
        return not (os.access(file_path, os.R_OK) and os.access(file_path, os.W_OK))

    def _read_file_content(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Lit le contenu d'un fichier, avec gestion sudo si nécessaire.

        Args:
            path: Chemin du fichier à lire

        Returns:
            Optional[str]: Contenu du fichier ou None en cas d'erreur
        """
        file_path = Path(path)
        self.log_debug(f"Lecture du fichier: {file_path}", log_levels=log_levels)

        # Essayer d'abord avec les droits standards
        try:
            if file_path.exists() and os.access(file_path, os.R_OK):
                return file_path.read_text(encoding='utf-8')
        except (PermissionError, OSError) as e:
            self.log_debug(f"Lecture standard échouée pour {file_path}: {e}", log_levels=log_levels)

        # Si on arrive ici, il faut utiliser sudo
        self._sudo_mode = True
        success_read, content, stderr_read = self.run(['cat', str(file_path)],
                                                     check=False, needs_sudo=True,
                                                     no_output=True, error_as_warning=True)

        if not success_read:
            if "No such file" in stderr_read or "no such file" in stderr_read.lower():
                self.log_debug(f"Fichier introuvable: {file_path}", log_levels=log_levels)
            else:
                self.log_error(f"Impossible de lire le fichier {file_path}. Stderr: {stderr_read}", log_levels=log_levels)
            return None

        return content

    def _get_file_stats(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, int]]:
        """
        Obtient les statistiques d'un fichier (uid, gid, mode), avec gestion sudo si nécessaire.

        Args:
            path: Chemin du fichier

        Returns:
            Optional[Dict[str, int]]: Dictionnaire avec uid, gid, mode ou None en cas d'erreur
        """
        file_path = Path(path)

        # Essayer d'abord avec les droits standards
        try:
            if file_path.exists():
                file_stat = file_path.stat()
                return {
                    'uid': file_stat.st_uid,
                    'gid': file_stat.st_gid,
                    'mode': stat.S_IMODE(file_stat.st_mode)
                }
        except (PermissionError, OSError) as e:
            self.log_debug(f"Impossible d'obtenir les stats standard pour {file_path}: {e}", log_levels=log_levels)

        # Si on arrive ici, il faut utiliser sudo
        self._sudo_mode = True
        cmd_stat = ['stat', '-c', '%u:%g:%a', str(file_path)]
        stat_success, stat_stdout, _ = self.run(cmd_stat, check=False, no_output=True,
                                               error_as_warning=True, needs_sudo=True)

        if stat_success and stat_stdout.strip():
            try:
                uid, gid, mode_octal = stat_stdout.strip().split(':')
                return {
                    'uid': int(uid),
                    'gid': int(gid),
                    'mode': int(mode_octal, 8)  # Convertir le mode octal en entier
                }
            except (ValueError, IndexError) as e:
                self.log_warning(f"Erreur lors du traitement des stats pour {file_path}: {e}", log_levels=log_levels)

        return None

    def _backup_file(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Crée une sauvegarde d'un fichier, avec gestion sudo si nécessaire.

        Args:
            path: Chemin du fichier à sauvegarder

        Returns:
            Optional[str]: Chemin de la sauvegarde ou None en cas d'erreur
        """
        file_path = Path(path)

        # Si le fichier n'existe pas, pas besoin de sauvegarde
        if not file_path.exists():
            # Double vérification avec sudo si nécessaire
            if self._sudo_mode:
                success_test, _, _ = self.run(['test', '-e', str(file_path)],
                                             check=False, no_output=True,
                                             error_as_warning=True, needs_sudo=True)
                if not success_test:
                    self.log_debug(f"Fichier {file_path} non trouvé, pas de sauvegarde nécessaire.", log_levels=log_levels)
                    return None
            else:
                self.log_debug(f"Fichier {file_path} non trouvé, pas de sauvegarde nécessaire.", log_levels=log_levels)
                return None

        backup_path = file_path.with_suffix(f"{file_path.suffix}.bak_{int(time.time())}")

        # Essayer d'abord avec les droits standards
        try:
            if not self._sudo_mode:
                shutil.copy2(file_path, backup_path)
                self.log_debug(f"Sauvegarde créée: {backup_path}", log_levels=log_levels)
                return str(backup_path)
        except (PermissionError, OSError) as e:
            self.log_debug(f"Sauvegarde standard échouée pour {file_path}: {e}", log_levels=log_levels)
            self._sudo_mode = True

        # Si on arrive ici, il faut utiliser sudo
        cmd_cp = ['cp', '-a', str(file_path), str(backup_path)]
        success, _, stderr = self.run(cmd_cp, check=False, needs_sudo=True)

        if not success:
            self.log_warning(f"Échec de la création de la sauvegarde {backup_path}. Stderr: {stderr}", log_levels=log_levels)
            return None

        self.log_debug(f"Sauvegarde créée avec sudo: {backup_path}", log_levels=log_levels)
        return str(backup_path)

    def _apply_file_permissions(self, path: Union[str, Path], stats: Dict[str, int], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Applique les permissions et propriétaires à un fichier, avec gestion sudo si nécessaire.

        Args:
            path: Chemin du fichier
            stats: Dictionnaire avec uid, gid, mode

        Returns:
            bool: True si l'opération réussit, False sinon
        """
        file_path = Path(path)

        # Essayer d'abord avec les droits standards
        try:
            if not self._sudo_mode:
                file_path.chmod(stats['mode'])
                os.chown(file_path, stats['uid'], stats['gid'])
                return True
        except (PermissionError, OSError) as e:
            self.log_debug(f"Application des permissions standard échouée pour {file_path}: {e}", log_levels=log_levels)
            self._sudo_mode = True

        # Si on arrive ici, il faut utiliser sudo
        success_chmod = self.run(['chmod', f"{stats['mode']:o}", str(file_path)],
                                needs_sudo=True, check=False, no_output=True)[0]
        success_chown = self.run(['chown', f"{stats['uid']}:{stats['gid']}", str(file_path)],
                                needs_sudo=True, check=False, no_output=True)[0]

        return success_chmod and success_chown

    def _write_file_content(self, path: Union[str, Path], content: str, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Écrit du contenu dans un fichier, avec sauvegarde optionnelle et gestion sudo.

        Args:
            path: Chemin du fichier
            content: Contenu à écrire
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'écriture réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Écriture dans le fichier: {file_path}", log_levels=log_levels)

        # Vérifier si sudo est nécessaire
        self._sudo_mode = self._check_sudo_required(file_path)

        # Obtenir les stats originales (pour restauration après écriture)
        original_stats = None
        if file_path.exists():
            original_stats = self._get_file_stats(file_path)

        # Créer une sauvegarde si demandé
        if backup:
            backup_file = self._backup_file(file_path)

            # Si la sauvegarde réussit et qu'on n'avait pas les stats, les prendre de la sauvegarde
            if backup_file and not original_stats:
                original_stats = self._get_file_stats(backup_file)

        # Utiliser un fichier temporaire pour l'écriture
        tmp_file_path = None
        try:
            fd, tmp_file = tempfile.mkstemp(suffix=".tmp", text=True)
            os.close(fd)  # Fermer le descripteur immédiatement
            tmp_file_path = Path(tmp_file)

            # Écrire le contenu dans le fichier temporaire
            tmp_file_path.write_text(content, encoding='utf-8')
            self.log_debug(f"Contenu écrit dans le fichier temporaire: {tmp_file_path}", log_levels=log_levels)

            # Déplacer le fichier temporaire vers la destination finale
            if self._sudo_mode:
                # Utiliser une commande avec sudo
                cmd_cp = ['cp', str(tmp_file_path), str(file_path)]
                success_cp, _, stderr_cp = self.run(cmd_cp, check=False, needs_sudo=True)
                if not success_cp:
                    self.log_error(f"Échec de la copie vers {file_path}. Stderr: {stderr_cp}", log_levels=log_levels)
                    return False
            else:
                # Utiliser les fonctions Python standard
                shutil.copy2(tmp_file_path, file_path)

            # Restaurer les permissions et propriétaires originaux
            if original_stats:
                success_perm = self._apply_file_permissions(file_path, original_stats)
                if not success_perm:
                    self.log_warning(f"Impossible de restaurer les permissions originales pour {file_path}", log_levels=log_levels)
            else:
                # Appliquer des permissions par défaut si aucune info originale
                default_stats = {'uid': os.getuid(), 'gid': os.getgid(), 'mode': 0o644}
                self._apply_file_permissions(file_path, default_stats)

            self.log_info(f"Fichier {file_path} écrit/mis à jour avec succès.", log_levels=log_levels)
            return True

        except Exception as e:
            self.log_error(f"Erreur lors de l'écriture dans {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

        finally:
            # Nettoyer le fichier temporaire
            if tmp_file_path and tmp_file_path.exists():
                try:
                    tmp_file_path.unlink()
                except Exception as e_unlink:
                    self.log_warning(f"Impossible de supprimer le fichier temporaire {tmp_file_path}: {e_unlink}", log_levels=log_levels)

    # --- Méthodes INI ---

    def _manual_ini_parse(self, content: str, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, str]]:
        """
        Parse manuellement un fichier INI simple ligne par ligne.

        Args:
            content: Contenu du fichier INI

        Returns:
            Dict[str, Dict[str, str]]: Structure INI parsée
        """
        self.log_debug("Tentative de parsing INI manuel simplifié.", log_levels=log_levels)
        data = {'DEFAULT': {}}  # Utiliser une section DEFAULT par défaut
        current_section = 'DEFAULT'

        for line in content.splitlines():
            line_strip = line.strip()

            # Ignorer commentaires et lignes vides
            if not line_strip or line_strip.startswith('#') or line_strip.startswith(';'):
                continue

            # Détecter les sections
            if line_strip.startswith('[') and line_strip.endswith(']'):
                section_name = line_strip[1:-1].strip()
                if section_name:
                    current_section = section_name
                    if current_section not in data:
                        data[current_section] = {}
                continue

            # Chercher le premier '=' comme délimiteur clé/valeur
            if '=' in line_strip:
                key, value = line_strip.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Supprimer les guillemets autour de la valeur
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]

                if key:  # Ignorer si clé vide
                    data[current_section][key] = value

        # Supprimer la section DEFAULT si elle est vide et qu'il y a d'autres sections
        if 'DEFAULT' in data and not data['DEFAULT'] and len(data) > 1:
            del data['DEFAULT']

        return data

    def read_ini_file(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Dict[str, str]]]:
        """
        Lit un fichier INI et le retourne sous forme de dictionnaire imbriqué.
        Gère les fichiers sans section d'en-tête via [DEFAULT].
        Tente un parsing manuel si configparser échoue silencieusement.

        Args:
            path: Chemin du fichier INI

        Returns:
            Optional[Dict[str, Dict[str, str]]]: Structure INI parsée ou None en cas d'erreur
        """
        file_path = Path(path)
        self.log_debug(f"Lecture du fichier INI: {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        content = self._read_file_content(file_path)
        if content is None:
            return None

        # 1. Essayer avec configparser (non strict)
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config_dict = None
        processed_content = content  # Garder une copie pour le parsing manuel

        try:
            # Vérifier s'il faut ajouter une section DEFAULT
            needs_default_section = True
            has_content = False

            for line in content.splitlines():
                line_strip = line.strip()
                if not line_strip or line_strip.startswith('#') or line_strip.startswith(';'):
                    continue

                has_content = True
                if line_strip.startswith('['):
                    needs_default_section = False
                    break

            if has_content and needs_default_section:
                self.log_debug("Aucune section détectée via configparser, ajout de [DEFAULT].", log_levels=log_levels)
                processed_content = "[DEFAULT]\n" + content

            # Utiliser un StringIO pour éviter les problèmes de fichiers
            config.read_string(processed_content)

            # Convertir en dictionnaire standard
            parsed_dict = {section: dict(config.items(section)) for section in config.sections()}

            # Ajouter la section DEFAULT si elle existe et contient des données
            if config.defaults():
                parsed_dict['DEFAULT'] = dict(config.defaults())

            # Vérifier si le parsing a réussi mais retourné un dict vide alors qu'il y avait du contenu
            if has_content and not parsed_dict and not config.defaults():
                self.log_debug("Configparser a retourné un résultat vide malgré du contenu. Tentative de parsing manuel.", log_levels=log_levels)
            else:
                config_dict = parsed_dict  # Le parsing a fonctionné

        except configparser.Error as e:
            # Erreur de parsing explicite, tenter le parsing manuel
            self.log_warning(f"Erreur de parsing INI standard: {e}. Tentative de parsing manuel.", log_levels=log_levels)
        except Exception as e:
            # Autre erreur inattendue, tenter le parsing manuel
            self.log_warning(f"Erreur inattendue lors du parsing INI standard: {e}. Tentative de parsing manuel.", log_levels=log_levels)

        # 2. Essayer le parsing manuel si configparser a échoué ou retourné vide pour un fichier non vide
        if config_dict is None or (has_content and not config_dict):
            try:
                config_dict = self._manual_ini_parse(content)  # Utiliser le contenu original

                if not config_dict or ('DEFAULT' in config_dict and not config_dict['DEFAULT'] and len(config_dict) == 1):
                    # Si le parsing manuel a aussi échoué, retourner un dict vide
                    config_dict = {}
                else:
                    self.log_debug("Parsing INI réussi via la méthode manuelle.", log_levels=log_levels)

            except Exception as manual_e:
                self.log_error(f"Le parsing manuel a également échoué: {manual_e}", exc_info=True, log_levels=log_levels)
                return None  # Échec des deux méthodes

        self.log_debug(f"Contenu INI final lu: {config_dict}", log_levels=log_levels)
        return config_dict if config_dict is not None else {}

    def get_ini_value(self, path: Union[str, Path], section: str, key: str, default: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Récupère une valeur spécifique d'un fichier INI.

        Args:
            path: Chemin du fichier INI
            section: Nom de la section
            key: Nom de la clé
            default: Valeur par défaut si la clé n'existe pas

        Returns:
            Optional[str]: Valeur de la clé ou valeur par défaut
        """
        config_dict = self.read_ini_file(path)
        if config_dict is None:
            # Vérifier si le fichier n'existe pas
            file_path = Path(path)
            if not file_path.exists():
                return default
            return None  # Erreur de lecture/parsing

        # Si la section DEFAULT a été ajoutée implicitement, la vérifier aussi
        value = config_dict.get(section, {}).get(key)
        if value is None and section != 'DEFAULT':
            value = config_dict.get('DEFAULT', {}).get(key)

        return value if value is not None else default

    def set_ini_value(self, path: Union[str, Path], section: str, key: str, value: Optional[str],
create_section: bool = True, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit ou supprime une valeur dans un fichier INI.

        Args:
            path: Chemin du fichier INI
            section: Nom de la section
            key: Nom de la clé
            value: Nouvelle valeur ou None pour supprimer la clé
            create_section: Si True, crée la section si elle n'existe pas
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la modification réussit, False sinon
        """
        file_path = Path(path)
        action = "Suppression de" if value is None else "Définition de"
        self.log_debug(f"{action} la clé INI '{key}' dans la section '[{section}]' du fichier: {file_path}", log_levels=log_levels)
        if value is not None:
            self.log_debug(f"  Nouvelle valeur: '{value}'", log_levels=log_levels)

        # Utiliser un ConfigParser pour préserver la structure et les commentaires
        config = configparser.ConfigParser(interpolation=None)

        # Lire le contenu existant
        current_content = ""
        if file_path.exists():
            content_read = self._read_file_content(file_path)
            if content_read:
                current_content = content_read

        # Prétraitement pour ajouter [DEFAULT] si nécessaire
        original_needs_default = False
        processed_content = current_content

        if current_content:
            needs_default_section = True
            has_content = False

            for line in current_content.splitlines():
                line_strip = line.strip()
                if not line_strip or line_strip.startswith('#') or line_strip.startswith(';'):
                    continue

                has_content = True
                if line_strip.startswith('['):
                    needs_default_section = False
                    break

            if has_content and needs_default_section:
                processed_content = "[DEFAULT]\n" + current_content
                original_needs_default = True

        try:
            # Lire le contenu existant
            if processed_content:
                config.read_string(processed_content)

            # Vérifier/Créer la section
            target_section = section if section else 'DEFAULT'
            if not config.has_section(target_section) and target_section != 'DEFAULT':
                if create_section:
                    self.log_debug(f"Création de la section INI: [{target_section}]", log_levels=log_levels)
                    config.add_section(target_section)
                else:
                    self.log_error(f"La section INI '[{target_section}]' n'existe pas et create_section=False.", log_levels=log_levels)
                    return False

            # Définir ou supprimer la valeur
            if value is None:
                if config.has_option(target_section, key):
                    config.remove_option(target_section, key)
                    self.log_debug(f"Clé '{key}' supprimée de la section '[{target_section}]'.", log_levels=log_levels)
                else:
                    self.log_debug(f"Clé '{key}' n'existait pas dans la section '[{target_section}]'.", log_levels=log_levels)
            else:
                config.set(target_section, key, str(value))  # Assurer que la valeur est une chaîne
                self.log_debug(f"Clé '{key}' définie à '{value}' dans la section '[{target_section}]'.", log_levels=log_levels)

            # Écrire le contenu modifié dans une chaîne
            string_io = io.StringIO()
            config.write(string_io)
            new_content = string_io.getvalue()

            # Si l'original n'avait pas de section, et qu'on a écrit seulement dans [DEFAULT],
            # on retire l'en-tête [DEFAULT] du contenu final.
            if original_needs_default and not config.sections():
                lines = new_content.splitlines()
                if lines and lines[0].strip() == '[DEFAULT]':
                    new_content = "\n".join(lines[1:])
                    self.log_debug("En-tête [DEFAULT] retiré avant l'écriture car fichier original sans section.", log_levels=log_levels)

            # Écrire le fichier final
            return self._write_file_content(file_path, new_content, backup=backup)

        except Exception as e:
            self.log_error(f"Erreur lors de la modification de la configuration INI: {e}", exc_info=True, log_levels=log_levels)
            return False

    # --- Méthodes JSON ---

    def read_json_file(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[Any]:
        """
        Lit un fichier JSON et le retourne comme objet Python.

        Args:
            path: Chemin du fichier JSON

        Returns:
            Optional[Any]: Contenu JSON parsé ou None en cas d'erreur
        """
        file_path = Path(path)
        self.log_debug(f"Lecture du fichier JSON: {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        content = self._read_file_content(file_path)
        if content is None:
            return None

        try:
            data = json.loads(content)
            self.log_debug("Contenu JSON lu avec succès.", log_levels=log_levels)
            return data
        except json.JSONDecodeError as e:
            self.log_error(f"Erreur de parsing JSON dans {file_path}: {e}", log_levels=log_levels)
            return None
        except Exception as e:
            self.log_error(f"Erreur inattendue lors du parsing JSON pour {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return None

    def write_json_file(self, path: Union[str, Path], data: Any, indent: Optional[int] = 2, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Écrit un objet Python dans un fichier JSON.

        Args:
            path: Chemin du fichier JSON
            data: Données à écrire
            indent: Nombre d'espaces pour l'indentation (None pour minifier)
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'écriture réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Écriture des données JSON dans: {file_path}", log_levels=log_levels)

        try:
            # Utiliser ensure_ascii=False pour un meilleur support UTF-8
            json_content = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
            return self._write_file_content(file_path, json_content, backup=backup)
        except Exception as e:
            self.log_error(f"Erreur lors de la génération ou écriture du contenu JSON: {e}", exc_info=True, log_levels=log_levels)
            return False

    # --- Méthodes Fichiers Texte Génériques ---

    def read_file_lines(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        """
        Lit toutes les lignes d'un fichier texte.

        Args:
            path: Chemin du fichier

        Returns:
            Optional[List[str]]: Liste des lignes ou None en cas d'erreur
        """
        file_path = Path(path)
        self.log_debug(f"Lecture des lignes du fichier: {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        content = self._read_file_content(file_path)
        if content is None:
            return None

        # Retourner les lignes en gardant les fins de ligne originales
        return content.splitlines(keepends=True)

    def get_line_containing(self, path: Union[str, Path], pattern: str, first_match_only: bool = True, log_levels: Optional[Dict[str, str]] = None) -> Union[Optional[str], List[str], None]:
        """
        Trouve la première ou toutes les lignes contenant un motif regex.

        Args:
            path: Chemin du fichier
            pattern: Motif regex à rechercher
            first_match_only: Si True, renvoie seulement la première ligne correspondante

        Returns:
            Union[Optional[str], List[str], None]: Ligne correspondante, liste de lignes ou None
        """
        lines = self.read_file_lines(path)
        if lines is None:
            return None

        self.log_debug(f"Recherche du pattern '{pattern}' dans {path}", log_levels=log_levels)
        found_lines = []

        try:
            regex = re.compile(pattern)
            for line in lines:
                if regex.search(line):
                    # Rstrip seulement pour le retour, garder la ligne originale pour l'écriture
                    line_clean = line.rstrip('\n')
                    if first_match_only:
                        return line_clean
                    found_lines.append(line_clean)

            return found_lines if found_lines else ([] if not first_match_only else None)

        except re.error as e:
            self.log_error(f"Erreur de regex dans le pattern '{pattern}': {e}", log_levels=log_levels)
            return None

    def replace_line(self, path: Union[str, Path], pattern: str, new_line: str, replace_all: bool = False, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Remplace la première ou toutes les lignes correspondant à un motif regex.

        Args:
            path: Chemin du fichier
            pattern: Motif regex à rechercher
            new_line: Nouvelle ligne à utiliser en remplacement
            replace_all: Si True, remplace toutes les occurrences, sinon uniquement la première
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si le remplacement réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Remplacement des lignes correspondant à '{pattern}' dans {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        lines = self.read_file_lines(file_path)
        if lines is None:
            return False

        new_lines = []
        modified = False
        replaced_count = 0

        try:
            regex = re.compile(pattern)
            # S'assurer que la nouvelle ligne a une fin de ligne
            new_line_with_eol = new_line.rstrip('\n') + '\n'

            for line in lines:
                # Utiliser search pour trouver le pattern n'importe où dans la ligne
                if regex.search(line) and (replace_all or replaced_count == 0):
                    new_lines.append(new_line_with_eol)
                    modified = True
                    replaced_count += 1
                    self.log_debug(f"  Ligne remplacée: {line.strip()} -> {new_line.strip()}", log_levels=log_levels)
                else:
                    new_lines.append(line)  # Garder la ligne originale avec sa fin de ligne

            if not modified:
                self.log_debug("Aucune ligne correspondante trouvée pour remplacement.", log_levels=log_levels)
                return True  # Pas d'erreur si rien à remplacer

            # Écrire le contenu modifié
            return self._write_file_content(file_path, "".join(new_lines), backup=backup)

        except re.error as e:
            self.log_error(f"Erreur de regex dans le pattern '{pattern}': {e}", log_levels=log_levels)
            return False
        except Exception as e:
            self.log_error(f"Erreur lors du remplacement dans {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def comment_line(self, path: Union[str, Path], pattern: str, comment_char: str = '#', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Commente les lignes correspondant à un motif regex.

        Args:
            path: Chemin du fichier
            pattern: Motif regex à rechercher
            comment_char: Caractère de commentaire à utiliser
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si le commentage réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Commentage des lignes correspondant à '{pattern}' dans {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        lines = self.read_file_lines(file_path)
        if lines is None:
            return False

        new_lines = []
        modified = False

        try:
            regex = re.compile(pattern)
            for line in lines:
                line_strip = line.strip()
                # Ne commenter que si elle correspond ET n'est pas déjà commentée (ou vide)
                if line_strip and not line_strip.startswith(comment_char) and regex.search(line):
                    # Préserver l'indentation originale
                    indent = line[:len(line) - len(line.lstrip())]
                    new_lines.append(f"{indent}{comment_char} {line_strip}\n")
                    modified = True
                    self.log_debug(f"  Ligne commentée: {line_strip}", log_levels=log_levels)
                else:
                    new_lines.append(line)  # Garder la ligne originale

            if not modified:
                self.log_debug("Aucune ligne à commenter trouvée.", log_levels=log_levels)
                return True

            # Écrire le contenu modifié
            return self._write_file_content(file_path, "".join(new_lines), backup=backup)

        except re.error as e:
            self.log_error(f"Erreur de regex dans le pattern '{pattern}': {e}", log_levels=log_levels)
            return False
        except Exception as e:
            self.log_error(f"Erreur lors du commentage dans {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def uncomment_line(self, path: Union[str, Path], pattern: str, comment_char: str = '#', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Décommente les lignes correspondant à un motif regex.

        Args:
            path: Chemin du fichier
            pattern: Motif regex à rechercher
            comment_char: Caractère de commentaire à supprimer
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si le décommentage réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Décommentage des lignes correspondant à '{pattern}' dans {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        lines = self.read_file_lines(file_path)
        if lines is None:
            return False

        new_lines = []
        modified = False

        try:
            regex = re.compile(pattern)
            # Regex pour trouver le commentaire au début (avec ou sans espace après)
            comment_regex = re.compile(r"^(\s*)" + re.escape(comment_char) + r"\s*(.*)")

            for line in lines:
                match_comment = comment_regex.match(line)
                # Vérifier si la ligne est commentée ET si le contenu décommenté correspond au pattern
                if match_comment:
                    indent, uncommented_content = match_comment.groups()
                    if regex.search(uncommented_content):  # Vérifier le pattern sur le contenu décommenté
                        new_lines.append(f"{indent}{uncommented_content}\n")  # Restaurer indentation
                        modified = True
                        self.log_debug(f"  Ligne décommentée: {line.strip()}", log_levels=log_levels)
                    else:
                        new_lines.append(line)  # Ne correspond pas au pattern, garder commenté
                else:
                    new_lines.append(line)  # Pas commenté, garder tel quel

            if not modified:
                self.log_debug("Aucune ligne à décommenter trouvée.", log_levels=log_levels)
                return True

            # Écrire le contenu modifié
            return self._write_file_content(file_path, "".join(new_lines), backup=backup)

        except re.error as e:
            self.log_error(f"Erreur de regex dans le pattern '{pattern}': {e}", log_levels=log_levels)
            return False
        except Exception as e:
            self.log_error(f"Erreur lors du décommentage dans {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def append_line(self, path: Union[str, Path], line_to_append: str, ensure_newline: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute une ligne à la fin d'un fichier.

        Args:
            path: Chemin du fichier
            line_to_append: Ligne à ajouter
            ensure_newline: Si True, s'assure que la ligne a un saut de ligne à la fin

        Returns:
            bool: True si l'ajout réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Ajout de la ligne à la fin de {file_path}: {line_to_append[:50]}...", log_levels=log_levels)

        # Préparer le contenu à ajouter
        content_to_append = line_to_append
        if ensure_newline and not content_to_append.endswith('\n'):
            content_to_append += '\n'

        # Vérifier si sudo est nécessaire
        self._sudo_mode = self._check_sudo_required(file_path)

        # Si le fichier n'existe pas ou n'est pas accessible en écriture, utiliser _write_file_content
        if not file_path.exists() or self._sudo_mode:
            # Lire le contenu existant si le fichier existe
            existing_content = ""
            if file_path.exists():
                existing_content_read = self._read_file_content(file_path)
                if existing_content_read is not None:
                    existing_content = existing_content_read

            # Ajouter la nouvelle ligne et écrire le fichier
            new_content = existing_content + content_to_append
            return self._write_file_content(file_path, new_content, backup=False)

        # Si le fichier existe et est accessible en écriture, utiliser la méthode d'écriture standard
        try:
            with file_path.open('a', encoding='utf-8') as f:
                f.write(content_to_append)
            self.log_info(f"Ligne ajoutée avec succès à {file_path}.", log_levels=log_levels)
            return True
        except Exception as e:
            self.log_error(f"Erreur lors de l'ajout de la ligne à {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def ensure_line_exists(self, path: Union[str, Path], line_to_ensure: str, pattern_to_check: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        S'assure qu'une ligne spécifique existe dans un fichier, l'ajoute sinon.

        Args:
            path: Chemin du fichier
            line_to_ensure: La ligne exacte qui doit exister (sera ajoutée si absente)
            pattern_to_check: Regex pour vérifier l'existence. Si None, utilise line_to_ensure littéralement
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la ligne existe ou a été ajoutée avec succès
        """
        file_path = Path(path)
        self.log_debug(f"Vérification/Ajout de la ligne dans {file_path}: {line_to_ensure[:50]}...", log_levels=log_levels)

        # Lire le contenu actuel
        current_content = ""
        if file_path.exists():
            content_read = self._read_file_content(file_path)
            if content_read is not None:
                current_content = content_read

        # Vérifier l'existence
        line_exists = False
        try:
            check_pattern = pattern_to_check if pattern_to_check else r'^' + re.escape(line_to_ensure.strip()) + r'\s*$'
            if re.search(check_pattern, current_content, re.MULTILINE):
                line_exists = True
        except re.error as e:
            self.log_error(f"Erreur de regex dans le pattern '{pattern_to_check}': {e}", log_levels=log_levels)
            return False

        # Ajouter si nécessaire
        if line_exists:
            return True
        else:
            # Ajouter la ligne avec un saut de ligne avant si nécessaire
            new_content = current_content
            if current_content and not current_content.endswith('\n'):
                new_content += '\n'
            new_content += line_to_ensure.rstrip('\n') + '\n'

            return self._write_file_content(file_path, new_content, backup=backup)

    # --- Méthodes pour les fichiers de configuration à blocs (type Dovecot) ---
    def _parse_block_config(self, content: str, log_levels: Optional[Dict[str, str]] = None) -> dict:
        """
        Parse un fichier de configuration utilisant une structure en blocs avec accolades.
        Supporte les configurations comme Dovecot, Nginx, etc.
        Version améliorée avec meilleure gestion des blocs anonymes et accolades.

        Args:
            content: Contenu du fichier à parser

        Returns:
            dict: Structure hiérarchique représentant la configuration
        """
        self.log_debug("Parsing d'un fichier de configuration à blocs", log_levels=log_levels)

        # Structure pour stocker la configuration parsée
        config = {}

        # Pile pour suivre les blocs imbriqués actuels
        stack = [config]

        # Contexte actuel (bloc parent)
        current_context = config

        # État du parsing
        in_string = False
        in_comment = False
        multiline_comment = False
        escape_next = False
        line_num = 1
        buffer = ""
        current_key = None

        # Compteur pour générer des clés uniques pour les sections anonymes
        anonymous_block_counter = 0

        # Parcourir chaque caractère
        i = 0
        while i < len(content):
            char = content[i]

            # Gestion des sauts de ligne pour le comptage
            if char == '\n':
                line_num += 1
                in_comment = False  # Fin d'un commentaire en ligne

            # Gestion des commentaires
            if not in_string and not multiline_comment and not in_comment:
                # Commentaire en ligne (#)
                if char == '#':
                    in_comment = True
                    i += 1
                    continue

                # Commentaire multiligne (/* */)
                if char == '/' and i + 1 < len(content) and content[i + 1] == '*':
                    multiline_comment = True
                    i += 2
                    continue

            # Fin d'un commentaire multiligne
            if multiline_comment and char == '*' and i + 1 < len(content) and content[i + 1] == '/':
                multiline_comment = False
                i += 2
                continue

            # Ignorer les caractères dans les commentaires
            if in_comment or multiline_comment:
                i += 1
                continue

            # Gestion des chaînes entre guillemets
            if (char == '"' or char == "'") and not escape_next:
                in_string = not in_string

            # Gestion des caractères échappés
            if char == '\\' and not escape_next:
                escape_next = True
                i += 1
                continue
            else:
                escape_next = False

            # Si nous sommes dans une chaîne, ajouter le caractère au buffer
            if in_string:
                buffer += char
                i += 1
                continue

            # Début d'un nouveau bloc
            if char == '{':
                if current_key:
                    # Créer un nouveau bloc sous la clé actuelle
                    new_block = {}

                    # Si la clé existe déjà et contient une valeur simple
                    if current_key in current_context:
                        if isinstance(current_context[current_key], dict):
                            # La clé existe déjà et c'est un dictionnaire
                            # Dans ce cas, nous devons transformer la structure en liste de blocs
                            if not isinstance(current_context[current_key], list):
                                current_context[current_key] = [current_context[current_key]]
                            current_context[current_key].append(new_block)
                        else:
                            # Garder la valeur primitive comme propriété spéciale du bloc
                            value = current_context[current_key]
                            current_context[current_key] = new_block
                            new_block["_value"] = value.strip() if isinstance(value, str) else value
                    else:
                        # Nouvelle clé
                        current_context[current_key] = new_block

                    # Pousser le nouveau bloc sur la pile
                    stack.append(new_block)
                    current_context = new_block
                    current_key = None
                else:
                    # Bloc anonyme - créer un nom unique
                    anonymous_block_counter += 1
                    anonymous_key = f"_anonymous_block_{anonymous_block_counter}"
                    self.log_debug(f"Bloc anonyme trouvé à la ligne {line_num}, utilisation de la clé {anonymous_key}", log_levels=log_levels)

                    new_block = {}
                    current_context[anonymous_key] = new_block

                    # Pousser le nouveau bloc sur la pile
                    stack.append(new_block)
                    current_context = new_block

                buffer = ""

            # Fin d'un bloc
            elif char == '}':
                # Traiter toute donnée restante dans le buffer avant de fermer le bloc
                if buffer.strip() and current_key:
                    current_context[current_key] = buffer.strip()
                    buffer = ""
                    current_key = None

                # Remonter d'un niveau
                if len(stack) > 1:  # Éviter de dépasser la racine
                    stack.pop()
                    current_context = stack[-1]
                else:
                    self.log_debug(f"Accolade fermante excessive à la ligne {line_num}, ignorée", log_levels=log_levels)

                buffer = ""

            # Séparateur de clé-valeur
            elif char == '=' and current_key is None and not in_string:
                current_key = buffer.strip()
                buffer = ""

            # Fin d'instruction (point-virgule)
            elif char == ';' and not in_string:
                if current_key is not None:
                    value = buffer.strip()
                    # Gérer les valeurs multiples pour la même clé
                    if current_key in current_context:
                        existing = current_context[current_key]
                        if isinstance(existing, list):
                            if isinstance(existing[0], dict):
                                # Liste de blocs - ajouter la valeur comme bloc avec _value
                                new_block = {"_value": value}
                                existing.append(new_block)
                            else:
                                # Liste de valeurs - ajouter simplement la valeur
                                existing.append(value)
                        elif isinstance(existing, dict):
                            # Convertir en liste de blocs
                            current_context[current_key] = [existing, {"_value": value}]
                        else:
                            # Convertir en liste de valeurs
                            current_context[current_key] = [existing, value]
                    else:
                        current_context[current_key] = value

                    current_key = None
                    buffer = ""
                elif buffer.strip():
                    # Instruction sans clé (directive simple)
                    value = buffer.strip()
                    # Générer une clé spéciale pour les directives simples
                    directive_key = f"_directive_{len(current_context)}"
                    current_context[directive_key] = value
                    buffer = ""

            # Espace blanc entre directives/blocs
            elif char.isspace() and not buffer.strip() and current_key is None:
                pass  # Ignorer les espaces entre directives

            # Tout autre caractère est ajouté au buffer
            else:
                buffer += char

            i += 1

        # Gérer les données restantes dans le buffer
        if buffer.strip() and current_key is not None:
            current_context[current_key] = buffer.strip()

        # Vérifier les blocs non fermés (la pile devrait normalement ne contenir que la racine)
        if len(stack) > 1:
            self.log_warning(f"Fichier de configuration incomplet : {len(stack) - 1} blocs non fermés", log_levels=log_levels)

        return config

    def _format_block_config(self, config: dict, indent: int = 0, in_block: bool = False, log_levels: Optional[Dict[str, str]] = None) -> str:
        """
        Formate une structure de configuration en blocs en texte.

        Args:
            config: Structure de configuration
            indent: Niveau d'indentation actuel
            in_block: Si True, nous sommes dans un bloc nommé

        Returns:
            str: Représentation textuelle formatée
        """
        lines = []
        indent_str = "    " * indent

        # Valeur spéciale pour le bloc lui-même
        if "_value" in config:
            special_value = config.pop("_value")
            if special_value:
                lines.append(f"{special_value}")

        for key, value in config.items():
            # Ignorer les clés spéciales commençant par _
            if key.startswith("_directive_"):
                lines.append(f"{indent_str}{value};")
                continue

            if isinstance(value, dict):
                lines.append(f"{indent_str}{key} {{")
                lines.append(self._format_block_config(value, indent + 1, True))
                lines.append(f"{indent_str}}}")
            elif isinstance(value, list):
                # Gérer les listes de valeurs ou de blocs
                if all(isinstance(item, dict) for item in value):
                    # Liste de blocs
                    for item in value:
                        lines.append(f"{indent_str}{key} {{")
                        lines.append(self._format_block_config(item, indent + 1, True))
                        lines.append(f"{indent_str}}}")
                else:
                    # Liste de valeurs
                    for item in value:
                        lines.append(f"{indent_str}{key} = {item};")
            else:
                # Valeur simple
                lines.append(f"{indent_str}{key} = {value};")

        return "\n".join(lines)

    def read_block_config_file(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """
        Lit un fichier de configuration utilisant une structure en blocs avec accolades.

        Args:
            path: Chemin du fichier à lire

        Returns:
            Optional[Dict]: Structure de configuration parsée ou None en cas d'erreur
        """
        file_path = Path(path)
        self.log_debug(f"Lecture du fichier de configuration à blocs: {file_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        content = self._read_file_content(file_path)
        if content is None:
            return None

        try:
            # Parser le contenu
            config = self._parse_block_config(content)
            print(config)
            return config
        except Exception as e:
            self.log_error(f"Erreur lors du parsing du fichier de configuration {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return None

    def write_block_config_file(self, path: Union[str, Path], config: dict, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Écrit une structure de configuration en blocs dans un fichier.

        Args:
            path: Chemin du fichier à écrire
            config: Structure de configuration à écrire
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'écriture réussit, False sinon
        """
        file_path = Path(path)
        self.log_debug(f"Écriture de la configuration en blocs dans: {file_path}", log_levels=log_levels)

        try:
            # Formater la configuration
            content = self._format_block_config(config)

            # Écrire le fichier
            return self._write_file_content(file_path, content, backup=backup)
        except Exception as e:
            self.log_error(f"Erreur lors de l'écriture du fichier de configuration {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def update_block_config(self, path: Union[str, Path], key_path: str, value: Any, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Met à jour une valeur dans un fichier de configuration à blocs.

        Args:
            path: Chemin du fichier de configuration
            key_path: Chemin de la clé à mettre à jour (format 'section/sous-section/clé')
            value: Nouvelle valeur à définir
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        config = self.read_block_config_file(path)
        if config is None:
            self.log_error(f"Impossible de lire le fichier de configuration pour mise à jour: {path}", log_levels=log_levels)
            return False

        # Parcourir le chemin pour trouver et mettre à jour la valeur
        keys = key_path.split('/')
        current = config

        # Naviguer jusqu'au parent de la clé à mettre à jour
        for i, key in enumerate(keys[:-1]):
            if key not in current:
                # Créer les sections manquantes
                current[key] = {}
            elif not isinstance(current[key], dict):
                # Convertir une valeur simple en dictionnaire si nécessaire
                old_value = current[key]
                current[key] = {"_value": old_value}

            current = current[key]

        # Mettre à jour la valeur
        last_key = keys[-1]
        current[last_key] = value

        # Écrire la configuration mise à jour
        return self.write_block_config_file(path, config, backup=backup)