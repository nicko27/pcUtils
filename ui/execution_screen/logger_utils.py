#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitaires de journalisation pour le module d'exécution.
Version optimisée pour améliorer la réactivité de l'interface et
le traitement des messages en temps réel.
"""

import time
import threading
import json
import asyncio
import sys
import logging
import traceback
from typing import Dict, Any, Optional, Union, List, Tuple, Deque, Set, Callable
from collections import deque
import os


# Configuration du logger interne
logger = logging.getLogger("logger_utils")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Détecter si nous sommes dans un environnement Textual
try:
    from textual.widgets import Static
    from textual.containers import ScrollableContainer
    # Importer ProgressBar si votre PluginContainer l'utilise directement
    # from textual.widgets import ProgressBar
    TEXTUAL_AVAILABLE = True
    logger.debug("Mode Textual détecté")
except ImportError:
    TEXTUAL_AVAILABLE = False
    logger.debug("Mode texte (sans Textual)")
    # Définir des classes factices si Textual n'est pas disponible
    class Static:
        def update(self, *args, **kwargs):
            pass

        @property
        def renderable(self):
            return ""

    class ScrollableContainer:
        def scroll_end(self, *args, **kwargs):
            pass

        def query_one(self, *args, **kwargs):
            return None

# Imports internes - avec gestion d'erreur pour permettre l'usage autonome
try:
    from ..utils.messaging import Message, MessageType, MessageFormatter
except ImportError:
    try:
        from utils.messaging import Message, MessageType, MessageFormatter
    except ImportError:
        # Classes de fallback si les modules ne sont pas disponibles
        logger.warning("Import des modules de messaging échoué, utilisation de classes de secours")

        class MessageType:
            """Version simplifiée pour fonctionnement en mode autonome"""
            INFO = "info"
            WARNING = "warning"
            ERROR = "error"
            SUCCESS = "success"
            DEBUG = "debug"
            PROGRESS = "progress"
            PROGRESS_TEXT = "progress-text"
            START = "start"
            END = "end"
            UNKNOWN = "unknown"

        class Message:
            """Version simplifiée pour fonctionnement en mode autonome"""
            def __init__(self, type=MessageType.INFO, content="", source=None,
                        target_ip=None, progress=None, step=None, total_steps=None,
                        data=None, instance_id=None):
                self.type = type
                self.content = content
                self.source = source
                self.target_ip = target_ip
                self.progress = progress
                self.step = step
                self.total_steps = total_steps
                self.data = data or {}
                self.instance_id = instance_id

            def to_string(self):
                return f"[{self.type}] {self.content}"

        class MessageFormatter:
            """Version simplifiée pour fonctionnement en mode autonome"""
            @staticmethod
            def format_for_rich_textual(message):
                return f"[{message.type}] {message.content}"

            @staticmethod
            def format_for_log_file(message):
                return f"{message.content}"

# Détection du mode débogueur
def is_debugger_active() -> bool:
    """Détecte si un débogueur est actif - version robuste."""
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

    # Méthode 4: Vérifier IPython
    try:
        import builtins
        return hasattr(builtins, '__IPYTHON__')
    except ImportError:
        pass

    return False


class LoggerUtils:
    """
    Classe utilitaire optimisée pour la gestion des logs dans
    l'interface Textual ou en mode terminal.
    """

    # Files d'attente et de déduplication
    _pending_messages: Deque[Message] = deque(maxlen=500)
    _message_cache: Dict[str, Tuple[float, int]] = {}
    _seen_messages_maxlen = 200

    # État et configuration
    _logs_timer_running = False
    _last_flush_time = 0.0
    _batch_size = 10 if not is_debugger_active() else 3
    _batch_time = 0.1 if not is_debugger_active() else 0.02
    _refresh_scheduled = False
    _refresh_lock = threading.RLock()
    _output_lock = threading.RLock()

    # Compteur pour générer des IDs uniques pour les messages
    _message_counter = 0
    _counter_lock = threading.RLock()

    @classmethod
    def get_next_message_id(cls) -> int:
        """Génère un ID unique pour chaque message."""
        with cls._counter_lock:
            cls._message_counter += 1
            return cls._message_counter

    @staticmethod
    async def _periodic_logs_display(app):
        """
        Processus asynchrone pour afficher périodiquement les messages en attente.
        Cette méthode s'exécute en continu en arrière-plan.

        Args:
            app: L'application textual
        """
        if not TEXTUAL_AVAILABLE:
            logger.warning("Tentative de lancer _periodic_logs_display sans Textual")
            return

        try:
            LoggerUtils._logs_timer_running = True
            last_flush_time = time.monotonic()
            logger.debug("Démarrage de la boucle de traitement des logs")

            while LoggerUtils._logs_timer_running:
                try:
                    current_time = time.monotonic()
                    queue_size = len(LoggerUtils._pending_messages)

                    # Calculer si un flush est nécessaire
                    should_flush = queue_size >= LoggerUtils._batch_size
                    time_to_flush = (current_time - last_flush_time) >= LoggerUtils._batch_time
                    force_flush = (current_time - last_flush_time) >= 0.5  # Flush périodique forcé

                    if (queue_size > 0 and (should_flush or time_to_flush)) or force_flush:
                        try:
                            await LoggerUtils.flush_pending_messages(app)
                            last_flush_time = time.monotonic()
                        except Exception as e:
                            logger.error(f"Erreur pendant flush périodique: {e}", exc_info=True)
                            # Éviter les boucles d'erreurs rapides
                            await asyncio.sleep(0.1)
                            # Réinitialiser en cas d'erreur
                            LoggerUtils._pending_messages.clear()
                            last_flush_time = time.monotonic()

                    # Pause courte pour libérer la boucle asyncio
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    logger.info("Tâche périodique de logs annulée")
                    raise
                except Exception as e:
                    logger.error(f"Erreur dans la boucle de logs: {e}", exc_info=True)
                    await asyncio.sleep(0.1)  # Éviter les boucles d'erreurs rapides

        except Exception as e:
            logger.error(f"Erreur fatale dans le traitement périodique des logs: {e}",
                         exc_info=True)
        finally:
            LoggerUtils._logs_timer_running = False
            logger.info("Boucle de traitement des logs terminée")

    @classmethod
    async def start_logs_timer(cls, app):
        """
        Démarre le timer d'affichage des logs en arrière-plan.

        Args:
            app: L'application textual
        """
        if not TEXTUAL_AVAILABLE:
            logger.warning("Impossible de démarrer le timer sans Textual")
            return

        # Éviter de démarrer plusieurs timers
        if cls._logs_timer_running:
            logger.debug("Timer de logs déjà en cours")
            return

        try:
            # Créer une nouvelle tâche pour le traitement périodique
            task = asyncio.create_task(cls._periodic_logs_display(app))
            # Ignorer les erreurs à la fin pour éviter les crashs
            task.add_done_callback(lambda t: t.exception() if t.done() and not t.cancelled() else None)
            logger.debug("Timer de logs démarré avec succès")
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du timer: {e}", exc_info=True)

    @classmethod
    async def stop_logs_timer(cls):
        """Arrête le timer d'affichage des logs."""
        logger.info("Arrêt du timer de logs demandé")
        cls._logs_timer_running = False
        # Assurer un dernier flush
        try:
            if hasattr(cls, '_app') and cls._app:
                await cls.flush_pending_messages(cls._app)
        except Exception as e:
            logger.error(f"Erreur lors du dernier flush: {e}")

    @classmethod
    def _is_duplicate_message(cls, message: Message) -> bool:
        """
        Vérifie si un message est un doublon récent.

        Args:
            message: Le message à vérifier

        Returns:
            bool: True si c'est un doublon récent à ignorer
        """
        # Ne pas dédupliquer certains types de messages
        if not isinstance(message, Message):
            return False

        if message.type in [MessageType.PROGRESS, MessageType.PROGRESS_TEXT,
                           MessageType.ERROR, MessageType.END]:
            return False

        if not isinstance(message.content, str):
            return False

        # Créer une clé unique basée sur les attributs du message
        try:
            message_key = f"{message.type}:{message.content}:{message.source}:{message.target_ip}"

            now = time.monotonic()
            last_time, count = cls._message_cache.get(message_key, (0.0, 0))

            # Ignorer les messages répétés trop fréquemment (moins de 1 seconde d'intervalle)
            if now - last_time < 1.0 and count >= 3:
                cls._message_cache[message_key] = (now, count + 1)

                # Générer occasionnellement un message résumé pour les messages répétés
                if count % 20 == 0:
                    logger.debug(f"Message répété {count} fois: {message.content[:50]}...")
                return True

            # Mettre à jour le cache
            cls._message_cache[message_key] = (now, count + 1)

            # Limiter la taille du cache
            if len(cls._message_cache) > cls._seen_messages_maxlen:
                try:
                    # Supprimer les entrées les plus anciennes
                    oldest_keys = sorted(cls._message_cache.keys(),
                                       key=lambda k: cls._message_cache[k][0])[:50]
                    for k in oldest_keys:
                        cls._message_cache.pop(k, None)
                except Exception:
                    # En cas d'erreur, vider complètement le cache
                    cls._message_cache.clear()
        except Exception as e:
            logger.debug(f"Erreur dans la déduplication: {e}")

        return False

    @classmethod
    async def _update_plugin_widget_display(cls, app, message: Message) -> bool:
        """
        Met à jour l'affichage d'un widget de plugin avec les infos de progression.

        Args:
            app: L'application Textual
            message: Le message contenant les informations de progression

        Returns:
            bool: True si la mise à jour a réussi
        """
        if not TEXTUAL_AVAILABLE:
            return False

        try:
            # Trouver le widget correspondant au plugin
            plugin_widget = await cls._find_plugin_widget(app, message)
            if not plugin_widget:
                return False

            # Vérifier que le widget a les méthodes nécessaires
            if not hasattr(plugin_widget, 'update_progress'):
                logger.debug(f"Widget trouvé mais sans méthode update_progress")
                return False

            # Extraire les informations de progression
            if message.type == MessageType.PROGRESS:
                # Progression numérique simple
                percent = 0
                if hasattr(message, 'progress') and message.progress is not None:
                    percent = max(0, min(100, float(message.progress) * 100))

                status_text = ""
                if hasattr(message, 'step') and hasattr(message, 'total_steps'):
                    if message.step is not None and message.total_steps is not None:
                        status_text = f"Étape {message.step}/{message.total_steps}"
                elif percent > 0:
                    status_text = f"{int(percent)}%"

                # Appel à la méthode de mise à jour
                try:
                    if asyncio.iscoroutinefunction(plugin_widget.update_progress):
                        await plugin_widget.update_progress(percent / 100.0, status_text)
                    else:
                        plugin_widget.update_progress(percent / 100.0, status_text)
                    return True
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour de progression: {e}")
                    return False

            elif message.type == MessageType.PROGRESS_TEXT:
                # Progression avec texte personnalisé
                if not hasattr(message, 'data') or not isinstance(message.data, dict):
                    return False

                data = message.data
                percent = float(data.get("percentage", 0))
                status = data.get("status", "running")

                if status == "stop":
                    # Barre terminée
                    status_text = f"{data.get('pre_text', 'Terminé')}"
                    percent = 100.0
                else:
                    # Barre en cours
                    pre_text = data.get("pre_text", "")
                    post_text = data.get("post_text", "")
                    if pre_text and post_text:
                        status_text = f"{pre_text}: {post_text}"
                    elif pre_text:
                        status_text = pre_text
                    elif post_text:
                        status_text = post_text
                    else:
                        status_text = f"{int(percent)}%"

                # Appel à la méthode de mise à jour
                try:
                    if asyncio.iscoroutinefunction(plugin_widget.update_progress):
                        await plugin_widget.update_progress(percent / 100.0, status_text)
                    else:
                        plugin_widget.update_progress(percent / 100.0, status_text)
                    return True
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour de progression texte: {e}")
                    return False

            return False
        except Exception as e:
            logger.error(f"Erreur dans _update_plugin_widget_display: {e}", exc_info=True)
            return False

    @classmethod
    async def _find_plugin_widget(cls, app, message: Message) -> Optional[Any]:
        """
        Trouve le widget du plugin correspondant au message.

        Args:
            app: L'application Textual
            message: Le message contenant les informations de plugin

        Returns:
            Le widget du plugin ou None si non trouvé
        """
        if not TEXTUAL_AVAILABLE:
            return None

        try:
            # Vérifier que le message contient les informations nécessaires
            if not hasattr(message, 'source') or not hasattr(message, 'instance_id'):
                return None

            if message.source is None:
                return None

            # Essayer de trouver le widget dans l'attribut plugins de l'app
            target_plugin_id = f"{message.source}_{message.instance_id}"
            if hasattr(app, 'plugins') and isinstance(app.plugins, dict):
                # Chercher par ID dans le dictionnaire de plugins
                for plugin_id, widget in app.plugins.items():
                    if target_plugin_id in str(plugin_id) and hasattr(widget, 'update_progress'):
                        return widget

            # Essayer avec une recherche par requête (plus lent mais plus robuste)
            try:
                # Trouver tous les widgets de type PluginContainer
                for widget in app.query("PluginContainer"):
                    if hasattr(widget, 'plugin_name') and hasattr(widget, 'instance_id'):
                        if (str(widget.plugin_name) == str(message.source) and
                            str(widget.instance_id) == str(message.instance_id)):
                            if hasattr(widget, 'update_progress'):
                                return widget
            except Exception as e:
                logger.debug(f"Erreur recherche par query: {e}")

            # Essayer de chercher par ID directement
            try:
                plugin_id = f"plugin-{message.source}_{message.instance_id}"
                widget = app.query_one(f"#{plugin_id}")
                if widget and hasattr(widget, 'update_progress'):
                    return widget
            except Exception:
                pass

            # Dernière tentative: chercher par attribut target_ip
            if hasattr(message, 'target_ip') and message.target_ip:
                for widget in app.query("*"):
                    if (hasattr(widget, 'target_ip') and
                        widget.target_ip == message.target_ip and
                        hasattr(widget, 'update_progress')):
                        return widget

        except Exception as e:
            logger.debug(f"Erreur lors de la recherche du widget: {e}")

        return None

    @classmethod
    async def process_output_line(cls, app, line: str, plugin_widget=None,
                                 target_ip: Optional[str] = None):
        """
        Traite une ligne de sortie (stdout/stderr) et l'affiche dans l'interface.

        Args:
            app: L'application Textual
            line: La ligne à traiter (texte brut ou JSON)
            plugin_widget: Le widget du plugin (optionnel, peut être détecté)
            target_ip: L'adresse IP cible (optionnel)
        """
        if not TEXTUAL_AVAILABLE or not line:
            return

        # Stocker une référence à l'app pour le flush final
        cls._app = app

        # Détecter si on est sur l'écran d'exécution
        try:
            screen_name = app.screen.__class__.__name__ if hasattr(app, 'screen') else "Unknown"
            needs_queue = "ExecutionScreen" not in screen_name
        except Exception:
            # En cas d'erreur, mettre en file d'attente par défaut
            needs_queue = True

        # Essayer de parser comme JSON
        message_obj: Optional[Message] = None
        try:
            if isinstance(line, str) and line.strip().startswith('{') and line.strip().endswith('}'):
                # Tenter de parser comme JSON
                try:
                    log_entry = json.loads(line)

                    # Construire un objet Message à partir du JSON
                    level = log_entry.get("level", "info").lower()
                    message_content = log_entry.get("message", "")
                    plugin_name = log_entry.get("plugin_name")
                    instance_id = log_entry.get("instance_id")

                    # Déterminer le type de message
                    if level == "progress":
                        message_type = MessageType.PROGRESS
                    elif level == "progress-text":
                        message_type = MessageType.PROGRESS_TEXT
                    elif level == "error":
                        message_type = MessageType.ERROR
                    elif level == "warning":
                        message_type = MessageType.WARNING
                    elif level == "success":
                        message_type = MessageType.SUCCESS
                    elif level == "debug":
                        message_type = MessageType.DEBUG
                    elif level == "start":
                        message_type = MessageType.START
                    elif level == "end":
                        message_type = MessageType.END
                    else:
                        message_type = MessageType.INFO

                    # Créer l'objet Message
                    message_obj = Message(
                        type=message_type,
                        content=message_content,
                        source=plugin_name,
                        instance_id=instance_id,
                        target_ip=target_ip
                    )

                    # Ajouter des attributs supplémentaires pour les barres de progression
                    if message_type == MessageType.PROGRESS and isinstance(message_content, dict):
                        data = message_content.get("data", {})
                        message_obj.progress = float(data.get("percentage", 0)) / 100
                        message_obj.step = data.get("current_step")
                        message_obj.total_steps = data.get("total_steps")
                    elif message_type == MessageType.PROGRESS_TEXT:
                        message_obj.data = message_content.get("data", {}) if isinstance(message_content, dict) else {}

                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                    # En cas d'erreur de parsing JSON, traiter comme du texte brut
                    message_obj = Message(
                        type=MessageType.INFO,
                        content=line,
                        target_ip=target_ip
                    )
            else:
                # Si ce n'est pas un JSON valide, traiter comme du texte brut
                message_obj = Message(
                    type=MessageType.INFO,
                    content=line,
                    target_ip=target_ip
                )

                # Détecter le type de message par des mots-clés
                line_lower = line.lower()
                if any(err in line_lower for err in ['error', 'erreur', 'failed', 'échec', 'traceback', 'exception']):
                    message_obj.type = MessageType.ERROR
                elif any(warn in line_lower for warn in ['warning', 'attention', 'avertissement']):
                    message_obj.type = MessageType.WARNING
                elif any(succ in line_lower for succ in ['success', 'succès', 'terminé', 'réussi']):
                    message_obj.type = MessageType.SUCCESS
        except Exception as e:
            # En cas d'erreur, créer un message d'erreur
            logger.error(f"Erreur traitement ligne: {e} - ligne: {line[:100]}", exc_info=True)
            message_obj = Message(
                type=MessageType.ERROR,
                content=f"Erreur de traitement: {str(e)}",
                target_ip=target_ip
            )

        # Traitement des messages de progression
        if message_obj and message_obj.type in [MessageType.PROGRESS, MessageType.PROGRESS_TEXT]:
            # Mettre à jour la barre de progression si possible
            if not needs_queue:
                try:
                    await cls._update_plugin_widget_display(app, message_obj)
                except Exception as e:
                    logger.error(f"Erreur mise à jour barre: {e}")

            # Ajouter à la file d'attente pour les barres en mode différé
            if needs_queue:
                queue = cls._pending_messages
                queue.append(message_obj)

            # Ne pas afficher les mises à jour de barres dans les logs textuels
            return

        # Pour les messages normaux
        if message_obj:
            # Soit ajouter à la file d'attente, soit afficher immédiatement
            if needs_queue:
                queue = cls._pending_messages
                queue.append(message_obj)
            else:
                await cls.display_message(app, message_obj)

    @classmethod
    async def display_message(cls, app, message_obj: Message):
        """
        Affiche un message dans le widget de logs.

        Args:
            app: L'application Textual
            message_obj: Le message à afficher
        """
        if not TEXTUAL_AVAILABLE:
            return

        try:
            # Ignorer les messages de progression
            if message_obj.type in [MessageType.PROGRESS, MessageType.PROGRESS_TEXT]:
                return

            # Vérifier la duplication pour les messages standards
            if cls._is_duplicate_message(message_obj):
                return

            # Formater le message
            formatted_message = ""
            try:
                formatted_message = MessageFormatter.format_for_rich_textual(message_obj)
            except Exception as e:
                logger.error(f"Erreur formatage message: {e}")
                formatted_message = f"[ERROR] Erreur formatage: {str(message_obj.content)}"

            if not formatted_message:
                return

            # Récupérer le widget de logs
            try:
                logs = app.query_one("#logs-text", Static)
                logs_container = app.query_one("#logs-container", ScrollableContainer)
            except Exception as e:
                # Si on ne trouve pas le widget, mettre en file d'attente
                logger.debug(f"Widget logs non trouvé: {e}")
                queue = cls._pending_messages
                queue.append(message_obj)
                return

            # Mettre à jour le contenu des logs
            try:
                with cls._output_lock:
                    current_text = logs.renderable if logs.renderable else ""
                    # Ajouter un saut de ligne si nécessaire
                    if current_text and not current_text.endswith("\n"):
                        current_text += "\n"
                    # Ajouter le nouveau message
                    logs.update(current_text + formatted_message)
                    # Faire défiler vers le bas
                    logs_container.scroll_end(animate=False)

                # Planifier un rafraîchissement
                if not cls._refresh_scheduled:
                    cls._refresh_scheduled = True
                    cls._schedule_refresh(app)
            except Exception as e:
                logger.error(f"Erreur mise à jour widget logs: {e}", exc_info=True)
                # En cas d'erreur, mettre en file d'attente
                queue = cls._pending_messages
                queue.append(message_obj)

        except Exception as e:
            logger.error(f"Erreur dans display_message: {e}", exc_info=True)

    @classmethod
    async def flush_pending_messages(cls, app):
        """
        Traite immédiatement tous les messages en attente.

        Args:
            app: L'application Textual
        """
        if not TEXTUAL_AVAILABLE:
            return

        try:
            # Vérifier que les widgets nécessaires existent
            try:
                logs = app.query_one("#logs-text", Static)
                logs_container = app.query_one("#logs-container", ScrollableContainer)
            except Exception:
                # Si les widgets ne sont pas disponibles, on ne peut pas flush
                return

            # Collecter les messages à traiter
            messages_to_process = []
            max_messages = 100  # Limite de sécurité pour éviter les surcharges d'UI

            # Ensuite les messages normaux
            try:
                while cls._pending_messages and len(messages_to_process) < max_messages:
                    messages_to_process.append(cls._pending_messages.popleft())
            except Exception as e:
                logger.error(f"Erreur extraction queue normale: {e}")
                cls._pending_messages.clear()  # Vider en cas d'erreur

            if not messages_to_process:
                return

            # Traiter les messages
            log_lines = []  # Messages texte à afficher
            progress_updates = []  # Mises à jour de progression à traiter

            # Trier les messages par type
            for msg in messages_to_process:
                if msg.type in [MessageType.PROGRESS, MessageType.PROGRESS_TEXT]:
                    progress_updates.append(msg)
                else:
                    # Vérifier les doublons pour les messages normaux
                    if not cls._is_duplicate_message(msg):
                        try:
                            formatted = MessageFormatter.format_for_rich_textual(msg)
                            if formatted:
                                log_lines.append(formatted)
                        except Exception as e:
                            logger.error(f"Erreur formatage: {e}")

            # Traiter les mises à jour de barres de progression
            for msg in progress_updates:
                try:
                    await cls._update_plugin_widget_display(app, msg)
                except Exception as e:
                    logger.debug(f"Erreur mise à jour barre: {e}")

            # Mettre à jour le texte des logs
            if log_lines:
                try:
                    with cls._output_lock:
                        current_text = logs.renderable if logs.renderable else ""
                        if current_text and not current_text.endswith("\n"):
                            current_text += "\n"
                        # Ajouter toutes les nouvelles lignes en une fois
                        logs.update(current_text + "\n".join(log_lines))
                        # Scroll vers le bas
                        logs_container.scroll_end(animate=False)
                except Exception as e:
                    logger.error(f"Erreur mise à jour logs: {e}", exc_info=True)

            # Planifier un rafraîchissement de l'UI
            if log_lines or progress_updates:
                if not cls._refresh_scheduled:
                    cls._refresh_scheduled = True
                    cls._schedule_refresh(app)

        except Exception as e:
            logger.error(f"Erreur critique dans flush_pending_messages: {e}", exc_info=True)
            # Réinitialiser les files d'attente en cas d'erreur majeure
            cls._pending_messages.clear()
        try:
            logs = app.query_one("#logs-text", Static)
            if logs:
                # Forcer un rafraîchissement du widget
                logs.refresh()

                # Scroller vers le bas
                logs_container = app.query_one("#logs-container", ScrollableContainer)
                if logs_container:
                    logs_container.scroll_end(animate=False)
        except Exception as e:
            logger.error(f"Erreur lors du rafraîchissement du widget de logs: {e}")


        # Planifier un rafraîchissement de l'application
        try:
            if hasattr(app, 'refresh'):
                app.refresh()
        except Exception as e:
            logger.error(f"Erreur lors du rafraîchissement de l'application: {e}")


    @classmethod
    def _schedule_refresh(cls, app):
        """
        Planifie un rafraîchissement différé de l'interface.

        Args:
            app: L'application Textual
        """
        try:
            with cls._refresh_lock:
                if hasattr(app, 'call_later'):
                    app.call_later(lambda: cls._do_refresh(app))
                else:
                    # Fallback si call_later n'existe pas
                    cls._do_refresh(app)
        except Exception as e:
            logger.debug(f"Erreur planification refresh: {e}")
            cls._refresh_scheduled = False

    @classmethod
    def _do_refresh(cls, app):
        """
        Effectue le rafraîchissement de l'interface.

        Args:
            app: L'application Textual
        """
        try:
            if hasattr(app, 'is_mounted') and app.is_mounted:
                if hasattr(app, 'refresh'):
                    app.refresh()
        except Exception as e:
            logger.debug(f"Erreur refresh: {e}")
        finally:
            cls._refresh_scheduled = False

    @classmethod
    async def add_log(cls, app, message: str, level: str = "info", target_ip: Optional[str] = None):
        """
        Ajoute un message au log via LoggerUtils.

        Args:
            app: L'application Textual
            message: Le message à ajouter
            level: Le niveau du message (info, warning, error, success, debug, etc.)
            target_ip: L'adresse IP cible (pour SSH)
        """
        try:
            # Valider et normaliser le niveau
            level_lower = level.lower()
            valid_levels = ["info", "warning", "error", "success", "debug", "start", "end"]
            if level_lower not in valid_levels:
                level_lower = "info"

            # Mapper les niveaux texte aux types de messages
            message_type_map = {
                "info": MessageType.INFO,
                "warning": MessageType.WARNING,
                "error": MessageType.ERROR,
                "success": MessageType.SUCCESS,
                "debug": MessageType.DEBUG,
                "start": MessageType.START,
                "end": MessageType.END
            }
            message_type = message_type_map.get(level_lower, MessageType.INFO)

            # Ajouter un préfixe pour les messages de fin
            if message_type == MessageType.END and not message.startswith("✓"):
                message = f"✓ {message}"

            # Créer l'objet message
            message_obj = Message(
                type=message_type,
                content=message,
                target_ip=target_ip
            )


            # Vérifier si nous sommes sur l'écran d'exécution
            try:
                screen_name = app.screen.__class__.__name__ if hasattr(app, 'screen') else "Unknown"
                on_execution_screen = "ExecutionScreen" in screen_name
            except Exception:
                on_execution_screen = False

            # Sur l'écran d'exécution, afficher immédiatement
            # Sinon, mettre en file d'attente
            if on_execution_screen:
                await cls.display_message(app, message_obj)
            else:
                queue = cls._pending_messages
                queue.append(message_obj)

        except Exception as e:
            logger.error(f"Erreur add_log: {e}", exc_info=True)

    @classmethod
    async def clear_logs(cls, app):
        """
        Efface tous les logs et réinitialise les files d'attente.

        Args:
            app: L'application Textual
        """
        try:
            # Vider les files d'attente
            cls._pending_messages.clear()
            cls._message_cache.clear()

            # Vider le widget de logs
            if TEXTUAL_AVAILABLE:
                try:
                    logs = app.query_one("#logs-text", Static)
                    logs.update("")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Erreur clear_logs: {e}")

    @classmethod
    def toggle_logs(cls, app) -> None:
        """
        Affiche ou masque le conteneur de logs.

        Args:
            app: L'application Textual
        """
        if not TEXTUAL_AVAILABLE:
            return

        try:
            logs_container = app.query_one("#logs-container")
            logs_container.toggle_class("hidden")

            # Mettre à jour l'état si l'app garde une trace
            if hasattr(app, 'show_logs'):
                app.show_logs = not logs_container.has_class("hidden")

            # Rafraîchir l'interface
            if not cls._refresh_scheduled:
                cls._refresh_scheduled = True
                cls._schedule_refresh(app)

        except Exception as e:
            logger.error(f"Erreur toggle_logs: {e}")

    @classmethod
    async def ensure_logs_widget_exists(cls, app) -> bool:
        """
        S'assure que le widget de logs existe et le crée si nécessaire.

        Args:
            app: L'application Textual

        Returns:
            bool: True si le widget existe ou a été créé avec succès
        """
        if not TEXTUAL_AVAILABLE:
            return False

        try:
            # Vérifier si le widget existe déjà
            app.query_one("#logs-text", Static)
            return True
        except Exception:
            pass

        try:
            # Essayer de créer le widget
            logs_container = app.query_one("#logs-container", ScrollableContainer)
            logs_text = Static(id="logs-text", classes="logs")

            # Utiliser await pour mount si c'est une coroutine
            if asyncio.iscoroutinefunction(logs_container.mount):
                await logs_container.mount(logs_text)
            else:
                logs_container.mount(logs_text)

            # Rendre visible
            logs_container.remove_class("hidden")

            # Mettre à jour l'état si l'app garde une trace
            if hasattr(app, 'show_logs'):
                app.show_logs = True

            # Rafraîchir l'interface
            if not cls._refresh_scheduled:
                cls._refresh_scheduled = True
                cls._schedule_refresh(app)

            return True

        except Exception as e:
            logger.error(f"Impossible de créer le widget de logs: {e}")
            return False

    @classmethod
    def force_flush(cls):
        """
        Force un flush synchrone des messages en attente.
        Utile pour les situations où asyncio n'est pas disponible.
        """
        if hasattr(cls, '_app') and cls._app:
            try:
                # Créer une nouvelle boucle asyncio si nécessaire
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # Aucune boucle n'existe
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                # Exécuter le flush de façon synchrone
                future = asyncio.ensure_future(cls.flush_pending_messages(cls._app))
                loop.run_until_complete(future)
            except Exception as e:
                logger.error(f"Erreur pendant force_flush: {e}")
                # Réinitialiser en cas d'erreur
                cls._pending_messages.clear()

    @classmethod
    def log_to_console(cls, message: str, level: str = "info"):
        """
        Écrit un message directement sur la console, sans passer par l'interface.
        Utile pour le débogage ou quand l'interface n'est pas disponible.

        Args:
            message: Le message à logger
            level: Niveau du message (info, warning, error, success, debug)
        """
        # Codes couleur ANSI
        colors = {
            "info": "\033[0;37m",      # Blanc
            "warning": "\033[0;33m",   # Jaune
            "error": "\033[0;31m",     # Rouge
            "success": "\033[0;32m",   # Vert
            "debug": "\033[0;36m",     # Cyan
        }
        reset = "\033[0m"

        timestamp = time.strftime("%H:%M:%S")
        color = colors.get(level.lower(), colors["info"])

        print(f"{timestamp} [{color}{level.upper():7}{reset}] {message}")

    @classmethod
    def get_pending_message_count(cls) -> int:
        """
        Retourne le nombre de messages en attente.
        Utile pour diagnostiquer des problèmes de blocage des files d'attente.

        Returns:
            int: Nombre total de messages en attente
        """
        return len(cls._pending_messages)