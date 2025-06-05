#!/usr/bin/env python3
"""
Module utilitaire pour manipuler les fichiers de configuration Dovecot.
Hérite de ConfigFileCommands pour réutiliser les fonctionnalités de gestion de fichiers.
Implémente un modèle cohérent "lire, modifier, écrire" pour les configurations Dovecot.
"""

from plugins_utils.config_files import ConfigFileCommands
from pathlib import Path
import os
from typing import Union, Optional, Dict, Any, List, Tuple
import re


class DovecotCommands(ConfigFileCommands):
    """
    Classe pour manipuler les fichiers de configuration Dovecot.
    Hérite de ConfigFileCommands pour réutiliser les fonctionnalités de gestion de fichiers.
    Permet une manipulation cohérente des configurations avec le modèle "lire, modifier, écrire".
    """

    # Chemins par défaut pour les fichiers de configuration
    DEFAULT_CONFIG_PATHS = {
        'main': '/etc/dovecot/dovecot.conf',
        'mail': '/etc/dovecot/conf.d/10-mail.conf',
        'auth': '/etc/dovecot/conf.d/10-auth.conf',
        'master': '/etc/dovecot/conf.d/10-master.conf',
        'ssl': '/etc/dovecot/conf.d/10-ssl.conf',
        'quota': '/etc/dovecot/conf.d/90-quota.conf',
        'acl': '/etc/dovecot/dovecot-acl',
        'sieve': '/etc/dovecot/conf.d/90-sieve.conf',
    }

    def __init__(self, logger=None, target_ip=None, config_dir='/etc/dovecot'):
        """
        Initialise le gestionnaire de fichiers de configuration Dovecot.

        Args:
            logger: Logger à utiliser
            target_ip: IP cible (pour les opérations à distance)
            config_dir: Répertoire de base des configurations Dovecot
        """
        super().__init__(logger, target_ip)
        self.config_dir = Path(config_dir)
        self.loaded_configs = {}  # Cache pour les configurations chargées

    def get_config_path(self, config_type: str, log_levels: Optional[Dict[str, str]] = None) -> Path:
        """
        Obtient le chemin complet d'un fichier de configuration spécifique.

        Args:
            config_type: Type de configuration ('main', 'mail', 'auth', etc.)

        Returns:
            Path: Chemin complet du fichier de configuration
        """
        if config_type in self.DEFAULT_CONFIG_PATHS:
            return Path(self.DEFAULT_CONFIG_PATHS[config_type])

        # Si c'est un chemin direct ou un fichier spécifique dans conf.d
        if os.path.sep in config_type:
            return Path(config_type)

        # Chercher dans conf.d
        return self.config_dir / 'conf.d' / config_type

    def read_config(self, config_type: str, force_reload: bool = False, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """
        Lit un fichier de configuration Dovecot.
        Utilise un cache pour éviter de relire les fichiers inutilement.

        Args:
            config_type: Type de configuration ('main', 'mail', 'auth', etc.) ou chemin
            force_reload: Si True, force la relecture même si déjà en cache

        Returns:
            dict: Structure de configuration parsée ou None en cas d'erreur
        """
        config_path = self.get_config_path(config_type)

        # Utiliser le cache sauf si force_reload est True
        if not force_reload and str(config_path) in self.loaded_configs:
            self.log_debug(f"Utilisation de la configuration en cache pour {config_path}", log_levels=log_levels)
            return self.loaded_configs[str(config_path)]

        self.log_debug(f"Lecture de la configuration Dovecot: {config_path}", log_levels=log_levels)

        # Utiliser _read_file_content de ConfigFileCommands
        content = self._read_file_content(config_path)
        if content is None:
            return None

        config = self.parse_dovecot_config(content)

        if config is not None:
            # Mettre en cache
            self.loaded_configs[str(config_path)] = config

        return config

    def _strip_comment(self, line: str) -> str:
        """
        Supprime les commentaires d'une ligne, en préservant les # à l'intérieur des guillemets.

        Args:
            line: La ligne à traiter

        Returns:
            La ligne sans les commentaires
        """
        pattern = r'^((?:[^#"]*|"[^"]*")*?)(?:#.*)?$'
        match = re.match(pattern, line)
        if match:
            return match.group(1).strip()
        return ""

    def _parse_line(self, line: str) -> Tuple[str, str]:
        """
        Parse une ligne d'assignation (key = value).

        Args:
            line: La ligne à parser

        Returns:
            Tuple contenant (clé, valeur)
        """
        if '=' not in line:
            return line.strip(), ""

        parties = line.split('=', 1)
        key = parties[0].strip()
        value = parties[1].strip()

        # Supprimer les points-virgules en fin de valeur
        if value.endswith(';'):
            value = value[:-1].strip()

        return key, value

    def parse_dovecot_config(self, content: Union[str, List[str]], log_levels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Parse un fichier de configuration Dovecot complet avec une structure hiérarchique.

        Args:
            content: Contenu du fichier (chaîne ou liste de lignes)

        Returns:
            Dict[str, Any]: Structure hiérarchique représentant la configuration
        """
        self.log_debug("Parsing d'un fichier de configuration Dovecot", log_levels=log_levels)

        # Convertir le contenu en liste de lignes si nécessaire
        if isinstance(content, str):
            content_lines = content.splitlines()
        else:
            content_lines = content

        # Structure finale
        config = {}

        # Variables pour le suivi des blocs
        block_stack = []  # Pile pour suivre les blocs imbriqués [(type, name), ...]
        current_content = []  # Contenu du bloc courant
        in_block = False

        # Analyser ligne par ligne
        for line in content_lines:
            # Nettoyer la ligne
            clean_line = self._strip_comment(line.strip())
            if not clean_line:
                continue

            # Détecter le début d'un bloc
            if '{' in clean_line and not in_block:
                in_block = True

                # Extraire le type et le nom du bloc
                # Pour les lignes comme "namespace USER {" ou "plugin {"
                block_header = clean_line.split('{')[0].strip()
                parts = block_header.split(None, 1)

                if len(parts) >= 2:
                    # C'est un bloc avec type et nom, comme "namespace USER"
                    block_type, block_name = parts
                else:
                    # C'est un bloc sans nom spécifique, comme "plugin"
                    block_type = parts[0]
                    block_name = ""

                # Empiler ce bloc
                block_stack.append((block_type, block_name))
                current_content = []

                # Traiter tout ce qui suit l'accolade sur cette ligne
                remainder = clean_line.split('{', 1)[1].strip()
                if remainder and remainder != '}':
                    current_content.append(remainder)

                # Si le bloc se termine sur la même ligne
                if '}' in remainder:
                    in_block = False
                    self._process_block_content(config, block_stack.pop(), current_content)

            # Détecter la fin d'un bloc
            elif '}' in clean_line and in_block:
                # Ajouter le contenu jusqu'à l'accolade fermante
                if '{' not in clean_line:  # Ignorer les nouvelles ouvertures sur la même ligne
                    content_before_brace = clean_line.split('}')[0].strip()
                    if content_before_brace:
                        current_content.append(content_before_brace)

                # Fermer ce bloc et le traiter
                in_block = False
                if block_stack:
                    self._process_block_content(config, block_stack.pop(), current_content)

                # Vérifier s'il y a du contenu après l'accolade fermante
                remainder = clean_line.split('}', 1)[1].strip()
                if remainder:
                    if '{' in remainder:
                        # Nouvelle ouverture de bloc
                        self.log_warning(f"Nouvelle ouverture de bloc sur la même ligne: {remainder}", log_levels=log_levels)
                    else:
                        # Traiter comme une ligne normale
                        key, value = self._parse_line(remainder)
                        if key:
                            config[key] = value

            # Ligne à l'intérieur d'un bloc
            elif in_block:
                current_content.append(clean_line)

            # Ligne normale hors bloc
            else:
                key, value = self._parse_line(clean_line)
                if key:
                    config[key] = value

        # Vérifier si tous les blocs ont été fermés
        if block_stack:
            self.log_warning(f"Des blocs n'ont pas été fermés: {block_stack}", log_levels=log_levels)

        return config

    def _process_block_content(self, config: Dict[str, Any], block_info: Tuple[str, str], content: List[str]):
        """
        Traite le contenu d'un bloc et l'ajoute à la configuration.

        Args:
            config: Dictionnaire de configuration à mettre à jour
            block_info: Tuple (type_bloc, nom_bloc)
            content: Liste des lignes de contenu du bloc
        """
        block_type, block_name = block_info
        block_config = {}

        # Parcourir le contenu du bloc
        i = 0
        while i < len(content):
            line = content[i]
            i += 1

            # Ignorer les accolades isolées
            if line == '{' or line == '}':
                continue

            # Sous-bloc
            if '{' in line:
                # Extraire l'en-tête du sous-bloc
                sub_header = line.split('{')[0].strip()
                sub_parts = sub_header.split(None, 1)

                if len(sub_parts) >= 2:
                    sub_type, sub_name = sub_parts
                else:
                    sub_type = sub_parts[0]
                    sub_name = ""

                # Collecter le contenu du sous-bloc
                sub_content = []
                brace_level = 1

                # Ajouter le reste de la ligne d'ouverture
                remainder = line.split('{', 1)[1].strip()
                if remainder and remainder != '}':
                    sub_content.append(remainder)

                # Si le bloc ne se termine pas sur la même ligne
                if '}' not in remainder:
                    while i < len(content) and brace_level > 0:
                        sub_line = content[i]
                        i += 1

                        if '{' in sub_line:
                            brace_level += 1
                        if '}' in sub_line:
                            brace_level -= 1

                        # Si c'est la dernière accolade, ne pas inclure ce qui suit
                        if brace_level == 0 and '}' in sub_line:
                            before_brace = sub_line.split('}')[0].strip()
                            if before_brace:
                                sub_content.append(before_brace)
                        else:
                            sub_content.append(sub_line)

                # Traiter récursivement ce sous-bloc
                sub_config = {}
                self._process_block_content(sub_config, (sub_type, sub_name), sub_content)

                # Fusionner avec la configuration du bloc parent
                block_config.update(sub_config)

            # Ligne normale d'assignation
            else:
                key, value = self._parse_line(line)
                if key:
                    block_config[key] = value

        # Ajouter ce bloc à la configuration globale
        if block_type:
            # Créer la section si elle n'existe pas
            if block_type not in config:
                config[block_type] = {}

            # Ajouter le bloc nommé à la section
            if block_name:
                config[block_type][block_name] = block_config
            else:
                # Si pas de nom spécifique, fusionner directement avec la section
                config[block_type].update(block_config)
        else:
            # Si pas de type spécifique, fusionner avec la configuration globale
            config.update(block_config)

    def write_config(self, config_type: str, config: Dict, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Écrit une structure de configuration dans un fichier.

        Args:
            config_type: Type de configuration ('main', 'mail', 'auth', etc.) ou chemin
            config: Structure de configuration à écrire
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'écriture réussit, False sinon
        """
        config_path = self.get_config_path(config_type)
        self.log_debug(f"Écriture de la configuration Dovecot: {config_path}", log_levels=log_levels)

        # Générer la représentation texte de la configuration
        config_content = self.generate_config_string(config)

        # Utiliser _write_file_content de ConfigFileCommands pour écrire le fichier
        success = self._write_file_content(config_path, config_content, backup=backup)

        if success:
            # Mettre à jour le cache
            self.loaded_configs[str(config_path)] = config
            self.log_success(f"Configuration Dovecot {config_path} mise à jour avec succès", log_levels=log_levels)
        else:
            self.log_error(f"Échec de l'écriture de la configuration Dovecot {config_path}", log_levels=log_levels)

        return success

    def generate_config_string(self, config: Dict[str, Any], indent_level: int = 0, log_levels: Optional[Dict[str, str]] = None) -> str:
        """
        Génère une représentation textuelle d'une configuration Dovecot.
        Respecte le formatage spécifique de Dovecot pour les plugins et namespaces.

        Args:
            config: Dictionnaire de configuration
            indent_level: Niveau d'indentation actuel

        Returns:
            str: Représentation textuelle formatée
        """
        lines = []
        indent = "  " * indent_level

        # Vérifier que config est bien un dictionnaire
        if not isinstance(config, dict):
            self.log_warning(f"Erreur: objet non-dictionnaire rencontré dans generate_config_string: {type(config)} - {config}", log_levels=log_levels)
            return str(config)  # Retourner la représentation en chaîne de caractères

        # Traiter d'abord les paramètres simples (non-dictionnaires)
        for key, value in config.items():
            if not isinstance(value, dict):
                lines.append(f"{indent}{key} = {value}")

        # Ensuite traiter les blocs
        for key, value in config.items():
            if isinstance(value, dict):
                # Cas spécial pour "plugin" - doit être formaté différemment
                if key == "plugin":
                    # Formater la section plugin comme un bloc
                    lines.append(f"\n{indent}plugin {{")

                    # Ajouter chaque paramètre du plugin
                    plugin_indent = indent + "  "
                    for plugin_key, plugin_value in value.items():
                        if isinstance(plugin_value, dict):
                            # Sous-section dans plugin (rare)
                            lines.append(f"{plugin_indent}{plugin_key} {{")
                            sub_indent = plugin_indent + "  "
                            for sub_key, sub_value in plugin_value.items():
                                lines.append(f"{sub_indent}{sub_key} = {sub_value}")
                            lines.append(f"{plugin_indent}}}")
                        else:
                            # Paramètre simple de plugin
                            lines.append(f"{plugin_indent}{plugin_key} = {plugin_value}")

                    lines.append(f"{indent}}}")

                # Cas spécial pour les namespaces (namespace USER, namespace INBOX, etc.)
                elif key == "namespace":
                    for namespace_name, namespace_config in value.items():
                        if not isinstance(namespace_config, dict):
                            continue

                        # Formater chaque namespace
                        lines.append(f"\n{indent}namespace {namespace_name} {{")

                        # Ajouter chaque paramètre du namespace
                        ns_indent = indent + "  "
                        for ns_key, ns_value in namespace_config.items():
                            if isinstance(ns_value, dict):
                                # Sous-section dans namespace (rare)
                                lines.append(f"{ns_indent}{ns_key} {{")
                                sub_indent = ns_indent + "  "
                                for sub_key, sub_value in ns_value.items():
                                    lines.append(f"{sub_indent}{sub_key} = {sub_value}")
                                lines.append(f"{ns_indent}}}")
                            else:
                                # Paramètre simple de namespace
                                lines.append(f"{ns_indent}{ns_key} = {ns_value}")

                        lines.append(f"{indent}}}")

                # Autres types de blocs comme protocol, service, etc.
                elif key in ["protocol", "service"]:
                    for block_name, block_config in value.items():
                        # Formater le bloc
                        lines.append(f"\n{indent}{key} {block_name} {{")

                        # Ajouter chaque paramètre du bloc
                        if isinstance(block_config, dict):
                            block_indent = indent + "  "
                            for block_key, block_value in block_config.items():
                                if isinstance(block_value, dict):
                                    # Sous-section
                                    lines.append(f"{block_indent}{block_key} {{")
                                    sub_indent = block_indent + "  "
                                    for sub_key, sub_value in block_value.items():
                                        lines.append(f"{sub_indent}{sub_key} = {sub_value}")
                                    lines.append(f"{block_indent}}}")
                                else:
                                    # Paramètre simple
                                    lines.append(f"{block_indent}{block_key} = {block_value}")

                        lines.append(f"{indent}}}")

                # Autres blocs simples
                else:
                    # Formater comme un bloc standard
                    lines.append(f"\n{indent}{key} {{")
                    block_indent = indent + "  "

                    if isinstance(value, dict):
                        for block_key, block_value in value.items():
                            if isinstance(block_value, dict):
                                # Sous-section
                                lines.append(f"{block_indent}{block_key} {{")
                                sub_indent = block_indent + "  "
                                for sub_key, sub_value in block_value.items():
                                    lines.append(f"{sub_indent}{sub_key} = {sub_value}")
                                lines.append(f"{block_indent}}}")
                            else:
                                # Paramètre simple
                                lines.append(f"{block_indent}{block_key} = {block_value}")

                    lines.append(f"{indent}}}")

        return '\n'.join(lines)


    def clear_cache(self, config_type: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> None:
        """
        Vide le cache de configurations.

        Args:
            config_type: Type de configuration spécifique à vider, ou None pour tout vider
        """
        if config_type is None:
            self.loaded_configs = {}
            self.log_debug("Cache de configurations vidé", log_levels=log_levels)
        else:
            config_path = str(self.get_config_path(config_type))
            if config_path in self.loaded_configs:
                del self.loaded_configs[config_path]
                self.log_debug(f"Cache vidé pour {config_path}", log_levels=log_levels)

    def get_global_setting(self, setting_name: str, default: Any = None, log_levels: Optional[Dict[str, str]] = None) -> Any:
        """
        Récupère un paramètre global dans la configuration principale.

        Args:
            setting_name: Nom du paramètre à récupérer
            default: Valeur par défaut si le paramètre n'existe pas

        Returns:
            Any: Valeur du paramètre ou valeur par défaut
        """
        config = self.read_config('main')
        if config is None:
            return default

        return config.get(setting_name, default)

    def set_global_setting(self, setting_name: str, value: Any, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit un paramètre global dans la configuration principale.

        Args:
            setting_name: Nom du paramètre à définir
            value: Nouvelle valeur du paramètre
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        config = self.read_config('main')
        if config is None:
            self.log_error("Impossible de lire la configuration principale", log_levels=log_levels)
            return False

        # Mettre à jour le paramètre
        config[setting_name] = value

        # Écrire la configuration mise à jour
        return self.write_config('main', config, backup=backup)

    def get_mail_setting(self, setting_name: str, default: Any = None, log_levels: Optional[Dict[str, str]] = None) -> Any:
        """
        Récupère un paramètre dans la configuration mail.

        Args:
            setting_name: Nom du paramètre à récupérer
            default: Valeur par défaut si le paramètre n'existe pas

        Returns:
            Any: Valeur du paramètre ou valeur par défaut
        """
        config = self.read_config('mail')
        if config is None:
            return default

        return config.get(setting_name, default)

    def set_mail_setting(self, setting_name: str, value: Any, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit un paramètre dans la configuration mail.

        Args:
            setting_name: Nom du paramètre à définir
            value: Nouvelle valeur du paramètre
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        config = self.read_config('mail')
        if config is None:
            self.log_error("Impossible de lire la configuration mail", log_levels=log_levels)
            return False

        # Mettre à jour le paramètre
        config[setting_name] = value

        # Écrire la configuration mise à jour
        return self.write_config('mail', config, backup=backup)

    def get_mail_plugins(self, log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Récupère la liste des plugins mail activés.

        Returns:
            List[str]: Liste des plugins activés
        """
        plugins_str = self.get_mail_setting('mail_plugins', '')
        if not plugins_str:
            return []

        return [p.strip() for p in str(plugins_str).split()]

    def set_mail_plugins(self, plugins: List[str], backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit la liste des plugins mail activés.

        Args:
            plugins: Liste des plugins à activer
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        plugins_str = ' '.join(plugins)
        return self.set_mail_setting('mail_plugins', plugins_str, backup=backup)

    def add_mail_plugin(self, plugin_name: str, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute un plugin mail s'il n'est pas déjà activé.

        Args:
            plugin_name: Nom du plugin à ajouter
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        plugins = self.get_mail_plugins()
        if plugin_name in plugins:
            self.log_debug(f"Le plugin {plugin_name} est déjà activé", log_levels=log_levels)
            return True

        plugins.append(plugin_name)
        return self.set_mail_plugins(plugins, backup=backup)

    def remove_mail_plugin(self, plugin_name: str, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime un plugin mail s'il est activé.

        Args:
            plugin_name: Nom du plugin à supprimer
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        plugins = self.get_mail_plugins()
        if plugin_name not in plugins:
            self.log_debug(f"Le plugin {plugin_name} n'est pas activé", log_levels=log_levels)
            return True

        plugins.remove(plugin_name)
        return self.set_mail_plugins(plugins, backup=backup)

    def get_plugin_setting(self, plugin_type: str, setting_name: str, default: Any = None, log_levels: Optional[Dict[str, str]] = None) -> Any:
        """
        Récupère un paramètre dans la configuration d'un plugin.

        Args:
            plugin_type: Type de plugin ('quota', 'acl', 'sieve', etc.)
            setting_name: Nom du paramètre à récupérer
            default: Valeur par défaut si le paramètre n'existe pas

        Returns:
            Any: Valeur du paramètre ou valeur par défaut
        """
        config = self.read_config(plugin_type)
        if config is None:
            return default

        plugin_settings = config.get('plugin', {})
        return plugin_settings.get(setting_name, default)

    def set_plugin_setting(self, plugin_type: str, setting_name: str, value: Any, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit un paramètre dans la configuration d'un plugin.

        Args:
            plugin_type: Type de plugin ('quota', 'acl', 'sieve', etc.)
            setting_name: Nom du paramètre à définir
            value: Nouvelle valeur du paramètre
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        config = self.read_config(plugin_type)
        if config is None:
            self.log_error(f"Impossible de lire la configuration du plugin {plugin_type}", log_levels=log_levels)
            return False

        # Créer la section 'plugin' si elle n'existe pas
        if 'plugin' not in config:
            config['plugin'] = {}

        # Mettre à jour le paramètre
        config['plugin'][setting_name] = value

        # Écrire la configuration mise à jour
        return self.write_config(plugin_type, config, backup=backup)

    def get_namespace(self, namespace_name: str, config_type: str = 'mail', log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """
        Récupère un namespace spécifique.

        Args:
            namespace_name: Nom du namespace à récupérer
            config_type: Type de configuration ou chemin du fichier (défaut: 'mail')

        Returns:
            Optional[Dict]: Configuration du namespace ou None s'il n'existe pas
        """
        config = self.read_config(config_type)
        if config is None:
            return None

        if 'namespace' in config and namespace_name in config['namespace']:
            return config['namespace'][namespace_name]

        return None

    def add_namespace(self, namespace_name: str, namespace_config: Dict, config_type: str = 'mail', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute un namespace à la configuration.

        Args:
            namespace_name: Nom du namespace à ajouter
            namespace_config: Configuration du namespace
            config_type: Type de configuration ou chemin du fichier (défaut: 'mail')
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'ajout réussit, False sinon
        """
        config = self.read_config(config_type)
        if config is None:
            self.log_error(f"Impossible de lire la configuration {config_type}", log_levels=log_levels)
            return False

        # Créer la section namespace si elle n'existe pas
        if 'namespace' not in config:
            config['namespace'] = {}

        # Vérifier si le namespace existe déjà
        if namespace_name in config['namespace']:
            self.log_warning(f"Le namespace '{namespace_name}' existe déjà et sera écrasé", log_levels=log_levels)

        # Ajouter le namespace
        config['namespace'][namespace_name] = namespace_config

        # Écrire la configuration mise à jour
        return self.write_config(config_type, config, backup=backup)

    def update_namespace(self, namespace_name: str, namespace_config: Dict, config_type: str = 'mail', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Met à jour un namespace existant.

        Args:
            namespace_name: Nom du namespace à mettre à jour
            namespace_config: Nouvelle configuration du namespace
            config_type: Type de configuration ou chemin du fichier (défaut: 'mail')
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        config = self.read_config(config_type)
        if config is None:
            self.log_error(f"Impossible de lire la configuration {config_type}", log_levels=log_levels)
            return False

        # Vérifier si le namespace existe
        if 'namespace' not in config or namespace_name not in config['namespace']:
            self.log_warning(f"Le namespace '{namespace_name}' n'existe pas", log_levels=log_levels)
            return False

        # Mettre à jour le namespace
        config['namespace'][namespace_name] = namespace_config

        # Écrire la configuration mise à jour
        return self.write_config(config_type, config, backup=backup)

    def delete_namespace(self, namespace_name: str, config_type: str = 'mail', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime un namespace.

        Args:
            namespace_name: Nom du namespace à supprimer
            config_type: Type de configuration ou chemin du fichier (défaut: 'mail')
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la suppression réussit, False sinon
        """
        config = self.read_config(config_type)
        if config is None:
            self.log_error(f"Impossible de lire la configuration {config_type}", log_levels=log_levels)
            return False

        # Vérifier si le namespace existe
        if 'namespace' not in config or namespace_name not in config['namespace']:
            self.log_warning(f"Le namespace '{namespace_name}' n'existe pas", log_levels=log_levels)
            return False

        # Supprimer le namespace
        del config['namespace'][namespace_name]

        # Si plus aucun namespace, supprimer la section namespace
        if not config['namespace']:
            del config['namespace']

        # Écrire la configuration mise à jour
        return self.write_config(config_type, config, backup=backup)

    def create_public_namespace(self, unite: str, location: Optional[str] = None, config_type: str = 'mail', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Crée un namespace public pour une unité spécifique.

        Args:
            unite: Nom de l'unité (ex: "FINANCE")
            location: Chemin de stockage (par défaut: "/partage/Mail_archive/{unite}")
            config_type: Type de configuration ou chemin du fichier (défaut: 'mail')
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la création réussit, False sinon
        """
        if location is None:
            location = f"/partage/Mail_archive/{unite}"

        namespace_name = f"PUBLIC_{unite}"
        namespace_config = {
            "inbox": "no",
            "type": "public",
            "separator": "/",
            "prefix": f"Archives_{unite}/",
            "location": f"maildir:{location}",
            "subscriptions": "no",
            "list": "yes"
        }

        return self.add_namespace(namespace_name, namespace_config, config_type, backup)

    def uncomment_namespace(self, namespace_pattern: str, config_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Décommente un namespace commenté.
        Cette méthode manipule directement le contenu du fichier plutôt que la structure parsée.

        Args:
            namespace_pattern: Motif pour identifier le namespace (ex: "PUBLIC_FINANCE")
            config_path: Chemin du fichier de configuration ou None pour utiliser le fichier mail par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si le décommentage réussit, False sinon
        """
        if config_path is None:
            config_path = self.get_config_path('mail')
        else:
            config_path = self.get_config_path(config_path)

        # Lire le contenu du fichier
        content = self._read_file_content(config_path)
        if content is None:
            self.log_error(f"Impossible de lire le fichier {config_path}.", log_levels=log_levels)
            return False

        # Identifier le début du namespace commenté
        import re
        pattern = rf"^#namespace\s+{namespace_pattern}\s*\{{"

        # Rechercher le bloc de namespace commenté
        lines = content.splitlines()
        new_lines = []
        in_commented_namespace = False
        namespace_found = False

        for line in lines:
            # Détecter le début du namespace commenté
            if not in_commented_namespace and re.match(pattern, line.strip()):
                in_commented_namespace = True
                namespace_found = True
                # Décommenter la ligne de début
                new_lines.append(line.replace('#', '', 1))
                continue

            # Décommenter les lignes dans le namespace
            if in_commented_namespace:
                # Détecter la fin du bloc commenté
                stripped = line.strip()
                if stripped == '#}':
                    in_commented_namespace = False
                    new_lines.append(line.replace('#', '', 1))
                    continue

                # Si la ligne est commentée, la décommenter
                if stripped.startswith('#'):
                    new_lines.append(line.replace('#', '', 1))
                else:
                    # Ligne déjà non commentée à l'intérieur du bloc
                    new_lines.append(line)
            else:
                # Lignes en dehors du namespace commenté
                new_lines.append(line)

        if not namespace_found:
            self.log_warning(f"Namespace '{namespace_pattern}' commenté non trouvé dans {config_path}", log_levels=log_levels)
            return False

        # Écrire le contenu mis à jour
        new_content = '\n'.join(new_lines)
        success = self._write_file_content(config_path, new_content, backup=backup)

        # Vider le cache pour ce fichier
        if success:
            self.clear_cache(str(config_path))

        return success

    def comment_namespace(self, namespace_name: str, config_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Commente un namespace existant.
        Cette méthode manipule directement le contenu du fichier plutôt que la structure parsée.

        Args:
            namespace_name: Nom du namespace à commenter (ex: "PUBLIC_FINANCE")
            config_path: Chemin du fichier de configuration ou None pour utiliser le fichier mail par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si le commentage réussit, False sinon
        """
        if config_path is None:
            config_path = self.get_config_path('mail')
        else:
            config_path = self.get_config_path(config_path)

        # Lire le contenu du fichier
        content = self._read_file_content(config_path)
        if content is None:
            self.log_error(f"Impossible de lire le fichier {config_path}.", log_levels=log_levels)
            return False

        # Identifier le début du namespace
        import re
        pattern = rf"^namespace\s+{namespace_name}\s*\{{"

        # Rechercher le bloc de namespace
        lines = content.splitlines()
        new_lines = []
        in_namespace = False
        namespace_found = False

        for line in lines:
            # Détecter le début du namespace
            if not in_namespace and re.match(pattern, line.strip()):
                in_namespace = True
                namespace_found = True
                # Commenter la ligne de début
                new_lines.append('#' + line)
                continue

            # Commenter les lignes dans le namespace
            if in_namespace:
                # Détecter la fin du bloc
                if line.strip() == '}':
                    in_namespace = False
                    new_lines.append('#' + line)
                    continue

                # Commenter la ligne
                new_lines.append('#' + line)
            else:
                # Lignes en dehors du namespace
                new_lines.append(line)

        if not namespace_found:
            self.log_warning(f"Namespace '{namespace_name}' non trouvé dans {config_path}", log_levels=log_levels)
            return False

        # Écrire le contenu mis à jour
        new_content = '\n'.join(new_lines)
        success = self._write_file_content(config_path, new_content, backup=backup)

        # Vider le cache pour ce fichier
        if success:
            self.clear_cache(str(config_path))

        return success

    def create_namespace_from_template(self, template_name: str, new_name: str,
                                    replacements: Dict[str, str], config_path: Optional[str] = None,
backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Crée un nouveau namespace basé sur un template existant.

        Args:
            template_name: Nom du namespace template (avec ou sans le préfixe "namespace ")
            new_name: Nom du nouveau namespace (sans le préfixe "namespace ")
            replacements: Dictionnaire {pattern: replacement} pour les substitutions
            config_path: Chemin du fichier de configuration ou None pour utiliser le fichier mail par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la création réussit, False sinon
        """
        # Déterminer le type de configuration
        config_type = 'mail' if config_path is None else config_path

        # Charger la configuration
        config = self.read_config(config_type)
        if config is None:
            self.log_error(f"Impossible de lire la configuration pour créer le namespace {new_name}", log_levels=log_levels)
            return False

        # Récupérer le namespace template
        if not template_name.startswith("namespace "):
            template_key = template_name
        else:
            template_key = template_name.split(" ", 1)[1]  # Extraire le nom après "namespace "

        template_namespace = self.get_namespace(template_key, config_type)
        if template_namespace is None:
            self.log_error(f"Le namespace template '{template_name}' n'existe pas", log_levels=log_levels)
            return False

        # Cloner la configuration du template
        import copy
        new_config = copy.deepcopy(template_namespace)

        # Appliquer les remplacements
        import json
        config_str = json.dumps(new_config)
        for pattern, replacement in replacements.items():
            config_str = config_str.replace(pattern, replacement)

        try:
            new_config = json.loads(config_str)
        except json.JSONDecodeError as e:
            self.log_error(f"Erreur lors du remplacement des valeurs: {e}", log_levels=log_levels)
            return False

        # Ajouter le nouveau namespace
        return self.add_namespace(new_name, new_config, config_type, backup=backup)

    # --- Méthodes pour la gestion des ACL ---

    def read_acl_file(self, acl_path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> List[Tuple[str, str, str, str]]:
        """
        Lit un fichier d'ACL Dovecot et retourne les règles sous forme de liste.
        Le format attendu est: mailbox identifier=user rights [#comment]

        Args:
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut

        Returns:
            List[Tuple[str, str, str, str]]: Liste de (mailbox, identifier, rights, comment)
        """
        if acl_path is None:
            acl_path = self.get_config_path('acl')
        else:
            acl_path = Path(acl_path)

        self.log_debug(f"Lecture du fichier ACL: {acl_path}", log_levels=log_levels)

        # Lire le contenu du fichier
        content = self._read_file_content(acl_path)
        if content is None:
            self.log_error(f"Impossible de lire le fichier ACL {acl_path}.", log_levels=log_levels)
            return []

        acl_entries = []

        for line in content.splitlines():
            line = line.strip()

            # Ignorer les lignes vides et les commentaires complets
            if not line or line.startswith('#'):
                continue

            # Extraire le commentaire éventuel
            comment = ""
            if '#' in line:
                line_parts = line.split('#', 1)
                line = line_parts[0].strip()
                comment = line_parts[1].strip()

            # Extraire les parties de la règle
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                self.log_warning(f"Format ACL invalide, ignoré: {line}", log_levels=log_levels)
                continue

            mailbox = parts[0]
            identifier = parts[1]
            rights = parts[2]

            acl_entries.append((mailbox, identifier, rights, comment))

        return acl_entries

    def write_acl_file(self, acl_entries: List[Tuple[str, str, str, str]], acl_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Écrit les règles ACL dans un fichier.

        Args:
            acl_entries: Liste de (mailbox, identifier, rights, comment)
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'écriture réussit, False sinon
        """
        if acl_path is None:
            acl_path = self.get_config_path('acl')
        else:
            acl_path = Path(acl_path)

        self.log_debug(f"Écriture du fichier ACL: {acl_path}", log_levels=log_levels)

        # Formater le contenu
        lines = []
        for entry in acl_entries:
            mailbox, identifier, rights, comment = entry
            line = f"{mailbox} {identifier} {rights}"
            if comment:
                line += f" #{comment}"
            lines.append(line)

        content = '\n'.join(lines) + '\n'

        # Écrire le fichier
        return self._write_file_content(acl_path, content, backup=backup)

    def get_acl_entries(self, mailbox: Optional[str] = None, acl_path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> List[Tuple[str, str, str, str]]:
        """
        Récupère les entrées ACL, éventuellement filtrées par boîte aux lettres.

        Args:
            mailbox: Nom de la boîte aux lettres pour filtrer ou None pour toutes
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut

        Returns:
            List[Tuple[str, str, str, str]]: Liste de (mailbox, identifier, rights, comment)
        """
        acl_entries = self.read_acl_file(acl_path)

        if mailbox is None:
            return acl_entries

        # Filtrer par boîte aux lettres
        return [entry for entry in acl_entries if entry[0] == mailbox]

    def add_acl_entry(self, mailbox: str, identifier: str, rights: str, comment: str = "",
acl_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute une entrée ACL.

        Args:
            mailbox: Nom de la boîte aux lettres (ex: "Archives_FINANCE")
            identifier: Identifiant (ex: "group=finance")
            rights: Droits d'accès (ex: "lrwts")
            comment: Commentaire optionnel
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'ajout réussit, False sinon
        """
        acl_entries = self.read_acl_file(acl_path)

        # Vérifier si l'entrée existe déjà
        for i, entry in enumerate(acl_entries):
            if entry[0] == mailbox and entry[1] == identifier:
                self.log_warning(f"L'entrée ACL pour {mailbox} {identifier} existe déjà, mise à jour", log_levels=log_levels)
                acl_entries[i] = (mailbox, identifier, rights, comment)
                return self.write_acl_file(acl_entries, acl_path, backup)

        # Ajouter la nouvelle entrée
        acl_entries.append((mailbox, identifier, rights, comment))
        return self.write_acl_file(acl_entries, acl_path, backup)

    def update_acl_entry(self, mailbox: str, identifier: str, rights: str, comment: Optional[str] = None,
acl_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Met à jour une entrée ACL existante.

        Args:
            mailbox: Nom de la boîte aux lettres (ex: "Archives_FINANCE")
            identifier: Identifiant (ex: "group=finance")
            rights: Nouveaux droits d'accès
            comment: Nouveau commentaire ou None pour conserver l'existant
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        acl_entries = self.read_acl_file(acl_path)

        # Rechercher l'entrée à mettre à jour
        entry_found = False
        for i, entry in enumerate(acl_entries):
            if entry[0] == mailbox and entry[1] == identifier:
                # Conserver le commentaire existant si aucun nouveau n'est spécifié
                current_comment = entry[3] if comment is None else comment
                acl_entries[i] = (mailbox, identifier, rights, current_comment)
                entry_found = True
                break

        if not entry_found:
            self.log_warning(f"L'entrée ACL pour {mailbox} {identifier} n'existe pas", log_levels=log_levels)
            return False

        return self.write_acl_file(acl_entries, acl_path, backup)

    def delete_acl_entry(self, mailbox: str, identifier: str, acl_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime une entrée ACL.

        Args:
            mailbox: Nom de la boîte aux lettres
            identifier: Identifiant
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la suppression réussit, False sinon
        """
        acl_entries = self.read_acl_file(acl_path)

        # Filtrer l'entrée à supprimer
        new_entries = [entry for entry in acl_entries if not (entry[0] == mailbox and entry[1] == identifier)]

        if len(new_entries) == len(acl_entries):
            self.log_warning(f"L'entrée ACL pour {mailbox} {identifier} n'existe pas", log_levels=log_levels)
            return False

        return self.write_acl_file(new_entries, acl_path, backup)

    def delete_all_mailbox_acls(self, mailbox: str, acl_path: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime toutes les entrées ACL pour une boîte aux lettres spécifique.

        Args:
            mailbox: Nom de la boîte aux lettres
            acl_path: Chemin du fichier ACL ou None pour utiliser l'emplacement par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la suppression réussit, False sinon
        """
        acl_entries = self.read_acl_file(acl_path)

        # Filtrer les entrées pour la boîte aux lettres
        new_entries = [entry for entry in acl_entries if entry[0] != mailbox]

        if len(new_entries) == len(acl_entries):
            self.log_warning(f"Aucune entrée ACL trouvée pour la boîte aux lettres {mailbox}", log_levels=log_levels)
            return False

        return self.write_acl_file(new_entries, acl_path, backup)

    def enable_acl_plugin(self, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Active le plugin ACL.

        Args:
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'activation réussit, False sinon
        """
        return self.add_mail_plugin('acl', backup=backup)

    def configure_acl_settings(self, acl_dir: Optional[str] = None, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Configure les paramètres du plugin ACL.

        Args:
            acl_dir: Répertoire pour les fichiers ACL ou None pour utiliser le répertoire par défaut
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la configuration réussit, False sinon
        """
        # Activer le plugin
        success = self.enable_acl_plugin(backup)
        if not success:
            return False

        # Définir le répertoire ACL
        if acl_dir:
            return self.set_plugin_setting('acl', 'acl_dir', acl_dir, backup)

        return True

    # --- Méthodes de gestion des quotas ---

    def get_quota_rule(self, rule_name: str = 'quota_rule', default: Any = None, log_levels: Optional[Dict[str, str]] = None) -> Any:
        """
        Récupère une règle de quota.

        Args:
            rule_name: Nom de la règle ('quota_rule', 'quota_rule2', etc.)
            default: Valeur par défaut si la règle n'existe pas

        Returns:
            Any: Valeur de la règle ou valeur par défaut
        """
        return self.get_plugin_setting('quota', rule_name, default)

    def set_quota_rule(self, rule_value: str, rule_name: str = 'quota_rule', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Définit une règle de quota.

        Args:
            rule_value: Valeur de la règle (ex: '*:storage=1G')
            rule_name: Nom de la règle ('quota_rule', 'quota_rule2', etc.)
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la mise à jour réussit, False sinon
        """
        return self.set_plugin_setting('quota', rule_name, rule_value, backup=backup)

    def enable_quota(self, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Active le plugin de quota.

        Args:
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si l'activation réussit, False sinon
        """
        return self.add_mail_plugin('quota', backup=backup)

    def configure_quota_backend(self, backend_type: str = 'maildir', desc: str = 'User quota', backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Configure le backend de quota.

        Args:
            backend_type: Type de backend ('maildir', 'dict', 'fs', etc.)
            desc: Description du quota
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la configuration réussit, False sinon
        """
        # Activer le plugin de quota
        if not self.enable_quota(backup):
            return False

        # Configurer le backend
        backend_value = f"{backend_type}:{desc}"
        return self.set_plugin_setting('quota', 'quota', backend_value, backup=backup)

    def set_quota_warning(self, threshold: int, command: str, user_placeholder: bool = True,
warning_num: int = 1, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Configure un message d'avertissement de quota.

        Args:
            threshold: Seuil en pourcentage (ex: 95 pour 95%)
            command: Commande à exécuter (sans %u)
            user_placeholder: Si True, ajoute %u à la fin de la commande
            warning_num: Numéro de l'avertissement (1 pour quota_warning, 2 pour quota_warning2, etc.)
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la configuration réussit, False sinon
        """
        # Construire le nom du paramètre
        param_name = f"quota_warning{'' if warning_num == 1 else warning_num}"

        # Construire la valeur
        value = f"storage={threshold}%% {command}"
        if user_placeholder:
            value += " %u"

        return self.set_plugin_setting('quota', param_name, value, backup=backup)

    def set_quota_exceeded_message(self, message: str, backup: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Configure le message affiché quand le quota est dépassé.

        Args:
            message: Message à afficher
            backup: Si True, crée une sauvegarde du fichier original

        Returns:
            bool: True si la configuration réussit, False sinon
        """
        return self.set_plugin_setting('quota', 'quota_exceeded_message', message, backup=backup)