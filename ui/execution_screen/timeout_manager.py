"""
Gestionnaire centralisé des timeouts pour optimiser les performances et éviter les blocages.
"""

import asyncio
import time
from typing import Dict, Callable, Any, Optional
from threading import RLock

class TimeoutManager:
    """Gestionnaire centralisé pour tous les timeouts du système."""

    _instance = None
    _lock = RLock()

    def __init__(self):
        """Initialise le gestionnaire de timeouts."""
        self._default_timeouts = {
            'ssh_connection': 30,
            'ssh_execution': 300,
            'plugin_execution': 600,
            'file_transfer': 120,
            'ip_resolution': 10
        }
        self._active_operations = {}

    @classmethod
    def get_instance(cls) -> 'TimeoutManager':
        """Récupère l'instance unique du gestionnaire."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = TimeoutManager()
        return cls._instance

    def get_timeout(self, operation_type: str, custom_timeout: Optional[int] = None) -> int:
        """
        Récupère le timeout approprié pour une opération.

        Args:
            operation_type: Type d'opération
            custom_timeout: Timeout personnalisé (optionnel)

        Returns:
            int: Timeout en secondes
        """
        if custom_timeout and custom_timeout > 0:
            return custom_timeout

        return self._default_timeouts.get(operation_type, 60)

    def set_default_timeout(self, operation_type: str, timeout: int) -> None:
        """
        Définit un timeout par défaut pour un type d'opération.

        Args:
            operation_type: Type d'opération
            timeout: Timeout en secondes
        """
        if timeout > 0:
            self._default_timeouts[operation_type] = timeout

    async def execute_with_timeout(self, coro, operation_type: str,
                                 custom_timeout: Optional[int] = None,
                                 operation_id: Optional[str] = None) -> Any:
        """
        Exécute une coroutine avec timeout adaptatif.

        Args:
            coro: Coroutine à exécuter
            operation_type: Type d'opération
            custom_timeout: Timeout personnalisé
            operation_id: ID unique pour l'opération

        Returns:
            Any: Résultat de la coroutine

        Raises:
            asyncio.TimeoutError: Si l'opération dépasse le timeout
        """
        timeout = self.get_timeout(operation_type, custom_timeout)
        start_time = time.time()

        # Enregistrer l'opération
        if operation_id:
            with self._lock:
                self._active_operations[operation_id] = {
                    'type': operation_type,
                    'start_time': start_time,
                    'timeout': timeout
                }

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            raise asyncio.TimeoutError(
                f"Opération {operation_type} expirée après {execution_time:.1f}s "
                f"(timeout: {timeout}s)"
            )
        finally:
            # Nettoyer l'enregistrement
            if operation_id:
                with self._lock:
                    self._active_operations.pop(operation_id, None)

    def get_active_operations(self) -> Dict[str, Dict]:
        """
        Récupère les opérations en cours.

        Returns:
            Dict: Opérations actives
        """
        with self._lock:
            return self._active_operations.copy()

    def cancel_operation(self, operation_id: str) -> bool:
        """
        Annule une opération en cours.

        Args:
            operation_id: ID de l'opération à annuler

        Returns:
            bool: True si l'opération a été trouvée et marquée pour annulation
        """
        with self._lock:
            if operation_id in self._active_operations:
                self._active_operations[operation_id]['cancelled'] = True
                return True
            return False
