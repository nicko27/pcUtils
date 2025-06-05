"""
Module pour la gestion de la sélection des plugins.
Contient les classes et fonctions pour l'interface de sélection.
"""

from .plugin_utils import get_plugin_folder_name, load_plugin_info
from .plugin_card import PluginCard
from .plugin_list_item import PluginListItem
from .selected_plugins_panel import SelectedPluginsPanel

__all__ = [
    'get_plugin_folder_name',
    'load_plugin_info',
    'PluginCard',
    'PluginListItem',
    'SelectedPluginsPanel'
]