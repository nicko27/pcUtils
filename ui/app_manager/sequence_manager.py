"""
Module de gestion des séquences.

Ce module fournit des fonctionnalités pour rechercher et 
charger des séquences, notamment par leur raccourci.
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List, Union
from ruamel.yaml import YAML
from ..utils.logging import get_logger

logger = get_logger('sequence_manager')

class SequenceManager:
    """
    Gestionnaire de séquences.
    
    Cette classe est responsable de rechercher et charger des séquences
    à partir de leur nom de fichier ou de leur raccourci.
    """
    
    # Instance YAML partagée pour toute la classe
    _yaml = YAML()
    
    # Cache des séquences chargées
    _sequence_cache: Dict[str, Dict[str, Any]] = {}
    
    # Cache des raccourcis
    _shortcut_cache: Dict[str, str] = {}
    
    @classmethod
    def find_sequence_by_shortcut(cls, shortcut: str) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
        """
        Trouve une séquence par son raccourci.
        
        Args:
            shortcut: Le raccourci à rechercher
            
        Returns:
            Tuple: (chemin_sequence, données_sequence) ou (None, None) si non trouvé
        """
        # Vérifier d'abord dans le cache des raccourcis
        if shortcut in cls._shortcut_cache:
            sequence_path = Path(cls._shortcut_cache[shortcut])
            sequence_data = cls.load_sequence(sequence_path)
            return sequence_path, sequence_data
            
        # Si non trouvé dans le cache, rechercher dans tous les fichiers
        sequences_dir = Path('sequences')
        matching_sequences = []
        
        # S'assurer que le dossier existe
        if not sequences_dir.exists():
            logger.error(f"Dossier des séquences non trouvé: {sequences_dir}")
            return None, None
        
        # Parcourir tous les fichiers .yml dans le dossier sequences
        for file_path in sequences_dir.glob('*.yml'):
            try:
                sequence_path = file_path
                sequence = cls._load_sequence_file(sequence_path)
                
                if not sequence:
                    continue
                    
                # Vérifier si cette séquence a le raccourci recherché
                if 'shortcut' in sequence:
                    shortcuts = sequence['shortcut']
                    
                    # Le shortcut peut être une chaîne ou une liste
                    if isinstance(shortcuts, str) and shortcuts == shortcut:
                        matching_sequences.append((sequence_path, sequence))
                        # Mettre en cache ce raccourci
                        cls._shortcut_cache[shortcut] = str(sequence_path)
                    elif isinstance(shortcuts, list) and shortcut in shortcuts:
                        matching_sequences.append((sequence_path, sequence))
                        # Mettre en cache ce raccourci
                        cls._shortcut_cache[shortcut] = str(sequence_path)
                        
            except Exception as e:
                logger.error(f"Erreur lors de la lecture du fichier de séquence {file_path}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Vérifier le nombre de correspondances
        if len(matching_sequences) == 0:
            logger.error(f"Aucune séquence trouvée avec le raccourci '{shortcut}'")
            return None, None
        elif len(matching_sequences) > 1:
            logger.error(f"Plusieurs séquences trouvées avec le raccourci '{shortcut}':")
            for sequence_path, _ in matching_sequences:
                logger.error(f"- {sequence_path.name}")
            return None, None
        else:
            # Une seule correspondance trouvée
            return matching_sequences[0]
            
    @classmethod
    def load_sequence(cls, sequence_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Charge une séquence depuis un fichier.
        
        Args:
            sequence_path: Chemin vers le fichier de séquence
            
        Returns:
            Optional[Dict[str, Any]]: Données de la séquence ou None si erreur
        """
        # Convertir en Path si nécessaire
        if isinstance(sequence_path, str):
            sequence_path = Path(sequence_path)
            
        # Vérifier d'abord dans le cache
        cache_key = str(sequence_path)
        if cache_key in cls._sequence_cache:
            logger.debug(f"Séquence trouvée dans le cache: {cache_key}")
            return cls._sequence_cache[cache_key]
            
        # Charger depuis le fichier
        return cls._load_sequence_file(sequence_path)
        
    @classmethod
    def _load_sequence_file(cls, sequence_path: Path) -> Optional[Dict[str, Any]]:
        """
        Charge une séquence depuis un fichier et la met en cache.
        
        Args:
            sequence_path: Chemin vers le fichier de séquence
            
        Returns:
            Optional[Dict[str, Any]]: Données de la séquence ou None si erreur
        """
        try:
            if not sequence_path.exists():
                logger.error(f"Fichier de séquence non trouvé: {sequence_path}")
                return None
                
            with open(sequence_path, 'r', encoding='utf-8') as f:
                sequence = cls._yaml.load(f)
                
                # Vérifier que la séquence est valide
                if not isinstance(sequence, dict):
                    logger.error(f"Format de séquence invalide dans {sequence_path}")
                    return None
                    
                # Vérifier les champs requis
                if 'name' not in sequence or 'plugins' not in sequence:
                    logger.error(f"Champs requis manquants dans la séquence {sequence_path}")
                    return None
                    
                # Mettre en cache
                cls._sequence_cache[str(sequence_path)] = sequence
                logger.debug(f"Séquence chargée et mise en cache: {sequence_path}")
                
                return sequence
                
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la séquence {sequence_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    @classmethod
    def get_available_sequences(cls) -> List[Dict[str, Any]]:
        """
        Récupère la liste de toutes les séquences disponibles.
        
        Returns:
            List[Dict[str, Any]]: Liste des métadonnées des séquences disponibles
        """
        sequences = []
        sequences_dir = Path('sequences')
        
        if not sequences_dir.exists():
            logger.warning(f"Dossier des séquences non trouvé: {sequences_dir}")
            return sequences
            
        for sequence_path in sequences_dir.glob('*.yml'):
            try:
                sequence = cls.load_sequence(sequence_path)
                
                if sequence:
                    sequences.append({
                        'name': sequence.get('name', sequence_path.stem),
                        'description': sequence.get('description', ''),
                        'file_name': sequence_path.name,
                        'plugins_count': len(sequence.get('plugins', [])),
                        'shortcut': sequence.get('shortcut', ''),
                        'path': str(sequence_path)
                    })
            except Exception as e:
                logger.error(f"Erreur lors du traitement de {sequence_path}: {e}")
                
        # Trier par nom
        sequences.sort(key=lambda s: s['name'].lower())
        return sequences
        
    @classmethod
    def save_sequence(cls, sequence_data: Dict[str, Any], sequence_path: Union[str, Path]) -> bool:
        """
        Sauvegarde une séquence dans un fichier.
        
        Args:
            sequence_data: Données de la séquence à sauvegarder
            sequence_path: Chemin où sauvegarder le fichier
            
        Returns:
            bool: True si la sauvegarde a réussi, False sinon
        """
        # Convertir en Path si nécessaire
        if isinstance(sequence_path, str):
            sequence_path = Path(sequence_path)
            
        try:
            # Vérifier que les données sont valides
            if not isinstance(sequence_data, dict):
                logger.error("Les données de séquence doivent être un dictionnaire")
                return False
                
            # Vérifier les champs requis
            required_fields = ['name', 'plugins']
            for field in required_fields:
                if field not in sequence_data:
                    logger.error(f"Champ requis manquant: {field}")
                    return False
                    
            # Créer le dossier parent si nécessaire
            sequence_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Sauvegarder dans le fichier
            with open(sequence_path, 'w', encoding='utf-8') as f:
                cls._yaml.dump(sequence_data, f)
                
            # Mettre à jour le cache
            cls._sequence_cache[str(sequence_path)] = sequence_data
            
            # Invalider le cache des raccourcis (puisque les raccourcis peuvent avoir changé)
            if 'shortcut' in sequence_data:
                shortcuts = sequence_data['shortcut']
                if isinstance(shortcuts, str):
                    cls._shortcut_cache[shortcuts] = str(sequence_path)
                elif isinstance(shortcuts, list):
                    for shortcut in shortcuts:
                        cls._shortcut_cache[shortcut] = str(sequence_path)
                        
            logger.info(f"Séquence sauvegardée: {sequence_path}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la séquence: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    @classmethod
    def clear_cache(cls) -> None:
        """
        Vide les caches des séquences et des raccourcis.
        Utile pour les tests ou après des modifications externes.
        """
        cls._sequence_cache.clear()
        cls._shortcut_cache.clear()
        logger.debug("Caches des séquences vidés")