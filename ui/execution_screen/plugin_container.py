"""
Module définissant le conteneur pour un plugin à exécuter.
"""

import threading
from ..utils.logging import get_logger
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Label, ProgressBar

from ..choice_screen.plugin_utils import get_plugin_folder_name

logger = get_logger('plugin_container')

class PluginContainer(Container):
    """Conteneur pour afficher l'état et la progression d'un plugin"""

    def __init__(self, plugin_id: str, plugin_name: str, plugin_show_name: str, plugin_icon: str):
        """Initialise le conteneur avec l'ID et le nom du plugin

        Args:
            plugin_id: L'ID complet du plugin (ex: bash_interactive_1) - doit être déjà sanitizé
            plugin_name: Le nom interne du plugin
            plugin_show_name: Le nom à afficher dans l'interface
            plugin_icon: L'icône associée au plugin
        """
        # Ensure the ID is valid for Textual widgets (only letters, numbers, underscores, hyphens)
        import re
        # Create a valid ID by replacing invalid characters with underscores
        # and ensuring it doesn't start with a number
        # Utiliser uniquement le plugin_id qui est déjà unique
        valid_id = re.sub(r'[^a-zA-Z0-9_-]', '_', plugin_id)
        # If it starts with a number, prepend an underscore
        if valid_id and valid_id[0].isdigit():
            valid_id = f"_{valid_id}"
            
        try:
            widget_id = f"plugin-{valid_id}"
            logger.debug(f"Creating container with ID: {widget_id}")
            super().__init__(id=widget_id)
        except Exception as e:
            # Fallback to a generic ID if there's still an issue
            logger.error(f"Error creating container with ID '{widget_id}': {str(e)}")
            # Use a UUID as fallback
            import uuid
            fallback_id = f"plugin-{uuid.uuid4().hex[:8]}"
            logger.debug(f"Using fallback ID: {fallback_id}")
            super().__init__(id=fallback_id)
            
        self.plugin_id = plugin_id
        # Récupérer le nom du dossier pour les logs
        try:
            self.folder_name = get_plugin_folder_name(plugin_id)
        except Exception as e:
            logger.error(f"Error getting folder name for {plugin_id}: {str(e)}")
            self.folder_name = plugin_name
            
        # Nom affiché dans l'interface
        self.plugin_name = plugin_name
        self.plugin_show_name = plugin_show_name
        self.plugin_icon = plugin_icon
        self.target_ip = None  # IP cible pour les plugins SSH avec plusieurs IPs
        self.status = "waiting"  # Statut initial du plugin (waiting, running, success, error)
        self.output = ""  # Initialiser l'attribut output
        self.classes = "plugin-container waiting"
        
        # Variables pour stocker les mises à jour en attente
        self._pending_status = None
        self._pending_progress = None
        self._pending_step = None

    def compose(self) -> ComposeResult:
        """Création des widgets du conteneur"""
        with Horizontal(classes="plugin-content"):
            yield Label(self.plugin_icon+"  "+self.plugin_show_name, classes="plugin-name")
            yield ProgressBar(classes="plugin-progress", show_eta=False, total=100.0)
            yield Label("En attente", classes="plugin-status")
            
    def on_mount(self) -> None:
        """Appelé lorsque le conteneur est monté dans le DOM"""
        logger.debug(f"Conteneur {self.plugin_id} monté")
        
        # Appliquer les mises à jour en attente si elles existent
        try:
            # Appliquer le statut en attente
            if hasattr(self, '_pending_status') and self._pending_status:
                try:
                    status_widget = self.query_one(".plugin-status")
                    if status_widget:
                        status_widget.update(self._pending_status)
                        logger.debug(f"Statut en attente appliqué pour {self.plugin_id}: {self._pending_status}")
                except Exception as e:
                    logger.error(f"Impossible d'appliquer le statut en attente: {e}")
            
            # Appliquer la progression en attente
            if hasattr(self, '_pending_progress') and self._pending_progress is not None:
                try:
                    progress_bar = self.query_one(ProgressBar)
                    if progress_bar:
                        progress_value = max(0.0, min(1.0, float(self._pending_progress)))
                        progress_bar.update(progress=progress_value * 100)
                        logger.debug(f"Progression en attente appliquée pour {self.plugin_id}: {self._pending_progress}")
                except Exception as e:
                    logger.error(f"Impossible d'appliquer la progression en attente: {e}")
                    
            # Appliquer le texte de statut en attente
            if hasattr(self, '_pending_step') and self._pending_step:
                try:
                    status_label = self.query_one(".plugin-status")
                    if status_label:
                        status_label.update(self._pending_step)
                        logger.debug(f"Texte de statut en attente appliqué pour {self.plugin_id}: {self._pending_step}")
                except Exception as e:
                    logger.error(f"Impossible d'appliquer le texte de statut en attente: {e}")
        except Exception as e:
            logger.error(f"Erreur lors de l'application des mises à jour en attente: {e}")

    def update_progress(self, progress: float, step: str = None):
        """Mise à jour synchrone de la progression du plugin"""
        try:
            # Récupérer la barre de progression
            try:
                progress_bar = self.query_one(ProgressBar)
                if progress_bar:
                    # Assurer que la progression est entre 0 et 1
                    progress_value = max(0.0, min(1.0, float(progress)))
                    # Convertir en pourcentage pour l'affichage
                    progress_bar.update(progress=progress_value * 100)
                    # Forcer le rafraîchissement
                    progress_bar.refresh()
            except Exception as e:
                logger.debug(f"Barre de progression non disponible pour {self.plugin_id}: {e}")
                # Stocker la progression pour l'appliquer plus tard si nécessaire
                self._pending_progress = progress

            # Mettre à jour le texte de statut si fourni
            if step:
                try:
                    status_label = self.query_one(".plugin-status")
                    if status_label:
                        status_label.update(step)
                        # Forcer le rafraîchissement
                        status_label.refresh()
                except Exception as e:
                    logger.debug(f"Label de statut non disponible pour {self.plugin_id}: {e}")
                    # Stocker le statut pour l'appliquer plus tard si nécessaire
                    self._pending_step = step
                    
            # Forcer le rafraîchissement du conteneur si monté
            if self.is_mounted:
                self.refresh()
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour de la progression: {str(e)}")
            
    async def update_progress_async(self, progress: float, step: str = None):
        """Mise à jour asynchrone de la progression du plugin"""
        try:
            # Assurer que nous sommes dans le thread principal
            if not self.app._thread_id == threading.get_ident():
                await self.app.call_from_thread(self.update_progress_async, progress, step)
                return
                
            # Récupérer la barre de progression
            progress_bar = self.query_one(ProgressBar)
            if progress_bar:
                # Assurer que la progression est entre 0 et 1
                progress_value = max(0.0, min(1.0, float(progress)))
                # Convertir en pourcentage pour l'affichage
                await progress_bar.update(progress=progress_value * 100)

            # Mettre à jour le texte de statut si fourni
            if step:
                status_label = self.query_one(".plugin-status")
                if status_label:
                    await status_label.update(step)
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour asynchrone de la progression: {str(e)}")

    def set_status(self, status: str, message: str = None):
        """Mise à jour du statut du plugin"""
        # Stocker le statut comme attribut
        self.status = status
        
        # Mettre à jour les classes CSS
        self.classes = f"plugin-container {status}"

        # Définir le texte du statut
        status_map = {
            'waiting': 'En attente',
            'running': 'En cours',
            'success': 'Terminé',
            'error': 'Erreur'
        }
        status_text = status_map.get(status, status)
        if message:
            status_text = f"{status_text} - {message}"

        # Mettre à jour le widget de statut s'il existe
        try:
            status_widget = self.query_one(".plugin-status")
            if status_widget:
                status_widget.update(status_text)
        except Exception as e:
            # Si le widget n'existe pas encore, stocker le statut pour plus tard
            logger.debug(f"Widget de statut non disponible pour {self.plugin_id}: {e}")
            # Stocker le statut pour l'appliquer plus tard si nécessaire
            self._pending_status = status_text
        
    def set_output(self, output: str):
        """Stocke la sortie du plugin pour référence ultérieure
        
        Args:
            output: La sortie du plugin
        """
        try:
            # Stocker la sortie comme attribut de l'objet
            self.output = output
            logger.debug(f"Sortie stockée pour le plugin {self.plugin_id}")
        except Exception as e:
            logger.error(f"Erreur lors du stockage de la sortie pour {self.plugin_id}: {str(e)}")