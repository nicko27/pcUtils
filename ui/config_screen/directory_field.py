from textual.app import ComposeResult
from textual.widgets import Button, Input
from textual.containers import Horizontal, VerticalGroup
from subprocess import Popen, PIPE
import os
import shutil
from typing import Optional, Tuple, Any, Union
import asyncio

from .text_field import TextField
from ..utils.logging import get_logger

logger = get_logger('directory_field')

class DirectoryField(TextField):
    """
    Champ de sélection de répertoire avec un bouton de navigation.

    Ce champ étend TextField en ajoutant un sélecteur de répertoire graphique
    via zenity lorsque disponible.
    """

    def __init__(self, source_id: str, field_id: str, field_config: dict, fields_by_id: dict = None, is_global: bool = False):
        """
        Initialisation du champ répertoire.

        Args:
            source_id: Identifiant de la source (plugin ou config globale)
            field_id: Identifiant du champ
            field_config: Configuration du champ
            fields_by_id: Dictionnaire des champs par ID
            is_global: Si True, c'est un champ global
        """
        # Initialiser les attributs spécifiques
        self._browse_button: Optional[Button] = None

        # Vérifier si zenity est disponible et si un display est présent
        self._has_display = os.environ.get('DISPLAY') is not None
        self._has_zenity = shutil.which('zenity') is not None

        # Appeler l'initialisation du parent
        super().__init__(source_id, field_id, field_config, fields_by_id, is_global)

        logger.debug(f"Champ répertoire {self.field_id} initialisé " +
                    f"(zenity: {self._has_zenity}, display: {self._has_display})")

    def compose(self) -> ComposeResult:
        """
        Création des éléments visuels du champ.

        Returns:
            ComposeResult: Éléments UI du champ
        """
        # Rendre les éléments de base (label, etc.)
        parent_widgets = list(super().compose())

        # Ajouter les widgets du parent
        for widget in parent_widgets:
            yield widget

        # Ajouter le bouton Browse
        button_label = "Parcourir..." if self._has_display and self._has_zenity else "Parcourir... (Non disponible)"
        self._browse_button = Button(
            button_label,
            id=f"browse_{self.field_id}",
            classes="browse-button"
        )

        # État initial: activé sauf si explicitement désactivé ou zenity indisponible
        should_disable = (self.disabled if hasattr(self, 'disabled') else False) or not (self._has_display and self._has_zenity)
        self._browse_button.disabled = should_disable

        if should_disable:
            self._browse_button.add_class('disabled')
        else:
            self._browse_button.remove_class('disabled')

        yield self._browse_button

    def on_mount(self) -> None:
        """
        Méthode appelée lors du montage du widget dans l'interface.
        """
        logger.debug(f"Montage du champ répertoire {self.field_id}")

        # Appeler la méthode du parent pour gérer la valeur
        super().on_mount()

        # Mettre à jour l'état du bouton browse en fonction de l'état du champ
        if hasattr(self, '_browse_button') and self._browse_button:
            should_disable = (self.disabled if hasattr(self, 'disabled') else False) or not (self._has_display and self._has_zenity)
            self._browse_button.disabled = should_disable

            if should_disable:
                self._browse_button.add_class('disabled')
            else:
                self._browse_button.remove_class('disabled')

    def set_disabled(self, disabled: bool) -> None:
        """
        Active ou désactive le champ et son bouton Browse.

        Args:
            disabled: True pour désactiver, False pour activer
        """
        # Appeler d'abord la méthode parente pour désactiver le champ texte
        super().set_disabled(disabled)

        # Mettre à jour l'état du bouton browse
        if hasattr(self, '_browse_button') and self._browse_button:
            should_disable = disabled or not (self._has_display and self._has_zenity)
            self._browse_button.disabled = should_disable

            if should_disable:
                self._browse_button.add_class('disabled')
            else:
                self._browse_button.remove_class('disabled')

    def validate_input(self, value: str) -> Tuple[bool, str]:
        """
        Valide une valeur d'entrée avec vérification de répertoire.

        Args:
            value: Valeur à valider

        Returns:
            Tuple[bool, str]: (est_valide, message_erreur)
        """
        # Utiliser d'abord la validation de base (vide, longueur, etc.)
        is_valid, error_msg = super().validate_input(value)
        if not is_valid:
            return is_valid, error_msg

        # Validation spécifique aux répertoires
        if value and self.field_config.get('exists', False):
            # Vérifier si le répertoire existe
            if not os.path.exists(value):
                return False, "Ce répertoire n'existe pas"

            # Vérifier si c'est bien un répertoire
            if not os.path.isdir(value):
                return False, "Ce chemin n'est pas un répertoire"

        # Valide par défaut
        return True, ""

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """
        Gestionnaire d'événement quand l'utilisateur clique sur le bouton Browse.

        Args:
            event: Événement de bouton pressé
        """
        # Vérifier que c'est bien notre bouton
        if event.button.id != f"browse_{self.field_id}":
            return

        logger.debug(f"Bouton Browse pressé pour {self.field_id}")

        # Vérifier si zenity est disponible et si un display est présent
        if not self._has_display:
            logger.warning("Aucun affichage (DISPLAY) disponible pour lancer zenity")
            self.app.notify("Aucun affichage disponible pour le sélecteur de fichiers", severity="warning")
            return

        if not self._has_zenity:
            logger.warning("Zenity n'est pas installé sur le système")
            self.app.notify("Le programme 'zenity' est requis pour le sélecteur de fichiers", severity="warning")
            return

        # Lancer le sélecteur de répertoire via zenity
        self._run_zenity_directory_selector()

    def _run_zenity_directory_selector(self) -> None:
        """
        Exécute zenity pour sélectionner un répertoire et applique le résultat.
        Méthode synchrone qui lance un thread pour ne pas bloquer l'interface.
        """
        try:
            # Récupérer le répertoire actuel comme point de départ
            current_dir = self._internal_value if self._internal_value else ""

            # Préparer les arguments pour zenity
            zenity_args = ['zenity', '--file-selection', '--directory']

            # Ajouter le répertoire de départ si valide
            if current_dir and os.path.isdir(current_dir):
                zenity_args.extend(['--filename', current_dir])

            # Titre de la boîte de dialogue
            title = self.field_config.get('label', f"Sélectionner un répertoire pour {self.field_id}")
            zenity_args.extend(['--title', title])

            logger.debug(f"Lancement de zenity avec les arguments: {zenity_args}")

            # Lancer zenity de façon synchrone mais dans un thread séparé
            def run_zenity_in_thread():
                try:
                    process = Popen(zenity_args, stdout=PIPE, stderr=PIPE)
                    stdout, stderr = process.communicate()

                    # Si l'utilisateur a sélectionné un répertoire (code de retour 0)
                    if process.returncode == 0:
                        selected_dir = stdout.decode().strip()
                        logger.debug(f"Répertoire sélectionné: '{selected_dir}'")

                        # Appliquer le répertoire sélectionné si différent
                        if selected_dir and selected_dir != self._internal_value:
                            # Nous devons utiliser call_from_thread pour mettre à jour l'interface
                            self.app.call_from_thread(self.set_value, selected_dir)
                    else:
                        logger.debug(f"Sélection de répertoire annulée par l'utilisateur (code {process.returncode})")

                except Exception as e:
                    logger.error(f"Erreur dans le thread zenity: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # Notification depuis un thread
                    self.app.call_from_thread(
                        self.app.notify,
                        f"Erreur lors de la sélection du répertoire: {str(e)}",
                        severity="error"
                    )

            # Démarrer le thread
            self.app.run_worker(run_zenity_in_thread, thread=True)

        except Exception as e:
            logger.error(f"Erreur lors de la sélection du répertoire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.app.notify(f"Erreur lors de la sélection du répertoire: {str(e)}", severity="error")