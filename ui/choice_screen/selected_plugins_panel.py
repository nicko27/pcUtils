from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set
from textual.app import ComposeResult
from textual.containers import Container, VerticalGroup
from textual.widgets import Label, Button, Static
from textual.css.query import NoMatches

from .plugin_list_item import PluginListItem
from .plugin_card import PluginCard
from .sequence_handler import SequenceHandler
from ..utils.logging import get_logger

logger = get_logger('selected_plugins_panel')

class SelectedPluginsPanel(Static):
    """
    Panneau affichant les plugins sélectionnés et leur ordre.
    
    Cette classe gère l'affichage des plugins sélectionnés, leur organisation
    en séquences, et les actions associées (suppression).
    """
    
    def __init__(self, *args, **kwargs):
        """
        Initialise le panneau des plugins sélectionnés.
        
        Args:
            *args: Arguments positionnels pour la classe parente
            **kwargs: Arguments nommés pour la classe parente
        """
        super().__init__(*args, **kwargs)
        self.selected_plugins = []  # Liste des plugins sélectionnés
        self.sequence_map = {}      # Mapping des plugins appartenant à des séquences
        self.sequence_handler = SequenceHandler()  # Gestionnaire de séquences

    def compose(self) -> ComposeResult:
        """
        Compose l'interface du panneau.
        
        Returns:
            ComposeResult: Résultat de la composition
        """
        with VerticalGroup(id="selected-plugins-list"):
            yield Label("Plugins sélectionnés", id="selected-plugins-list-title")
            yield Container(id="selected-plugins-list-content")

    def update_plugins(self, plugins: List) -> None:
        """
        Met à jour l'affichage lorsque les plugins sélectionnés changent.
        
        Args:
            plugins: Liste des plugins sélectionnés (tuples plugin_name, instance_id, [config])
        """
        self.selected_plugins = plugins
        self._clear_content()
        
        if not plugins:
            self._show_empty_message()
            return

        # Analyser les relations de séquence
        self._analyze_sequence_relationships(plugins)
        
        # Créer les éléments de la liste
        self._create_plugin_items(plugins)
        
        logger.debug(f"Panneau mis à jour avec {len(plugins)} plugins")

    def _clear_content(self) -> None:
        """Efface le contenu du panneau."""
        try:
            container = self.query_one("#selected-plugins-list-content", Container)
            container.remove_children()
        except NoMatches:
            logger.error("Container #selected-plugins-list-content non trouvé")

    def _show_empty_message(self) -> None:
        """Affiche un message quand aucun plugin n'est sélectionné."""
        try:
            container = self.query_one("#selected-plugins-list-content", Container)
            container.mount(Label("Aucun plugin sélectionné", classes="no-plugins"))
        except NoMatches:
            logger.error("Container #selected-plugins-list-content non trouvé")

    def _analyze_sequence_relationships(self, plugins: List) -> None:
        """
        Analyse les relations de séquence entre les plugins.
        
        Cette méthode identifie quels plugins font partie de quelles séquences
        et construit une carte des relations.
        
        Args:
            plugins: Liste des plugins à analyser
        """
        # Réinitialiser le mapping et le set des plugins de séquence déjà associés
        self.sequence_map = {}
        self._matched_sequence_plugins = set()
        
        # Identifier les séquences dans la liste
        sequence_indices = {}  # {sequence_id: index_dans_liste}
        for idx, plugin_data in enumerate(plugins):
            plugin_name = plugin_data[0]
            instance_id = plugin_data[1]
            
            if not isinstance(plugin_name, str):
                logger.warning(f"Type de nom de plugin inattendu à l'index {idx}: {type(plugin_name)}")
                continue
                
            if plugin_name.startswith('__sequence__'):
                sequence_indices[instance_id] = idx
                logger.debug(f"Séquence détectée: {plugin_name}, ID: {instance_id}, index: {idx}")
                
                # Charger les détails de la séquence
                sequence_details = self._load_sequence_details(plugin_name)
                if sequence_details and 'plugins' in sequence_details:
                    self.sequence_map[instance_id] = {
                        'name': sequence_details.get('name', plugin_name.replace('__sequence__', '')),
                        'plugins': sequence_details.get('plugins', []),
                        'start_index': idx
                    }
        
        # Pour chaque plugin, vérifier s'il appartient à une séquence
        for idx, plugin_data in enumerate(plugins):
            if idx in sequence_indices.values():
                continue  # Ignorer les séquences elles-mêmes
                
            plugin_name = plugin_data[0]
            if not isinstance(plugin_name, str) or plugin_name.startswith('__sequence__'):
                continue
                
            # Extraire la configuration si disponible
            plugin_config = {}
            if len(plugin_data) >= 3:
                plugin_config = plugin_data[2]
                
            # Pour chaque séquence, vérifier si ce plugin fait partie de ses plugins
            for sequence_id, sequence_info in self.sequence_map.items():
                sequence_start_idx = sequence_info['start_index']
                
                # Un plugin fait partie d'une séquence s'il suit la séquence et correspond à un de ses plugins
                if idx > sequence_start_idx and self._plugin_matches_sequence(plugin_name, plugin_config, sequence_info['plugins']):
                    if 'member_indices' not in sequence_info:
                        sequence_info['member_indices'] = []
                    
                    sequence_info['member_indices'].append(idx)
                    logger.debug(f"Plugin {plugin_name} (index {idx}) identifié comme membre de la séquence {sequence_id}")
                    break

    def _load_sequence_details(self, sequence_name: str) -> Dict[str, Any]:
        """
        Charge les détails d'une séquence à partir de son fichier YAML.
        
        Args:
            sequence_name: Nom de la séquence (format __sequence__nom)
            
        Returns:
            Dict[str, Any]: Détails de la séquence ou dictionnaire vide si erreur
        """
        try:
            # Extraire le nom du fichier
            file_name = sequence_name.replace('__sequence__', '')
            if not file_name.endswith('.yml'):
                file_name = f"{file_name}.yml"
                
            sequence_path = Path('sequences') / file_name
            return self.sequence_handler.load_sequence(sequence_path) or {}
                
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence {sequence_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}

    def _plugin_matches_sequence(self, plugin_name: str, plugin_config: Dict[str, Any], 
                                sequence_plugins: List) -> bool:
        """
        Vérifie si un plugin correspond à l'un des plugins définis dans une séquence.
        
        Args:
            plugin_name: Nom du plugin à vérifier
            plugin_config: Configuration du plugin
            sequence_plugins: Liste des plugins dans la séquence
            
        Returns:
            bool: True si le plugin correspond à un plugin de la séquence
        """
        # Garder une trace des plugins de séquence déjà associés
        # pour éviter d'associer plusieurs instances réelles à la même instance de séquence
        if not hasattr(self, '_matched_sequence_plugins'):
            self._matched_sequence_plugins = set()
            
        for i, seq_plugin in enumerate(sequence_plugins):
            # Générer un identifiant unique pour cette entrée de séquence
            seq_entry_id = f"{i}"
            
            # Cas 1: Format dict avec 'name'
            if isinstance(seq_plugin, dict) and 'name' in seq_plugin:
                seq_plugin_name = seq_plugin['name']
                
                # Vérifier si le nom du plugin correspond
                if seq_plugin_name == plugin_name:
                    # Créer un identifiant unique pour cette entrée de séquence basé sur son nom et sa config
                    seq_config = {}
                    if 'config' in seq_plugin:
                        seq_config = seq_plugin['config']
                        seq_entry_id = f"{seq_plugin_name}_{i}_{str(seq_config)}"
                    elif 'variables' in seq_plugin:  # Rétrocompatibilité
                        seq_config = seq_plugin['variables']
                        seq_entry_id = f"{seq_plugin_name}_{i}_{str(seq_config)}"
                    else:
                        seq_entry_id = f"{seq_plugin_name}_{i}"
                    
                    # Vérifier si cette entrée de séquence a déjà été associée
                    if seq_entry_id in self._matched_sequence_plugins:
                        continue
                    
                    # Vérifier la configuration si présente
                    if seq_config and plugin_config:
                        # Une correspondance partielle suffit (configs supplémentaires autorisées)
                        all_keys_match = True
                        for key, value in seq_config.items():
                            if key not in plugin_config or plugin_config[key] != value:
                                all_keys_match = False
                                break
                                
                        if all_keys_match:
                            # Marquer cette entrée comme associée
                            self._matched_sequence_plugins.add(seq_entry_id)
                            return True
                    # Si pas de config dans la séquence ou dans le plugin
                    elif not seq_config and not plugin_config:
                        # Marquer cette entrée comme associée
                        self._matched_sequence_plugins.add(seq_entry_id)
                        return True
                        
            # Cas 2: Format simple (string)
            elif isinstance(seq_plugin, str) and seq_plugin == plugin_name:
                seq_entry_id = f"{seq_plugin}_{i}"
                
                # Vérifier si cette entrée de séquence a déjà été associée
                if seq_entry_id in self._matched_sequence_plugins:
                    continue
                    
                # Marquer cette entrée comme associée
                self._matched_sequence_plugins.add(seq_entry_id)
                return True
                
        return False

    def _create_plugin_items(self, plugins: List) -> None:
        """
        Crée et monte les éléments de liste pour les plugins sélectionnés.
        
        Args:
            plugins: Liste des plugins à afficher
        """
        try:
            container = self.query_one("#selected-plugins-list-content", Container)
        except NoMatches:
            logger.error("Container #selected-plugins-list-content non trouvé")
            return
            
        # Créer tous les éléments
        items = []
        for idx, plugin in enumerate(plugins, 1):
            item = None
            
            try:
                # Créer l'élément avec la configuration appropriée
                if len(plugin) >= 3:
                    plugin_name, instance_id, config = plugin
                    item = PluginListItem((plugin_name, instance_id, config), idx)
                else:
                    plugin_name, instance_id = plugin[:2]
                    item = PluginListItem((plugin_name, instance_id), idx)
                
                items.append(item)
            except Exception as e:
                logger.error(f"Erreur lors de la création de l'élément {idx}: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
        # Marquer les éléments qui font partie de séquences
        for sequence_id, sequence_info in self.sequence_map.items():
            if 'member_indices' in sequence_info:
                try:
                    # Trouver l'élément de la séquence elle-même
                    sequence_item = items[sequence_info['start_index']]
                    sequence_item.sequence_id = sequence_id
                    
                    # Marquer tous les membres de la séquence
                    for member_idx in sequence_info['member_indices']:
                        if 0 <= member_idx < len(items):
                            member_item = items[member_idx]
                            member_item.set_sequence_attributes(
                                is_part_of_sequence=True,
                                sequence_id=sequence_id,
                                sequence_name=sequence_info['name']
                            )
                except IndexError:
                    logger.error(f"Index hors limites lors du marquage des membres de séquence: {sequence_id}")
                except Exception as e:
                    logger.error(f"Erreur lors du marquage des membres de séquence {sequence_id}: {e}")
                    
        # Monter tous les éléments
        for item in items:
            try:
                container.mount(item)
            except Exception as e:
                logger.error(f"Erreur lors du montage de l'élément: {e}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """
        Gère les clics sur les boutons dans le panneau.
        
        Args:
            event: Événement de bouton pressé
        """
        if not event.button.id or not event.button.id.startswith('remove_'):
            return
            
        button_id = event.button.id
        is_sequence_button = 'sequence-remove-button' in event.button.classes
        
        try:
            if is_sequence_button:
                # Extraire l'ID de l'instance de séquence
                instance_id = int(button_id.replace('remove_seq_', ''))
                await self._remove_sequence_and_members(instance_id)
            else:
                # Extraction standard pour les plugins
                parts = button_id.replace('remove_', '').split('_')
                instance_id = int(parts[-1])
                plugin_name = '_'.join(parts[:-1])
                await self._remove_plugin(plugin_name, instance_id)
        except (ValueError, IndexError) as e:
            logger.error(f"Erreur lors de l'extraction de l'ID: {e} pour bouton {button_id}")
        except Exception as e:
            logger.error(f"Erreur inattendue lors du traitement du bouton {button_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _remove_sequence_and_members(self, sequence_id: int) -> None:
        """
        Supprime une séquence et tous ses membres.
        
        Args:
            sequence_id: ID de l'instance de la séquence
        """
        indices_to_remove = []
        
        # Trouver la séquence
        sequence_found = False
        sequence_name = None
        
        for idx, plugin_data in enumerate(self.app.selected_plugins):
            plugin_name, instance_id = plugin_data[0], plugin_data[1]
            
            if instance_id == sequence_id and plugin_name.startswith('__sequence__'):
                sequence_found = True
                sequence_name = plugin_name
                indices_to_remove.append(idx)
                break
                
        if not sequence_found:
            logger.error(f"Séquence non trouvée pour l'ID: {sequence_id}")
            return
            
        # Trouver les membres de la séquence
        if sequence_id in self.sequence_map and 'member_indices' in self.sequence_map[sequence_id]:
            for member_idx in self.sequence_map[sequence_id]['member_indices']:
                indices_to_remove.append(member_idx)
        # Alternativement, trouver les plugins qui suivent jusqu'à la prochaine séquence
        else:
            start_idx = indices_to_remove[0] + 1
            while start_idx < len(self.app.selected_plugins):
                plugin_name = self.app.selected_plugins[start_idx][0]
                if plugin_name.startswith('__sequence__'):
                    break
                indices_to_remove.append(start_idx)
                start_idx += 1
                
        # Trier les indices en ordre décroissant pour supprimer de la fin vers le début
        indices_to_remove.sort(reverse=True)
        
        # Supprimer les plugins
        for idx in indices_to_remove:
            if 0 <= idx < len(self.app.selected_plugins):
                self.app.selected_plugins.pop(idx)
                
        # Mettre à jour l'affichage
        self.update_plugins(self.app.selected_plugins)
        
        # Mettre à jour les cartes de plugins
        if sequence_name:
            await self._update_plugin_cards(sequence_name)

    async def _remove_plugin(self, plugin_name: str, instance_id: int) -> None:
        """
        Supprime un plugin spécifique de la liste.
        
        Args:
            plugin_name: Nom du plugin à supprimer
            instance_id: ID de l'instance à supprimer
        """
        # Créer une nouvelle liste sans le plugin spécifié
        new_selected_plugins = [
            p for p in self.app.selected_plugins 
            if not (p[0] == plugin_name and p[1] == instance_id)
        ]
        
        # Mettre à jour la liste
        self.app.selected_plugins = new_selected_plugins
        
        # Mettre à jour l'affichage
        self.update_plugins(self.app.selected_plugins)
        
        # Vérifier si c'était la dernière instance de ce plugin
        if not any(p[0] == plugin_name for p in self.app.selected_plugins):
            await self._update_plugin_cards(plugin_name)
            
    async def _update_plugin_cards(self, plugin_name: str) -> None:
        """
        Met à jour l'état des cartes de plugins.
        
        Args:
            plugin_name: Nom du plugin dont les cartes doivent être mises à jour
        """
        try:
            # Rechercher toutes les cartes correspondant au plugin
            for card in self.app.query(PluginCard):
                if card.plugin_name == plugin_name:
                    card.selected = False
                    card.update_styles()
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des cartes pour {plugin_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())