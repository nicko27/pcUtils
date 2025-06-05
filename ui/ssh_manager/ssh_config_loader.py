"""
Module pour charger et gérer la configuration SSH.
"""

import os
from ruamel.yaml import YAML
import socket
import ipaddress
from typing import Dict, Any, Optional

# Initialiser YAML
yaml = YAML()

from ..utils.logging import get_logger

logger = get_logger('ssh_config_loader')

class SSHConfigLoader:
    """Classe pour charger et gérer la configuration SSH"""
    
    _instance = None
    _config = None
    
    @classmethod
    def get_instance(cls):
        """Singleton pour accéder à l'instance de configuration"""
        if cls._instance is None:
            cls._instance = SSHConfigLoader()
        return cls._instance
    
    def __init__(self):
        """Initialise le chargeur de configuration SSH"""
        self.load_config()
        self._local_ips = None
    
    def load_config(self) -> Dict[str, Any]:
        """Charge la configuration SSH depuis le fichier YAML"""
        try:
            # Chemin du fichier de configuration
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'ssh_config.yml'
            )
            
            # Vérifier si le fichier existe
            if not os.path.exists(config_path):
                logger.warning(f"Fichier de configuration SSH non trouvé: {config_path}")
                self._config = self._get_default_config()
                return self._config
            
            # Charger le fichier YAML
            with open(config_path, 'r') as file:
                self._config = yaml.load(file)
            
            logger.info(f"Configuration SSH chargée depuis {config_path}")
            return self._config
            
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la configuration SSH: {str(e)}")
            self._config = self._get_default_config()
            return self._config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Retourne la configuration par défaut"""
        return {
            'connection': {
                'connect_timeout': 10,
                'transfer_timeout': 60,
                'command_timeout': 120,
                'retry_count': 2,
                'retry_delay': 3
            },
            'authentication': {
                'auto_add_keys': True,
                'known_hosts_file': "",
                'try_key_auth': True,
                'private_key_path': ""
            },
            'execution': {
                'use_local_for_localhost': True,
                'force_ssh_for_localhost': False,
                'remote_temp_dir': "/tmp/pcutils",
                'cleanup_temp_files': True,
                'parallel_execution': False,
                'max_parallel': 5
            },
            'logging': {
                'log_level': "info",
                'show_commands': False,
                'log_full_output': False
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        """Retourne la configuration complète"""
        if self._config is None:
            self.load_config()
        return self._config
    
    def get_connection_config(self) -> Dict[str, Any]:
        """Retourne la configuration de connexion"""
        return self.get_config().get('connection', {})
    
    def get_authentication_config(self) -> Dict[str, Any]:
        """Retourne la configuration d'authentification"""
        return self.get_config().get('authentication', {})
    
    def get_execution_config(self) -> Dict[str, Any]:
        """Retourne la configuration d'exécution"""
        return self.get_config().get('execution', {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """Retourne la configuration de journalisation"""
        return self.get_config().get('logging', {})
    
    def get_local_ips(self) -> list:
        """Récupère les adresses IP locales de la machine"""
        if self._local_ips is not None:
            return self._local_ips
            
        try:
            local_ips = []
            # Obtenir le nom d'hôte
            hostname = socket.gethostname()
            # Obtenir l'adresse IP principale
            main_ip = socket.gethostbyname(hostname)
            local_ips.append(main_ip)
            
            # Obtenir toutes les interfaces réseau
            for interface in socket.getaddrinfo(socket.gethostname(), None):
                ip = interface[4][0]
                # Ne garder que les IPv4 et ignorer les loopback
                if '.' in ip and not ip.startswith('127.'):
                    if ip not in local_ips:
                        local_ips.append(ip)
            
            # Ajouter localhost
            if '127.0.0.1' not in local_ips:
                local_ips.append('127.0.0.1')
                
            self._local_ips = local_ips
            logger.debug(f"Adresses IP locales détectées: {local_ips}")
            return local_ips
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des adresses IP locales: {str(e)}")
            # En cas d'erreur, retourner localhost
            self._local_ips = ['127.0.0.1']
            return self._local_ips
    
    def should_use_local_execution(self, ip_address: str) -> bool:
        """
        Détermine si une adresse IP doit être traitée en local
        
        Args:
            ip_address: L'adresse IP à vérifier
            
        Returns:
            True si l'exécution doit être locale, False sinon
        """
        # Si l'exécution SSH est forcée même pour localhost
        if self.get_execution_config().get('force_ssh_for_localhost', False):
            return False
        
        # Si l'utilisation locale pour localhost est activée
        if self.get_execution_config().get('use_local_for_localhost', True):
            # Vérifier si l'IP est locale
            local_ips = self.get_local_ips()
            if ip_address in local_ips:
                logger.info(f"L'adresse IP {ip_address} est locale, utilisation de l'exécution locale")
                return True
                
            # Vérifier si c'est une IP de loopback
            try:
                ip_obj = ipaddress.ip_address(ip_address)
                if ip_obj.is_loopback:
                    logger.info(f"L'adresse IP {ip_address} est une adresse de loopback, utilisation de l'exécution locale")
                    return True
            except ValueError:
                # Si l'IP n'est pas valide, continuer
                pass
        
        return False
