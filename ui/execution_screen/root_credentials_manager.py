"""
Module pour la gestion des identifiants root.
"""

import os
import pwd
import getpass
from typing import Dict, Any, Optional, Tuple
from ..utils.logging import get_logger
from ..ssh_manager.ssh_config_loader import SSHConfigLoader

logger = get_logger('root_credentials_manager')

def is_running_as_root() -> bool:
    """Vérifie si le programme est exécuté en tant que root"""
    return os.geteuid() == 0

def get_sudo_user() -> Tuple[str, str]:
    """Récupère l'utilisateur qui a lancé sudo et son répertoire home"""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        # Si SUDO_USER est défini, on l'utilise
        try:
            pw_record = pwd.getpwnam(sudo_user)
            return sudo_user, pw_record.pw_dir
        except KeyError:
            pass
    
    # Sinon, on utilise l'utilisateur courant
    current_user = getpass.getuser()
    try:
        pw_record = pwd.getpwnam(current_user)
        return current_user, pw_record.pw_dir
    except KeyError:
        return current_user, os.path.expanduser('~')

class RootCredentialsManager:
    """Classe pour gérer les identifiants root et les mettre en cache"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Récupère l'instance unique du gestionnaire d'identifiants root"""
        if cls._instance is None:
            cls._instance = RootCredentialsManager()
        return cls._instance
    
    def __init__(self):
        """Initialise le gestionnaire d'identifiants root"""
        self._local_root_credentials = None
        self._ssh_root_credentials = {}  # Dictionnaire pour stocker les identifiants par IP
        self._running_as_root = is_running_as_root()
        
        if self._running_as_root:
            # Si on est déjà root, récupérer l'utilisateur qui a lancé sudo
            self._sudo_user, self._sudo_home = get_sudo_user()
            logger.info(f"Programme exécuté en tant que root, utilisateur original: {self._sudo_user}")
        else:
            self._sudo_user = None
            self._sudo_home = None
    
    def is_running_as_root(self) -> bool:
        """Vérifie si le programme est exécuté en tant que root"""
        return self._running_as_root
    
    def get_sudo_user(self) -> str:
        """Récupère l'utilisateur qui a lancé sudo"""
        return self._sudo_user
    
    def get_sudo_home(self) -> str:
        """Récupère le répertoire home de l'utilisateur qui a lancé sudo"""
        return self._sudo_home
    
    def get_local_root_credentials(self) -> Optional[Dict[str, Any]]:
        """Récupère les identifiants root locaux"""
        return self._local_root_credentials
    
    def set_local_root_credentials(self, credentials: Dict[str, Any]):
        """Définit les identifiants root locaux"""
        self._local_root_credentials = credentials
        logger.debug("Identifiants root locaux mis en cache")
    
    def clear_local_root_credentials(self):
        """Efface les identifiants root locaux"""
        self._local_root_credentials = None
        logger.debug("Identifiants root locaux effacés")
    
    def get_ssh_root_credentials(self, ip_address: str) -> Optional[Dict[str, Any]]:
        """Récupère les identifiants root SSH pour une adresse IP donnée"""
        return self._ssh_root_credentials.get(ip_address)
    
    def set_ssh_root_credentials(self, ip_address: str, credentials: Dict[str, Any]):
        """Définit les identifiants root SSH pour une adresse IP donnée"""
        self._ssh_root_credentials[ip_address] = credentials
        logger.debug(f"Identifiants root SSH mis en cache pour {ip_address}")
    
    def clear_ssh_root_credentials(self, ip_address: Optional[str] = None):
        """Efface les identifiants root SSH pour une adresse IP donnée ou tous si None"""
        if ip_address:
            if ip_address in self._ssh_root_credentials:
                del self._ssh_root_credentials[ip_address]
                logger.debug(f"Identifiants root SSH effacés pour {ip_address}")
        else:
            self._ssh_root_credentials = {}
            logger.debug("Tous les identifiants root SSH effacés")
    
    def prepare_local_root_credentials(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Prépare les identifiants root locaux à partir de la configuration"""
        # Si nous avons déjà des identifiants en cache, les retourner
        if self._local_root_credentials:
            logger.debug("Utilisation des identifiants root locaux en cache")
            return self._local_root_credentials
        
        # Récupérer la configuration SSH
        ssh_config = SSHConfigLoader.get_instance().get_authentication_config()
        
        # Déterminer si nous utilisons les mêmes identifiants que SSH
        local_root_same = ssh_config.get('local_root_same', True)
        
        if local_root_same:
            # Utiliser les identifiants SSH
            credentials = {
                'user': ssh_config.get('ssh_user', ''),
                'password': ssh_config.get('ssh_passwd', '')
            }
            logger.debug("Utilisation des identifiants SSH pour l'accès root local")
        else:
            # Utiliser des identifiants spécifiques
            credentials = {
                'user': ssh_config.get('local_root_user', 'root'),
                'password': ssh_config.get('local_root_passwd', '')
            }
            logger.debug("Utilisation d'identifiants spécifiques pour l'accès root local")
        
        # Mettre en cache les identifiants
        self.set_local_root_credentials(credentials)
        
        return credentials
    
    # Dans la méthode prepare_ssh_root_credentials de RootCredentialsManager
    def prepare_ssh_root_credentials(self, ip_address, config):
        # Récupérer les identifiants en cache
        cached_credentials = self.get_ssh_root_credentials(ip_address)
        if cached_credentials:
            return cached_credentials
            
        # Récupérer la configuration SSH
        ssh_config = SSHConfigLoader.get_instance().get_authentication_config()
        
        # Déterminer si on utilise les mêmes identifiants
        # Vérifier dans les deux endroits possibles (config et ssh_config)
        ssh_root_same = config.get('ssh_root_same', ssh_config.get('ssh_root_same', True))
        
        if ssh_root_same:
            # Utiliser les identifiants SSH de l'utilisateur
            credentials = {
                'user': config.get('ssh_user', ''),
                'password': config.get('ssh_passwd', '')
            }
            logger.debug(f"Utilisation des identifiants utilisateur SSH pour l'accès root")
        else:
            # Utiliser des identifiants spécifiques
            credentials = {
                'user': config.get('ssh_root_user', ssh_config.get('ssh_root_user', 'root')),
                'password': config.get('ssh_root_passwd', ssh_config.get('ssh_root_passwd', ''))
            }
            logger.debug(f"Utilisation d'identifiants root spécifiques")
        
        # Mettre en cache les identifiants
        self.set_ssh_root_credentials(ip_address, credentials)
        
        return credentials
        
    def get_root_password(self, ip_address: str = None) -> str:
        """Récupère le mot de passe root pour une adresse IP donnée ou pour l'accès local
        
        Args:
            ip_address (str, optional): Adresse IP pour laquelle récupérer le mot de passe root.
                                       Si None, récupère le mot de passe root local.
        
        Returns:
            str: Le mot de passe root
        """
        if ip_address:
            # Récupérer les identifiants SSH pour cette IP
            credentials = self.get_ssh_root_credentials(ip_address)
            if not credentials:
                # Si pas en cache, les préparer
                ssh_config = SSHConfigLoader.get_instance().get_authentication_config()
                credentials = self.prepare_ssh_root_credentials(ip_address, ssh_config)
            
            logger.debug(f"Récupération du mot de passe root pour {ip_address}")
            return credentials.get('password', '')
        else:
            # Récupérer les identifiants locaux
            credentials = self.get_local_root_credentials()
            if not credentials:
                # Si pas en cache, les préparer
                ssh_config = SSHConfigLoader.get_instance().get_authentication_config()
                credentials = self.prepare_local_root_credentials(ssh_config)
            
            logger.debug("Récupération du mot de passe root local")
            return credentials.get('password', '')
