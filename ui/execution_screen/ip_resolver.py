"""
Gestionnaire centralisé pour la résolution et la gestion des adresses IP.
Évite le recalcul multiple des wildcards et optimise la gestion des IPs SSH.
"""

import re
import ipaddress
import time
from typing import List, Set, Dict, Tuple, Optional, Union
from threading import RLock

# Gestion robuste des imports
try:
    from ..utils.logging import get_logger
except ImportError:
    try:
        from utils.logging import get_logger
    except ImportError:
        import logging
        def get_logger(name):
            return logging.getLogger(name)

logger = get_logger('ip_resolver')

class IPResolver:
    """
    Gestionnaire centralisé pour la résolution des adresses IP.
    Gère l'expansion des wildcards, la mise en cache et l'optimisation des requêtes.
    """

    _instance = None
    _lock = RLock()

    def __init__(self):
        """Initialise le gestionnaire d'IPs."""
        self._ip_cache: Dict[str, Tuple[List[str], float]] = {}
        self._cache_timeout = 300  # 5 minutes
        self._max_cache_size = 100
        self._max_expansion_size = 1000  # Limite pour éviter l'explosion combinatoire

    @classmethod
    def get_instance(cls) -> 'IPResolver':
        """Récupère l'instance unique du gestionnaire."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = IPResolver()
        return cls._instance

    def resolve_ips(self, config: Dict, force_refresh: bool = False) -> List[str]:
        """
        Résout les adresses IP depuis une configuration plugin.

        Args:
            config: Configuration du plugin contenant les IPs
            force_refresh: Si True, force le recalcul même si en cache

        Returns:
            List[str]: Liste des IPs résolues et filtrées
        """
        try:
            # Créer une clé de cache basée sur la configuration IP
            cache_key = self._create_cache_key(config)

            # Vérifier le cache
            if not force_refresh and cache_key in self._ip_cache:
                cached_ips, timestamp = self._ip_cache[cache_key]
                if time.time() - timestamp < self._cache_timeout:
                    logger.debug(f"IPs récupérées depuis le cache: {len(cached_ips)} IPs")
                    return cached_ips.copy()

            # Résoudre les IPs
            target_ips = self._resolve_target_ips(config)
            exception_ips = self._resolve_exception_ips(config)

            # Filtrer les exceptions
            filtered_ips = self._filter_exception_ips(target_ips, exception_ips)

            # Valider les IPs
            valid_ips = self._validate_ips(filtered_ips)

            # Mettre en cache
            self._cache_result(cache_key, valid_ips)

            logger.info(f"IPs résolues: {len(valid_ips)} IPs valides")
            logger.debug(f"IPs: {valid_ips}")

            return valid_ips

        except Exception as e:
            logger.error(f"Erreur lors de la résolution des IPs: {e}")
            return []

    def _create_cache_key(self, config: Dict) -> str:
        """
        Crée une clé de cache basée sur la configuration IP.

        Args:
            config: Configuration du plugin

        Returns:
            str: Clé de cache unique
        """
        key_parts = []

        # Ajouter les IPs cibles
        for key in ['ssh_ips', 'target_ip', 'target_ips']:
            if key in config:
                value = config[key]
                if isinstance(value, (list, tuple)):
                    key_parts.append(f"{key}:{','.join(map(str, value))}")
                else:
                    key_parts.append(f"{key}:{value}")

        # Ajouter les IPs d'exception
        for key in ['ssh_exception_ips', 'exception_ips']:
            if key in config:
                value = config[key]
                if isinstance(value, (list, tuple)):
                    key_parts.append(f"{key}:{','.join(map(str, value))}")
                else:
                    key_parts.append(f"{key}:{value}")

        return "|".join(key_parts) if key_parts else "empty"

    def _resolve_target_ips(self, config: Dict) -> List[str]:
        """
        Résout les IPs cibles depuis la configuration.

        Args:
            config: Configuration du plugin

        Returns:
            List[str]: Liste des IPs cibles
        """
        target_ips = []

        # Chercher dans les différentes clés possibles par ordre de priorité
        ip_keys = ['ssh_ips', 'target_ip', 'target_ips']

        for key in ip_keys:
            if key in config:
                ip_value = config[key]
                logger.debug(f"Résolution des IPs depuis {key}: {ip_value}")

                resolved_ips = self._parse_ip_value(ip_value)
                target_ips.extend(resolved_ips)

                # Si on trouve des IPs, on s'arrête (priorité)
                if resolved_ips:
                    logger.debug(f"IPs trouvées via {key}: {len(resolved_ips)} IPs")
                    break

        return target_ips

    def _resolve_exception_ips(self, config: Dict) -> List[str]:
        """
        Résout les IPs d'exception depuis la configuration.

        Args:
            config: Configuration du plugin

        Returns:
            List[str]: Liste des IPs d'exception
        """
        exception_ips = []

        # Chercher dans les différentes clés d'exception
        exception_keys = ['ssh_exception_ips', 'exception_ips']

        for key in exception_keys:
            if key in config:
                ip_value = config[key]
                logger.debug(f"Résolution des IPs d'exception depuis {key}: {ip_value}")

                resolved_ips = self._parse_ip_value(ip_value)
                exception_ips.extend(resolved_ips)

        return exception_ips

    def _parse_ip_value(self, ip_value: Union[str, List, None]) -> List[str]:
        """
        Parse une valeur IP (string, liste, etc.) en liste d'IPs.

        Args:
            ip_value: Valeur à parser

        Returns:
            List[str]: Liste des IPs parsées
        """
        if not ip_value:
            return []

        ips = []

        if isinstance(ip_value, str):
            # Traiter une chaîne d'IPs
            ips = self._parse_ip_string(ip_value)
        elif isinstance(ip_value, (list, tuple)):
            # Traiter une liste d'IPs
            for item in ip_value:
                if isinstance(item, str):
                    ips.extend(self._parse_ip_string(item))
                else:
                    logger.warning(f"Type d'IP non supporté dans la liste: {type(item)}")
        else:
            logger.warning(f"Type d'IP non supporté: {type(ip_value)}")

        return ips

    def _parse_ip_string(self, ip_string: str) -> List[str]:
        """
        Parse une chaîne d'IPs (avec possibles virgules, wildcards, etc.).

        Args:
            ip_string: Chaîne à parser

        Returns:
            List[str]: Liste des IPs parsées
        """
        ips = []

        # Diviser par virgules d'abord
        parts = [part.strip() for part in ip_string.split(',') if part.strip()]

        for part in parts:
            if '*' in part or '-' in part:
                # Expansion de wildcard
                expanded = self._expand_ip_pattern(part)
                ips.extend(expanded)
            else:
                # IP simple
                ips.append(part)

        return ips

    def _expand_ip_pattern(self, pattern: str) -> List[str]:
        """
        Développe un motif d'adresse IP en liste d'adresses concrètes.

        Args:
            pattern: Motif d'adresse IP (peut contenir des * ou des plages)

        Returns:
            List[str]: Liste des adresses IP correspondantes
        """
        logger.debug(f"Expansion du pattern: {pattern}")

        # Si c'est une IP simple sans wildcard
        if '*' not in pattern and '-' not in pattern:
            return [pattern] if self._is_valid_ip_format(pattern) else []

        # Si c'est un motif avec wildcard
        parts = pattern.split('.')
        if len(parts) != 4:
            logger.warning(f"Format IP invalide: {pattern}")
            return []

        # Générer toutes les combinaisons possibles
        ranges = []
        total_combinations = 1

        for part in parts:
            if part == '*':
                ranges.append(list(range(1, 255)))  # Éviter 0 et 255
                total_combinations *= 254
            elif '-' in part:
                # Gestion des plages comme "1-5"
                try:
                    start, end = map(int, part.split('-', 1))
                    if 0 <= start <= 255 and 0 <= end <= 255 and start <= end:
                        ranges.append(list(range(start, end + 1)))
                        total_combinations *= (end - start + 1)
                    else:
                        logger.warning(f"Plage IP invalide: {part}")
                        return []
                except (ValueError, IndexError):
                    logger.warning(f"Format de plage IP invalide: {part}")
                    return []
            else:
                try:
                    # Octet spécifique
                    octet = int(part)
                    if 0 <= octet <= 255:
                        ranges.append([octet])
                    else:
                        logger.warning(f"Octet IP invalide: {part}")
                        return []
                except ValueError:
                    logger.warning(f"Octet IP non numérique: {part}")
                    return []

        # Vérifier la limite d'expansion
        if total_combinations > self._max_expansion_size:
            logger.warning(f"Pattern trop large ({total_combinations} IPs), limitation à {self._max_expansion_size}")
            # Retourner un échantillon représentatif
            return self._generate_sample_ips(ranges, self._max_expansion_size)

        # Générer toutes les combinaisons
        result = []
        for a in ranges[0]:
            for b in ranges[1]:
                for c in ranges[2]:
                    for d in ranges[3]:
                        result.append(f"{a}.{b}.{c}.{d}")

        logger.debug(f"Pattern {pattern} développé en {len(result)} IPs")
        return result

    def _generate_sample_ips(self, ranges: List[List[int]], max_count: int) -> List[str]:
        """
        Génère un échantillon représentatif d'IPs quand l'expansion complète est trop large.

        Args:
            ranges: Listes des plages pour chaque octet
            max_count: Nombre maximum d'IPs à générer

        Returns:
            List[str]: Échantillon d'IPs
        """
        import random

        ips = set()
        attempts = 0
        max_attempts = max_count * 10

        while len(ips) < max_count and attempts < max_attempts:
            ip_parts = []
            for range_list in ranges:
                ip_parts.append(random.choice(range_list))

            ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{ip_parts[3]}"
            ips.add(ip)
            attempts += 1

        result = list(ips)
        logger.info(f"Échantillon généré: {len(result)} IPs sur {max_count} demandées")
        return result

    def _filter_exception_ips(self, target_ips: List[str], exception_ips: List[str]) -> List[str]:
        """
        Filtre les IPs d'exception des IPs cibles.

        Args:
            target_ips: Liste des IPs cibles
            exception_ips: Liste des IPs à exclure

        Returns:
            List[str]: IPs filtrées
        """
        if not exception_ips:
            return target_ips

        # Convertir en set pour une recherche plus rapide
        exception_set = set(exception_ips)
        filtered = [ip for ip in target_ips if ip not in exception_set]

        excluded_count = len(target_ips) - len(filtered)
        if excluded_count > 0:
            logger.info(f"{excluded_count} IPs exclues par les règles d'exception")

        return filtered

    def _validate_ips(self, ips: List[str]) -> List[str]:
        """
        Valide une liste d'IPs et retire celles qui sont invalides.

        Args:
            ips: Liste des IPs à valider

        Returns:
            List[str]: IPs valides uniquement
        """
        valid_ips = []
        invalid_count = 0

        for ip in ips:
            if self._is_valid_ip_format(ip):
                valid_ips.append(ip)
            else:
                invalid_count += 1
                logger.debug(f"IP invalide ignorée: {ip}")

        if invalid_count > 0:
            logger.warning(f"{invalid_count} IPs invalides ont été ignorées")

        # Supprimer les doublons en préservant l'ordre
        seen = set()
        unique_ips = []
        for ip in valid_ips:
            if ip not in seen:
                seen.add(ip)
                unique_ips.append(ip)

        duplicate_count = len(valid_ips) - len(unique_ips)
        if duplicate_count > 0:
            logger.info(f"{duplicate_count} IPs dupliquées supprimées")

        return unique_ips

    def _is_valid_ip_format(self, ip: str) -> bool:
        """
        Vérifie si une chaîne est une adresse IP valide.

        Args:
            ip: Adresse IP à vérifier

        Returns:
            bool: True si l'IP est valide
        """
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def is_ip_match(self, ip: str, pattern: str) -> bool:
        """Vérifie si une IP correspond à un motif avec jokers."""
        regex_pattern = pattern.replace('.', '\\.').replace('*', '.*')
        return bool(re.match(f'^{regex_pattern}$', ip))

    def _cache_result(self, cache_key: str, ips: List[str]) -> None:
        """
        Met en cache le résultat de résolution d'IPs.

        Args:
            cache_key: Clé de cache
            ips: Liste des IPs à mettre en cache
        """
        with self._lock:
            # Nettoyer le cache si trop plein
            if len(self._ip_cache) >= self._max_cache_size:
                self._cleanup_cache()

            # Ajouter au cache
            self._ip_cache[cache_key] = (ips.copy(), time.time())
            logger.debug(f"Résultat mis en cache: {len(ips)} IPs")

    def _cleanup_cache(self) -> None:
        """Nettoie le cache en supprimant les entrées les plus anciennes."""
        current_time = time.time()

        # Supprimer les entrées expirées
        expired_keys = [
            key for key, (_, timestamp) in self._ip_cache.items()
            if current_time - timestamp > self._cache_timeout
        ]

        for key in expired_keys:
            del self._ip_cache[key]

        # Si encore trop d'entrées, supprimer les plus anciennes
        if len(self._ip_cache) >= self._max_cache_size:
            # Trier par timestamp et garder seulement la moitié
            sorted_items = sorted(
                self._ip_cache.items(),
                key=lambda x: x[1][1]  # Trier par timestamp
            )

            keep_count = self._max_cache_size // 2
            keys_to_remove = [item[0] for item in sorted_items[:-keep_count]]

            for key in keys_to_remove:
                del self._ip_cache[key]

        logger.debug(f"Cache nettoyé: {len(self._ip_cache)} entrées restantes")

    def clear_cache(self) -> None:
        """Vide complètement le cache."""
        with self._lock:
            self._ip_cache.clear()
            logger.info("Cache IP vidé")

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Récupère les statistiques du cache.

        Returns:
            Dict[str, int]: Statistiques du cache
        """
        with self._lock:
            return {
                'total_entries': len(self._ip_cache),
                'max_size': self._max_cache_size,
                'timeout_seconds': self._cache_timeout
            }





    def get_resolved_count(self, config: Dict) -> int:
        """
        Retourne le nombre d'IPs qui seraient résolues par une configuration.
        Utile pour estimer la charge avant résolution.

        Args:
            config: Configuration à analyser

        Returns:
            int: Nombre estimé d'IPs
        """
        try:
            cache_key = self._create_cache_key(config)

            # Vérifier le cache d'abord
            if cache_key in self._ip_cache:
                cached_ips, _ = self._ip_cache[cache_key]
                return len(cached_ips)

            # Estimation rapide sans résolution complète
            target_ips = self._resolve_target_ips(config)
            return len(target_ips)

        except Exception as e:
            logger.error(f"Erreur lors de l'estimation du nombre d'IPs: {e}")
            return 0


# ---------------------------------------------------------------------------
# Fonctions utilitaires de module pour compatibilité avec l'ancien code
# ---------------------------------------------------------------------------

def get_target_ips(config: dict) -> List[str]:
    """Fonction de compatibilité pour récupérer les IPs cibles."""
    resolver = IPResolver.get_instance()
    return resolver.resolve_ips(config)


def expand_ip_pattern(pattern: str) -> List[str]:
    """Fonction de compatibilité pour l'expansion de patterns IP."""
    resolver = IPResolver.get_instance()
    return resolver._expand_ip_pattern(pattern)


def is_ip_match(ip: str, pattern: str) -> bool:
    """Fonction de compatibilité pour vérifier la correspondance IP/pattern."""
    resolver = IPResolver.get_instance()
    return resolver.is_ip_match(ip, pattern)


