from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Union
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label, Button

from .plugin_utils import load_plugin_info
from ..utils.logging import get_logger

logger = get_logger('plugin_list_item')

class PluginListItem(Horizontal):
    """
    Représente un élément dans la liste des plugins sélectionnés.
    
    Cette classe gère l'affichage d'un plugin ou d'une séquence
    dans le panneau de plugins sélectionnés.
    """

    def __init__(self, plugin_data: tuple, index: int):
        """
        Initialise un élément de liste pour un plugin sélectionné.
        
        Args:
            plugin_data: Tuple contenant (nom_plugin, id_instance [, config])
            index: Position dans la liste des plugins
        """
        super().__init__()
        
        # Gérer le cas où plugin_data est un tuple de 3 éléments (nom, id, config)
        if len(plugin_data) == 3:
            self.plugin_name, self.instance_id, self.config = plugin_data
            logger.debug(f"Plugin avec config: {self.plugin_name}")
        else:
            self.plugin_name, self.instance_id = plugin_data
            self.config = {}
            logger.debug(f"Plugin sans config: {self.plugin_name}")
            
        self.index = index  # Index de l'élément dans la liste
        
        # Vérifier si c'est une séquence
        self.is_sequence = isinstance(self.plugin_name, str) and self.plugin_name.startswith('__sequence__')
        
        # Attributs pour les plugins faisant partie d'une séquence
        # Ces attributs sont définis par SelectedPluginsPanel
        self.is_part_of_sequence = False
        self.sequence_id = None
        self.sequence_name = None
        
        # Charger les informations du plugin ou de la séquence
        if self.is_sequence:
            # Pour les séquences, charger les informations depuis le fichier YAML
            default_info = self._load_sequence_info(self.plugin_name)
        else:
            default_info = {
                "name": self.plugin_name,
                "icon": "📦"
            }
        
        self.plugin_info = load_plugin_info(self.plugin_name, default_info)
        logger.debug(f"Info du plugin/séquence chargées pour {self.plugin_name}")

    def _load_sequence_info(self, sequence_name: str) -> Dict[str, Any]:
        """
        Charge les informations d'une séquence depuis son fichier YAML.
        
        Args:
            sequence_name: Nom de la séquence (format __sequence__nom)
            
        Returns:
            Dict[str, Any]: Informations de base de la séquence
        """
        try:
            # Extraire le nom du fichier de séquence
            file_name = sequence_name.replace('__sequence__', '')
            logger.debug(f"Chargement de la séquence: {file_name}")
            
            if not file_name:
                logger.warning("Nom de fichier vide pour la séquence")
                return {"name": "Sans nom", "icon": "⚙️ "}
            
            # Vérifier si l'extension .yml est présente
            if not file_name.endswith('.yml'):
                file_name = f"{file_name}.yml"
                
            # Construire le chemin du fichier YAML
            sequence_path = Path('sequences') / file_name
            
            if not sequence_path.exists():
                logger.warning(f"Fichier de séquence non trouvé: {sequence_path}")
                return {"name": file_name, "icon": "⚙️ "}
                
            # Charger le contenu du fichier YAML
            from ruamel.yaml import YAML
            yaml = YAML()
            with open(sequence_path, 'r', encoding='utf-8') as f:
                sequence_data = yaml.load(f)
                
            # Vérifier si le fichier YAML contient un nom et une description
            if isinstance(sequence_data, dict):
                return {
                    "name": sequence_data.get('name', file_name),
                    "icon": "⚙️",
                    "description": sequence_data.get('description', ''),
                    "plugins_count": len(sequence_data.get('plugins', []))
                }
            else:
                logger.warning(f"Format de séquence invalide dans {file_name}")
                return {"name": file_name, "icon": "⚙️"}
                
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence {sequence_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"name": "Erreur", "icon": "⚙️", "description": str(e)}
    
    def set_sequence_attributes(self, is_part_of_sequence: bool, sequence_id: str = None, sequence_name: str = None) -> None:
        """
        Met à jour les attributs de séquence et rafraîchit l'affichage.
        
        Args:
            is_part_of_sequence: Indique si ce plugin fait partie d'une séquence
            sequence_id: ID de la séquence à laquelle ce plugin appartient
            sequence_name: Nom de la séquence à laquelle ce plugin appartient
        """
        # Mettre à jour les attributs
        self.is_part_of_sequence = is_part_of_sequence
        self.sequence_id = sequence_id
        self.sequence_name = sequence_name
        
        # Forcer le rafraîchissement de l'affichage
        self.refresh()
        
        logger.debug(f"Attributs de séquence mis à jour pour {self.plugin_name} (sequence: {sequence_name})")
    
    def compose(self) -> ComposeResult:
        """
        Compose l'affichage de l'élément.
        
        Returns:
            ComposeResult: Résultat de la composition
        """
        # Sauvegarder l'état original de is_sequence pour l'utiliser plus tard
        original_is_sequence = self.is_sequence
        
        # Déterminer les informations d'affichage en fonction du type
        if original_is_sequence:
            # Pour les séquences
            name = self.plugin_info.get('name', self.plugin_name.replace('__sequence__', ''))
            icon = self.plugin_info.get('icon', '⚙️')
        else:
            # Pour les plugins normaux
            name = self.plugin_info.get('name', self.plugin_name)
            icon = self.plugin_info.get('icon', '📦')
        
        logger.debug(f"Composition de l'élément {self.plugin_name} (is_sequence: {original_is_sequence})")
        
        # Déterminer les classes du label
        label_classes = "plugin-list-name"
        
        if original_is_sequence:
            # Style spécifique pour les séquences
            label_classes += " sequence-list-name"
        elif self.is_part_of_sequence:
            # Style pour les plugins faisant partie d'une séquence
            label_classes += " sequence-list-name"
            if self.sequence_id is not None:
                label_classes += f" sequence-item-name sequence-plugin sequence-{self.sequence_id}"
        
        # Création du texte à afficher
        if original_is_sequence:
            # Texte spécifique pour les séquences
            sequence_name = name if name else "Sans nom"
            display_text = f"{icon} SÉQUENCE: {sequence_name}"
        else:
            # Texte standard pour les plugins
            display_text = f"{icon}  {name}"
            
        # Créer et retourner le label avec désactivation de l'interprétation du markup
        yield Label(display_text, classes=label_classes, markup=False)
        
        # Créer un ID pour le bouton de suppression
        if original_is_sequence:
            # ID spécial pour les séquences
            safe_name = f"seq_{self.instance_id}"
        else:
            # Pour les plugins normaux, nettoyer le nom
            safe_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in self.plugin_name)
            # Éviter les ID trop longs
            if len(safe_name) > 20:
                safe_name = safe_name[:20]
            safe_name = f"{safe_name}_{self.instance_id}"
            
        button_id = f"remove_{safe_name}"
        
        # Déterminer les classes du bouton
        if original_is_sequence:
            button_classes = "remove-button sequence-remove-button"
        elif self.is_part_of_sequence:
            # Masquer le bouton pour les plugins d'une séquence
            button_classes = "remove-button hidden"
        else:
            button_classes = "remove-button"
        
        # Créer et retourner le bouton de suppression
        yield Button("X", id=button_id, variant="error", classes=button_classes)