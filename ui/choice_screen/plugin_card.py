from textual.app import ComposeResult
from textual.widgets import Label, Static
from textual.reactive import reactive
from textual.message import Message
from textual.widget import Widget
from pathlib import Path
from typing import Dict, Any, Optional, Union

from .plugin_utils import load_plugin_info
from ..utils.logging import get_logger

logger = get_logger('plugin_card')

class PluginCard(Static):
    """
    Widget représentant une carte de plugin dans l'interface.

    Cette classe gère l'affichage et l'interaction des cartes de plugins
    et de séquences dans l'écran de sélection.
    """

    # État réactif pour savoir si le plugin est sélectionné
    selected = reactive(False)

    def __init__(self, plugin_name: str, *args, **kwargs):
        """
        Initialise une carte de plugin.

        Args:
            plugin_name: Nom du plugin ou de la séquence
            *args: Arguments positionnels pour la classe parente
            **kwargs: Arguments nommés pour la classe parente
        """
        super().__init__(*args, **kwargs)
        self.plugin_name = plugin_name
        self.is_sequence = plugin_name.startswith('__sequence__')

        # Charger les infos du plugin ou de la séquence
        if self.is_sequence:
            self.sequence_file = plugin_name.replace('__sequence__', '')
            self.plugin_info = self._load_sequence_info(self.sequence_file)
        else:
            self.plugin_info = load_plugin_info(plugin_name)

    def compose(self) -> ComposeResult:
        """
        Compose le contenu visuel de la carte de plugin.

        Returns:
            ComposeResult: Résultat de la composition
        """
        name = self.plugin_info.get('name', 'Plugin sans nom')
        description = self.plugin_info.get('description', '')

        if self.is_sequence:
            # Affichage spécifique pour les séquences
            icon = '⚙️'
            yield Label(f"{icon}  {name}", classes="plugin-name sequence-name")

            plugins_count = self.plugin_info.get('plugins_count', 0)
            if description:
                yield Label(f"{description} ({plugins_count} plugins)", classes="plugin-description")
            else:
                yield Label(f"{plugins_count} plugins", classes="plugin-description")
        else:
            # Affichage standard pour les plugins
            icon = self.plugin_info.get('icon', '📦')

            # Ajouter des icônes spécifiques selon les capacités du plugin
            multiple = self.plugin_info.get('multiple', False)
            remote = self.plugin_info.get('remote_execution', False)
            icon_multiple=""
            icon_remote=""
            if multiple:
                icon_multiple = f"🔁"  # Icône de recyclage pour les plugins réutilisables
            if remote:
                icon_remote = f"{icon} 🌐"  # Icône globe pour exécution distante

            yield Label(f"{icon}  {name} {icon_multiple} {icon_remote}", classes="plugin-name")

            if description:
                yield Label(description, classes="plugin-description")

    def on_click(self) -> None:
        """
        Gère les clics sur la carte de plugin.

        Ce gestionnaire a un comportement différent selon le type de plugin :
        - Pour les séquences, bascule simplement l'état de sélection
        - Pour les plugins multiples déjà sélectionnés, ajoute une nouvelle instance
        - Pour les autres plugins, bascule l'état de sélection
        """
        # Traitement spécial pour les séquences
        if self.is_sequence:
            self.selected = not self.selected
            self.update_styles()
            self.app.post_message(self.PluginSelectionChanged(self.plugin_name, self.selected, self))
            return

        # Récupérer les infos du plugin pour vérifier s'il est multiple
        plugin_info = load_plugin_info(self.plugin_name)
        multiple = plugin_info.get('multiple', False)

        # Si c'est un plugin multiple déjà sélectionné, ajouter une instance
        if multiple and self.selected:
            self.app.post_message(self.AddPluginInstance(self.plugin_name, self))
            # Ajouter une animation visuelle temporaire
            self.add_class("instance-added")
            # Le retirer après un délai (la classe CSS doit définir une transition)
            self.set_timer(0.5, self.remove_instance_added_animation)
        else:
            # Sinon, basculer l'état de sélection
            self.selected = not self.selected
            self.update_styles()
            self.app.post_message(self.PluginSelectionChanged(self.plugin_name, self.selected, self))

    def remove_instance_added_animation(self) -> None:
        """Retire l'animation d'ajout d'instance après un délai."""
        self.remove_class("instance-added")

    def update_styles(self) -> None:
        """
        Met à jour les styles CSS de la carte selon l'état de sélection.
        """
        if self.selected:
            self.add_class('selected')
        else:
            self.remove_class('selected')

    def _load_sequence_info(self, sequence_file: str) -> Dict[str, Any]:
        """
        Charge les informations d'une séquence depuis son fichier YAML.

        Args:
            sequence_file: Nom du fichier de séquence

        Returns:
            Dict[str, Any]: Informations de la séquence
        """
        try:
            from .sequence_handler import SequenceHandler

            # Utiliser SequenceHandler pour charger la séquence
            sequence_handler = SequenceHandler()
            sequence_path = Path('sequences') / sequence_file

            if not sequence_path.exists():
                logger.error(f"Fichier de séquence non trouvé : {sequence_path}")
                return {
                    'name': 'Séquence inconnue',
                    'description': 'Fichier non trouvé',
                    'plugins_count': 0
                }

            # Charger la séquence
            sequence = sequence_handler.load_sequence(sequence_path)

            if not sequence:
                return {
                    'name': 'Séquence invalide',
                    'description': 'Format incorrect',
                    'plugins_count': 0
                }

            return {
                'name': sequence.get('name', sequence_file),
                'description': sequence.get('description', 'Aucune description'),
                'plugins_count': len(sequence.get('plugins', []))
            }

        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence {sequence_file}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'name': 'Erreur',
                'description': f'Erreur: {str(e)}',
                'plugins_count': 0
            }

    class PluginSelectionChanged(Message):
        """
        Message envoyé lorsque la sélection d'un plugin change.

        Attributes:
            plugin_name: Nom du plugin
            selected: État de sélection (True=sélectionné, False=désélectionné)
            source: Widget source du message
        """
        def __init__(self, plugin_name: str, selected: bool, source: Widget):
            super().__init__()
            self.plugin_name = plugin_name
            self.selected = selected
            self.source = source

    class AddPluginInstance(Message):
        """
        Message spécifique pour ajouter une instance d'un plugin multiple.

        Attributes:
            plugin_name: Nom du plugin
            source: Widget source du message
        """
        def __init__(self, plugin_name: str, source: Widget):
            super().__init__()
            self.plugin_name = plugin_name
            self.source = source