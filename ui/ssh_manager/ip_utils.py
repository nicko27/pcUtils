"""
Utilitaires pour la gestion des adresses IP, notamment l'expansion des motifs et la gestion des exceptions.
"""

from typing import List

# Ces fonctions sont désormais fournies par IPResolver pour plus de cohérence
from ..execution_screen.ip_resolver import (
    get_target_ips as resolver_get_target_ips,
    expand_ip_pattern as resolver_expand_ip_pattern,
    IPResolver,
)

def is_ip_match(ip: str, pattern: str) -> bool:
    """Vérifie si une adresse IP correspond à un motif."""
    resolver = IPResolver.get_instance()
    return resolver.is_ip_match(ip, pattern)

def expand_ip_pattern(pattern: str) -> List[str]:
    """Développe un motif d'adresse IP."""
    return resolver_expand_ip_pattern(pattern)

def get_target_ips(config: dict) -> List[str]:
    """Récupère la liste des IPs cibles via IPResolver."""
    return resolver_get_target_ips(config)

