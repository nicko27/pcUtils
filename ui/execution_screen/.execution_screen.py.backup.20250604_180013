"""
Écran d'exécution des plugins.
Ce module fournit l'écran principal pour l'exécution des plugins configurés.
"""

import os
import asyncio
from typing import Dict, Any, Optional
import traceback
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button
from textual.message import Message

from ..utils.logging import get_logger
from .execution_widget import ExecutionWidget
from .logger_utils import LoggerUtils

logger = get_logger('execution_screen')

class ExecutionScreen(Screen):
    """
    Écran contenant le widget d'exécution des plugins.

    Cet écran coordonne le processus d'exécution des plugins configurés,
    gère les interactions utilisateur et les transitions entre écrans.
    """

    # Définir les raccourcis clavier, notamment ESC pour quitter
    BINDINGS = [
        ("escape", "quit", "Quitter"),
    ]

    # Chemin vers le fichier CSS
    CSS_PATH = str(Path(__file__).parent / "../styles/execution.tcss")

    def __init__(self, plugins_config: Optional[Dict[str, Any]] = None,
                auto_execute: bool = False,
                report_manager = None):
        """
        Initialise l'écran avec la configuration des plugins.

        Args:
            plugins_config: Dictionnaire de configuration des plugins
            auto_execute: Si True, lance l'exécution automatiquement
            report_manager: Gestionnaire de rapports optionnel
        """
        super().__init__()
        self.plugins_config = plugins_config or {}
        self.auto_execute = auto_execute
        self.report_manager = report_manager
        self._execution_running = False
        self._execution_task = None
        self._current_plugin_widget = None  # Ajout : Garder une référence au widget actuel

        logger.debug(f"ExecutionScreen initialisé avec {len(self.plugins_config)} plugins")
        logger.debug(f"Mode auto-exécution: {self.auto_execute}")

    async def on_mount(self) -> None:
        """
        Appelé quand l'écran est monté dans l'interface.
        Initialise l'exécution en mode auto si nécessaire.
        """
        try:
            logger.debug("Montage de l'écran d'exécution")

            # Créer une tâche asynchrone pour l'initialisation avec un délai
            # Cela permet à l'interface de s'afficher complètement avant de commencer l'exécution
            self._init_task = asyncio.create_task(self._delayed_initialization())
        except Exception as e:
            logger.error(f"Erreur lors du montage de l'écran d'exécution: {e}")
            logger.error(traceback.format_exc())
            self.notify(f"Erreur lors de l'initialisation: {e}", severity="error")

    async def _delayed_initialization(self) -> None:
        """
        Initialise l'écran après un délai pour permettre à l'interface de s'afficher.
        Cette méthode est appelée via une tâche asynchrone créée dans on_mount.
        """
        try:
            # Attendre que l'interface soit complètement affichée
            logger.debug("Attente pour permettre à l'interface de s'afficher complètement")
            await asyncio.sleep(1.0)  # Délai d'1 seconde

            # Vérifier que l'écran est toujours monté
            if not self.is_mounted:
                logger.debug("L'écran n'est plus monté, annulation de l'initialisation")
                return

            # Maintenant initialiser l'écran
            logger.debug("Début de l'initialisation de l'écran après délai")
            await self.initialize_screen()
        except Exception as e:
            logger.error(f"Erreur dans l'initialisation différée: {e}")
            logger.error(traceback.format_exc())
            self.notify(f"Erreur lors de l'initialisation: {e}", severity="error")

    async def initialize_screen(self) -> None:
        """
        Initialise l'écran après le montage complet.
        Configure l'interface selon le mode d'exécution (auto ou manuel).
        """
        try:
            # Récupérer le widget d'exécution
            widget = self.query_one(ExecutionWidget)
            self._current_plugin_widget = widget  # Ajout : Sauvegarder la référence

            if self.auto_execute:
                # En mode auto, masquer les boutons Démarrer et Retour définitivement
                try:
                    start_button = widget.query_one("#start-button")
                    back_button = widget.query_one("#back-button")
                    if start_button and back_button:
                        start_button.add_class("hidden")
                        back_button.add_class("hidden")
                        logger.debug("Boutons Démarrer et Retour masqués en mode auto")
                except Exception as e:
                    logger.error(f"Erreur lors du masquage des boutons en mode auto: {e}")

                # Lancer l'exécution automatiquement
                if widget:
                    # Forcer un rafraîchissement de l'interface avant de commencer
                    logger.debug("Rafraîchissement de l'interface avant l'exécution automatique")
                    self.refresh()

                    # Attendre un délai pour s'assurer que l'interface est complètement chargée
                    await asyncio.sleep(0.5)

                    # Vérifier que l'écran est toujours monté
                    if not self.is_mounted:
                        logger.debug("L'écran n'est plus monté, annulation de l'exécution automatique")
                        return

                    # Forcer un second rafraîchissement
                    self.refresh()
                    await asyncio.sleep(0.1)
                    self._execution_running = True

                    try:
                        # Exécuter directement plutôt que via une tâche
                        logger.debug("Démarrage direct de l'exécution")
                        await widget.start_execution(auto_mode=True)
                        logger.debug("Exécution terminée avec succès")
                    except asyncio.CancelledError:
                        logger.info("Exécution automatique annulée par l'utilisateur")
                        self.notify("Exécution annulée", severity="warning")
                    except Exception as e:
                        logger.error(f"Erreur pendant l'exécution: {e}")
                        logger.error(traceback.format_exc())
                        self.notify(f"Erreur: {e}", severity="error")
                    finally:
                        # S'assurer que le flag d'exécution est remis à False
                        self._execution_running = False
            await LoggerUtils.flush_pending_messages(self)

        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de l'écran: {e}")
            logger.error(traceback.format_exc())
            self.notify(f"Erreur lors de l'initialisation: {e}", severity="error")

    def action_quit(self) -> None:
        """
        Gère l'action de quitter l'écran via la touche ESC.
        Si une exécution est en cours, l'arrête proprement avant de quitter.
        """
        try:
            logger.info("Demande de sortie via touche ESC")

            # Vérifier si une exécution est en cours
            if self._execution_running:
                logger.info("Exécution en cours détectée, lancement de la procédure d'annulation")

                # Arrêter l'exécution en cours
                if self._execution_task is not None:
                    try:
                        logger.info("Annulation de la tâche d'exécution en cours")
                        self._execution_task.cancel()
                    except Exception as e:
                        logger.warning(f"Erreur lors de l'annulation de la tâche: {e}")

                # Arrêter également l'exécution dans le widget
                try:
                    widget = self.query_one(ExecutionWidget)
                    if hasattr(widget, 'is_running'):
                        logger.info("Arrêt de l'exécution dans le widget")
                        widget.is_running = False
                except Exception as e:
                    logger.warning(f"Impossible d'arrêter l'exécution dans le widget: {e}")

                # Lancer la procédure d'annulation asynchrone
                asyncio.create_task(self._handle_cancellation())
                # Notifier l'utilisateur
                self.notify("Annulation de l'exécution en cours...", severity="warning")
                return  # Ne pas quitter immédiatement

            # Si aucune exécution en cours, quitter l'application
            self.app.exit()
        except Exception as e:
            logger.error(f"Erreur lors de la sortie: {e}")
            logger.error(traceback.format_exc())
            self.notify(f"Erreur lors de la sortie: {e}", severity="error")
            # Tenter de quitter même en cas d'erreur
            try:
                self.app.pop_screen()
            except Exception:
                pass

    async def on_execution_completed(self) -> None:
        """
        Appelé quand l'exécution des plugins est terminée.
        Peut être surchargé pour des actions supplémentaires.
        """
        logger.debug("Exécution terminée")

        try:
            widget = self.query_one(ExecutionWidget)
            if widget:
                # Force un rafraîchissement final de l'interface
                widget.refresh()
                # Force un flush final des logs
                await LoggerUtils.flush_pending_messages(self)
                # Attendre un court instant
                await asyncio.sleep(0.1)
                # Force un second flush pour s'assurer que tout est bien traité
                await LoggerUtils.flush_pending_messages(self)
        except Exception as e:
            logger.error(f"Erreur lors du flush final des logs: {e}")
            logger.error(traceback.format_exc())


    async def _handle_cancellation(self) -> None:
        """
        Gère l'annulation de l'exécution et quitte l'écran après un court délai.
        """
        try:
            # Marquer l'exécution comme terminée
            self._execution_running = False

            # Arrêter tous les plugins en cours
            try:
                widget = self.query_one(ExecutionWidget)
                if hasattr(widget, 'is_running'):
                    logger.info("Arrêt forcé des plugins en cours d'exécution")
                    widget.is_running = False
            except Exception as e:
                logger.warning(f"Impossible d'arrêter les plugins en cours: {e}")

            # Attendre pour que l'annulation prenne effet
            logger.debug("Attente de 1 seconde pour permettre l'arrêt complet de l'exécution")
            await asyncio.sleep(1.0)

            # Vérifier que l'écran est toujours monté
            if not self.is_mounted:
                logger.debug("L'écran n'est plus monté, annulation de la fermeture")
                return

            # Quitter l'écran ou l'application selon le contexte
            if self.auto_execute:
                logger.info("Mode auto détecté, fermeture de l'application après annulation")
                self.app.exit()
            else:
                logger.info("Annulation de l'exécution terminée, retour à l'écran précédent")
                self.app.pop_screen()
        except Exception as e:
            logger.error(f"Erreur lors de la gestion de l'annulation: {e}")
            logger.error(traceback.format_exc())
            # Tenter de quitter l'écran même en cas d'erreur
            try:
                self.app.pop_screen()
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        """
        Compose l'interface de l'écran.

        Returns:
            ComposeResult: Résultat de la composition
        """
        try:
            # Créer le widget d'exécution avec la configuration des plugins
            yield ExecutionWidget(self.plugins_config)
        except Exception as e:
            logger.error(f"Erreur lors de la composition de l'écran d'exécution: {e}")
            logger.error(traceback.format_exc())
            # Affichage de secours en cas d'erreur
            from textual.widgets import Static
            yield Static(f"Erreur lors de la création de l'interface: {e}\n\n"
                         f"Veuillez vérifier les logs pour plus de détails.")