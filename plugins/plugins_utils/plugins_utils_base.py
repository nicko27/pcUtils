#!/usr/bin/env python3
"""
Module utilitaire de base pour les plugins.
Fournit une classe de base avec des fonctionnalités communes de journalisation,
d'exécution de commandes (avec gestion root) et de gestion de la progression.
Version optimisée pour améliorer la réactivité des logs et la détection des progressions.
"""

import os
import subprocess
import traceback
import time
import threading
import shlex  # Pour découper les commandes en chaîne de manière sécurisée
import re     # Pour la détection de patterns dans les sorties
import queue  # Pour le traitement par lots des sorties
import select # Pour la lecture non-bloquante des flux
import sys
import asyncio
from typing import Union, Optional, List, Tuple, Dict, Any, Set

from plugins_utils.plugin_logger import PluginLogger, is_debugger_active

DEFAULT_COMMAND_TIMEOUT = 300  # 5 minutes par défaut

# Patterns courants de progression pour les commandes système
PROGRESS_PATTERNS = [
    # apt/dpkg: "10%" ou "10% [###...]"
    re.compile(r'(\d+)%(?:\s+\[([#=> -]+)\])?'),
    # progression numérique: "5/20"
    re.compile(r'(\d+)/(\d+)'),
    # clés de progression courantes
    re.compile(r'(?:progress|progression|completed|terminé|avancement|étape)\s*[:=]\s*(\d+)(?:[.,](\d+))?%', re.IGNORECASE),
    # barres avec pourcentage
    re.compile(r'\[([#=\-_>]+\s*)\]\s*(\d+)%')
]

