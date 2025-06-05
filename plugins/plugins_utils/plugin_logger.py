#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour les logs standardisés en format JSONL ou texte standard.
Supporte plusieurs barres de progression avec styles personnalisables.
Version corrigée pour résoudre les problèmes de progression et de cohérence.
"""

import os
import logging
import time
import tempfile
import json
import sys
import queue
import threading
import traceback
import shlex
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Tuple, Deque
from collections import deque

# Logger interne pour les problèmes du PluginLogger lui-même
internal_logger = logging.getLogger(__name__)
internal_logger.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stderr)
formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
handler.setFormatter(formatter)
internal_logger.addHandler(handler)

# Couleurs ANSI pour le mode texte
ANSI_COLORS = {
    "reset": "\033[0m",
    "info": "\033[0;37m",      # Blanc
    "warning": "\033[0;33m",   # Jaune
    "error": "\033[0;31m",     # Rouge
    "success": "\033[0;32m",   # Vert
    "debug": "\033[0;36m",     # Cyan
    "start": "\033[0;34m",     # Bleu
    "end": "\033[0;35m",       # Magenta
    "timestamp": "\033[0;90m", # Gris
    "target_ip": "\033[0;95m", # Magenta clair
    "progress_bar": "\033[0;34m", # Bleu pour la barre par défaut
    "progress_text": "\033[0;37m"  # Blanc pour le texte autour
}

# Couleurs pour les barres visuelles
BAR_COLORS = {
    "blue": "\033[0;34m",
    "green": "\033[0;32m",
    "red": "\033[0;31m",
    "yellow": "\033[0;33m",
    "cyan": "\033[0;36m",
    "magenta": "\033[0;35m",
    "white": "\033[0;37m",
}


def is_debugger_active(log_levels: Optional[Dict[str, str]] = None) -> bool:
    """Détecte si un débogueur est actif - version robuste."""
    # Méthode 1: Vérifier sys.gettrace
    if hasattr(sys, 'gettrace') and sys.gettrace():
        internal_logger.debug("Débogueur détecté via sys.gettrace()")
        return True

    # Méthode 2: Vérifier les variables d'environnement
    debug_env_vars = [
        'PYTHONBREAKPOINT', 'VSCODE_DEBUG', 'PYCHARM_DEBUG',
        'PYDEVD_USE_FRAME_EVAL', 'DEBUG', 'TEXTUAL_DEBUG',
        'PYDEVD_LOAD_VALUES_ASYNC', 'DEBUGPY_LAUNCHER_PORT'
    ]
    for var in debug_env_vars:
        if os.environ.get(var):
            internal_logger.debug(f"Débogueur détecté via variable d'environnement: {var}")
            return True

    # Méthode 3: Vérifier les modules de débogage connus
    debug_modules = ['pydevd', 'debugpy', '_pydevd_bundle', 'pdb']
    for mod in debug_modules:
        if mod in sys.modules:
            internal_logger.debug(f"Débogueur détecté via module: {mod}")
            return True

    # Méthode 4: Vérifier si nous sommes sous IPython
    try:
        if 'IPython' in sys.modules:
            internal_logger.debug("IPython détecté")
            return True
        import builtins
        if hasattr(builtins, '__IPYTHON__'):
            internal_logger.debug("IPython détecté via __IPYTHON__")
            return True
    except Exception:
        pass

    # Méthode 5: Vérifier si la variable d'environnement FORCE_DEBUG_MODE est définie
    if os.environ.get('FORCE_DEBUG_MODE'):
        internal_logger.debug("Mode débogueur forcé via FORCE_DEBUG_MODE")
        return True

    return False


class ProgressTracker:
    """Gestionnaire centralisé pour le suivi de progression avec cohérence garantie."""

    def __init__(self):
        self._bars: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._last_updates: Dict[str, float] = {}

    def create_progress(self, bar_id: str, total_steps: int, description: str = "") -> bool:
        """Crée une nouvelle barre de progression."""
        with self._lock:
            if bar_id in self._bars:
                internal_logger.warning(f"Barre de progression {bar_id} existe déjà, réinitialisation")

            self._bars[bar_id] = {
                "total_steps": max(1, total_steps),
                "current_step": 0,
                "description": description,
                "created_at": time.monotonic(),
                "last_update": time.monotonic()
            }
            internal_logger.debug(f"Barre de progression créée: {bar_id} ({total_steps} étapes)")
            return True

    def update_progress(self, bar_id: str, current_step: Optional[int] = None,
                       advance: int = 1, new_total: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Met à jour une barre de progression avec vérifications de cohérence."""
        with self._lock:
            if bar_id not in self._bars:
                internal_logger.warning(f"Tentative de mise à jour d'une barre inexistante: {bar_id}")
                return None

            bar_data = self._bars[bar_id]

            # Gérer le changement de total_steps
            if new_total is not None and new_total != bar_data["total_steps"]:
                internal_logger.debug(f"Changement total_steps pour {bar_id}: {bar_data['total_steps']} -> {new_total}")
                bar_data["total_steps"] = max(1, new_total)
                # Ajuster current_step si nécessaire
                if bar_data["current_step"] > bar_data["total_steps"]:
                    bar_data["current_step"] = bar_data["total_steps"]

            # Mettre à jour current_step
            if current_step is not None:
                bar_data["current_step"] = max(0, min(current_step, bar_data["total_steps"]))
            else:
                bar_data["current_step"] = max(0, min(bar_data["current_step"] + advance, bar_data["total_steps"]))

            bar_data["last_update"] = time.monotonic()

            # Calculer le pourcentage de manière cohérente
            percentage = (bar_data["current_step"] / bar_data["total_steps"]) * 100.0

            return {
                "id": bar_id,
                "current_step": bar_data["current_step"],
                "total_steps": bar_data["total_steps"],
                "percentage": percentage,
                "description": bar_data["description"]
            }

    def get_progress(self, bar_id: str) -> Optional[Dict[str, Any]]:
        """Récupère l'état actuel d'une barre de progression."""
        with self._lock:
            if bar_id not in self._bars:
                return None

            bar_data = self._bars[bar_id]
            percentage = (bar_data["current_step"] / bar_data["total_steps"]) * 100.0

            return {
                "id": bar_id,
                "current_step": bar_data["current_step"],
                "total_steps": bar_data["total_steps"],
                "percentage": percentage,
                "description": bar_data["description"]
            }

    def should_throttle_update(self, bar_id: str, throttle_interval: float = 0.05) -> bool:
        """Détermine si une mise à jour doit être throttlée."""
        now = time.monotonic()
        last_time = self._last_updates.get(bar_id, 0.0)

        if now - last_time < throttle_interval:
            return True

        self._last_updates[bar_id] = now
        return False

    def remove_progress(self, bar_id: str) -> bool:
        """Supprime une barre de progression."""
        with self._lock:
            if bar_id in self._bars:
                del self._bars[bar_id]
                if bar_id in self._last_updates:
                    del self._last_updates[bar_id]
                internal_logger.debug(f"Barre de progression supprimée: {bar_id}")
                return True
            return False


