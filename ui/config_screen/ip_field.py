from textual.app import ComposeResult
from textual.widgets import Input
from textual.containers import VerticalGroup
from typing import Any, Optional, Tuple, cast
from .config_field import ConfigField
from ..utils.logging import get_logger

logger = get_logger('ip_field')

class IPField(ConfigField):
    """Champ d'adresse IP avec validation spécifique - Version indépendante de TextField"""
    
    def __init__(self, source_id: str, field_id: str, field_config: dict, fields_by_id: dict = None, is_global: bool = False):
        """Initialisation du champ IP avec une validation d'adresse IP spécifique"""
        # Initialiser les propriétés pour le contrôle des mises à jour AVANT d'appeler super().__init__
        self._internal_value: str = ""            # Valeur interne, toujours disponible
        self._updating_internally: bool = False   # Flag pour bloquer les mises à jour cycliques
        self._pending_value: Optional[str] = None # Valeur en attente (widget pas encore monté)
        
        # Maintenant appeler l'initialisation du parent
        super().__init__(source_id, field_id, field_config, fields_by_id, is_global)
        
        # Si la valeur a été modifiée par ConfigField via self.value, elle sera déjà dans self._internal_value
        # Sinon, initialiser avec la valeur par défaut
        if not self._internal_value and 'default' in self.field_config:
            initial_value = self.field_config.get('default', '')
            if initial_value is not None:
                self._internal_value = str(initial_value)
                logger.debug(f"Valeur initiale pour {self.field_id}: '{self._internal_value}'")
        
        logger.debug(f"Initialisation du champ IP {self.field_id}")
    
    def compose(self) -> ComposeResult:
        """Création des widgets du champ"""
        # Composer les éléments de base (label, etc.)
        logger.debug(f"🎨 Composition du champ IP {self.field_id}")
        yield from super().compose()
        
        # Essayer de récupérer la valeur de la séquence avant de créer le widget
        self._try_load_sequence_value()
        
        # Conteneur pour l'input
        with VerticalGroup(classes="input-container", id=f"container_{self.field_id}"):
            # Créer le widget Input avec la valeur interne actuelle
            input_value = self._internal_value
            logger.debug(f"💻 Création du widget IP pour {self.field_id} avec valeur: '{input_value}'")
            
            self.input = Input(
                placeholder=self.field_config.get('placeholder', ''),
                value=input_value,
                id=f"input_{self.field_id}"
            )
            # État initial: activé
            self.input.disabled = False
            self.input.remove_class('disabled')

            # Si le champ est désactivé via enabled_if
            if self.disabled:
                logger.debug(f"Champ IP {self.field_id} désactivé initialement")
                self.input.disabled = True
                self.input.add_class('disabled')
            yield self.input
    
    def validate_input(self, value: str) -> Tuple[bool, str]:
        """Validation spécifique pour les adresses IP"""
        # Si le champ est désactivé, pas de validation nécessaire
        if self.disabled:
            return True, ""
            
        # Champ obligatoire
        if self.field_config.get('required', False) and not value:
            return False, "Ce champ ne peut pas être vide"
            
        # Si la valeur est vide et le champ n'est pas obligatoire, c'est valide
        if not value:
            return True, ""
            
        # Validation du format IP
        import re
        ip_pattern = r'^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if not re.match(ip_pattern, value):
            return False, "Format d'adresse IP invalide"
            
        return True, ""
        
    def on_input_changed(self, event: Input.Changed) -> None:
        """Gestion des changements d'entrée avec validation IP spécifique"""
        # Vérifier que c'est bien notre input qui a changé
        if event.input.id != f"input_{self.field_id}":
            return
            
        # Si nous sommes déjà en train de mettre à jour l'input, ignorer
        if self._updating_internally:
            logger.debug(f"⚠️ Ignorer on_input_changed pendant mise à jour pour {self.field_id}")
            return
        
        # Récupérer la valeur de l'événement
        value = str(event.value) if event.value is not None else ""
        
        # Si la valeur n'a pas changé par rapport à notre valeur interne, ne rien faire
        if self._internal_value == value:
            logger.debug(f"✓ Valeur IP déjà à '{value}' pour {self.field_id}")
            return
        
        logger.debug(f"👁️ Changement d'adresse IP pour {self.field_id}: '{self._internal_value}' → '{value}'")
        
        # Appliquer la valeur sans mettre à jour l'input qui vient d'être modifié par l'utilisateur
        self.set_value(value, update_input=False)
    
    def _set_widget_value(self, value: str) -> None:
        """Méthode spécialisée pour mettre à jour le widget avec validation IP"""
        # Gérer le cas où le widget n'existe pas encore
        if not hasattr(self, 'input'):
            # Stocker la valeur en attente pour l'appliquer plus tard
            self._pending_value = value
            logger.debug(f"Widget input pas encore créé pour {self.field_id}, valeur en attente: '{value}'")
            return
        
        # Vérifier si la valeur actuelle est différente
        current_widget_value = self.input.value
        if current_widget_value == value:
            logger.debug(f"Widget IP déjà à '{value}' pour {self.field_id}")
            return
        
        # Mise à jour du widget
        logger.debug(f"Mise à jour du widget IP pour {self.field_id}: '{current_widget_value}' → '{value}'")
        self.input.value = value
        
        # Validation IP spécialisée et indication visuelle
        is_valid, error_msg = self.validate_input(value)
        if is_valid:
            self.input.remove_class('error')
            self.input.tooltip = None
        else:
            self.input.add_class('error')
            self.input.tooltip = error_msg
    
    def set_value(self, value: str, update_input: bool = True, update_dependencies: bool = True) -> bool:
        """Définit la valeur du champ avec mécanisme anti-cycles complet"""
        # Conversion à la chaîne pour uniformité
        value_str = str(value) if value is not None else ""
        
        # ===== PHASE 1: Vérifications préliminaires =====
        logger.debug(f"🔔 set_value({value_str}) pour {self.field_id}, update_input={update_input}")
        
        # Vérification 1: Prévenir les mises à jour récursives
        if self._updating_internally:
            logger.debug(f"⚠️ Déjà en cours de mise à jour pour {self.field_id}, évitement cycle")
            return True
            
        # Vérification 2: Valeur identique à la valeur interne actuelle
        if self._internal_value == value_str:
            logger.debug(f"✓ Valeur interne déjà à '{value_str}' pour {self.field_id}")
            return True
        
        # Marquer le début de la mise à jour
        self._updating_internally = True
        
        try:
            # ===== PHASE 2: Mise à jour de la valeur interne =====
            old_value = self._internal_value
            self._internal_value = value_str
            logger.debug(f"💾 Valeur interne mise à jour pour {self.field_id}: '{old_value}' → '{value_str}'")
            
            # ===== PHASE 3: Mise à jour du widget si demandé =====
            if update_input:
                self._set_widget_value(value_str)
                
            # ===== PHASE 4: Mise à jour des dépendances si demandé =====
            if update_dependencies:
                from .config_container import ConfigContainer
                parent = next((a for a in self.ancestors_with_self if isinstance(a, ConfigContainer)), None)
                if parent:
                    logger.debug(f"🔗 Notification des dépendances pour {self.field_id}")
                    parent.update_dependent_fields(self)
            
            logger.debug(f"✅ set_value réussi pour {self.field_id}")
            return True
            
        except Exception as e:
            # Capturer les exceptions pour éviter de bloquer l'interface
            logger.error(f"❌ Erreur dans set_value pour {self.field_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
        finally:
            # CRUCIAL: Toujours réinitialiser le flag pour permettre des mises à jour futures
            self._updating_internally = False
    
    def _try_load_sequence_value(self):
        """Essaie de charger la valeur depuis la configuration prédéfinie (séquence)"""
        try:
            # Trouver l'écran de configuration
            from .config_screen import PluginConfig
            config_screen = None
            
            # Rechercher l'écran de configuration dans la hiérarchie des ancêtres
            app = self.app if hasattr(self, 'app') and self.app else None
            if app and hasattr(app, 'screen') and isinstance(app.screen, PluginConfig):
                config_screen = app.screen
            
            if not config_screen or not hasattr(config_screen, 'current_config'):
                return
            
            # Récupérer le conteneur parent
            from .plugin_config_container import PluginConfigContainer
            parent = next((a for a in self.ancestors_with_self if isinstance(a, PluginConfigContainer)), None)
            if not parent or not hasattr(parent, 'id'):
                return
            
            # Récupérer l'ID de l'instance du plugin
            plugin_instance_id = parent.id.replace('plugin_', '')
            if plugin_instance_id not in config_screen.current_config:
                return
                
            # Récupérer la configuration prédéfinie
            predefined_config = config_screen.current_config[plugin_instance_id]
            
            # Obtenir la variable ou config, selon le format
            variable_name = self.field_config.get('variable', self.field_id)
            
            # Chercher dans 'config' (nouveau format)
            if 'config' in predefined_config and variable_name in predefined_config['config']:
                value = predefined_config['config'][variable_name]
                if value is not None:
                    logger.debug(f"💾 Valeur trouvée dans séquence pour {self.field_id}: '{value}'")
                    self._internal_value = str(value) if value is not None else ""
                    return
                    
            # Format 2: Chercher directement (ancien format)
            elif variable_name in predefined_config:
                value = predefined_config[variable_name]
                if value is not None:
                    logger.debug(f"💾 Valeur trouvée dans séquence (ancien format) pour {self.field_id}: '{value}'")
                    self._internal_value = str(value) if value is not None else ""
                    return
                    
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la valeur de séquence pour {self.field_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def get_value(self) -> str:
        """Récupère la valeur du champ IP, avec gestion des cas spéciaux"""
        # Priorité 1: Si le widget input existe, récupérer sa valeur directement
        if hasattr(self, 'input') and self.input is not None:
            input_value = self.input.value
            # Mettre à jour la valeur interne pour être cohérent
        if input_value != self._internal_value:
            logger.debug(f"Synchronisation de la valeur interne avec le widget pour {self.field_id}: '{self._internal_value}' → '{input_value}'")
            self._internal_value = input_value
        return input_value
        
        # Priorité 2: Si on a une valeur en attente, la renvoyer
        if hasattr(self, '_pending_value') and self._pending_value is not None:
            return self._pending_value
        
        # Priorité 3: Récupérer la valeur interne
        return self._internal_value
        
    # Interface de propriété pour accès simplifié
    @property
    def value(self) -> str:
        """Accès à la valeur interne"""
        return self._internal_value
        
    @value.setter
    def value(self, new_value: Any) -> None:
        """Modification de la valeur via l'accesseur"""
        # Déléguer à set_value, sans notification pour éviter les cycles
        if self._updating_internally:
            self._internal_value = str(new_value) if new_value is not None else ""
        else:
            self.set_value(new_value, update_dependencies=False)
            
    def restore_default(self) -> bool:
        """
        Réinitialise le champ IP à sa valeur par défaut définie dans la configuration.
        Prend en compte les valeurs par défaut dynamiques définies via des scripts.
        
        Returns:
            bool: True si la réinitialisation a réussi
        """
        try:
            # Vérifier si une valeur par défaut dynamique est définie
            if 'dynamic_default' in self.field_config and hasattr(self, '_get_dynamic_default'):
                logger.debug(f"Récupération de la valeur par défaut dynamique pour {self.field_id}")
                dynamic_value = self._get_dynamic_default()
                
                if dynamic_value is not None:
                    logger.debug(f"Réinitialisation du champ IP {self.field_id} à la valeur dynamique: '{dynamic_value}'")
                    return self.set_value(dynamic_value, update_input=True, update_dependencies=True)
                else:
                    logger.warning(f"Valeur dynamique non disponible pour {self.field_id}, utilisation de la valeur par défaut statique")
            
            # Sinon, utiliser la valeur par défaut statique
            default_value = self.field_config.get('default', '')
            logger.debug(f"Réinitialisation du champ IP {self.field_id} à la valeur par défaut statique: '{default_value}'")
            
            # Utiliser notre propre méthode set_value pour appliquer la valeur par défaut
            return self.set_value(default_value, update_input=True, update_dependencies=True)
        except Exception as e:
            logger.error(f"Erreur lors de la réinitialisation du champ IP {self.field_id}: {e}")
            return False
