"""
Gestionnaire de configuration des séquences.
Gère le chargement, la fusion et l'application des configurations de séquence aux plugins.
"""

from pathlib import Path
from ruamel.yaml import YAML
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from ..utils.logging import get_logger

logger = get_logger('sequence_config_manager')
yaml = YAML()
yaml.preserve_quotes = True

class SequenceConfigManager:
    """
    Gestionnaire de configuration des séquences
    
    Cette classe est responsable de:
    - Charger les configurations depuis les fichiers de séquence
    - Fusionner les configurations de différentes sources
    - Appliquer les configurations aux plugins sélectionnés
    - Gérer la rétrocompatibilité entre les anciens formats (variables) et nouveaux (config)
    """
    
    def __init__(self):
        """Initialise le gestionnaire de configuration."""
        # Données brutes de la séquence chargée
        self.sequence_data = None
        
        # Configurations indexées par nom de plugin -> liste de configurations
        # Chaque configuration est un dictionnaire avec format standardisé
        self.sequence_configs = {}
        
        # Configurations finales indexées par ID d'instance unique (plugin_name_instance_id)
        # Contient les configurations fusionnées prêtes à être utilisées
        self.current_config = {}
        
        # Ensemble des plugins qui ont déjà été associés à une configuration de séquence
        # Utilisé pour éviter d'associer plusieurs fois un plugin à une même configuration
        self._matched_plugins = set()
        
        logger.debug("Gestionnaire de configuration des séquences initialisé")
    
    def load_sequence(self, sequence_file: Union[str, Path]) -> None:
        """
        Charge une séquence depuis un fichier YAML.
        
        Args:
            sequence_file: Chemin vers le fichier de séquence
            
        Raises:
            FileNotFoundError: Si le fichier n'existe pas
            ValueError: Si le format de la séquence est invalide
        """
        try:
            # Convertir en Path si nécessaire
            sequence_path = Path(sequence_file) if isinstance(sequence_file, str) else sequence_file
            logger.debug(f"=== Chargement de la séquence: {sequence_path} ===")
            
            # Vérifier que le fichier existe
            if not sequence_path.exists():
                logger.error(f"Fichier de séquence non trouvé: {sequence_path}")
                raise FileNotFoundError(f"Fichier de séquence non trouvé: {sequence_path}")
            
            # Charger le contenu YAML
            with open(sequence_path, 'r', encoding='utf-8') as f:
                self.sequence_data = yaml.load(f)
            
            # Valider la structure de base
            if not isinstance(self.sequence_data, dict):
                logger.error(f"Format invalide: la séquence n'est pas un dictionnaire")
                raise ValueError("La séquence doit être un dictionnaire")
            
            # Vérifier les champs obligatoires
            required_fields = ['name', 'plugins']
            missing_fields = [field for field in required_fields if field not in self.sequence_data]
            if missing_fields:
                logger.error(f"Champs requis manquants: {', '.join(missing_fields)}")
                raise ValueError(f"Champs requis manquants: {', '.join(missing_fields)}")
            
            # Vérifier que plugins est une liste
            if not isinstance(self.sequence_data['plugins'], list):
                logger.error("Le champ 'plugins' doit être une liste")
                raise ValueError("Le champ 'plugins' doit être une liste")
            
            # Ajouter une description par défaut si absente
            if 'description' not in self.sequence_data:
                self.sequence_data['description'] = f"Séquence {self.sequence_data['name']}"
            
            logger.debug(f"Séquence chargée: {self.sequence_data['name']} " +
                         f"avec {len(self.sequence_data['plugins'])} plugins")
            
            # Initialiser le mapping des configurations par plugin
            self._init_sequence_configs()
            
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence: {e}")
            raise
    
    def _init_sequence_configs(self) -> None:
        """
        Initialise le mapping des configurations par plugin.
        Normalise et convertit toutes les configurations au format standardisé.
        """
        # Réinitialiser le dictionnaire
        self.sequence_configs = {}
        
        # Vérifier que les données de séquence existent
        if not self.sequence_data or 'plugins' not in self.sequence_data:
            logger.warning("Aucune donnée de séquence à initialiser")
            return
        
        # Parcourir tous les plugins de la séquence
        for position, plugin_config in enumerate(self.sequence_data['plugins']):
            # Traiter différents formats possibles
            
            # Format 1: Chaîne simple (juste le nom du plugin)
            if isinstance(plugin_config, str):
                plugin_name = plugin_config
                normalized_config = {
                    'plugin_name': plugin_name,
                    'config': {},
                    'position': position
                }
                
            # Format 2: Dictionnaire avec configuration
            elif isinstance(plugin_config, dict) and 'name' in plugin_config:
                plugin_name = plugin_config['name']
                
                # Créer une structure de configuration standardisée
                normalized_config = {
                    'plugin_name': plugin_name,
                    'config': {},
                    'position': position
                }
                
                # Gestion de la configuration avec rétrocompatibilité
                # Format moderne: utilise 'config'
                if 'config' in plugin_config:
                    if isinstance(plugin_config['config'], dict):
                        normalized_config['config'] = plugin_config['config'].copy()
                    else:
                        logger.warning(f"Format 'config' invalide pour {plugin_name} " +
                                      f"(position {position}): doit être un dictionnaire")
                
                # Format ancien: utilise 'variables'
                elif 'variables' in plugin_config:
                    if isinstance(plugin_config['variables'], dict):
                        normalized_config['config'] = plugin_config['variables'].copy()
                        logger.debug(f"Conversion du format ancien 'variables' " +
                                    f"vers 'config' pour {plugin_name}")
                    else:
                        logger.warning(f"Format 'variables' invalide pour {plugin_name} " +
                                      f"(position {position}): doit être un dictionnaire")
                
                # Copier les attributs spéciaux au niveau principal
                special_keys = {
                    'show_name', 'icon', 'remote_execution', 
                    'template', 'ignore_errors', 'timeout'
                }
                
                for key in special_keys:
                    if key in plugin_config:
                        normalized_config[key] = plugin_config[key]
            
            # Format invalide
            else:
                logger.warning(f"Plugin invalide à la position {position}: " +
                              f"doit être une chaîne ou un dictionnaire avec 'name'")
                continue
            
            # Ajouter au dictionnaire des configurations
            if plugin_name not in self.sequence_configs:
                self.sequence_configs[plugin_name] = []
            
            self.sequence_configs[plugin_name].append(normalized_config)
            
            logger.debug(f"Configuration ajoutée pour {plugin_name} (position {position})")
    
    def add_plugin_config(self, plugin_name: str, instance_id: Union[int, str], 
                         config: Dict[str, Any]) -> None:
        """
        Ajoute manuellement une configuration de plugin existante.
        Utile pour les configurations qui ne viennent pas d'une séquence.
        
        Args:
            plugin_name: Nom du plugin
            instance_id: ID unique de l'instance
            config: Configuration existante du plugin
        """
        # Créer un ID unique standardisé
        plugin_instance_id = f"{plugin_name}_{instance_id}"
        
        # Créer une structure de configuration standardisée
        normalized_config = {
            'plugin_name': plugin_name,
            'instance_id': instance_id,
            'config': {}
        }
        
        # Format 1: La configuration a déjà une structure 'config'
        if 'config' in config and isinstance(config['config'], dict):
            normalized_config['config'] = config['config'].copy()
        
        # Format 2: Ancienne structure plate
        else:
            # Identifier les clés spéciales vs. les clés de configuration
            special_keys = {
                'plugin_name', 'instance_id', 'name', 'show_name', 
                'icon', 'remote_execution', 'template'
            }
            
            # Copier les valeurs non spéciales dans config
            config_values = {k: v for k, v in config.items() if k not in special_keys}
            normalized_config['config'] = config_values
            
            # Copier les clés spéciales au niveau principal
            for key in special_keys:
                if key in config:
                    normalized_config[key] = config[key]
        
        # Stocker dans current_config avec l'ID standardisé
        self.current_config[plugin_instance_id] = normalized_config
        
        # Ajouter également à sequence_configs pour la fusion ultérieure
        if plugin_name not in self.sequence_configs:
            self.sequence_configs[plugin_name] = []
        
        self.sequence_configs[plugin_name].append(normalized_config)
        
        logger.debug(f"Configuration ajoutée manuellement pour {plugin_name} " +
                    f"(ID: {instance_id}) avec {len(normalized_config['config'])} paramètres")
    
    def apply_configs_to_plugins(self, plugin_instances: List[Tuple[str, Union[int, str], Optional[Dict]]]) -> Dict[str, Dict]:
        """
        Applique les configurations aux plugins sélectionnés.
        Fusionne les configurations de différentes sources selon l'ordre de priorité.
        
        Args:
            plugin_instances: Liste de tuples (plugin_name, instance_id, config?)
            
        Returns:
            Dict[str, Dict]: Configurations finales indexées par plugin_instance_id
        """
        # Réinitialiser les configurations finales et l'ensemble des plugins associés
        result_config = {}
        self._matched_plugins = set()
        
        logger.debug("=== DÉBUT FUSION DES CONFIGURATIONS ===")
        logger.debug(f"Plugins à configurer: {len(plugin_instances)}")
        logger.debug(f"Configuration initiale: {self.current_config}")
        
        # Compteurs pour suivre les instances de chaque type de plugin
        plugin_counters = {}
        
        # Créer un mapping des instances de séquence par plugin
        sequence_plugin_instances = self._index_sequence_plugins_by_type()
        
        # Parcourir tous les plugins sélectionnés
        for plugin_data in plugin_instances:
            # Extraire les données du plugin
            if len(plugin_data) >= 3:
                plugin_name, instance_id, existing_config = plugin_data
            else:
                plugin_name, instance_id = plugin_data[:2]
                existing_config = None
            
            # Ignorer les plugins spéciaux comme les séquences
            if isinstance(plugin_name, str) and plugin_name.startswith('__'):
                logger.debug(f"Plugin spécial ignoré: {plugin_name}")
                continue
            
            # Incrémenter le compteur pour ce type de plugin
            if plugin_name not in plugin_counters:
                plugin_counters[plugin_name] = 0
            current_count = plugin_counters[plugin_name]
            plugin_counters[plugin_name] += 1
            
            # Créer un ID unique standardisé
            plugin_instance_id = f"{plugin_name}_{instance_id}"
            
            logger.debug(f"Traitement du plugin {plugin_instance_id} " +
                        f"(instance {current_count + 1} de {plugin_name})")
            
            # 1. CRÉATION DE LA CONFIGURATION DE BASE
            config_data = self._create_base_config(plugin_name, instance_id)
            
            # 2. FUSION DES CONFIGURATIONS SELON PRIORITÉ
            
            # Priorité 1: Configuration par défaut existante dans self.current_config
            if plugin_instance_id in self.current_config:
                default_config = self.current_config[plugin_instance_id]
                logger.debug(f"Configuration par défaut trouvée pour {plugin_instance_id}: {default_config}")
                
                # Fusionner la configuration par défaut
                if 'config' in default_config and isinstance(default_config['config'], dict):
                    # Ne remplacer que si la configuration n'est pas vide
                    if default_config['config']:
                        config_data['config'].update(default_config['config'])
                        logger.debug(f"Configuration par défaut appliquée: " +
                                    f"{len(default_config['config'])} paramètres")
                
                # Copier les attributs spéciaux
                self._copy_special_attributes(default_config, config_data)
            
            # Priorité 2: Configuration de séquence si disponible
            existing_config_data = None
            if plugin_instance_id in self.current_config and 'config' in self.current_config[plugin_instance_id]:
                existing_config_data = self.current_config[plugin_instance_id]['config']
            seq_config = self._get_sequence_config(plugin_name, current_count, sequence_plugin_instances, existing_config_data)
            if seq_config:
                if 'config' in seq_config and isinstance(seq_config['config'], dict):
                    # Mise à jour avec la configuration de séquence (écrase les valeurs par défaut)
                    config_data['config'].update(seq_config['config'])
                    logger.debug(f"Configuration de séquence appliquée: " +
                                f"{len(seq_config['config'])} paramètres")
                
                # Copier les attributs spéciaux
                self._copy_special_attributes(seq_config, config_data)
            
            # Priorité 3: Configuration spécifique fournie (priorité maximale)
            if existing_config:
                config_data = self._merge_existing_config(config_data, existing_config)
                logger.debug("Configuration spécifique appliquée (priorité maximale)")
            
            # Enregistrer la configuration finale
            result_config[plugin_instance_id] = config_data
            logger.debug(f"Configuration finale pour {plugin_instance_id}: " +
                        f"{len(config_data['config'])} paramètres")
        
        logger.debug(f"=== CONFIGURATIONS FINALES: {len(result_config)} plugins configurés ===")
        return result_config
    
    def _index_sequence_plugins_by_type(self) -> Dict[str, List[int]]:
        """
        Crée un index des plugins dans la séquence par type.
        
        Returns:
            Dict[str, List[int]]: Pour chaque type de plugin, la liste des indices dans la séquence
        """
        sequence_plugins = {}
        
        if not self.sequence_data or 'plugins' not in self.sequence_data:
            return sequence_plugins
        
        for i, plugin_config in enumerate(self.sequence_data['plugins']):
            # Format 1: Chaîne simple (juste le nom du plugin)
            if isinstance(plugin_config, str):
                plugin_name = plugin_config
            
            # Format 2: Dictionnaire avec 'name'
            elif isinstance(plugin_config, dict) and 'name' in plugin_config:
                plugin_name = plugin_config['name']
            
            # Format invalide
            else:
                continue
            
            # Ajouter à l'index
            if plugin_name not in sequence_plugins:
                sequence_plugins[plugin_name] = []
            
            sequence_plugins[plugin_name].append(i)
        
        return sequence_plugins
    
    def _create_base_config(self, plugin_name: str, instance_id: Union[int, str]) -> Dict[str, Any]:
        """
        Crée une configuration de base pour un plugin.
        
        Args:
            plugin_name: Nom du plugin
            instance_id: ID de l'instance
            
        Returns:
            Dict[str, Any]: Configuration de base
        """
        return {
            'plugin_name': plugin_name,
            'instance_id': instance_id,
            'name': plugin_name,  # Sera remplacé par un nom plus descriptif si disponible
            'config': {}
        }
        
    def _get_sequence_config(self, plugin_name: str, instance_index: int,
                        sequence_plugin_instances: Dict[str, List[int]],
                        existing_config: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Récupère la configuration de séquence la plus appropriée pour un plugin.
        
        Args:
            plugin_name: Nom du plugin
            instance_index: Index de l'instance de ce type de plugin
            sequence_plugin_instances: Index des plugins par type dans la séquence
            existing_config: Configuration existante pour aider à trouver la meilleure correspondance
            
        Returns:
            Optional[Dict[str, Any]]: Configuration de séquence ou None si non trouvée
        """
        # Vérifier si ce type de plugin existe dans la séquence
        if plugin_name not in sequence_plugin_instances:
            return None
        
        # Récupérer tous les indices de ce type de plugin dans la séquence
        plugin_indices = sequence_plugin_instances[plugin_name]
        
        # Si pas d'indices disponibles, retourner None
        if not plugin_indices:
            return None
        
        # Si pas de configuration existante, utiliser l'approche par index
        if not existing_config:
            # Vérifier si nous avons assez d'instances pour cet index
            if instance_index >= len(plugin_indices):
                return None
            
            sequence_index = plugin_indices[instance_index]
        else:
            # Chercher la meilleure correspondance basée sur la configuration existante
            best_match_index = None
            best_match_score = -1
            
            for seq_idx in plugin_indices:
                # Vérifier si ce plugin a déjà été associé
                association_key = f"{plugin_name}_{seq_idx}"
                if association_key in self._matched_plugins:
                    continue
                    
                # Récupérer la configuration de la séquence
                seq_plugin_config = self.sequence_data['plugins'][seq_idx]
                
                # Ignorer les formats simples (chaînes)
                if isinstance(seq_plugin_config, str):
                    continue
                    
                # Récupérer la configuration
                seq_config = {}
                if 'config' in seq_plugin_config and isinstance(seq_plugin_config['config'], dict):
                    seq_config = seq_plugin_config['config']
                elif 'variables' in seq_plugin_config and isinstance(seq_plugin_config['variables'], dict):
                    seq_config = seq_plugin_config['variables']
                
                # Calculer un score de correspondance
                match_score = 0
                for key, value in existing_config.items():
                    if key in seq_config and seq_config[key] == value:
                        match_score += 1
                
                # Mettre à jour la meilleure correspondance si nécessaire
                if match_score > best_match_score:
                    best_match_score = match_score
                    best_match_index = seq_idx
            
            # Utiliser la meilleure correspondance ou l'index par défaut
            if best_match_index is not None:
                sequence_index = best_match_index
            elif instance_index < len(plugin_indices):
                sequence_index = plugin_indices[instance_index]
            else:
                return None
        
        # Créer un identifiant unique pour ce couple (plugin, position)
        association_key = f"{plugin_name}_{sequence_index}"
        
        # Vérifier si ce plugin a déjà été associé
        if association_key in self._matched_plugins:
            logger.debug(f"Plugin {plugin_name} à la position {sequence_index} déjà associé")
            return None
        
        # Marquer comme associé
        self._matched_plugins.add(association_key)
        
        # Récupérer et normaliser la configuration
        plugin_config = self.sequence_data['plugins'][sequence_index]
        
        # Format 1: Chaîne simple (juste le nom)
        if isinstance(plugin_config, str):
            return {'config': {}}
        
        # Format 2: Dictionnaire avec configuration
        elif isinstance(plugin_config, dict) and plugin_config.get('name') == plugin_name:
            # Normaliser la configuration
            normalized_config = {'config': {}}
            
            # Traiter 'config' ou 'variables'
            if 'config' in plugin_config and isinstance(plugin_config['config'], dict):
                normalized_config['config'] = plugin_config['config'].copy()
            elif 'variables' in plugin_config and isinstance(plugin_config['variables'], dict):
                normalized_config['config'] = plugin_config['variables'].copy()
            
            # Copier les attributs spéciaux
            special_keys = {
                'name', 'show_name', 'icon', 'remote_execution', 
                'template', 'ignore_errors', 'timeout'
            }
            
            for key in special_keys:
                if key in plugin_config:
                    normalized_config[key] = plugin_config[key]
            
            return normalized_config
        
        # Aucune configuration trouvée
        return None
    
    def _copy_special_attributes(self, source: Dict[str, Any], target: Dict[str, Any]) -> None:
        """
        Copie les attributs spéciaux d'une configuration à une autre.
        
        Args:
            source: Configuration source
            target: Configuration cible
        """
        special_keys = {
            'name', 'show_name', 'icon', 'remote_execution', 
            'template', 'ignore_errors', 'timeout'
        }
        
        for key in special_keys:
            if key in source:
                target[key] = source[key]
    
    def _merge_existing_config(self, base_config: Dict[str, Any], 
                             existing_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fusionne une configuration existante dans la configuration de base.
        La configuration existante a la priorité maximale.
        
        Args:
            base_config: Configuration de base
            existing_config: Configuration existante à fusionner
            
        Returns:
            Dict[str, Any]: Configuration fusionnée
        """
        # Créer une copie de la configuration de base
        merged_config = base_config.copy()
        
        # Format 1: La configuration a déjà une structure 'config'
        if 'config' in existing_config and isinstance(existing_config['config'], dict):
            merged_config['config'].update(existing_config['config'])
        
        # Format 2: Ancienne structure plate
        else:
            # Identifier les clés spéciales vs. les clés de configuration
            special_keys = {
                'plugin_name', 'instance_id', 'name', 'show_name', 
                'icon', 'remote_execution', 'template'
            }
            
            # Copier les valeurs non spéciales dans config
            config_values = {k: v for k, v in existing_config.items() if k not in special_keys}
            merged_config['config'].update(config_values)
        
        # Copier les attributs spéciaux
        self._copy_special_attributes(existing_config, merged_config)
        
        return merged_config
    
    def get_normalized_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Retourne une copie des configurations actuelles, toutes normalisées.
        
        Returns:
            Dict[str, Dict[str, Any]]: Configurations normalisées
        """
        return self.current_config.copy()
    
    def clear(self) -> None:
        """
        Réinitialise complètement le gestionnaire.
        """
        self.sequence_data = None
        self.sequence_configs = {}
        self.current_config = {}
        self._matched_plugins = set()
        logger.debug("Gestionnaire de configuration réinitialisé")