class PluginsUtilsBase:
    """
    Classe de base pour les utilitaires de plugins. Fournit la journalisation,
    l'exécution de commandes et la gestion de la progression.
    Assume par défaut que les commandes nécessitant des privilèges élevés
    seront exécutées en tant que root (via sudo si nécessaire).
    """

    def __init__(self, logger: Optional[PluginLogger] = None,
                 target_ip: Optional[str] = None,
                 debug_mode: bool = False,
                 debugger_mode: bool = None):
        """
        Initialise un utilitaire de base pour les plugins.

        Args:
            logger: Instance de PluginLogger à utiliser pour la journalisation (optionnel).
                    Si None, une nouvelle instance sera créée.
            target_ip: Adresse IP cible pour les logs (utile pour les exécutions SSH).
            debug_mode: Mode debug avec plus de verbosité et moins d'optimisations.
            debugger_mode: Mode spécial pour éviter les blocages du débogueur (auto-détecté si None).
        """
        # Auto-détection du mode débogueur si non spécifié
        if debugger_mode is None:
            self.debugger_mode = is_debugger_active()
        else:
            self.debugger_mode = debugger_mode

        # Créer un logger adapté au mode débogueur
        self.logger = logger if logger else PluginLogger(
            debug_mode=debug_mode,
            debugger_mode=self.debugger_mode
        )
        self.target_ip = target_ip
        self.debug_mode = debug_mode

        try:
            # Vérifier une seule fois si on est root
            self._is_root = (os.geteuid() == 0)
        except AttributeError:
            # Peut échouer sur certains systèmes non-Unix (ex: Windows)
            self._is_root = False  # Supposer non-root si euid n'existe pas

        self._current_task_id: Optional[str] = None
        self._task_total_steps: int = 1
        self._task_current_step: int = 0

        # Variables pour la gestion des barres visuelles
        self.use_visual_bars = True

        # Configuration pour le traitement par lots des sorties
        self._buffer_size = 8 if not self.debugger_mode else 1  # Réduire en mode débogueur
        self._throttle_time = 0.1 if not self.debugger_mode else 0.01  # Réduire en mode débogueur
        self._last_progress_update = {}  # Timestamps pour le throttling par plugin

        # Patterns spécifiques pour détection de progression
        self._apt_update_total_pattern = re.compile(r'Get:(\d+)')
        self._apt_install_pattern = re.compile(r'Setting up (\S+)')

        # Mémoriser les commandes en cours d'exécution pour le debugging
        self._running_commands: Dict[int, str] = {}
        self._command_lock = threading.RLock()

        # Variables pour la gestion des exécutions asynchrones
        self._output_queues: Dict[int, queue.Queue] = {}
        self._async_commands: Set[int] = set()

        # Verrou pour l'accès aux sorties
        self._output_lock = threading.RLock()

    # --- Méthodes de Logging (Déléguées au logger) ---

    def log_info(self, msg: str, log_levels: Optional[Dict[str, str]] = None):
        """Enregistre un message d'information."""
        self.logger.info(msg, target_ip=self.target_ip)

    def log_warning(self, msg: str, log_levels: Optional[Dict[str, str]] = None):
        """Enregistre un message d'avertissement."""
        self.logger.warning(msg, target_ip=self.target_ip)

    def log_error(self, msg: str, exc_info: bool = False, log_levels: Optional[Dict[str, str]] = None):
        """
        Enregistre un message d'erreur.

        Args:
            msg: Le message d'erreur.
            exc_info: Si True, ajoute le traceback de l'exception actuelle.
        """
        self.logger.error(msg, target_ip=self.target_ip)
        if exc_info:
            # Utiliser traceback.format_exc() pour obtenir le traceback formaté
            self.logger.error(f"Traceback:\n{traceback.format_exc()}", target_ip=self.target_ip)

    def log_debug(self, msg: str, log_levels: Optional[Dict[str, str]] = None):
        """Enregistre un message de débogage."""
        self.logger.debug(msg, target_ip=self.target_ip)

    def log_success(self, msg: str, log_levels: Optional[Dict[str, str]] = None):
        """Enregistre un message de succès."""
        self.logger.success(msg, target_ip=self.target_ip)

    # --- Méthodes de Gestion de Progression ---

    def start_task(self, total_steps: int, description: str = "", task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        """
        Démarre une nouvelle tâche avec un nombre défini d'étapes pour le suivi de progression.

        Args:
            total_steps: Nombre total d'étapes pour cette tâche.
            description: Description de la tâche (affichée avec la barre de progression).
            task_id: Identifiant unique pour la tâche (utile pour plusieurs tâches parallèles).
                     Si None, utilise un ID basé sur le timestamp.
        """
        self._current_task_id = task_id or f"task_{int(time.time())}"
        self._task_total_steps = max(1, total_steps)  # Assurer au moins 1 étape
        self._task_current_step = 0
        self.logger.set_total_steps(self._task_total_steps, self._current_task_id)

        if self.use_visual_bars:
            # Utiliser la description comme pre_text pour la barre visuelle
            self.logger.create_bar(self._current_task_id, self._task_total_steps, pre_text=description)
        else:
            self.log_info(f"Démarrage tâche: {description} ({self._task_total_steps} étapes)", log_levels=log_levels)

    def update_task(self, advance: int = 1, description: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        """
        Met à jour la progression de la tâche en cours.

        Args:
            advance: Nombre d'étapes à avancer (par défaut 1).
            description: Nouvelle description à afficher pour cette étape (optionnel).
        """
        if self._current_task_id is None:
            self.log_warning("Impossible de mettre à jour : aucune tâche démarrée.", log_levels=log_levels)
            return

        self._task_current_step += advance
        # S'assurer que l'étape actuelle ne dépasse pas le total
        current = min(self._task_current_step, self._task_total_steps)

        # Mettre à jour la progression numérique via le logger
        # Le logger calcule le pourcentage basé sur current/total
        self.logger.next_step(self._current_task_id, current_step=current)

        # Mettre à jour la barre visuelle si activée
        if self.use_visual_bars:
            # Utiliser la description fournie ou un format par défaut pour le post_text
            step_text = description if description else f"{current}/{self._task_total_steps}"
            # Utiliser next_bar pour avancer la barre visuelle
            self.logger.next_bar(self._current_task_id, current_step=current, post_text=step_text)
        elif description:
            # Afficher la description comme log si pas de barre visuelle
            self.log_info(description, log_levels=log_levels)

    def complete_task(self, success: bool = True, message: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        """
        Marque la tâche en cours comme terminée.

        Args:
            success: Indique si la tâche s'est terminée avec succès.
            message: Message final à afficher (optionnel).
        """
        if self._current_task_id is None:
            self.log_warning("Impossible de compléter : aucune tâche démarrée.", log_levels=log_levels)
            return  # Aucune tâche active

        final_step = self._task_total_steps

        # Mettre à jour la progression numérique à 100%
        self.logger.next_step(self._current_task_id, current_step=final_step)

        # Mettre à jour/supprimer la barre visuelle
        if self.use_visual_bars:
            final_text = message or ("Terminé" if success else "Échec")
            final_color = "green" if success else "red"
            # Mettre à jour une dernière fois avant de supprimer
            self.logger.update_bar(
                self._current_task_id,
                final_step,
                pre_text=final_text,  # Afficher le message final avant la barre
                color=final_color
            )
            # Supprimer la barre après un court délai
            self.logger.delete_bar(self._current_task_id)
        elif message:
            # Afficher le message final si pas de barre visuelle
            if success:
                self.log_success(message, log_levels=log_levels)
            else:
                self.log_error(message, log_levels=log_levels)

        # Réinitialiser l'état de la tâche
        self._current_task_id = None
        self._task_total_steps = 1
        self._task_current_step = 0

    def enable_visual_bars(self, enable: bool = True, log_levels: Optional[Dict[str, str]] = None):
        """Active ou désactive l'utilisation des barres de progression visuelles."""
        self.use_visual_bars = enable

    # --- Méthodes d'Exécution de Commandes Optimisées ---

    def run(self,
                cmd: Union[str, List[str]],
                input_data: Optional[str] = None,
                no_output: bool = False,
                print_command: bool = False,
                real_time_output: bool = True,  # Activé par défaut pour plus de réactivité
                error_as_warning: bool = False,
                timeout: Optional[int] = DEFAULT_COMMAND_TIMEOUT,
                check: bool = False,  # Par défaut False pour retourner succès/échec
                shell: bool = False,
                cwd: Optional[str] = None,
                env: Optional[Dict[str, str]] = None,
                needs_sudo: Optional[bool] = None,
show_progress: bool = True, log_levels: Optional[Dict[str, str]] = None) -> Tuple[bool, str, str]:
            """
            Exécute une commande système, en utilisant sudo si nécessaire et non déjà root.
            Version optimisée pour le traitement en temps réel des sorties et la détection
            des barres de progression dans les outils comme apt, dpkg, etc.

            Args:
                cmd: Commande à exécuter (chaîne ou liste d'arguments).
                    Si chaîne et shell=False, elle sera découpée avec shlex.
                input_data: Données à envoyer sur stdin (optionnel).
                no_output: Si True, ne journalise pas stdout/stderr.
                print_command: Si True, journalise la commande avant exécution.
                real_time_output: Si True, affiche la sortie en temps réel avec traitement par lots.
                error_as_warning: Si True, traite les erreurs (stderr) comme des avertissements.
                timeout: Timeout en secondes pour la commande (None pour aucun timeout).
                check: Si True, lève une exception CalledProcessError en cas d'échec.
                    Si False (par défaut), retourne le succès basé sur le code de retour.
                shell: Si True, exécute la commande via le shell système (attention sécurité).
                cwd: Répertoire de travail pour la commande (optionnel).
                env: Variables d'environnement pour la commande (optionnel). Si None,
                    l'environnement actuel est hérité. Si fourni, il remplace l'env.
                needs_sudo: Forcer l'utilisation de sudo (True), forcer la non-utilisation (False),
                            ou laisser la détection automatique (None, défaut).
                show_progress: Si True, détecte et affiche les barres de progression.

            Returns:
                Tuple (success: bool, stdout: str, stderr: str).
                'success' est True si le code de retour est 0.

            Raises:
                subprocess.CalledProcessError: Si la commande échoue et check=True.
                subprocess.TimeoutExpired: Si le timeout est dépassé.
                FileNotFoundError: Si la commande ou sudo n'est pas trouvée.
                PermissionError: Si sudo est nécessaire mais échoue (ex: mauvais mdp).
            """
            # En mode débogueur, simplifier l'exécution
            if self.debugger_mode:
                # Utiliser un timeout plus court en mode débogueur pour éviter les blocages
                if timeout is None or timeout > 30:
                    timeout = 30

                # Simplifier la lecture des sorties pour éviter les blocages
                real_time_output = False

            # 1. Préparation de la commande
            if isinstance(cmd, str) and not shell:
                try:
                    cmd_list = shlex.split(cmd)
                except ValueError as e:
                    self.log_error(f"Erreur lors du découpage de la commande: '{cmd}'. Erreur: {e}", log_levels=log_levels)
                    # Flush des logs avant de lever l'exception
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()
                    raise ValueError(f"Commande invalide: {cmd}") from e
            elif isinstance(cmd, list):
                cmd_list = cmd
            elif isinstance(cmd, str) and shell:
                cmd_list = cmd  # Le shell interprétera la chaîne
            else:
                self.log_error(f"Type de commande invalide: {type(cmd)}", log_levels=log_levels)
                # Flush des logs avant de lever l'exception
                if hasattr(self.logger, 'flush'):
                    self.logger.flush()
                raise TypeError("La commande doit être une chaîne ou une liste d'arguments.")

            # 2. Détermination de l'utilisation de sudo
            use_sudo = False
            if needs_sudo is True:
                if self._is_root:
                    self.log_debug("needs_sudo=True mais déjà root, sudo non utilisé.", log_levels=log_levels)
                else:
                    use_sudo = True
            elif needs_sudo is None and not self._is_root:
                # Détection automatique: si pas root, on utilise sudo
                use_sudo = True

            sudo_password = None
            if use_sudo:
                # Vérifier si sudo est disponible
                if subprocess.run(['which', 'sudo'], capture_output=True, text=True).returncode != 0:
                    self.log_error("Commande 'sudo' non trouvée. Impossible d'exécuter avec des privilèges élevés.", log_levels=log_levels)
                    # Flush des logs avant de lever l'exception
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()
                    raise FileNotFoundError("sudo n'est pas installé ou pas dans le PATH")

                # Préparer la commande sudo
                # Utiliser -S pour lire le mot de passe depuis stdin si besoin
                # Utiliser -E pour préserver l'environnement si env n'est pas fourni
                sudo_prefix = ["sudo", "-S"]
                effective_env = env  # Par défaut, utiliser l'env fourni
                if env is None:
                    sudo_prefix.append("-E")
                    effective_env = os.environ.copy()  # Hériter et potentiellement modifier

                # Récupérer le mot de passe sudo depuis l'environnement
                sudo_password = os.environ.get("SUDO_PASSWORD")

                if isinstance(cmd_list, list):
                    cmd_to_run = sudo_prefix + cmd_list
                else:  # shell=True
                    # Construire la commande shell avec sudo
                    # shlex.quote est essentiel pour la sécurité
                    quoted_cmd = shlex.quote(cmd_list)
                    cmd_to_run = f"{' '.join(sudo_prefix)} sh -c {quoted_cmd}"
                    shell = True  # Assurer que shell est True pour Popen
                    self.log_warning("Utilisation combinée de sudo et shell=True. Vérifier la commande.", log_levels=log_levels)

            else:
                cmd_to_run = cmd_list
                effective_env = env  # Utiliser l'env fourni ou None (héritage par Popen)

            # 3. Logging de la commande (masquer le mot de passe)
            cmd_str_for_log = ' '.join(cmd_to_run) if isinstance(cmd_to_run, list) else cmd_to_run
            if print_command:
                logged_cmd = cmd_str_for_log
                if sudo_password:
                    logged_cmd = logged_cmd.replace(sudo_password, '********')
                self.log_info(f"Exécution: {logged_cmd}", log_levels=log_levels)

            # Générer un ID unique pour cette commande
            command_id = hash(str(cmd_to_run) + str(time.time()))
            with self._command_lock:
                self._running_commands[command_id] = cmd_str_for_log

            # 4. Exécution avec subprocess.Popen
            stdout_data = []
            stderr_data = []
            process = None
            start_time = time.monotonic()

            try:
                process = subprocess.Popen(
                    cmd_to_run,
                    stdin=subprocess.PIPE,  # Toujours créer stdin pour passer le mot de passe sudo
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,  # Important pour l'encodage
                    shell=shell,
                    cwd=cwd,
                    env=effective_env,  # Utiliser l'environnement effectif
                    bufsize=1,  # Lecture ligne par ligne
                    universal_newlines=True  # Compatibilité Windows/Unix pour les fins de ligne
                )

                # 5. Gestion de l'input (y compris le mot de passe sudo)
                if (use_sudo and sudo_password) or input_data:
                    input_full = ""
                    if use_sudo and sudo_password:
                        input_full += sudo_password + "\n"  # Ajouter le mot de passe sudo
                    if input_data:
                        input_full += input_data

                    # Écrire l'input de manière non-bloquante
                    try:
                        process.stdin.write(input_full)
                        process.stdin.flush()
                    except (BrokenPipeError, IOError) as e:
                        self.log_warning(f"Impossible d'écrire dans stdin: {e}", log_levels=log_levels)
                    finally:
                        process.stdin.close()  # Fermer stdin après l'envoi

                # 6. Configurer le traitement optimisé des sorties
                if real_time_output and not self.debugger_mode:
                    # Détection du type de commande pour optimiser le traitement
                    cmd_name = cmd_list[0].lower() if isinstance(cmd_list, list) and cmd_list else ""
                    is_apt = any(apt_cmd in cmd_name for apt_cmd in ["apt", "apt-get", "dpkg"])

                    # Identifier un task_id unique pour cette commande
                    cmd_task_id = f"cmd_{command_id}"

                    # Créer une barre de progression pour cette commande si c'est apt et show_progress
                    progress_bar_created = False
                    if is_apt and self.use_visual_bars and show_progress and not no_output:
                        apt_cmd_desc = f"Commande: {cmd_name}"
                        if isinstance(cmd_list, list) and len(cmd_list) > 1:
                            apt_cmd_desc += f" {cmd_list[1]}"
                        self.logger.create_bar(cmd_task_id, 100, pre_text=apt_cmd_desc, bar_width=30)
                        progress_bar_created = True

                    # Lire les sorties en temps réel avec traitement par lots
                    success, output, error = self._read_process_output_optimized(
                        process, timeout, cmd_task_id, is_apt, not no_output,
                        error_as_warning, show_progress
                    )

                    # Compléter la barre de progression si elle a été créée
                    if progress_bar_created:
                        self.logger.update_bar(cmd_task_id, 100, color="green" if success else "red")
                        self.logger.delete_bar(cmd_task_id)

                    # Stocker les sorties complètes
                    stdout_data = output.splitlines()
                    stderr_data = error.splitlines()

                    # Le code de retour est déjà géré par _read_process_output_optimized
                    return_code = 0 if success else 1
                else:
                    # Utiliser communicate pour les cas où real_time_output n'est pas souhaité
                    # ou en mode débogueur pour éviter les blocages
                    try:
                        stdout_res, stderr_res = process.communicate(timeout=timeout)
                        if stdout_res: stdout_data = stdout_res.splitlines()
                        if stderr_res: stderr_data = stderr_res.splitlines()

                        # Afficher les sorties si demandé
                        if not no_output:
                            # Traiter toutes les lignes de stdout en une seule fois pour éviter
                            # le mélange avec d'autres messages de log
                            stdout_lines = [line.strip() for line in stdout_data if line.strip()]
                            if stdout_lines:
                                for line in stdout_lines:
                                    self.log_info(line, log_levels=log_levels)

                            # Puis traiter toutes les lignes stderr
                            stderr_lines = [line.strip() for line in stderr_data if line.strip()]
                            if stderr_lines:
                                log_stderr_func = self.log_warning if error_as_warning else self.log_error
                                for line in stderr_lines:
                                    log_stderr_func(line)

                        return_code = process.returncode

                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - start_time
                        self.log_error(f"Timeout ({timeout}s, écoulé: {elapsed:.2f}s) dépassé pour la commande: {cmd_str_for_log}", log_levels=log_levels)
                        try:
                            process.kill()
                        except Exception as e:
                            self.log_debug(f"Erreur lors de la tentative de kill du processus: {e}", log_levels=log_levels)

                        # Essayer de lire ce qui reste après kill
                        try:
                            stdout_res, stderr_res = process.communicate(timeout=1.0)  # Court timeout pour éviter blocage
                            if stdout_res: stdout_data.extend(stdout_res.splitlines())
                            if stderr_res: stderr_data.extend(stderr_res.splitlines())
                        except Exception as e:
                            self.log_debug(f"Erreur lors de la récupération des sorties après timeout: {e}", log_levels=log_levels)

                        # Flush des logs avant de relancer l'exception
                        if hasattr(self.logger, 'flush'):
                            self.logger.flush()

                        # Relancer l'exception
                        raise

                # 7. Construction des sorties complètes
                stdout = "\n".join(line.rstrip() for line in stdout_data)
                stderr = "\n".join(line.rstrip() for line in stderr_data)

                # 8. Vérification du succès
                success = (return_code == 0)

                # Gérer le cas spécifique de sudo échouant à cause du mot de passe
                if use_sudo and return_code != 0 and any(err_msg in stderr.lower() for err_msg in
                                                        ["incorrect password attempt",
                                                        "sudo: a password is required"]):
                    err_msg = "Échec de l'authentification sudo."
                    self.log_error(err_msg, log_levels=log_levels)

                    # Flush des logs avant de retourner ou lever une exception
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()

                    if check:
                        # Lever une exception PermissionError spécifique
                        raise PermissionError(err_msg)
                    else:
                        return False, stdout, stderr  # Retourner échec

                # Gérer check=True
                if check and not success:
                    error_msg_detail = f"Commande échouée avec code {return_code}.\nStderr: {stderr}\nStdout: {stdout}"
                    self.log_error(f"Erreur lors de l'exécution de: {cmd_str_for_log}", log_levels=log_levels)
                    self.log_error(error_msg_detail, log_levels=log_levels)

                    # Flush des logs avant de lever l'exception
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()

                    raise subprocess.CalledProcessError(return_code, cmd_to_run, output=stdout, stderr=stderr)

                # Nettoyer l'état interne
                with self._command_lock:
                    if command_id in self._running_commands:
                        del self._running_commands[command_id]

                # Flush des logs avant de retourner le résultat
                if hasattr(self.logger, 'flush'):
                    self.logger.flush()

                return success, stdout, stderr

            except FileNotFoundError as e:
                # Commande (ou sudo) non trouvée
                self.log_error(f"Erreur: Commande ou dépendance introuvable: {e.filename}", log_levels=log_levels)

                # Flush des logs avant de relancer l'exception
                if hasattr(self.logger, 'flush'):
                    self.logger.flush()

                raise  # Relancer pour que l'appelant sache

            except PermissionError as e:
                # Erreur de permission (souvent sudo)
                self.log_error(f"Erreur de permission: {e}", log_levels=log_levels)

                # Flush des logs avant de relancer l'exception
                if hasattr(self.logger, 'flush'):
                    self.logger.flush()

                raise  # Relancer

            except Exception as e:
                # Autres erreurs inattendues
                self.log_error(f"Erreur inattendue lors de l'exécution de {cmd_str_for_log}: {e}", exc_info=True, log_levels=log_levels)

                # Essayer de récupérer stdout/stderr si possible
                stdout_err = "\n".join(stdout_data)
                stderr_err = "\n".join(stderr_data)

                # Flush des logs avant de retourner ou lever une exception
                if hasattr(self.logger, 'flush'):
                    self.logger.flush()

                # Si check=True, lever l'exception originale est peut-être mieux
                if check: raise
                return False, stdout_err, stderr_err  # Retourner échec si check=False

            finally:
                # Nettoyer les ressources si besoin
                with self._command_lock:
                    if command_id in self._running_commands:
                        del self._running_commands[command_id]

                # S'assurer que les processus sont nettoyés
                if process is not None:
                    try:
                        if process.poll() is None:  # Le processus est encore en cours
                            process.terminate()
                            process.wait(timeout=1.0)  # Attendre la fin, avec timeout
                    except Exception:
                        # En dernier recours, essayer de tuer brutalement
                        try:
                            process.kill()
                        except Exception:
                            pass  # Ignorer les erreurs finales

                # Dernier flush des logs pour s'assurer que tout est bien traité
                if hasattr(self.logger, 'flush'):
                    try:
                        self.logger.flush()
                    except Exception:
                        pass  # Ignorer les erreurs lors du flush final

    def _read_process_output_optimized(self, process, timeout, task_id, is_apt,
                                  log_output, error_as_warning, show_progress, log_levels: Optional[Dict[str, str]] = None):
        """
        Lit et traite la sortie d'un processus en temps réel avec traitement par lots.
        Toutes les lignes sont traitées de manière égale, dans l'ordre chronologique.

        Args:
            process: Le processus subprocess.Popen
            timeout: Timeout en secondes (None pour aucun)
            task_id: Identifiant unique pour la tâche (pour les barres de progression)
            is_apt: Si True, appliquer des optimisations spécifiques à apt
            log_output: Si True, journaliser les lignes de sortie
            error_as_warning: Si True, traiter stderr comme des warnings
            show_progress: Si True, détecter et afficher les barres de progression

        Returns:
            Tuple (success: bool, stdout: str, stderr: str)
        """
        # Sorties complètes à retourner
        all_stdout_lines = []
        all_stderr_lines = []

        # Buffers pour le traitement par lots (pour éviter l'intercalage des sorties)
        stdout_batch = []
        stderr_batch = []

        # Identifiants des descripteurs de fichiers
        stdout_fd = process.stdout.fileno()
        stderr_fd = process.stderr.fileno()

        # Variables pour la détection de progression
        progress_percentage = 0
        total_items = None  # Pour apt-get update/install
        processed_items = 0
        last_percentage_update = 0

        # Timestamp de démarrage pour le timeout
        start_time = time.monotonic()
        last_batch_time = start_time

        # Utiliser un timeout pour les opérations de lecture pour éviter les blocages
        select_timeout = 0.1  # 100ms

        # Détecter si nous sommes dans l'application principale vs. ligne de commande
        # En mode application ou debugger, on traite différemment pour assurer l'ordre
        is_app_mode = 'TEXTUAL_APP' in os.environ or hasattr(sys, '_called_from_textual')
        is_debug_mode = self.debugger_mode
        enforce_sequential = is_app_mode or is_debug_mode

        # Boucle principale de lecture
        while process.poll() is None:
            # Vérifier le timeout global
            current_time = time.monotonic()
            if timeout is not None and current_time - start_time > timeout:
                try:
                    process.kill()
                except:
                    pass  # Ignorer les erreurs de kill
                raise subprocess.TimeoutExpired(process.args, timeout, None, None)

            # Utiliser select pour attendre des données sur les flux sans bloquer
            try:
                ready, _, _ = select.select([stdout_fd, stderr_fd], [], [], select_timeout)
            except (ValueError, OSError):
                # Descripteurs de fichiers invalides ou fermés
                break

            # En mode application/debug, on traite les sorties séquentiellement et immédiatement
            # pour éviter les problèmes d'ordre
            if enforce_sequential:
                # Traiter immédiatement chaque ligne disponible
                if stdout_fd in ready:
                    try:
                        line = process.stdout.readline()
                        if line:
                            line = line.rstrip()
                            all_stdout_lines.append(line)

                            # Traiter immédiatement sans batching
                            if log_output:
                                self.log_info(line, log_levels=log_levels)
                                if hasattr(self.logger, 'flush'):
                                    self.logger.flush()

                            # Détecter progression si nécessaire
                            if show_progress and (is_apt or self._detect_progress_in_line(line, task_id)):
                                # Pour apt, mettre à jour le compteur d'items
                                if is_apt:
                                    if total_items is None and "Get:" in line:
                                        match = self._apt_update_total_pattern.search(line)
                                        if match:
                                            total_items = int(match.group(1)) * 2

                                    if "Get:" in line or "Setting up " in line:
                                        processed_items += 1
                                        if total_items:
                                            progress_percentage = min(int((processed_items / total_items) * 100), 100)
                                            if progress_percentage - last_percentage_update >= 2:
                                                last_percentage_update = progress_percentage
                                                self._update_command_progress(task_id, progress_percentage)
                    except (IOError, OSError) as e:
                        self.log_debug(f"Erreur lors de la lecture de stdout: {e}", log_levels=log_levels)
                        break

                if stderr_fd in ready:
                    try:
                        line = process.stderr.readline()
                        if line:
                            line = line.rstrip()
                            all_stderr_lines.append(line)

                            # Traiter immédiatement sans batching
                            if log_output:
                                log_func = self.log_warning if error_as_warning else self.log_error
                                log_func(line)
                                if hasattr(self.logger, 'flush'):
                                    self.logger.flush()
                    except (IOError, OSError) as e:
                        self.log_debug(f"Erreur lors de la lecture de stderr: {e}", log_levels=log_levels)
                        break
            else:
                # Mode standard: Traitement par lots basé sur le temps écoulé
                batch_timeout = (current_time - last_batch_time) >= self._throttle_time

                # Si le timeout de traitement par lots est atteint, traiter les lots actuels
                if batch_timeout and (stdout_batch or stderr_batch):
                    with self._output_lock:
                        # Traiter d'abord toutes les lignes stdout
                        if stdout_batch:
                            self._process_output_batch(stdout_batch, False, log_output, error_as_warning)
                            stdout_batch = []

                        # Puis traiter toutes les lignes stderr
                        if stderr_batch:
                            self._process_output_batch(stderr_batch, True, log_output, error_as_warning)
                            stderr_batch = []

                    # Réinitialiser le timestamp du dernier traitement par lots
                    last_batch_time = current_time

                # Lire stdout si prêt
                if stdout_fd in ready:
                    try:
                        line = process.stdout.readline()
                        if line:
                            line = line.rstrip()
                            all_stdout_lines.append(line)

                            # Ajouter au batch pour traitement groupé
                            stdout_batch.append(line)

                            # Détecter les patterns de progression dans stdout si show_progress
                            if show_progress:
                                if is_apt:
                                    # Détecter le nombre total d'éléments pour apt-get update
                                    if total_items is None and "Get:" in line:
                                        match = self._apt_update_total_pattern.search(line)
                                        if match:
                                            # Estimer à partir du premier numéro trouvé
                                            total_items = int(match.group(1)) * 2  # Estimation approximative
                                            self.log_debug(f"Nombre total d'éléments apt estimé: {total_items}", log_levels=log_levels)

                                    # Compter les éléments traités (Get:X ou Setting up pkg)
                                    if "Get:" in line or "Setting up " in line:
                                        processed_items += 1
                                        # Calculer le pourcentage si on a une estimation du total
                                        if total_items:
                                            progress_percentage = min(int((processed_items / total_items) * 100), 100)
                                            # Éviter les mises à jour trop fréquentes
                                            if progress_percentage - last_percentage_update >= 2:  # Minimum 2% de différence
                                                last_percentage_update = progress_percentage
                                                # Mettre à jour la barre avec throttling
                                                self._update_command_progress(task_id, progress_percentage)

                                # Détecter les patterns génériques
                                self._detect_progress_in_line(line, task_id)
                    except (IOError, OSError) as e:
                        self.log_debug(f"Erreur lors de la lecture de stdout: {e}", log_levels=log_levels)
                        break

                # Lire stderr si prêt
                if stderr_fd in ready:
                    try:
                        line = process.stderr.readline()
                        if line:
                            line = line.rstrip()
                            all_stderr_lines.append(line)

                            # Ajouter au batch pour traitement groupé
                            stderr_batch.append(line)
                    except (IOError, OSError) as e:
                        self.log_debug(f"Erreur lors de la lecture de stderr: {e}", log_levels=log_levels)
                        break

            # Si aucun flux prêt, petite pause pour éviter de monopoliser le CPU
            if not ready:
                time.sleep(0.01)

        # Lire le reste de stdout
        remaining_stdout = self._read_remaining_stream(process.stdout)
        all_stdout_lines.extend(remaining_stdout)
        if log_output and remaining_stdout:
            if enforce_sequential:
                # Traiter immédiatement ligne par ligne
                for line in remaining_stdout:
                    self.log_info(line, log_levels=log_levels)
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()
            else:
                # Traiter par lot
                self._process_output_batch(remaining_stdout, False, log_output, error_as_warning)

        # Lire le reste de stderr
        remaining_stderr = self._read_remaining_stream(process.stderr)
        all_stderr_lines.extend(remaining_stderr)
        if log_output and remaining_stderr:
            if enforce_sequential:
                # Traiter immédiatement ligne par ligne
                log_func = self.log_warning if error_as_warning else self.log_error
                for line in remaining_stderr:
                    log_func(line)
                    if hasattr(self.logger, 'flush'):
                        self.logger.flush()
            else:
                # Traiter par lot
                self._process_output_batch(remaining_stderr, True, log_output, error_as_warning)

        # Traiter les buffers restants en mode normal
        if not enforce_sequential:
            with self._output_lock:
                if stdout_batch:
                    self._process_output_batch(stdout_batch, False, log_output, error_as_warning)
                if stderr_batch:
                    self._process_output_batch(stderr_batch, True, log_output, error_as_warning)

        # Flush final pour s'assurer que tout est affiché
        if hasattr(self.logger, 'flush'):
            self.logger.flush()

        # Récupérer le code de retour et construire les sorties complètes
        return_code = process.poll()
        success = return_code == 0

        stdout_output = "\n".join(all_stdout_lines)
        stderr_output = "\n".join(all_stderr_lines)

        return success, stdout_output, stderr_output

    def _read_remaining_stream(self, stream):
        """
        Lit les données restantes d'un flux jusqu'à EOF.

        Args:
            stream: Le flux à lire (process.stdout ou process.stderr)

        Returns:
            List[str]: Liste des lignes lues, sans les retours à la ligne
        """
        remaining_lines = []
        while True:
            try:
                line = stream.readline()
                if not line:
                    break
                line = line.rstrip()
                if line:  # Ignorer les lignes vides
                    remaining_lines.append(line)
            except (IOError, OSError):
                break
        return remaining_lines

    def _process_output_batch(self, lines, is_stderr, log_output, error_as_warning):
        """
        Traite un lot de lignes de sortie de manière égale, en une seule fois.

        Args:
            lines: Liste de lignes à traiter
            is_stderr: Si True, les lignes viennent de stderr
            log_output: Si True, journaliser les lignes
            error_as_warning: Si True, traiter stderr comme des warnings
        """
        if not log_output or not lines:
            return  # Ne pas traiter si log_output est False ou pas de lignes

        # Filtrer les lignes vides
        lines_to_log = [line for line in lines if line.strip()]
        if not lines_to_log:
            return

        # Pour éviter que les logs "manuel" s'intercalent avec ces logs
        if is_stderr:
            # Utiliser warning ou error selon la configuration
            log_func = self.logger.warning if error_as_warning else self.logger.error
            for line in lines_to_log:
                log_func(line)
        else:
            # Journaliser stdout comme info
            for line in lines_to_log:
                self.logger.info(line)

    # Dans plugins_utils_base.py -> class PluginsUtilsBase

    def _detect_progress_in_line(self, line, task_id):
        """
        Détecte les patterns de progression dans une ligne et met à jour la barre si nécessaire.

        Args:
            line: Ligne à analyser
            task_id: Identifiant de la tâche pour la barre de progression

        Returns:
            bool: True si une progression a été détectée
        """
        if not task_id or not self.use_visual_bars: # Ne pas détecter si pas de task_id ou barres désactivées
             return False

        for pattern in PROGRESS_PATTERNS:
            match = pattern.search(line)
            if match:
                # Extraire le pourcentage ou calculer à partir des groupes capturés
                groups = match.groups()
                try:
                    if len(groups) == 1 and groups[0] is not None:
                        # Format simple: 45% (capturé comme groupe 1)
                        percentage = int(groups[0])
                        self._update_command_progress(task_id, percentage)
                        return True
                    elif len(groups) >= 2:
                        # Vérifier si les groupes sont None avant d'appeler strip()
                        group1 = groups[0]
                        group2 = groups[1]

                        # Format: 5/20
                        if group1 is not None and group1.strip().isdigit() and \
                           group2 is not None and group2.strip().isdigit():
                            current = int(group1.strip())
                            total = int(group2.strip())
                            percentage = int((current / total) * 100) if total > 0 else 0
                            self._update_command_progress(task_id, percentage)
                            return True

                        # Format: [=====>   ] 45%
                        # Le groupe 1 peut être la barre, le groupe 2 le pourcentage
                        elif group2 is not None and group2.strip().isdigit():
                            percentage = int(group2.strip())
                            self._update_command_progress(task_id, percentage)
                            return True

                        # Format: Cas avec groupe optionnel pour décimales
                        # (?:progress|...)[:=]\s*(\d+)(?:[.,](\d+))?%
                        # Ici, group1 est la partie entière, group2 est la partie décimale (optionnelle)
                        elif group1 is not None and group1.strip().isdigit():
                            percentage = int(group1.strip())
                            # Ignorer group2 (décimale) pour la barre de progression
                            self._update_command_progress(task_id, percentage)
                            return True

                except (ValueError, IndexError, TypeError) as e:
                     # Logguer discrètement l'erreur de parsing de progression
                     self.log_debug(f"Erreur parsing progression ligne '{line}': {e}", log_levels=log_levels)
                     pass # Continuer avec le pattern suivant

        return False


    def _update_command_progress(self, task_id, percentage):
        """
        Met à jour la barre de progression d'une commande avec throttling.

        Args:
            task_id: Identifiant de la tâche
            percentage: Pourcentage de progression (0-100)
        """
        # Limiter les mises à jour trop fréquentes (sauf en mode debug)
        current_time = time.time()
        last_time = self._last_progress_update.get(task_id, 0)

        # En mode debug, mettre à jour plus souvent
        update_interval = 0.05 if self.debug_mode else 0.2

        # Vérifier s'il faut limiter la mise à jour
        if current_time - last_time < update_interval:
            return  # Trop tôt pour mettre à jour

        # Mettre à jour le timestamp
        self._last_progress_update[task_id] = current_time

        # Mettre à jour la barre de progression
        if self.use_visual_bars:
            percentage_clamped = min(max(0, percentage), 100)
            self.logger.update_bar(task_id, percentage_clamped, post_text=f"{percentage_clamped}%")

    async def run_async(self,
                        cmd: Union[str, List[str]],
                        input_data: Optional[str] = None,
                        no_output: bool = False,
                        print_command: bool = False,
                        error_as_warning: bool = False,
                        timeout: Optional[int] = DEFAULT_COMMAND_TIMEOUT,
                        check: bool = False,
                        shell: bool = False,
                        cwd: Optional[str] = None,
                        env: Optional[Dict[str, str]] = None,
                        needs_sudo: Optional[bool] = None,
                        show_progress: bool = True) -> Tuple[bool, str, str]:
        """
        Version asynchrone de run() pour être utilisée dans des contextes asyncio.
        Exécute une commande de manière non-bloquante, en permettant à l'interface de rester réactive.

        Args:
            [Mêmes arguments que run()]

        Returns:
            Tuple (success: bool, stdout: str, stderr: str).
        """
        # En mode débogueur, simplifier l'exécution pour éviter les blocages
        if self.debugger_mode:
            # Utiliser un timeout plus court en mode débogueur
            if timeout is None or timeout > 30:
                timeout = 30

            # Exécuter de manière synchrone mais dans une tâche asyncio
            return await asyncio.to_thread(
                self.run,
                cmd, input_data, no_output, print_command, False,  # real_time_output=False
                error_as_warning, timeout, check, shell, cwd, env, needs_sudo, show_progress
            )

        # Créer un événement pour signaler quand la commande est terminée
        done_event = asyncio.Event()

        # Résultat de l'exécution
        result = {"success": False, "stdout": "", "stderr": ""}

        # ID unique pour cette commande
        command_id = hash(str(cmd) + str(time.time()))

        # Tracer la commande pour le débogage
        with self._command_lock:
            self._running_commands[command_id] = str(cmd)
            self._async_commands.add(command_id)

        # Fonction qui sera exécutée dans un thread à part
        def thread_run(log_levels: Optional[Dict[str, str]] = None):
            try:
                # Exécuter la commande de manière synchrone
                success, stdout, stderr = self.run(
                    cmd, input_data, no_output, print_command, True,
                    error_as_warning, timeout, check, shell, cwd, env, needs_sudo, show_progress
                )

                # Stocker le résultat
                result["success"] = success
                result["stdout"] = stdout
                result["stderr"] = stderr
            except Exception as e:
                # Enregistrer l'erreur
                self.log_error(f"Erreur dans l'exécution asynchrone: {e}", exc_info=True, log_levels=log_levels)
                result["stderr"] = str(e)
            finally:
                # Signaler que l'exécution est terminée
                asyncio.run_coroutine_threadsafe(done_event.set(), asyncio.get_event_loop())

                # Nettoyer
                with self._command_lock:
                    if command_id in self._running_commands:
                        del self._running_commands[command_id]
                    if command_id in self._async_commands:
                        self._async_commands.remove(command_id)

        # Démarrer l'exécution dans un thread séparé
        thread = threading.Thread(target=thread_run, daemon=True)
        thread.start()

        try:
            # Attendre que l'exécution soit terminée, avec possibilité d'annulation
            await done_event.wait()
            return result["success"], result["stdout"], result["stderr"]
        except asyncio.CancelledError:
            # Si la tâche asyncio est annulée, tenter d'annuler la commande
            self.log_warning(f"Annulation de la commande asynchrone: {cmd}", log_levels=log_levels)
            # L'annulation propre n'est pas possible directement
            # Le mieux est de marquer la commande comme ne devant plus être traitée
            with self._command_lock:
                if command_id in self._running_commands:
                    del self._running_commands[command_id]
                if command_id in self._async_commands:
                    self._async_commands.remove(command_id)

            # Relever l'exception pour propager l'annulation
            raise

    def get_running_commands(self, log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Retourne la liste des commandes actuellement en cours d'exécution.
        Utile pour le débogage.

        Returns:
            List[str]: Liste des commandes en cours.
        """
        with self._command_lock:
            return list(self._running_commands.values())

    def is_command_running(self, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si des commandes sont en cours d'exécution.

        Returns:
            bool: True si au moins une commande est en cours.
        """
        with self._command_lock:
            return len(self._running_commands) > 0 or len(self._async_commands) > 0
