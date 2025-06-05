"""
Gestionnaire de séquences pour l'écran de sélection.
Gère le chargement, la validation et la gestion des séquences de plugins.
"""

from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Union, Set
from ruamel.yaml import YAML
from ..utils.logging import get_logger
import os
import time

logger = get_logger('sequence_handler')

class SequenceHandler:
    """
    Gestionnaire de séquences pour l'écran de sélection.
    
    Cette classe est responsable de:
    - Charger et valider les fichiers de séquence YAML
    - Gérer le cache des séquences pour optimiser les performances
    - Fournir les métadonnées des séquences disponibles
    - Rechercher des séquences par raccourci (shortcut)
    - Sauvegarder les séquences
    """

    def __init__(self):
        """
        Initialise le gestionnaire de séquences et crée le dossier si nécessaire.
        """
        # Répertoire de stockage des séquences
        self.sequences_dir = Path('sequences')
        
        # Caches pour optimiser les performances
        self.sequence_cache = {}          # Cache des séquences par chemin
        self.shortcut_cache = {}          # Cache des raccourcis vers les chemins
        self.available_sequences_cache = None  # Cache de la liste des séquences
        self.last_refresh_time = 0        # Horodatage du dernier rafraîchissement du cache
        
        # Instance YAML configurée pour préserver la structure des fichiers
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        
        # Créer le dossier sequences s'il n'existe pas
        self._ensure_sequences_dir()
        
        logger.debug(f"Initialisation du gestionnaire de séquences: {self.sequences_dir}")

    def _ensure_sequences_dir(self) -> None:
        """
        S'assure que le dossier des séquences existe, le crée si nécessaire.
        """
        if not self.sequences_dir.exists():
            try:
                self.sequences_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Dossier de séquences créé: {self.sequences_dir}")
            except Exception as e:
                logger.error(f"Impossible de créer le dossier de séquences: {e}")
                import traceback
                logger.error(traceback.format_exc())

    def load_sequence(self, sequence_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Charge une séquence depuis un fichier YAML avec cache.
        
        Args:
            sequence_path: Chemin vers le fichier de séquence
            
        Returns:
            Dict[str, Any]: Données de la séquence ou None en cas d'erreur
        """
        # Convertir en Path si nécessaire
        if isinstance(sequence_path, str):
            sequence_path = Path(sequence_path)
        
        # Convertir en str pour l'utilisation comme clé de cache
        cache_key = str(sequence_path)
        
        # Vérifier si le fichier a été modifié depuis le dernier chargement
        if cache_key in self.sequence_cache:
            # Vérifier si le fichier existe avant de tester sa date de modification
            if sequence_path.exists():
                file_mtime = sequence_path.stat().st_mtime
                cache_entry = self.sequence_cache[cache_key]
                
                # Si nous avons un horodatage et qu'il est récent, retourner la version en cache
                if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
                    cache_data, cache_mtime = cache_entry
                    
                    # Utiliser la version en cache si elle est à jour
                    if cache_mtime >= file_mtime:
                        logger.debug(f"Utilisation de la version en cache pour {sequence_path.name}")
                        return cache_data
                    else:
                        logger.debug(f"Version en cache obsolète pour {sequence_path.name}, rechargement")
                else:
                    # Ancienne structure de cache, retourner directement (pour compatibilité)
                    logger.debug(f"Séquence trouvée dans le cache (ancien format): {cache_key}")
                    return self.sequence_cache[cache_key]
        
        # Si on arrive ici, on doit charger le fichier
        try:
            if not sequence_path.exists():
                logger.error(f"Fichier de séquence non trouvé: {sequence_path}")
                return None

            with open(sequence_path, 'r', encoding='utf-8') as f:
                sequence = self.yaml.load(f)

            # Valider la séquence
            validation_result, error_message = self.validate_sequence(sequence)
            if not validation_result:
                logger.error(f"Séquence invalide ({sequence_path}): {error_message}")
                return None

            # Ajouter au cache avec l'horodatage
            file_mtime = sequence_path.stat().st_mtime
            self.sequence_cache[cache_key] = (sequence, file_mtime)
            
            logger.info(f"Séquence chargée et mise en cache: {sequence.get('name', 'Sans nom')}")
            return sequence

        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence {sequence_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def validate_sequence(self, sequence: Any) -> Tuple[bool, str]:
        """
        Valide le format d'une séquence.
        
        Args:
            sequence: Données de la séquence à valider
            
        Returns:
            Tuple[bool, str]: Tuple (validité, message d'erreur)
        """
        if not isinstance(sequence, dict):
            return False, "La séquence doit être un dictionnaire"

        # Vérifier les champs requis
        required_fields = ['name', 'plugins']
        missing_fields = [field for field in required_fields if field not in sequence]
        if missing_fields:
            return False, f"Champs requis manquants: {', '.join(missing_fields)}"

        if not isinstance(sequence['plugins'], list):
            return False, "Le champ 'plugins' doit être une liste"

        # Valider chaque configuration de plugin
        for i, plugin in enumerate(sequence['plugins']):
            plugin_valid, plugin_error = self._validate_plugin_config(plugin)
            if not plugin_valid:
                return False, f"Erreur dans la configuration du plugin #{i+1}: {plugin_error}"

        # Ajouter automatiquement une description si manquante
        if 'description' not in sequence:
            sequence['description'] = f"Séquence {sequence['name']}"

        return True, ""

    def _validate_plugin_config(self, config: Any) -> Tuple[bool, str]:
        """
        Valide la configuration d'un plugin dans une séquence.
        
        Args:
            config: Configuration du plugin à valider
            
        Returns:
            Tuple[bool, str]: Tuple (validité, message d'erreur)
        """
        # Cas 1: Chaîne simple (juste le nom du plugin)
        if isinstance(config, str):
            return True, ""
            
        # Cas 2: Dictionnaire avec configuration
        if isinstance(config, dict):
            # Vérifier le champ 'name' obligatoire
            if 'name' not in config:
                return False, "Le nom du plugin est requis"

            # Vérifier que les champs de configuration ont le bon format
            if 'config' in config and not isinstance(config['config'], dict):
                return False, "Le champ 'config' doit être un dictionnaire"
                
            # Pour la rétrocompatibilité: vérifier aussi 'variables'
            if 'variables' in config and not isinstance(config['variables'], dict):
                return False, "Le champ 'variables' doit être un dictionnaire"

            # Vérifier les conditions si présentes
            if 'conditions' in config:
                if not isinstance(config['conditions'], list):
                    return False, "Les conditions doivent être une liste"

                for i, condition in enumerate(config['conditions']):
                    condition_valid, condition_error = self._validate_condition(condition)
                    if not condition_valid:
                        return False, f"Erreur dans la condition #{i+1}: {condition_error}"

            return True, ""
        
        # Cas 3: Format invalide
        return False, "La configuration du plugin doit être une chaîne ou un dictionnaire"

    def _validate_condition(self, condition: Any) -> Tuple[bool, str]:
        """
        Valide une condition dans la configuration d'un plugin.
        
        Args:
            condition: Condition à valider
            
        Returns:
            Tuple[bool, str]: Tuple (validité, message d'erreur)
        """
        if not isinstance(condition, dict):
            return False, "Une condition doit être un dictionnaire"
            
        # Vérifier les champs requis
        required_fields = ['variable', 'operator', 'value']
        missing_fields = [field for field in required_fields if field not in condition]
        if missing_fields:
            return False, f"Champs requis manquants dans la condition: {', '.join(missing_fields)}"

        # Vérifier que l'opérateur est valide
        valid_operators = ['==', '!=', '>', '<', '>=', '<=', 'in', 'not in']
        if condition['operator'] not in valid_operators:
            return False, f"Opérateur invalide: {condition['operator']}. Valeurs autorisées: {', '.join(valid_operators)}"

        return True, ""

    def get_available_sequences(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Récupère la liste des séquences disponibles avec leurs métadonnées.
        Utilise un cache pour améliorer les performances lors d'appels répétés.
        
        Args:
            force_refresh: Force le rafraîchissement du cache même s'il est récent
            
        Returns:
            List[Dict[str, Any]]: Liste des séquences avec leurs métadonnées
        """
        # Vérifier si le cache est récent (moins de 5 secondes) et non vide
        current_time = time.time()
        cache_age = current_time - self.last_refresh_time
        
        if (not force_refresh and 
            self.available_sequences_cache is not None and 
            cache_age < 5):
            logger.debug(f"Utilisation du cache des séquences (âge: {cache_age:.1f}s)")
            return self.available_sequences_cache
            
        # Si on arrive ici, on doit rafraîchir le cache
        sequences = []
        
        # Vérifier que le dossier des séquences existe
        if not self.sequences_dir.exists():
            logger.warning(f"Dossier des séquences non trouvé: {self.sequences_dir}")
            self.available_sequences_cache = sequences
            self.last_refresh_time = current_time
            return sequences

        # Parcourir tous les fichiers YAML dans le dossier
        for seq_file in self.sequences_dir.glob('*.yml'):
            try:
                # Récupérer les métadonnées du fichier
                file_path = str(seq_file)
                file_mtime = seq_file.stat().st_mtime
                file_size = seq_file.stat().st_size
                
                # Charger la séquence - utilise le cache si disponible et à jour
                sequence = None
                
                # Vérifier si la séquence est dans le cache et à jour
                if file_path in self.sequence_cache:
                    cache_entry = self.sequence_cache[file_path]
                    
                    # Nouvelle structure de cache avec horodatage
                    if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
                        cache_data, cache_mtime = cache_entry
                        if cache_mtime >= file_mtime:
                            sequence = cache_data
                    # Ancienne structure de cache (pour compatibilité)
                    else:
                        sequence = cache_entry
                
                # Si pas dans le cache ou obsolète, charger depuis le fichier
                if sequence is None:
                    with open(seq_file, 'r', encoding='utf-8') as f:
                        sequence = self.yaml.load(f)
                        
                    # Valider et mettre en cache si valide
                    valid, _ = self.validate_sequence(sequence)
                    if valid:
                        self.sequence_cache[file_path] = (sequence, file_mtime)
                
                # Si la séquence est valide, extraire les métadonnées
                if sequence and isinstance(sequence, dict):
                    # Créer une entrée avec les métadonnées de base
                    sequence_entry = {
                        'name': sequence.get('name', seq_file.stem),
                        'description': sequence.get('description', ''),
                        'file_name': seq_file.name,
                        'plugins_count': len(sequence.get('plugins', [])),
                        'shortcut': sequence.get('shortcut', ''),
                        'modified': file_mtime,
                        'size': file_size,
                        'path': file_path
                    }
                    
                    # Mettre en cache les raccourcis pour recherche rapide
                    shortcuts = sequence.get('shortcut', [])
                    if isinstance(shortcuts, str):
                        # Un seul raccourci sous forme de chaîne
                        if shortcuts:
                            self.shortcut_cache[shortcuts] = file_path
                    elif isinstance(shortcuts, list):
                        # Liste de raccourcis
                        for shortcut in shortcuts:
                            if shortcut:
                                self.shortcut_cache[shortcut] = file_path
                    
                    # Ajouter à la liste des séquences
                    sequences.append(sequence_entry)
                else:
                    logger.warning(f"Séquence invalide ignorée: {seq_file.name}")
                    
            except Exception as e:
                logger.error(f"Erreur lors du chargement de {seq_file.name}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # Trier par nom (insensible à la casse)
        sorted_sequences = sorted(sequences, key=lambda x: x['name'].lower())
        
        # Mettre à jour le cache et l'horodatage
        self.available_sequences_cache = sorted_sequences
        self.last_refresh_time = current_time
        
        logger.debug(f"Cache des séquences rafraîchi: {len(sorted_sequences)} séquences trouvées")
        return sorted_sequences
        
    def save_sequence(self, sequence_data: Dict[str, Any], file_path: Union[str, Path]) -> bool:
        """
        Sauvegarde une séquence dans un fichier YAML.
        
        Args:
            sequence_data: Données de la séquence à sauvegarder
            file_path: Chemin où sauvegarder le fichier
            
        Returns:
            bool: True si la sauvegarde a réussi, False sinon
        """
        try:
            # Convertir en Path si nécessaire
            if isinstance(file_path, str):
                file_path = Path(file_path)
                
            # Valider la séquence avant de la sauvegarder
            valid, error = self.validate_sequence(sequence_data)
            if not valid:
                logger.error(f"Impossible de sauvegarder une séquence invalide: {error}")
                return False
                
            # Créer le répertoire parent si nécessaire
            parent_dir = file_path.parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)
                
            # Sauvegarder la séquence
            with open(file_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(sequence_data, f)
                
            # Mettre à jour le cache avec l'horodatage actuel
            cache_key = str(file_path)
            file_mtime = file_path.stat().st_mtime
            self.sequence_cache[cache_key] = (sequence_data, file_mtime)
            
            # Mettre à jour le cache des raccourcis
            shortcuts = sequence_data.get('shortcut', [])
            if isinstance(shortcuts, str):
                # Un seul raccourci sous forme de chaîne
                if shortcuts:
                    self.shortcut_cache[shortcuts] = cache_key
            elif isinstance(shortcuts, list):
                # Liste de raccourcis
                for shortcut in shortcuts:
                    if shortcut:
                        self.shortcut_cache[shortcut] = cache_key
            
            # Invalider le cache des séquences disponibles pour forcer un rafraîchissement
            self.available_sequences_cache = None
            
            logger.info(f"Séquence sauvegardée avec succès: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la séquence: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    def find_sequence_by_shortcut(self, shortcut: str) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
        """
        Trouve une séquence par son raccourci.
        
        Args:
            shortcut: Le raccourci à rechercher
            
        Returns:
            Tuple: (chemin_sequence, données_sequence) ou (None, None) si non trouvé
        """
        # Vérifier d'abord dans le cache des raccourcis
        if shortcut in self.shortcut_cache:
            sequence_path = Path(self.shortcut_cache[shortcut])
            sequence_data = self.load_sequence(sequence_path)
            
            if sequence_data:
                logger.debug(f"Séquence trouvée par raccourci '{shortcut}': {sequence_path.name}")
                return sequence_path, sequence_data
        
        # Si non trouvé dans le cache, rechercher dans toutes les séquences
        matching_sequences = []
        
        # Forcer le rafraîchissement du cache des séquences disponibles
        sequences = self.get_available_sequences(force_refresh=True)
        
        for sequence_info in sequences:
            file_name = sequence_info['file_name']
            seq_path = self.sequences_dir / file_name
            
            # Charger la séquence (utilise le cache interne si disponible)
            sequence_data = self.load_sequence(seq_path)
            if not sequence_data:
                continue
                
            # Vérifier si cette séquence a le raccourci recherché
            seq_shortcuts = sequence_data.get('shortcut', '')
            
            if isinstance(seq_shortcuts, str) and seq_shortcuts == shortcut:
                matching_sequences.append((seq_path, sequence_data))
                # Mettre en cache ce raccourci pour les prochaines recherches
                self.shortcut_cache[shortcut] = str(seq_path)
            elif isinstance(seq_shortcuts, list) and shortcut in seq_shortcuts:
                matching_sequences.append((seq_path, sequence_data))
                # Mettre en cache ce raccourci pour les prochaines recherches
                self.shortcut_cache[shortcut] = str(seq_path)
        
        # Analyser les résultats
        if len(matching_sequences) == 0:
            logger.error(f"Aucune séquence trouvée avec le raccourci '{shortcut}'")
            return None, None
        elif len(matching_sequences) > 1:
            logger.error(f"Plusieurs séquences trouvées avec le raccourci '{shortcut}':")
            for seq_path, _ in matching_sequences:
                logger.error(f"- {seq_path.name}")
            return None, None
        else:
            # Une seule correspondance trouvée
            return matching_sequences[0]
    
    def delete_sequence(self, sequence_path: Union[str, Path]) -> bool:
        """
        Supprime une séquence du disque et des caches.
        
        Args:
            sequence_path: Chemin vers le fichier de séquence à supprimer
            
        Returns:
            bool: True si la suppression a réussi, False sinon
        """
        try:
            # Convertir en Path si nécessaire
            if isinstance(sequence_path, str):
                sequence_path = Path(sequence_path)
                
            # Vérifier que le fichier existe
            if not sequence_path.exists():
                logger.error(f"Fichier de séquence non trouvé: {sequence_path}")
                return False
                
            # Convertir en str pour l'utilisation comme clé de cache
            cache_key = str(sequence_path)
            
            # Charger la séquence pour récupérer les raccourcis
            sequence = None
            if cache_key in self.sequence_cache:
                cache_entry = self.sequence_cache[cache_key]
                if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
                    sequence = cache_entry[0]
                else:
                    sequence = cache_entry
            else:
                # Charger depuis le fichier si pas en cache
                with open(sequence_path, 'r', encoding='utf-8') as f:
                    sequence = self.yaml.load(f)
            
            # Supprimer les raccourcis du cache
            if sequence and isinstance(sequence, dict):
                shortcuts = sequence.get('shortcut', [])
                if isinstance(shortcuts, str):
                    # Un seul raccourci sous forme de chaîne
                    if shortcuts and shortcuts in self.shortcut_cache:
                        del self.shortcut_cache[shortcuts]
                elif isinstance(shortcuts, list):
                    # Liste de raccourcis
                    for shortcut in shortcuts:
                        if shortcut and shortcut in self.shortcut_cache:
                            del self.shortcut_cache[shortcut]
            
            # Supprimer du cache des séquences
            if cache_key in self.sequence_cache:
                del self.sequence_cache[cache_key]
                
            # Supprimer le fichier
            sequence_path.unlink()
            
            # Invalider le cache des séquences disponibles
            self.available_sequences_cache = None
            
            logger.info(f"Séquence supprimée avec succès: {sequence_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de la séquence {sequence_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def duplicate_sequence(self, source_path: Union[str, Path], dest_path: Union[str, Path], 
                          new_name: Optional[str] = None) -> bool:
        """
        Duplique une séquence avec possibilité de renommer.
        
        Args:
            source_path: Chemin de la séquence source
            dest_path: Chemin de destination de la copie
            new_name: Nouveau nom pour la séquence (optionnel)
            
        Returns:
            bool: True si la duplication a réussi, False sinon
        """
        try:
            # Convertir en Path si nécessaire
            if isinstance(source_path, str):
                source_path = Path(source_path)
            if isinstance(dest_path, str):
                dest_path = Path(dest_path)
                
            # Vérifier que la source existe
            if not source_path.exists():
                logger.error(f"Fichier source non trouvé: {source_path}")
                return False
                
            # Charger la séquence source
            sequence_data = self.load_sequence(source_path)
            if not sequence_data:
                logger.error(f"Impossible de charger la séquence source: {source_path}")
                return False
                
            # Modifier le nom si demandé
            if new_name:
                sequence_data['name'] = new_name
                
                # Modifier aussi la description si elle contient l'ancien nom
                if 'description' in sequence_data:
                    old_name = sequence_data.get('name', source_path.stem)
                    if old_name in sequence_data['description']:
                        sequence_data['description'] = sequence_data['description'].replace(
                            old_name, new_name)
            
            # Sauvegarder la séquence à la destination
            return self.save_sequence(sequence_data, dest_path)
            
        except Exception as e:
            logger.error(f"Erreur lors de la duplication de la séquence: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    def clear_cache(self) -> None:
        """
        Vide les caches des séquences.
        Utile après des modifications externes ou pour forcer un rafraîchissement.
        """
        self.sequence_cache.clear()
        self.shortcut_cache.clear()
        self.available_sequences_cache = None
        self.last_refresh_time = 0
        logger.debug("Caches des séquences vidés")