# install/plugins/plugins_utils/dpkg.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour la gestion avancée des paquets Debian via dpkg.
Permet de gérer les sélections de paquets, les préréponses debconf et les opérations avancées sur dpkg.
"""

# Import de la classe de base et des types
from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import tempfile
import time
import shlex
from typing import Union, Optional, List, Dict, Any, Tuple

# Import conditionnel pour AptCommands (utilisé pour installer debconf-utils)
try:
    from .apt import AptCommands
    APT_AVAILABLE_FOR_DPKG = True
except ImportError:
    APT_AVAILABLE_FOR_DPKG = False
    class AptCommands: pass # Factice

class DpkgCommands(PluginsUtilsBase):
    """
    Classe avancée pour gérer dpkg, debconf et les sélections de paquets.
    Hérite de PluginUtilsBase pour l'exécution de commandes et la progression.
    """

    def __init__(self, logger=None, target_ip=None):
        """
        Initialise le gestionnaire de commandes dpkg et debconf.

        Args:
            logger: Instance de PluginLogger (optionnel).
            target_ip: IP cible pour les logs (optionnel).
        """
        super().__init__(logger, target_ip)
        # Stockage interne des sélections en attente
        self._package_selections: Dict[str, str] = {} # {package: status}
        self._debconf_selections: Dict[Tuple[str, str], Tuple[str, str]] = {} # {(pkg, quest): (type, val)}
        # Instance d'AptCommands pour installer debconf-utils si besoin
        self.last_run_return_code = 0
        self._apt_cmd = AptCommands(logger, target_ip) if APT_AVAILABLE_FOR_DPKG else None
        if not APT_AVAILABLE_FOR_DPKG:
             self.log_warning("Module AptCommands non trouvé. L'installation automatique de paquets sera désactivée.", log_levels=log_levels)

    def add_package_selection(self, package: str, status: str = "install", log_levels: Optional[Dict[str, str]] = None):
        """
        Ajoute ou met à jour une sélection de paquet individuelle dans la liste cumulative interne.

        Args:
            package: Nom du paquet.
            status: Statut souhaité ('install', 'hold', 'deinstall', 'purge').
        """
        valid_statuses = ["install", "hold", "deinstall", "purge"]
        status_lower = status.lower()
        if status_lower not in valid_statuses:
             self.log_warning(f"Statut de sélection dpkg invalide '{status}' pour {package}. Utilisation de 'install'.", log_levels=log_levels)
             status_lower = "install"
        self.log_debug(f"Ajout/Mise à jour sélection dpkg: {package} -> {status_lower}", log_levels=log_levels)
        self._package_selections[package] = status_lower

    def add_package_selections(self, selections: str, log_levels: Optional[Dict[str, str]] = None):
        """
        Ajoute des sélections de paquets depuis une chaîne multiligne à la liste cumulative interne.

        Args:
            selections: Chaîne contenant les sélections (une par ligne: "package status").
        """
        self.log_info("Ajout de sélections de paquets dpkg depuis une chaîne...", log_levels=log_levels)
        count = 0
        for line in selections.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split(None, 1) # Split seulement sur le premier espace
            if len(parts) == 2:
                package, status = parts
                self.add_package_selection(package.strip(), status.strip())
                count += 1
            else:
                 self.log_warning(f"Format invalide pour la sélection dpkg ignorée: {line}", log_levels=log_levels)
        self.log_info(f"{count} sélections de paquets dpkg ajoutées/mises à jour en mémoire.", log_levels=log_levels)

    def load_package_selections_from_file(self, filepath: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Charge les sélections depuis un fichier et les ajoute à la liste cumulative interne."""
        self.log_info(f"Chargement des sélections de paquets dpkg depuis: {filepath}", log_levels=log_levels)
        # La lecture du fichier peut nécessiter sudo
        success_read, content, stderr_read = self.run(['cat', filepath], check=False, needs_sudo=True, no_output=True)
        if not success_read:
             if "no such file" in stderr_read.lower():
                  self.log_error(f"Le fichier de sélections dpkg '{filepath}' n'existe pas.", log_levels=log_levels)
             else:
                  self.log_error(f"Impossible de lire le fichier de sélections dpkg '{filepath}'. Stderr: {stderr_read}", log_levels=log_levels)
             return False
        try:
            self.add_package_selections(content)
            return True
        except Exception as e:
            self.log_error(f"Erreur lors du traitement du contenu du fichier de sélections '{filepath}': {e}", log_levels=log_levels)
            return False

    def clear_package_selections(self, log_levels: Optional[Dict[str, str]] = None):
        """Efface toutes les sélections de paquets dpkg en attente (en mémoire)."""
        self.log_info("Effacement des sélections de paquets dpkg en attente.", log_levels=log_levels)
        self._package_selections = {}

    def apply_package_selections(self, task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Applique toutes les sélections de paquets en attente via `dpkg --set-selections`.
        La liste interne est vidée après une application réussie.

        Args:
            task_id: ID de tâche pour la progression (optionnel).

        Returns:
            bool: True si l'opération a réussi.
        """
        if not self._package_selections:
            self.log_warning("Aucune sélection de paquet dpkg en attente à appliquer.", log_levels=log_levels)
            return True

        count = len(self._package_selections)
        self.log_info(f"Application de {count} sélections de paquets dpkg...", log_levels=log_levels)
        current_task_id = task_id or f"dpkg_set_selections_{int(time.time())}"
        self.start_task(1, description="Application via dpkg --set-selections", task_id=current_task_id)

        # Construire la chaîne pour stdin
        selections_str = "\n".join(f"{pkg}\t{status}" for pkg, status in self._package_selections.items()) + "\n"
        self.log_debug(f"Contenu envoyé à dpkg --set-selections:\n{selections_str}", log_levels=log_levels)

        # Appeler dpkg --set-selections via stdin
        cmd = ['dpkg', '--set-selections']
        success, stdout, stderr = self.run(cmd, input_data=selections_str, check=False, needs_sudo=True)
        self.update_task() # Termine l'étape

        if success:
             self.log_success(f"{count} sélections de paquets dpkg appliquées avec succès.", log_levels=log_levels)
             self.clear_package_selections() # Vider après succès
             self.complete_task(success=True)
             return True
        else:
             self.log_error("Échec de l'application des sélections de paquets dpkg.", log_levels=log_levels)
             if stderr: self.log_error(f"Stderr: {stderr}", log_levels=log_levels)
             if stdout: self.log_info(f"Stdout: {stdout}", log_levels=log_levels) # stdout peut contenir des infos utiles
             self.complete_task(success=False, message="Échec dpkg --set-selections")
             return False

    # --- Méthodes Debconf ---

    def _ensure_debconf_commands(self) -> Tuple[bool, List[str]]:
        """
        Vérifie quelles commandes debconf sont disponibles.
        Ne tente pas d'installer debconf-utils.

        Returns:
            Tuple contenant:
            - bool: True si au moins une commande est disponible
            - List[str]: Liste des commandes disponibles
        """
        available_commands = []

        # Vérifier les commandes disponibles
        for cmd in ['debconf', 'debconf-communicate', 'debconf-show']:
            success, _, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if success:
                available_commands.append(cmd)

        if not available_commands:
            self.log_error("Aucune commande debconf n'est disponible. Les opérations debconf échoueront.", log_levels=log_levels)
            return False, []

        self.log_debug(f"Commandes debconf disponibles: {', '.join(available_commands)}", log_levels=log_levels)
        return True, available_commands

    def add_debconf_selection(self, package: str, question: str, q_type: str, value: str, log_levels: Optional[Dict[str, str]] = None):
        """
        Ajoute ou met à jour une pré-réponse debconf individuelle dans la liste cumulative interne.

        Args:
            package: Nom du paquet.
            question: Nom de la question debconf (ex: 'shared/accepted-oracle-license-v1-1').
            q_type: Type de la question (string, boolean, select, password, note, text, etc.).
            value: Valeur de la réponse (ex: 'true', 'password', 'Yes').
        """
        key = (package, question)
        # Nettoyer les arguments
        pkg_clean = package.strip()
        quest_clean = question.strip()
        type_clean = q_type.strip()
        val_clean = value.strip() # Ne pas convertir en booléen ici, garder la chaîne

        self.log_debug(f"Ajout/Mise à jour debconf: {pkg_clean} {quest_clean} {type_clean} '{val_clean}'", log_levels=log_levels)
        self._debconf_selections[(pkg_clean, quest_clean)] = (type_clean, val_clean)

    def add_debconf_selections(self, selections: str, log_levels: Optional[Dict[str, str]] = None):
        """Ajoute des pré-réponses debconf depuis une chaîne multiligne à la liste cumulative interne."""
        self.log_info("Ajout de pré-réponses debconf depuis une chaîne...", log_levels=log_levels)
        count = 0
        for line in selections.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Format: package question type value (séparés par espaces)
            parts = line.split(None, 3) # Split max 3 fois pour garder la valeur entière
            if len(parts) == 4:
                pkg, quest, q_type, val = parts
                self.add_debconf_selection(pkg, quest, q_type, val)
                count += 1
            else:
                 self.log_warning(f"Format invalide pour la pré-réponse debconf ignorée: {line}", log_levels=log_levels)
        self.log_info(f"{count} pré-réponses debconf ajoutées/mises à jour en mémoire.", log_levels=log_levels)

    def load_debconf_selections_from_file(self, filepath: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Charge les pré-réponses debconf depuis un fichier et les ajoute à la liste interne."""
        self.log_info(f"Chargement des pré-réponses debconf depuis: {filepath}", log_levels=log_levels)

        # Lire le fichier (peut nécessiter sudo)
        success_read, content, stderr_read = self.run(['cat', filepath], check=False, needs_sudo=True, no_output=True)
        if not success_read:
             if "no such file" in stderr_read.lower():
                  self.log_error(f"Le fichier de pré-réponses debconf '{filepath}' n'existe pas.", log_levels=log_levels)
             else:
                  self.log_error(f"Impossible de lire le fichier de pré-réponses debconf '{filepath}'. Stderr: {stderr_read}", log_levels=log_levels)
             return False
        try:
            self.add_debconf_selections(content)
            return True
        except Exception as e:
            self.log_error(f"Erreur lors du traitement du contenu du fichier debconf '{filepath}': {e}", log_levels=log_levels)
            return False

    def clear_debconf_selections(self, log_levels: Optional[Dict[str, str]] = None):
        """Efface toutes les pré-réponses debconf en attente (en mémoire)."""
        self.log_info("Effacement des pré-réponses debconf en attente.", log_levels=log_levels)
        self._debconf_selections = {}

    def apply_debconf_selections(self, task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Applique toutes les pré-réponses debconf en attente en utilisant des méthodes alternatives
        qui ne dépendent pas de debconf-utils.
        La liste interne est vidée après une application réussie.

        Args:
            task_id: ID de tâche pour la progression (optionnel).

        Returns:
            bool: True si l'opération a réussi.
        """
        if not self._debconf_selections:
            self.log_warning("Aucune pré-réponse debconf en attente à appliquer.", log_levels=log_levels)
            return True

        count = len(self._debconf_selections)
        self.log_info(f"Application de {count} pré-réponses debconf...", log_levels=log_levels)
        current_task_id = task_id or f"debconf_set_selections_{int(time.time())}"
        self.start_task(count, description="Application des pré-réponses debconf", task_id=current_task_id)

        # Vérifier si debconf est disponible (outil de base)
        has_debconf, _ = self._ensure_debconf_commands()

        if not has_debconf:
            self.log_error("Les commandes debconf de base ne sont pas disponibles. Impossible d'appliquer les sélections debconf.", log_levels=log_levels)
            self.complete_task(success=False, message="Commandes debconf non disponibles")
            return False

        # Créer un fichier temporaire pour les sélections
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
            try:
                # Écrire les sélections dans le fichier temporaire
                for (pkg, quest), (q_type, value) in self._debconf_selections.items():
                    temp_file.write(f"{pkg} {quest} {q_type} {value}\n")
                temp_file.flush()

                success = True
                stdout_all = ""
                stderr_all = ""
                completed = 0

                # Vérifier si debconf-set-selections est disponible
                has_set_selections, _, _ = self.run(['which', 'debconf-set-selections'], check=False, no_output=True, error_as_warning=True)

                if has_set_selections:
                    # Méthode 1: Essayer d'utiliser debconf-set-selections directement
                    self.log_debug("Tentative d'application avec debconf-set-selections...", log_levels=log_levels)
                    cmd = f"DEBIAN_FRONTEND=noninteractive debconf-set-selections {temp_file.name}"
                    success1, stdout1, stderr1 = self.run(cmd, shell=True, check=False, needs_sudo=True)

                    if success1:
                        self.log_debug("Application avec debconf-set-selections réussie", log_levels=log_levels)
                        success = True
                        stdout_all = stdout1
                        stderr_all = stderr1
                        completed = count
                        self.update_task(completed)
                    else:
                        self.log_warning(f"Échec avec debconf-set-selections: {stderr1}", log_levels=log_levels)
                        # Continuer avec les méthodes alternatives
                        success = False

                # Si debconf-set-selections a échoué ou n'est pas disponible, traiter individuellement
                if not has_set_selections or not success:
                    # Méthode 2: Traiter chaque entrée individuellement avec debconf-communicate
                    self.log_debug("Tentative avec debconf-communicate pour chaque entrée...", log_levels=log_levels)
                    success = True
                    completed = 0

                    for (pkg, quest), (q_type, value) in self._debconf_selections.items():
                        # Vérifier si debconf-communicate est disponible
                        has_communicate, _, _ = self.run(['which', 'debconf-communicate'], check=False, no_output=True, error_as_warning=True)

                        if has_communicate:
                            # Construire la commande debconf-communicate
                            # Format: echo "SET package/question value" | debconf-communicate package
                            debconf_cmd = f"echo 'SET {quest} {value}' | DEBIAN_FRONTEND=noninteractive debconf-communicate {pkg}"
                            entry_success, entry_stdout, entry_stderr = self.run(debconf_cmd, shell=True, check=False, needs_sudo=True)
                        else:
                            # Alternative: utiliser directement echo avec fichier de contrôle
                            debconf_cmd = f"echo {shlex.quote(pkg)} {shlex.quote(quest)} {shlex.quote(q_type)} {shlex.quote(value)} > /tmp/debconf_temp && DEBIAN_FRONTEND=noninteractive debconf-set-selections /tmp/debconf_temp && rm -f /tmp/debconf_temp"
                            entry_success, entry_stdout, entry_stderr = self.run(debconf_cmd, shell=True, check=False, needs_sudo=True)

                        # Collecter les résultats
                        success = success and entry_success
                        if entry_stdout:
                            stdout_all += f"[{pkg}/{quest}] {entry_stdout}\n"
                        if entry_stderr:
                            stderr_all += f"[{pkg}/{quest}] {entry_stderr}\n"

                        completed += 1
                        self.update_task(completed)

                        if not entry_success:
                            self.log_warning(f"Échec pour {pkg}/{quest}: {entry_stderr}", log_levels=log_levels)

                            # Méthode 3: Essayer avec debconf/db_set directement si disponible
                            self.log_debug(f"Tentative alternative pour {pkg}/{quest}...", log_levels=log_levels)
                            alt_cmd = f"DEBIAN_FRONTEND=noninteractive debconf-db-set DB_PATH=/var/cache/debconf/config.dat {pkg} {quest} {value}"
                            alt_success, alt_stdout, alt_stderr = self.run(alt_cmd, shell=True, check=False, needs_sudo=True)

                            if alt_success:
                                self.log_debug(f"Méthode alternative réussie pour {pkg}/{quest}", log_levels=log_levels)
                                success = True  # Rétablir le succès pour cette entrée

                self.update_task(count)  # S'assurer que la tâche est complète

                if success:
                    self.log_success(f"{count} pré-réponses debconf appliquées avec succès.", log_levels=log_levels)
                    self.clear_debconf_selections()  # Vider après succès
                    self.complete_task(success=True)
                    return True
                else:
                    self.log_error("Échec de l'application des pré-réponses debconf.", log_levels=log_levels)
                    if stderr_all:
                        self.log_error(f"Stderr: {stderr_all}", log_levels=log_levels)
                    if stdout_all:
                        self.log_info(f"Stdout: {stdout_all}", log_levels=log_levels)
                    self.complete_task(success=False, message="Échec de l'application debconf")
                    return False
            finally:
                # Supprimer le fichier temporaire
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    self.log_warning(f"Impossible de supprimer le fichier temporaire {temp_file.name}: {e}", log_levels=log_levels)

    def get_debconf_selections_for_package(self, package_name: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[Tuple[str, str], str]]:
        """
        Récupère les sélections debconf actuelles pour un paquet spécifique sans utiliser debconf-get-selections.
        Utilise directement la commande debconf-show qui fait partie du paquet debconf de base.

        Args:
            package_name: Nom du paquet.

        Returns:
            Dictionnaire où la clé est un tuple (question, type) et la valeur est la sélection actuelle.
            Retourne None en cas d'erreur, ou un dictionnaire vide si aucune sélection trouvée.
        """
        self.log_debug(f"Récupération des sélections debconf pour le paquet: {package_name}", log_levels=log_levels)

        # Créer un dictionnaire pour stocker les résultats
        selections: Dict[Tuple[str, str], str] = {}

        # Vérifier si debconf-show est disponible (fait partie du paquet debconf de base)
        has_debconf_show, _, _ = self.run(['which', 'debconf-show'], check=False, no_output=True, error_as_warning=True)

        if not has_debconf_show:
            # Si debconf-show n'est pas disponible, essayer de lire directement les fichiers de config
            self.log_warning("La commande debconf-show n'est pas disponible. Tentative de lecture directe des fichiers de config.", log_levels=log_levels)

            # Tenter de lire /var/cache/debconf/config.dat (peut nécessiter sudo)
            success, stdout, stderr = self.run(['grep', '-A5', f'^Name: {package_name}/', '/var/cache/debconf/config.dat'],
                                           check=False, needs_sudo=True, no_output=True)

            if not success:
                if self.last_run_return_code == 1:  # grep n'a rien trouvé
                    self.log_debug(f"Aucune configuration debconf trouvée pour le paquet '{package_name}'.", log_levels=log_levels)
                    return selections  # Retourner un dict vide
                else:
                    self.log_error(f"Erreur lors de la lecture des fichiers debconf: {stderr}", log_levels=log_levels)
                    return None

            # Traiter les résultats de grep sur config.dat
            current_question = None
            current_type = "string"  # Par défaut

            for line in stdout.splitlines():
                line = line.strip()

                if line.startswith('Name:'):
                    question_path = line.split(':', 1)[1].strip()
                    if question_path.startswith(f"{package_name}/"):
                        current_question = question_path[len(package_name)+1:]

                elif line.startswith('Type:') and current_question:
                    current_type = line.split(':', 1)[1].strip().lower()

                    # Lire la valeur correspondante dans templates.dat
                    value_cmd = ['grep', '-A2', f'^Name: {package_name}/{current_question}$', '/var/cache/debconf/templates.dat']
                    val_success, val_out, _ = self.run(value_cmd, check=False, needs_sudo=True, no_output=True)

                    if val_success:
                        for val_line in val_out.splitlines():
                            if val_line.startswith('Value:'):
                                value = val_line.split(':', 1)[1].strip()
                                selections[(current_question, current_type)] = value
                                break
        else:
            # Utiliser debconf-show qui est disponible
            cmd = ["debconf-show", package_name]
            success, stdout, stderr = self.run(cmd, check=False, no_output=True)

            if not success:
                # Vérifier si c'est parce que le paquet n'a pas de config debconf
                if "does not exist" in stderr.lower() or "no such package" in stderr.lower():
                    self.log_debug(f"Aucune configuration debconf trouvée pour le paquet '{package_name}'.", log_levels=log_levels)
                    return selections  # Retourner un dict vide
                else:
                    # Autre erreur
                    self.log_error(f"Échec de la récupération des sélections debconf pour '{package_name}'. Stderr: {stderr}", log_levels=log_levels)
                    return None

            # Parser la sortie de debconf-show
            # Format typique: "* question_name: valeur"
            for line in stdout.splitlines():
                line = line.strip()
                if not line or not line.startswith('*'):
                    continue

                # Enlever l'astérisque et diviser
                parts = line[1:].strip().split(':', 1)
                if len(parts) == 2:
                    question = parts[0].strip()
                    value = parts[1].strip()

                    # Le type n'est pas directement accessible via debconf-show
                    # On utilise 'string' par défaut, qui est le type le plus courant
                    q_type = "string"

                    # Pour les valeurs boolean, on peut essayer de détecter
                    if value.lower() in ["true", "false", "yes", "no"]:
                        q_type = "boolean"

                    selections[(question, q_type)] = value

        count = len(selections)
        self.log_debug(f"{count} sélection(s) debconf trouvée(s) pour '{package_name}'.", log_levels=log_levels)
        if count > 0:
            self.log_debug(f"Sélections pour {package_name}: {selections}", log_levels=log_levels)
        return selections

    def get_debconf_value(self, package_name: str, question_name: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Récupère la valeur d'une question debconf spécifique pour un paquet donné.
        Cette version fonctionne sans debconf-utils en utilisant les outils de base.

        Args:
            package_name: Nom du paquet.
            question_name: Nom de la question debconf.

        Returns:
            La valeur de la sélection sous forme de chaîne, ou None si non trouvée ou en cas d'erreur.
        """
        self.log_debug(f"Recherche de la valeur debconf pour: {package_name} -> {question_name}", log_levels=log_levels)

        # Récupérer toutes les sélections pour le paquet
        package_selections = self.get_debconf_selections_for_package(package_name)

        if package_selections is None:
            self.log_error(f"Impossible de récupérer les sélections pour {package_name}.", log_levels=log_levels)
            return None

        # Chercher la question dans les sélections récupérées
        for (question, q_type), value in package_selections.items():
            if question == question_name:
                self.log_debug(f"Valeur trouvée pour '{question_name}' ({package_name}): '{value}' (type: {q_type})", log_levels=log_levels)
                return value

        # Si on ne trouve pas dans les sélections, essayer avec debconf-communicate
        has_debconf, available_cmds = self._ensure_debconf_commands()

        if has_debconf and 'debconf-communicate' in available_cmds:
            try:
                # Format: echo "GET question_name" | debconf-communicate package_name
                cmd = f"echo 'GET {question_name}' | DEBIAN_FRONTEND=noninteractive debconf-communicate {package_name}"
                success, stdout, _ = self.run(cmd, shell=True, check=False, no_output=True)

                if success and stdout.strip():
                    # Analyser la sortie (typiquement "0 value")
                    parts = stdout.strip().split(' ', 1)
                    if len(parts) == 2 and parts[0] == '0':
                        self.log_debug(f"Valeur trouvée via debconf-communicate: '{parts[1]}'", log_levels=log_levels)
                        return parts[1]
            except Exception as e:
                self.log_warning(f"Erreur lors de l'utilisation de debconf-communicate: {e}", log_levels=log_levels)

        # Méthode de secours: lecture directe des fichiers
        try:
            # Rechercher dans les fichiers de configuration debconf
            cmd = f"grep -A1 '^Name: {package_name}/{question_name}$' /var/cache/debconf/config.dat /var/lib/debconf/config.dat 2>/dev/null"
            success, stdout, _ = self.run(cmd, shell=True, check=False, needs_sudo=True, no_output=True)

            if success and stdout.strip():
                for line in stdout.splitlines():
                    if line.startswith('Value:'):
                        value = line.split(':', 1)[1].strip()
                        self.log_debug(f"Valeur trouvée via lecture directe des fichiers: '{value}'", log_levels=log_levels)
                        return value
        except Exception as e:
            self.log_warning(f"Erreur lors de la lecture directe des fichiers debconf: {e}", log_levels=log_levels)

        self.log_debug(f"Aucune valeur debconf trouvée pour la question '{question_name}' du paquet '{package_name}'.", log_levels=log_levels)
        return None

    def list_installed_packages_with_pattern(
        self,
        pattern: str,
        log_levels: Optional[Dict[str, str]] = None
    ) -> List[str]:
        """
        Liste tous les paquets installés dont le nom contient le motif donné,
        en se basant sur `dpkg -l '*motif*'` et en ne conservant que les lignes
        dont le préfixe est 'ii' (installé).

        Args:
            pattern: Sous-chaîne à rechercher dans le nom du paquet (globbing).
            log_levels: Niveaux de log personnalisés.

        Returns:
            Liste des noms de paquets installés correspondant au motif.
        """
        # On encadre le motif pour la glob de dpkg
        glob = f"*{pattern}*"
        self.log_info(f"Recherche des paquets installés avec dpkg -l '{glob}'...", log_levels=log_levels)

        # Exécute dpkg -l avec le glob
        success, stdout, stderr = self.run(
            ['dpkg', '-l', glob],
            print_command=False,
            needs_sudo=False,
            no_output=True,
            log_levels=log_levels
        )
        if not success:
            self.log_error(f"Échec de dpkg -l: {stderr}", log_levels=log_levels)
            return []

        matches: List[str] = []
        # Chaque ligne de stdout a la forme :
        # ii  nom_du_paquet  version  description...
        for line in stdout.splitlines():
            if not line.startswith('ii'):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pkg_name = parts[1]
            # On double-vérifie le motif en regex si besoin
            if re.search(pattern, pkg_name):
                matches.append(pkg_name)

        self.log_debug(f"{len(matches)} paquet(s) installés trouvés pour '{pattern}': {matches}",
                       log_levels=log_levels)
        return matches

    def purge_packages(
        self,
        packages: List[str],
        log_levels: Optional[Dict[str, str]] = None,
        force_depends: bool = True,
        error_as_warning=False
    ) -> bool:
        """
        Purge une liste de paquets via dpkg -P, avec option --force-depends si souhaité.

        Args:
            packages: Liste de noms de paquets à purger.
            log_levels: Niveaux de log optionnels.
            force_depends: Si True, ajoute l'option --force-depends.

        Returns:
            True si l'opération a réussi, False sinon.
        """
        if not packages:
            self.log_warning("Aucune liste de paquets fournie pour la purge.", log_levels=log_levels)
            return True

        # Construire la commande dpkg
        cmd: List[str] = ['dpkg', '-P']
        if force_depends:
            cmd.append('--force-depends')
        cmd.extend(packages)

        # Log de la commande exécutée
        self.log_info(f"Exécution de la purge: {' '.join(shlex.quote(arg) for arg in cmd)}", log_levels=log_levels)

        # Exécution de la commande en sudo
        success, stdout, stderr = self.run(
            cmd,
            print_command=False,
            needs_sudo=True,
            real_time_output=True,
            error_as_warning=error_as_warning,
            log_levels=log_levels
        )
        if success:
            self.log_success(f"Purge réussie des paquets: {packages}", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la purge des paquets: {stderr}", log_levels=log_levels)
            if stdout:
                self.log_info(f"Stdout: {stdout}", log_levels=log_levels)
            return False
