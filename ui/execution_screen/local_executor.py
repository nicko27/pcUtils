#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module pour l'exécution locale des plugins.

Ce module fournit une classe pour exécuter des plugins PCUtils en local,
avec gestion asynchrone des sorties et intégration avec l'interface utilisateur.
"""

import os
import sys
import json
import asyncio
import logging
import traceback
import time
import subprocess
import tempfile
import shlex
import threading
from datetime import datetime
from typing import Dict, Tuple, Optional, Any, List, Union, Set
from pathlib import Path

# Vérifier si nous sommes dans un environnement avec les modules requis
try:
    from ruamel.yaml import YAML
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Imports internes
try:
    from ..utils.logging import get_logger
    from ..choice_screen.plugin_utils import get_plugin_folder_name
    from .logger_utils import LoggerUtils
    from .file_content_handler import FileContentHandler
    INTERNAL_MODULES_AVAILABLE = True
except ImportError:
    INTERNAL_MODULES_AVAILABLE = False

# Fallback logger en cas d'absence des modules internes
if INTERNAL_MODULES_AVAILABLE:
    logger = get_logger('local_executor')
else:
    logger = logging.getLogger('local_executor')
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class LocalExecutor:
    """
    Classe pour l'exécution locale des plugins PCUtils.

    Cette classe gère l'exécution des plugins en local, la capture des sorties
    et l'affichage des logs dans l'interface utilisateur.
    """

    def __init__(self, app=None):
        """
        Initialise l'exécuteur local.

        Args:
            app: Application Textual (optionnel)
        """
        self.app = app
        # Détecter si nous sommes dans un debugger
        self.debugger_mode = self._is_debugger_active()
        # État des commandes en cours
        self._running_processes = {}
        # Verrou pour les opérations concurrentes
        self._lock = threading.RLock()
        os.environ['TEXTUAL_APP']="1"
        logger.debug(f"LocalExecutor initialisé, debugger_mode={self.debugger_mode}")

    def _is_debugger_active(self) -> bool:
        """
        Détecte si le processus est exécuté dans un débogueur.

        Returns:
            bool: True si un débogueur est actif
        """
        # Méthode 1: Vérifier sys.gettrace
        if hasattr(sys, 'gettrace') and sys.gettrace():
            return True

        # Méthode 2: Vérifier les variables d'environnement
        debug_env_vars = [
            'PYTHONBREAKPOINT', 'VSCODE_DEBUG', 'PYCHARM_DEBUG',
            'PYDEVD_USE_FRAME_EVAL', 'DEBUG', 'TEXTUAL_DEBUG',
            'FORCE_DEBUG_MODE'
        ]
        if any(os.environ.get(var) for var in debug_env_vars):
            return True

        # Méthode 3: Vérifier les modules de débogage
        debug_modules = ['pydevd', 'debugpy', '_pydevd_bundle', 'pdb']
        if any(mod in sys.modules for mod in debug_modules):
            return True

        return False

    def log_message(self, message: str, level: str = "info", target_ip: Optional[str] = None):
        """
        Ajoute un message au log de l'application.

        Args:
            message: Le message à ajouter au log
            level: Le niveau de log (info, debug, error, success)
            target_ip: Adresse IP cible pour les plugins SSH (optionnel)
        """
        logger.debug(f"Ajout d'un message au log: {level}:{message[:50]}...")

        try:
            # Si LoggerUtils est disponible, l'utiliser
            if hasattr(LoggerUtils, 'add_log') and self.app:
                # Créer une coroutine pour ajouter le message au log
                async def add_log_async():
                    await LoggerUtils.add_log(self.app, message, level=level, target_ip=target_ip)

                # Exécuter la coroutine dans la boucle d'événements
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(add_log_async())
                except RuntimeError:
                    # Pas de boucle en cours
                    if self.debugger_mode:
                        # En mode débogueur, simplement afficher sur la console
                        print(f"[{level.upper()}] {message}")
                    else:
                        # Essayer de créer une boucle temporaire
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(add_log_async())
                            loop.close()
                        except Exception as e:
                            logger.error(f"Impossible d'exécuter add_log_async: {e}")
                            print(f"[{level.upper()}] {message}")
            else:
                # Fallback: afficher sur la console
                print(f"[{level.upper()}] {message}")

        except Exception as e:
            logger.error(f"Erreur lors de l'ajout du message au log: {e}")
            # Fallback ultime: simplement logger
            logger.log(
                logging.ERROR if level.lower() == "error" else
                logging.WARNING if level.lower() == "warning" else
                logging.INFO,
                message
            )

    async def execute_plugin(self, plugin_widget, folder_name: str, config: dict) -> Tuple[bool, str]:
        """
        Exécute un plugin localement.

        Args:
            plugin_widget: Le widget Textual représentant le plugin (peut être None)
            folder_name: Le nom du dossier du plugin
            config: La configuration du plugin

        Returns:
            Tuple[bool, str]: (succès, sortie)
        """
        process = None
        stdout_text = ""
        stderr_text = ""

        try:
            logger.info(f"Exécution locale du plugin {folder_name}")

            # Construire le chemin du plugin
            base_dir = self._determine_base_dir()
            plugin_dir = os.path.join(base_dir, "plugins", folder_name)
            logger.debug(f"Chemin du plugin: {plugin_dir}")

            # Vérifier si le répertoire du plugin existe
            if not os.path.isdir(plugin_dir):
                error_msg = f"Répertoire du plugin introuvable: {plugin_dir}"
                logger.error(error_msg)
                self.log_message(error_msg, "error")
                return False, error_msg

            # Déterminer le type de plugin (bash ou python)
            if os.path.exists(os.path.join(plugin_dir, "main.sh")):
                logger.info(f"Détecté comme plugin bash")
                is_bash_plugin = True
                exec_path = os.path.join(plugin_dir, "main.sh")
            else:
                # Sinon c'est un plugin Python
                exec_path = os.path.join(plugin_dir, "exec.py")
                logger.info(f"Détecté comme plugin Python")
                is_bash_plugin = False

            # Vérifier que le fichier d'exécution existe
            if not os.path.exists(exec_path):
                error_msg = f"Fichier d'exécution introuvable: {exec_path}"
                logger.error(error_msg)
                self.log_message(error_msg, "error")
                return False, error_msg

            logger.debug(f"Fichier d'exécution: {exec_path}")

            # Charger les paramètres du plugin depuis settings.yml
            plugin_settings = self._load_plugin_settings(plugin_dir)

            # Traiter le contenu des fichiers de configuration
            plugin_config_with_files = await self._process_file_content(plugin_settings, config, plugin_dir)

            # Préparer la commande en fonction du type de plugin
            cmd = self._prepare_command(is_bash_plugin, exec_path, plugin_config_with_files, config)

            # Logguer la commande préparée (sans mots de passe sensibles)
            safe_cmd = self._sanitize_command(cmd)
            logger.info(f"Exécution de la commande: {' '.join(safe_cmd)}")

            # Marquer le début de l'exécution
            target_ip = getattr(plugin_widget, 'target_ip', None) if plugin_widget else None
            self.log_message(f"Début de l'exécution du plugin {folder_name}", "start", target_ip)

            # Créer le processus
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=plugin_dir
            )

            # Enregistrer le processus pour la gestion des erreurs
            with self._lock:
                self._running_processes[process.pid] = {
                    'plugin': folder_name,
                    'start_time': time.time(),
                    'process': process
                }

            # Lire les sorties du processus de manière asynchrone
            stdout_lines, stderr_lines = await self._read_process_output(
                process, plugin_widget, folder_name, target_ip
            )

            # Attendre la fin du processus
            try:
                exit_code = await asyncio.wait_for(process.wait(), timeout=6000)
            except asyncio.TimeoutError:
                # Tuer le processus si timeout
                logger.error(f"Timeout atteint pour {folder_name}, terminaison forcée")
                self.log_message(f"Timeout d'exécution pour {folder_name}", "error", target_ip)
                process.kill()
                return False, "Timeout d'exécution"

            # Supprimer le processus de la liste des processus en cours
            with self._lock:
                self._running_processes.pop(process.pid, None)

            # Combiner les lignes en texte
            stdout_text = "\n".join(stdout_lines)
            stderr_text = "\n".join(stderr_lines)


            # Vérifier le code de retour
            if exit_code != 0:
                error_msg = stderr_text if stderr_text else f"Erreur inconnue (code {exit_code})"
                logger.error(f"Plugin {folder_name} terminé avec erreur: {exit_code}")
                self.log_message(f"Échec du plugin {folder_name}: {error_msg}", "error", target_ip)


                return False, error_msg

            # Succès
            logger.info(f"Plugin {folder_name} terminé avec succès")
            self.log_message(f"Plugin {folder_name} exécuté avec succès", "success", target_ip)

            # Flush LoggerUtils

            return True, stdout_text

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Erreur lors de l'exécution du plugin {folder_name}: {error_msg}")
            logger.error(traceback.format_exc())

            # Logguer l'erreur
            target_ip = getattr(plugin_widget, 'target_ip', None) if plugin_widget else None
            self.log_message(
                f"Erreur lors de l'exécution du plugin {folder_name}: {error_msg}",
                "error",
                target_ip
            )

            # Tuer le processus si toujours en cours
            if process and process.returncode is None:
                try:
                    process.kill()
                    logger.info(f"Processus {process.pid} tué suite à une erreur")
                except Exception:
                    pass

            # Nettoyer les processus en cours
            with self._lock:
                if process and process.pid in self._running_processes:
                    self._running_processes.pop(process.pid, None)


            return False, error_msg

    def _determine_base_dir(self) -> str:
        """
        Détermine le répertoire de base de l'application.

        Returns:
            str: Chemin du répertoire de base
        """
        # Méthode 1: Remonter depuis le module actuel
        try:
            current_file = os.path.abspath(__file__)
            # Remonter de 3 niveaux (local_executor.py -> execution_screen -> ui -> base)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
            if os.path.isdir(os.path.join(base_dir, "plugins")):
                return base_dir
        except NameError:
            pass  # __file__ n'est pas défini

        # Méthode 2: Utiliser le répertoire courant
        if os.path.isdir("plugins"):
            return os.getcwd()

        # Méthode 3: Tester plusieurs chemins relatifs possibles
        for path in [".", "..", "../..", "../../.."]:
            test_path = os.path.abspath(path)
            if os.path.isdir(os.path.join(test_path, "plugins")):
                return test_path

        # Fallback: retourner le répertoire courant avec avertissement
        logger.warning("Impossible de déterminer le répertoire de base, utilisation du répertoire courant")
        return os.getcwd()

    def _load_plugin_settings(self, plugin_dir: str) -> Dict:
        """
        Charge les paramètres du plugin depuis settings.yml.

        Args:
            plugin_dir: Répertoire du plugin

        Returns:
            Dict: Paramètres du plugin ou dict vide en cas d'erreur
        """
        settings_path = os.path.join(plugin_dir, "settings.yml")
        if not os.path.exists(settings_path):
            logger.debug(f"Fichier settings.yml absent pour ce plugin")
            return {}

        if not YAML_AVAILABLE:
            logger.warning("Module ruamel.yaml non disponible, impossible de lire settings.yml")
            return {}

        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = YAML().load(f)
            logger.debug(f"Paramètres du plugin chargés: {settings}")
            return settings if settings else {}
        except Exception as e:
            logger.error(f"Erreur lors de la lecture des paramètres du plugin: {e}")
            logger.error(traceback.format_exc())
            return {}

    async def _process_file_content(self, plugin_settings: Dict, config: Dict, plugin_dir: str) -> Dict:
        """
        Traite le contenu des fichiers de configuration.

        Args:
            plugin_settings: Paramètres du plugin
            config: Configuration du plugin
            plugin_dir: Répertoire du plugin

        Returns:
            Dict: Configuration complète avec contenu des fichiers
        """
        # Configuration complète (copie pour éviter de modifier l'originale)
        plugin_config_with_files = config.copy()

        # Vérifier si le module FileContentHandler est disponible
        if not INTERNAL_MODULES_AVAILABLE:
            logger.warning("Module FileContentHandler non disponible, traitement des fichiers ignoré")
            return plugin_config_with_files

        try:
            # Traiter le contenu des fichiers
            file_content = FileContentHandler.process_file_content(plugin_settings, config, plugin_dir)

            # S'assurer que le contenu est ajouté au bon endroit dans la configuration
            if 'config' in plugin_config_with_files and isinstance(plugin_config_with_files['config'], dict):
                for param_name, content in file_content.items():
                    plugin_config_with_files['config'][param_name] = content
                    logger.info(f"Contenu du fichier intégré dans config.{param_name}")
            else:
                # Fallback: ajouter directement à la racine
                for param_name, content in file_content.items():
                    plugin_config_with_files[param_name] = content
                    logger.info(f"Contenu du fichier intégré dans la configuration sous {param_name}")

            return plugin_config_with_files

        except Exception as e:
            logger.error(f"Erreur lors du traitement des fichiers de configuration: {e}")
            logger.error(traceback.format_exc())
            return plugin_config_with_files

    def _prepare_command(self, is_bash_plugin: bool, exec_path: str,
                         plugin_config_with_files: Dict, config: Dict) -> List[str]:
        """
        Prépare la commande à exécuter en fonction du type de plugin.

        Args:
            is_bash_plugin: Si True, c'est un plugin bash
            exec_path: Chemin du fichier d'exécution
            plugin_config_with_files: Configuration complète avec contenu des fichiers
            config: Configuration originale

        Returns:
            List[str]: Commande à exécuter
        """
        if is_bash_plugin:
            # Pour un plugin Bash, passer les paramètres en ligne de commande
            plugin_name = config.get('name', os.path.basename(os.path.dirname(exec_path)))
            intensity = config.get('intensity', 'light')
            return ["bash", exec_path, plugin_name, intensity]
        else:
            # Pour un plugin Python, créer un fichier temporaire de configuration
            # si la configuration est complexe
            if len(json.dumps(plugin_config_with_files)) > 1000:
                # Configuration trop grande pour la ligne de commande
                temp_config_file = self._create_temp_config_file(plugin_config_with_files)
                return [sys.executable, exec_path, "-c", temp_config_file]
            else:
                # Configuration simple, passer directement en JSON
                return [sys.executable, exec_path, json.dumps(plugin_config_with_files)]

    def _create_temp_config_file(self, config: Dict) -> str:
        """
        Crée un fichier temporaire pour stocker la configuration.

        Args:
            config: Configuration du plugin

        Returns:
            str: Chemin du fichier temporaire
        """
        try:
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as temp:
                temp_path = temp.name
                json.dump(config, temp, indent=2)
                logger.debug(f"Configuration temporaire créée: {temp_path}")
                return temp_path
        except Exception as e:
            logger.error(f"Erreur lors de la création du fichier temporaire: {e}")
            # Fallback: fichier dans /tmp
            temp_path = f"/tmp/pcutils_config_{int(time.time())}.json"
            with open(temp_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.debug(f"Configuration fallback créée: {temp_path}")
            return temp_path

    def _sanitize_command(self, cmd: List[str]) -> List[str]:
        """
        Retire les informations sensibles de la commande pour le logging.

        Args:
            cmd: La commande à nettoyer

        Returns:
            List[str]: Commande sans informations sensibles
        """
        safe_cmd = []
        for arg in cmd:
            # Si l'argument est un fichier JSON ou une chaîne JSON
            if arg.endswith('.json') or (arg.startswith('{') and arg.endswith('}')):
                # Remplacer les mots de passe dans la chaîne JSON
                try:
                    if arg.endswith('.json'):
                        with open(arg, 'r') as f:
                            config = json.load(f)
                    else:
                        config = json.loads(arg)

                    # Fonction récursive pour masquer les mots de passe
                    def mask_passwords(obj):
                        if isinstance(obj, dict):
                            for key, value in obj.items():
                                if isinstance(key, str) and any(pwd in key.lower() for pwd in
                                                             ['password', 'passwd', 'mdp', 'secret']):
                                    obj[key] = "********"
                                elif isinstance(value, (dict, list)):
                                    mask_passwords(value)
                        elif isinstance(obj, list):
                            for i, item in enumerate(obj):
                                if isinstance(item, (dict, list)):
                                    mask_passwords(item)
                        return obj

                    masked_config = mask_passwords(config)

                    if arg.endswith('.json'):
                        safe_cmd.append(arg)  # Garder le chemin du fichier
                    else:
                        safe_cmd.append(json.dumps(masked_config))
                except Exception:
                    # En cas d'erreur, utiliser un placeholder
                    safe_cmd.append("[CONFIG JSON]")
            else:
                safe_cmd.append(arg)

        return safe_cmd

    async def _read_process_output(self, process, plugin_widget, plugin_name, target_ip=None):
        """
        Lit et traite les sorties du processus de manière asynchrone.

        Args:
            process: Processus en cours d'exécution
            plugin_widget: Widget du plugin dans l'interface
            plugin_name: Nom du plugin
            target_ip: Adresse IP cible (pour les plugins SSH)

        Returns:
            Tuple[List[str], List[str]]: Lignes de stdout et stderr
        """
        stdout_lines = []
        stderr_lines = []

        # Déterminer si nous sommes dans un contexte d'application ou de debugging
        enforce_sequential = self.debugger_mode

        # Fonction pour lire un flux de manière asynchrone
        async def read_stream(stream, is_stderr=False):
            lines = []

            while True:
                try:
                    line = await stream.readline()
                    if not line:
                        break

                    line_decoded = line.decode('utf-8', errors='replace').strip()
                    if not line_decoded:
                        continue

                    # Stocker la ligne
                    lines.append(line_decoded)

                    # Traiter JSON si possible
                    try:
                        if line_decoded.startswith('{') and line_decoded.endswith('}'):
                            # Tenter de parser comme JSON
                            log_entry = json.loads(line_decoded)

                            # Déterminer le niveau de log
                            level = log_entry.get('level', 'info' if not is_stderr else 'error').lower()
                            message = log_entry.get('message', line_decoded)

                            # Traiter via LoggerUtils si disponible
                            if hasattr(LoggerUtils, 'process_output_line') and self.app:
                                await LoggerUtils.process_output_line(
                                    self.app,
                                    line_decoded,  # Garder le JSON intact
                                    plugin_widget,
                                    target_ip=target_ip
                                )

                                # En mode application ou debug, forcer un flush après chaque message
                                if enforce_sequential and hasattr(LoggerUtils, 'flush_pending_messages'):
                                    await LoggerUtils.flush_pending_messages(self.app)
                            else:
                                # Fallback: utiliser log_message
                                self.log_message(message, level, target_ip)
                        else:
                            # Texte brut
                            if is_stderr:
                                level = "error"
                            else:
                                # Détecter le niveau basé sur des mots-clés
                                line_lower = line_decoded.lower()
                                if any(err in line_lower for err in ['error', 'erreur', 'failed', 'échec']):
                                    level = "error"
                                elif any(warn in line_lower for warn in ['warning', 'attention']):
                                    level = "warning"
                                elif any(succ in line_lower for succ in ['success', 'succès', 'terminé']):
                                    level = "success"
                                else:
                                    level = "info"

                            # Traiter via LoggerUtils si disponible
                            if hasattr(LoggerUtils, 'process_output_line') and self.app:
                                # Créer un JSON pour le traitement uniforme
                                json_wrapper = json.dumps({
                                    "timestamp": datetime.now().isoformat(),
                                    "level": level,
                                    "message": line_decoded,
                                    "plugin_name": plugin_name
                                })

                                await LoggerUtils.process_output_line(
                                    self.app,
                                    json_wrapper,
                                    plugin_widget,
                                    target_ip=target_ip
                                )

                                # En mode application ou debug, forcer un flush après chaque message
                                if enforce_sequential and hasattr(LoggerUtils, 'flush_pending_messages'):
                                    await LoggerUtils.flush_pending_messages(self.app)
                            else:
                                # Fallback: utiliser log_message
                                self.log_message(line_decoded, level, target_ip)
                    except json.JSONDecodeError:
                        # Ce n'est pas du JSON valide, traiter comme du texte
                        if is_stderr:
                            self.log_message(line_decoded, "error", target_ip)
                        else:
                            self.log_message(line_decoded, "info", target_ip)
                    except Exception as e:
                        logger.error(f"Erreur traitement ligne: {e}")
                        # Assurer que la ligne est loggée malgré l'erreur
                        self.log_message(line_decoded, "error" if is_stderr else "info", target_ip)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Erreur lecture flux: {e}")
                    break

            return lines

        # Lire les deux flux en parallèle en mode normal
        if not enforce_sequential:
            try:
                stdout_task = asyncio.create_task(read_stream(process.stdout, False))
                stderr_task = asyncio.create_task(read_stream(process.stderr, True))

                stdout_lines, stderr_lines = await asyncio.gather(stdout_task, stderr_task)
            except asyncio.CancelledError:
                # Annuler proprement les tâches en cas d'annulation
                if 'stdout_task' in locals():
                    stdout_task.cancel()
                if 'stderr_task' in locals():
                    stderr_task.cancel()
                raise
        else:
            # En mode application ou debug, lire séquentiellement pour garantir l'ordre exact des messages
            # Lire d'abord tout stdout
            stdout_lines = await read_stream(process.stdout, False)

            # Puis lire tout stderr
            stderr_lines = await read_stream(process.stderr, True)

            # Forcer un flush final
            if hasattr(LoggerUtils, 'flush_pending_messages') and self.app:
                await LoggerUtils.flush_pending_messages(self.app)

        return stdout_lines, stderr_lines

    def update_global_progress(self, app, progress: float):
        """
        Met à jour la barre de progression globale dans l'interface.

        Args:
            app: Application Textual
            progress: Valeur de progression (0.0 à 1.0)
        """
        # S'assurer que progress est bien entre 0 et 1
        progress = max(0.0, min(1.0, progress))

        try:
            # Rechercher la barre de progression globale
            progress_bar = app.query_one("#global-progress")
            if progress_bar:
                # Mettre à jour la barre de progression
                progress_bar.update(total=1.0, progress=progress)
                logger.debug(f"Progression globale mise à jour: {progress*100:.1f}%")
        except Exception as e:
            logger.debug(f"Impossible de mettre à jour la barre de progression globale: {e}")

    def kill_all_processes(self):
        """
        Tue tous les processus en cours d'exécution.
        Utile avant la fermeture de l'application.
        """
        with self._lock:
            running_count = len(self._running_processes)
            if running_count > 0:
                logger.warning(f"Arrêt forcé de {running_count} processus")
                for pid, info in list(self._running_processes.items()):
                    try:
                        process = info['process']
                        if process and process.returncode is None:
                            process.kill()
                            logger.info(f"Processus {pid} ({info['plugin']}) tué")
                    except Exception as e:
                        logger.error(f"Erreur lors de la terminaison du processus {pid}: {e}")

                self._running_processes.clear()