class PluginLogger:
    """
    Gère la journalisation standardisée et les barres de progression
    pour les plugins avec cohérence améliorée.
    """

    def __init__(self, plugin_name: Optional[str] = None,
                 instance_id: Optional[Union[str, int]] = None,
                 text_mode: bool = False,
                 debug_mode: bool = False,
                 ssh_mode: bool = False,
                 debugger_mode: Optional[bool] = None,
                 bar_width: int = 20):
        """
        Initialise le logger avec gestionnaire de progression centralisé.
        """
        self.plugin_name = plugin_name
        self.instance_id = instance_id
        self.debug_mode = debug_mode
        self.ssh_mode = ssh_mode
        self.bar_width = max(5, bar_width)
        self.text_mode = text_mode

        # Auto-détection du mode debugger
        if debugger_mode is None:
            self.debugger_mode = is_debugger_active()
        else:
            self.debugger_mode = debugger_mode

        # Forcer mode texte si debugger actif pour éviter les blocages
        if self.debugger_mode and not self.text_mode:
            internal_logger.info("Mode débogueur détecté, activation du mode synchrone")
            self.text_mode = True

        # Détection auto mode texte si pas SSH et TTY
        if not self.text_mode and not self.ssh_mode and sys.stdout.isatty():
            if not os.environ.get("TEXTUAL_APP"):
                self.text_mode = True

        # Gestionnaire de progression centralisé
        self.progress_tracker = ProgressTracker()

        # Barres numériques (pourcentage, pour JSONL)
        self.default_pb_id = self._generate_default_pb_id()

        # Barres visuelles (texte)
        self.bars: Dict[str, Dict[str, Any]] = {}
        self.use_visual_bars = True
        self.default_filled_char = "■"
        self.default_empty_char = "□"

        # Fichiers de logs
        self.log_file: Optional[str] = None
        self.init_logs()

        # Verrou pour la synchronisation des écritures
        self._write_lock = threading.RLock()

        # Anti-duplication
        self._seen_messages: Dict[tuple, tuple] = {}
        self._seen_messages_maxlen = 50

        # Throttling unifié
        self._progress_throttle = 0.05 if not self.debug_mode else 0.01

        # File d'attente pour le traitement chronologique
        self._message_queue: queue.Queue = queue.Queue()
        self._running = True
        self._message_thread: Optional[threading.Thread] = None
        self._message_counter = 0
        self._message_counter_lock = threading.Lock()

        # Démarrer le thread de traitement si pas en mode débogueur
        if not self.debugger_mode:
            self._message_thread = threading.Thread(
                target=self._process_message_queue,
                daemon=True
            )
            self._message_thread.start()

        internal_logger.info(f"PluginLogger initialisé: {plugin_name}, debugger={self.debugger_mode}")

    def _generate_default_pb_id(self) -> str:
        """Génère un ID par défaut prévisible pour la barre de progression."""
        if self.plugin_name and self.instance_id:
            return f"pb_{self.plugin_name}_{self.instance_id}_main"
        else:
            return f"pb_default_{int(time.time())}"

    def init_logs(self, log_levels: Optional[Dict[str, str]] = None):
        """Initialise le chemin du fichier log."""
        if self.plugin_name is None or self.instance_id is None:
            internal_logger.debug("Plugin name ou ID manquant, initialisation logs ignorée")
            return

        # Déterminer le répertoire des logs
        env_log_dir = os.environ.get('PCUTILS_LOG_DIR')
        log_dir_path: Optional[Path] = None

        if env_log_dir and os.path.isdir(env_log_dir):
            log_dir_path = Path(env_log_dir)
        elif self.ssh_mode:
            log_dir_path = Path(tempfile.gettempdir()) / 'pcUtils_logs'
        else:
            try:
                project_root = Path(__file__).resolve().parents[2]
                log_dir_path = project_root / "logs"
            except (NameError, IndexError):
                log_dir_path = Path("logs")

        if log_dir_path:
            try:
                log_dir_path.mkdir(parents=True, exist_ok=True)

                if self.ssh_mode or (hasattr(os, 'geteuid') and os.geteuid() == 0):
                    try:
                        os.chmod(log_dir_path, 0o777)
                    except Exception:
                        pass

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_filename = f"plugin_{self.plugin_name}_{self.instance_id}_{timestamp}.jsonl"
                self.log_file = str(log_dir_path / log_filename)

                if self.ssh_mode:
                    log_path_msg = {"level": "info", "message": f"LOG_FILE:{self.log_file}"}
                    print(json.dumps(log_path_msg), flush=True)

            except Exception as e:
                internal_logger.error(f"Erreur config logs: {e}")
                self.log_file = None

    def _get_next_message_id_and_time(self) -> Tuple[int, float]:
        """Obtient un ID unique et le timestamp pour un message."""
        with self._message_counter_lock:
            self._message_counter += 1
            return self._message_counter, time.monotonic()

    def _process_message_queue(self):
        """Traite les messages en file d'attente de manière chronologique."""
        internal_logger.debug("Thread de traitement des messages démarré")

        while self._running:
            try:
                batch = []
                # Attendre le premier message
                try:
                    first_message = self._message_queue.get(timeout=0.05)
                    batch.append(first_message)
                    self._message_queue.task_done()
                except queue.Empty:
                    continue

                # Collecter d'autres messages disponibles
                max_batch_time = time.time() + 0.01
                while len(batch) < 10 and time.time() < max_batch_time:
                    try:
                        message = self._message_queue.get_nowait()
                        batch.append(message)
                        self._message_queue.task_done()
                    except queue.Empty:
                        break

                # Trier par ID chronologique
                batch.sort(key=lambda x: x[4])

                # Traiter le lot
                if batch:
                    self._process_message_batch(batch)

            except Exception as e:
                internal_logger.error(f"Erreur traitement queue: {e}")
                time.sleep(0.1)

    def _process_message_batch(self, messages):
        """Traite un lot de messages."""
        log_lines_to_write = []
        console_outputs = []

        for level, message, target_ip, _, msg_id, _ in messages:
            # Préparer l'entrée pour le fichier log
            if self.log_file:
                log_entry_file = {
                    "timestamp": datetime.now().isoformat(),
                    "level": level.lower(),
                    "plugin_name": self.plugin_name,
                    "instance_id": self.instance_id,
                    "target_ip": target_ip,
                    "message_id": msg_id,
                    "message": message
                }
                log_entry_file = {k: v for k, v in log_entry_file.items() if v is not None}
                try:
                    log_lines_to_write.append(json.dumps(log_entry_file, ensure_ascii=False))
                except Exception as json_err:
                    internal_logger.warning(f"Erreur JSON log file: {json_err}")

            # Préparer la sortie console
            if self.text_mode:
                # Mode texte avec couleurs
                if level.lower() in ["progress", "progress-text"]:
                    continue  # Géré par _emit_bar

                timestamp_txt = datetime.now().strftime("%H:%M:%S")
                color = ANSI_COLORS.get(level.lower(), ANSI_COLORS["info"])
                target_info = f"{ANSI_COLORS['target_ip']}@{target_ip}{ANSI_COLORS['reset']} " if target_ip else ""

                msg_str = str(message)
                console_line = (
                    f"{ANSI_COLORS['timestamp']}{timestamp_txt}{ANSI_COLORS['reset']} "
                    f"{color}[{level.upper():<7}]{ANSI_COLORS['reset']} "
                    f"{target_info}{msg_str}"
                )
                console_outputs.append(console_line)
            else:
                # Mode JSONL pour stdout
                log_entry_stdout = {
                    "timestamp": datetime.now().isoformat(),
                    "level": level.lower(),
                    "plugin_name": self.plugin_name,
                    "instance_id": self.instance_id,
                    "target_ip": target_ip,
                    "message": message
                }
                log_entry_stdout = {k: v for k, v in log_entry_stdout.items() if v is not None}
                try:
                    console_outputs.append(json.dumps(log_entry_stdout, ensure_ascii=False))
                except Exception as json_err:
                    internal_logger.warning(f"Erreur JSON stdout: {json_err}")

        # Écrire les sorties avec verrou
        with self._write_lock:
            # Fichier log
            if self.log_file and log_lines_to_write:
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        for line in log_lines_to_write:
                            f.write(line + '\n')
                except Exception as e:
                    internal_logger.error(f"Erreur écriture log: {e}")

            # Console
            if console_outputs:
                try:
                    output_str = "\n".join(console_outputs) + "\n"
                    sys.stdout.write(output_str)
                    sys.stdout.flush()
                except Exception as e:
                    internal_logger.error(f"Erreur écriture stdout: {e}")

    def _emit_log(self, level: str, message: Any, target_ip: Optional[str] = None,
                  force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        """Met un message dans la file d'attente pour traitement."""
        # Redirection de niveau si définie
        override_level = (log_levels or {}).get(level, level)

        known_levels = {"info", "warning", "error", "success", "debug", "start", "end", "progress", "progress-text"}
        if override_level not in known_levels:
            return

        msg_id, timestamp = self._get_next_message_id_and_time()

        # Traitement immédiat en mode debug
        if self.debugger_mode or force_flush:
            batch = [(override_level, message, target_ip, True, msg_id, timestamp)]
            self._process_message_batch(batch)
            return

        # Gestion de la duplication
        is_progress = override_level in ["progress", "progress-text"]
        allow_dedup = not is_progress and isinstance(message, str) and not self.debug_mode

        if allow_dedup:
            message_key = (override_level, message, target_ip)
            now = time.monotonic()
            last_seen_time, count = self._seen_messages.get(message_key, (0.0, 0))
            if now - last_seen_time < 1.0 and count >= 3:
                self._seen_messages[message_key] = (now, count + 1)
                return
            self._seen_messages[message_key] = (now, count + 1)

        # Mise en file d'attente
        self._message_queue.put((override_level, message, target_ip, force_flush, msg_id, timestamp))

    # Méthodes de logging public
    def info(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("info", message, target_ip, force_flush, log_levels)

    def warning(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("warning", message, target_ip, force_flush, log_levels)

    def error(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("error", message, target_ip, force_flush, log_levels)

    def success(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("success", message, target_ip, force_flush, log_levels)

    def debug(self, message: str, target_ip: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        if self.debug_mode:
            self._emit_log("debug", message, target_ip)

    def start(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("start", message, target_ip, force_flush)

    def end(self, message: str, target_ip: Optional[str] = None, force_flush: bool = False, log_levels: Optional[Dict[str, str]] = None):
        self._emit_log("end", message, target_ip, force_flush)

    # --- Gestion Progression Numérique (JSONL) ---

    def set_total_steps(self, total: int, pb_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        """Définit le nombre total d'étapes avec gestion cohérente."""
        bar_id = pb_id or self.default_pb_id

        # Utiliser le gestionnaire centralisé
        success = self.progress_tracker.create_progress(bar_id, total)
        if success:
            internal_logger.debug(f"Progression numérique '{bar_id}' initialisée: {total} étapes")
            self._emit_progress_update(bar_id)

    def next_step(self, pb_id: Optional[str] = None, current_step: Optional[int] = None, log_levels: Optional[Dict[str, str]] = None) -> int:
        """Avance la progression numérique avec cohérence garantie."""
        bar_id = pb_id or self.default_pb_id

        # Utiliser le gestionnaire centralisé
        progress_data = self.progress_tracker.update_progress(
            bar_id, current_step=current_step, advance=1 if current_step is None else 0
        )

        if progress_data is None:
            internal_logger.warning(f"Progression numérique inconnue: {bar_id}")
            return 0

        current = progress_data["current_step"]

        # Appliquer le throttling
        if not self.debug_mode and self.progress_tracker.should_throttle_update(bar_id, self._progress_throttle):
            return current

        # Émettre la mise à jour
        self._emit_progress_update(bar_id)
        return current

    def _emit_progress_update(self, bar_id: str):
        """Émet le message JSONL pour la progression numérique."""
        progress_data = self.progress_tracker.get_progress(bar_id)
        if progress_data is None or self.text_mode:
            return

        progress_message = {
            "type": "progress",
            "data": {
                "id": bar_id,
                "percentage": progress_data["percentage"] / 100.0,  # Normaliser 0-1
                "current_step": progress_data["current_step"],
                "total_steps": progress_data["total_steps"]
            }
        }
        self._emit_log("progress", progress_message)

    # --- Gestion Progression Visuelle (Texte) ---

    def enable_visual_bars(self, enable: bool = True, log_levels: Optional[Dict[str, str]] = None):
        """Active/désactive les barres visuelles."""
        self.use_visual_bars = enable

    def create_bar(self, id: str, total: int = 1, description: str = "",
                   pre_text: Optional[str] = None, post_text: str = "",
                   color: str = "blue", filled_char: Optional[str] = None,
                   empty_char: Optional[str] = None, bar_width: Optional[int] = None,
                   log_levels: Optional[Dict[str, str]] = None):
        """Crée une barre de progression visuelle."""
        if not self.use_visual_bars:
            return

        width = bar_width if bar_width is not None else self.bar_width
        f_char = filled_char or self.default_filled_char
        e_char = empty_char or self.default_empty_char
        final_pre_text = pre_text if pre_text is not None else description

        self.bars[id] = {
            "total_steps": max(1, total),
            "current_step": 0,
            "pre_text": final_pre_text,
            "post_text": post_text,
            "color": color,
            "filled_char": f_char,
            "empty_char": e_char,
            "bar_width": width,
            "_last_line_len": 0
        }

        # Afficher la barre initiale
        self._emit_bar(id, 0)

    def update_bar(self, id: str, current: int, total: Optional[int] = None,
                   pre_text: Optional[str] = None, post_text: Optional[str] = None,
                   color: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None):
        """Met à jour une barre visuelle avec throttling."""
        if not self.use_visual_bars or id not in self.bars:
            return

        # Appliquer le throttling
        if not self.debug_mode and self.progress_tracker.should_throttle_update(f"textbar_{id}", self._progress_throttle):
            return

        # Mettre à jour les données
        bar_data = self.bars[id]
        bar_data["current_step"] = current
        if total is not None:
            bar_data["total_steps"] = max(1, total)
        if pre_text is not None:
            bar_data["pre_text"] = pre_text
        if post_text is not None:
            bar_data["post_text"] = post_text
        if color is not None:
            bar_data["color"] = color

        # Émettre la mise à jour
        self._emit_bar(id, current)

    def next_bar(self, id: str, current_step: Optional[int] = None,
                 pre_text: Optional[str] = None, post_text: Optional[str] = None,
                 log_levels: Optional[Dict[str, str]] = None) -> int:
        """Avance une barre visuelle."""
        if not self.use_visual_bars or id not in self.bars:
            return 0

        bar_data = self.bars[id]
        total = bar_data["total_steps"]

        if current_step is not None:
            bar_data["current_step"] = min(max(0, current_step), total)
        else:
            bar_data["current_step"] = min(bar_data["current_step"] + 1, total)

        if pre_text is not None:
            bar_data["pre_text"] = pre_text
        if post_text is not None:
            bar_data["post_text"] = post_text

        current = bar_data["current_step"]

        # Appliquer le throttling
        if not self.debug_mode and self.progress_tracker.should_throttle_update(f"textbar_{id}", self._progress_throttle):
            return current

        self._emit_bar(id, current)
        return current

    def _emit_bar(self, id: str, current: int):
        """Émet le message pour la barre visuelle avec cohérence garantie."""
        if id not in self.bars:
            return

        bar_data = self.bars[id]
        total = bar_data["total_steps"]
        current_clamped = min(max(0, current), total)
        width = bar_data["bar_width"]

        # Calcul cohérent du pourcentage
        percentage = int((current_clamped / total) * 100) if total > 0 else 100
        filled_width = int(width * current_clamped / total) if total > 0 else width
        filled_width = min(max(0, filled_width), width)

        bar_str = (bar_data["filled_char"] * filled_width +
                   bar_data["empty_char"] * (width - filled_width))

        if self.text_mode:
            with self._write_lock:
                try:
                    timestamp_txt = datetime.now().strftime("%H:%M:%S")
                    level_txt = "[PROGRES]"
                    bar_color_ansi = BAR_COLORS.get(bar_data["color"], ANSI_COLORS["progress_bar"])

                    prefix = (
                        f"{ANSI_COLORS['timestamp']}{timestamp_txt}{ANSI_COLORS['reset']} "
                        f"{ANSI_COLORS['progress_bar']}{level_txt}{ANSI_COLORS['reset']} "
                    )
                    bar_content = (
                        f"{ANSI_COLORS['progress_text']}{bar_data['pre_text']} {ANSI_COLORS['reset']}"
                        f"[{bar_color_ansi}{bar_str}{ANSI_COLORS['reset']}]"
                        f"{ANSI_COLORS['progress_text']} {percentage}% {bar_data['post_text']}{ANSI_COLORS['reset']}"
                    )
                    bar_display = prefix + bar_content

                    visible_len = len(f"{timestamp_txt} {level_txt} {bar_data['pre_text']} [{bar_str}] {percentage}% {bar_data['post_text']}")
                    padding = " " * (bar_data.get("_last_line_len", 0) - visible_len)

                    sys.stdout.write(f"\r{bar_display}{padding}")
                    sys.stdout.flush()
                    bar_data["_last_line_len"] = visible_len
                except Exception as e:
                    internal_logger.error(f"Erreur écriture barre texte: {e}")
        else:
            # Mode JSONL avec données cohérentes
            progress_message = {
                "type": "progress-text",
                "data": {
                    "id": id,
                    "percentage": percentage,
                    "current_step": current_clamped,
                    "total_steps": total,
                    "status": "running",
                    "pre_text": bar_data["pre_text"],
                    "post_text": f"{percentage}%",  # Garantir cohérence
                    "color": bar_data["color"],
                    "filled_char": bar_data["filled_char"],
                    "empty_char": bar_data["empty_char"],
                    "bar": bar_str
                }
            }
            self._emit_log("progress-text", progress_message)

    def delete_bar(self, id: str, log_levels: Optional[Dict[str, str]] = None):
        """Supprime une barre de progression visuelle."""
        if not self.use_visual_bars or id not in self.bars:
            return

        bar_data = self.bars.pop(id)

        if self.text_mode:
            with self._write_lock:
                try:
                    last_len = bar_data.get("_last_line_len", 0)
                    sys.stdout.write(f"\r{' ' * last_len}\r\n")
                    sys.stdout.flush()
                except Exception as e:
                    internal_logger.error(f"Erreur nettoyage barre: {e}")
        else:
            stop_message = {
                "type": "progress-text",
                "data": {
                    "id": id,
                    "status": "stop",
                    "pre_text": bar_data.get("pre_text", "Tâche"),
                    "percentage": 100
                }
            }
            self._emit_log("progress-text", stop_message, force_flush=True)

    def flush(self, log_levels: Optional[Dict[str, str]] = None):
        """Force le traitement immédiat des messages en attente."""
        if self.debugger_mode:
            return

        try:
            all_messages = []
            while not self._message_queue.empty():
                try:
                    all_messages.append(self._message_queue.get_nowait())
                    self._message_queue.task_done()
                except queue.Empty:
                    break

            if all_messages:
                all_messages.sort(key=lambda x: x[4])
                self._process_message_batch(all_messages)
            else:
                with self._write_lock:
                    try:
                        sys.stdout.flush()
                    except Exception:
                        pass
        except Exception as e:
            internal_logger.error(f"Erreur lors du flush: {e}")

    def shutdown(self, log_levels: Optional[Dict[str, str]] = None):
        """Arrête proprement le thread de traitement."""
        if self.debugger_mode or not self._running:
            return

        self._running = False
        self.flush()

        if self._message_thread and self._message_thread.is_alive():
            self._message_thread.join(timeout=0.2)

    def __del__(self):
        """Nettoyage lors de la destruction."""
        try:
            if hasattr(self, '_running') and self._running:
                self.shutdown()
        except Exception:
            pass
