# install/plugins/plugins_utils/validation_utils.py
#!/usr/bin/env python3
"""
Module utilitaire fournissant des fonctions de validation pour divers formats de données.
Valide les noms d'hôte, FQDN, IP, ports, emails, URLs, etc.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import re
import ipaddress
from urllib.parse import urlparse
from typing import Union, Optional, List, Dict, Any, Tuple

# Essayer d'importer UserGroupCommands pour valider utilisateurs/groupes
try:
    from .users_groups import UserGroupCommands
    USER_GROUP_CHECK_AVAILABLE = True
except ImportError:
    USER_GROUP_CHECK_AVAILABLE = False
    class UserGroupCommands: pass # Factice

class ValidationUtils(PluginsUtilsBase):
    """
    Classe fournissant des méthodes statiques pour la validation de données.
    Hérite de PluginUtilsBase uniquement pour l'accès potentiel au logger via cls.
    """

    # RFC 1123 refined hostname validation (less strict than pure RFC 952)
    # Allows leading digits, max length 253 (for FQDN), parts max 63 chars.
    # Does not allow leading/trailing hyphens in parts.
    HOSTNAME_REGEX = re.compile(r'^(?=.{1,253}$)([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$')
    HOSTNAME_REGEX_ALLOW_UNDERSCORE = re.compile(r'^(?=.{1,253}$)([a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?)(?:\.([a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?))*$')

    # Simple email regex (covers most common cases, not fully RFC 5322 compliant)
    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

    # Cron schedule basic format check (5 or 6 fields)
    # Allows *, -, ,, / and digits. Does not validate ranges/steps deeply.
    CRON_SCHEDULE_REGEX = re.compile(r"^(\*|(?:\d+|\d+-\d+|\*)\/\d+|\d+(?:,\d+)*|\d+-\d+)\s+" # Minute
                                     r"(\*|(?:\d+|\d+-\d+|\*)\/\d+|\d+(?:,\d+)*|\d+-\d+)\s+" # Hour
                                     r"(\*|(?:\d+|\d+-\d+|\*)\/\d+|\d+(?:,\d+)*|\d+-\d+)\s+" # Day of Month
                                     r"(\*|(?:\d+|\d+-\d+|\*)\/\d+|\d+(?:,\d+)*|\d+-\d+|[a-zA-Z]{3}(?:,[a-zA-Z]{3})*)\s+" # Month
                                     r"(\*|(?:\d+|\d+-\d+|\*)\/\d+|\d+(?:,\d+)*|\d+-\d+|[a-zA-Z]{3}(?:,[a-zA-Z]{3})*)" # Day of Week
                                     r"(?:\s+.*)?$") # Allow optional 6th field (year) or command


    @classmethod
    def is_valid_hostname(cls, hostname: str, allow_underscore: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide un nom d'hôte selon la RFC 1123 (avec option pour underscores).

        Args:
            hostname: Le nom d'hôte à valider.
            allow_underscore: Si True, autorise les underscores (non standard mais courant).

        Returns:
            bool: True si le nom d'hôte est valide.
        """
        if not isinstance(hostname, str) or not hostname:
            return False
        regex = cls.HOSTNAME_REGEX_ALLOW_UNDERSCORE if allow_underscore else cls.HOSTNAME_REGEX
        if regex.match(hostname):
            return True
        cls.get_logger().debug(f"Nom d'hôte invalide: '{hostname}' (allow_underscore={allow_underscore})")
        return False

    @classmethod
    def is_valid_fqdn(cls, fqdn: str, allow_underscore: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide un nom de domaine pleinement qualifié (FQDN).
        Un FQDN doit contenir au moins un point et respecter les règles de nom d'hôte.

        Args:
            fqdn: Le FQDN à valider.
            allow_underscore: Si True, autorise les underscores dans les parties du domaine.

        Returns:
            bool: True si le FQDN est valide.
        """
        if not isinstance(fqdn, str) or '.' not in fqdn:
            cls.get_logger().debug(f"FQDN invalide (manque '.'): '{fqdn}'")
            return False
        # Utiliser la validation hostname qui gère la structure et la longueur
        return cls.is_valid_hostname(fqdn, allow_underscore)

    @classmethod
    def is_valid_ip_address(cls, ip_str: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide une adresse IPv4 ou IPv6.

        Args:
            ip_str: La chaîne représentant l'adresse IP.

        Returns:
            bool: True si l'adresse est valide.
        """
        if not isinstance(ip_str, str): return False
        try:
            ipaddress.ip_address(ip_str)
            return True
        except ValueError:
            cls.get_logger().debug(f"Adresse IP invalide: '{ip_str}'")
            return False

    @classmethod
    def is_valid_port(cls, port: Any, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide un numéro de port réseau (1-65535).

        Args:
            port: La valeur à vérifier (peut être int ou str).

        Returns:
            bool: True si le port est valide.
        """
        try:
            port_int = int(port)
            if 1 <= port_int <= 65535:
                return True
            cls.get_logger().debug(f"Numéro de port hors plage (1-65535): '{port}'")
            return False
        except (ValueError, TypeError):
            cls.get_logger().debug(f"Numéro de port invalide (non numérique): '{port}'")
            return False

    @classmethod
    def is_valid_email(cls, email: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide basiquement une adresse email.

        Args:
            email: L'adresse email à vérifier.

        Returns:
            bool: True si le format semble valide.
        """
        if not isinstance(email, str) or not email:
            return False
        if cls.EMAIL_REGEX.match(email):
            return True
        cls.get_logger().debug(f"Adresse email invalide: '{email}'")
        return False

    @classmethod
    def is_valid_url(cls, url: str, required_schemes: Optional[List[str]] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide une URL et vérifie optionnellement son schéma.

        Args:
            url: L'URL à vérifier.
            required_schemes: Liste optionnelle de schémas autorisés (ex: ['http', 'https']).

        Returns:
            bool: True si l'URL est valide (et a un schéma autorisé si spécifié).
        """
        if not isinstance(url, str) or not url:
            return False
        try:
            result = urlparse(url)
            # Doit avoir au moins un schéma et un netloc (domaine/IP)
            is_struct_valid = all([result.scheme, result.netloc])
            if not is_struct_valid:
                 cls.get_logger().debug(f"Structure URL invalide: '{url}'")
                 return False
            # Vérifier le schéma si requis
            if required_schemes:
                 is_scheme_valid = result.scheme in required_schemes
                 if not is_scheme_valid:
                      cls.get_logger().debug(f"Schéma URL non autorisé: '{result.scheme}' (attendu: {required_schemes})")
                      return False
            return True # Structure valide et schéma autorisé (ou non vérifié)
        except ValueError:
            cls.get_logger().debug(f"Erreur de parsing URL: '{url}'")
            return False
        except Exception as e:
             cls.get_logger().error(f"Erreur inattendue lors de la validation URL '{url}': {e}")
             return False

    @classmethod
    def is_valid_cron_schedule(cls, schedule_str: str, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide basiquement le format d'une planification cron (5 ou 6 champs).

        Args:
            schedule_str: La chaîne de planification (ex: "* * * * *").

        Returns:
            bool: True si le format de base semble correct.
        """
        if not isinstance(schedule_str, str): return False
        # Vérifier s'il y a 5 ou 6 champs séparés par des espaces
        parts = schedule_str.strip().split()
        if not (5 <= len(parts) <= 6):
             cls.get_logger().debug(f"Format Cron invalide (nombre de champs != 5 ou 6): '{schedule_str}'")
             return False
        # Utiliser la regex pour une vérification de format plus poussée
        if cls.CRON_SCHEDULE_REGEX.match(" ".join(parts[:5])): # Vérifier les 5 premiers champs obligatoires
             return True
        cls.get_logger().debug(f"Format Cron invalide (pattern non respecté): '{schedule_str}'")
        return False

    @classmethod
    def is_valid_user(cls, username: str, check_system: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide un nom d'utilisateur (format et existence optionnelle).

        Args:
            username: Nom d'utilisateur à valider.
            check_system: Si True, vérifie aussi l'existence via UserGroupCommands.

        Returns:
            bool: True si le format est valide (et l'utilisateur existe si check_system=True).
        """
        if not isinstance(username, str) or not username: return False
        # Regex simple pour nom d'utilisateur Linux standard
        # Commence par une lettre ou _, suivi de lettres, chiffres, _, -
        # Typiquement max 32 caractères, mais on ne vérifie pas la longueur ici.
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', username):
             cls.get_logger().debug(f"Format de nom d'utilisateur invalide: '{username}'")
             return False

        if check_system:
             if not USER_GROUP_CHECK_AVAILABLE:
                  cls.get_logger().warning("Vérification d'existence utilisateur impossible: UserGroupCommands non disponible.")
                  return True # Valide le format mais pas l'existence
             try:
                  ug_checker = UserGroupCommands(cls.get_logger()) # Utiliser le logger de classe
                  exists = ug_checker.user_exists(username)
                  if not exists: cls.get_logger().debug(f"Utilisateur système '{username}' non trouvé.")
                  return exists
             except Exception as e:
                  cls.get_logger().error(f"Erreur lors de la vérification de l'utilisateur système '{username}': {e}")
                  return False # Erreur = invalide
        return True # Format valide

    @classmethod
    def is_valid_group(cls, groupname: str, check_system: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Valide un nom de groupe (format et existence optionnelle).

        Args:
            groupname: Nom du groupe à valider.
            check_system: Si True, vérifie aussi l'existence via UserGroupCommands.

        Returns:
            bool: True si le format est valide (et le groupe existe si check_system=True).
        """
        if not isinstance(groupname, str) or not groupname: return False
        # Regex similaire à username
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', groupname):
             cls.get_logger().debug(f"Format de nom de groupe invalide: '{groupname}'")
             return False

        if check_system:
             if not USER_GROUP_CHECK_AVAILABLE:
                  cls.get_logger().warning("Vérification d'existence groupe impossible: UserGroupCommands non disponible.")
                  return True # Valide le format mais pas l'existence
             try:
                  ug_checker = UserGroupCommands(cls.get_logger())
                  exists = ug_checker.group_exists(groupname)
                  if not exists: cls.get_logger().debug(f"Groupe système '{groupname}' non trouvé.")
                  return exists
             except Exception as e:
                  cls.get_logger().error(f"Erreur lors de la vérification du groupe système '{groupname}': {e}")
                  return False # Erreur = invalide
        return True # Format valide

    # Ajouter d'autres méthodes de validation au besoin...
    # Ex: is_valid_mac_address, is_valid_uuid, etc.

    # Helper pour obtenir le logger même depuis les méthodes de classe
    @staticmethod
    def get_logger(log_levels: Optional[Dict[str, str]] = None):
        # Retourne un logger standard si appelé hors contexte d'instance
        return logging.getLogger(__name__)
