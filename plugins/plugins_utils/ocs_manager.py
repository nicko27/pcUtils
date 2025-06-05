# install/plugins/plugins_utils/ocs_manager.py
#!/usr/bin/env python3
"""
Module utilitaire pour interagir avec OCS Inventory NG (Agent et Serveur API REST).
Utilise la commande 'ocsinventory-agent' et potentiellement la bibliothèque 'requests'.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import configparser # Pour parser les fichiers .ini simples si nécessaire
import xml.etree.ElementTree as ET # Pour parser la config XML de l'agent
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

# Essayer d'importer requests pour l'API REST
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

class OcsManagerCommands(PluginsUtilsBase):
    """
    Classe pour interagir avec l'agent OCS Inventory et le serveur via API REST.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    DEFAULT_AGENT_CONFIG_PATHS = [
        "/etc/ocsinventory/ocsinventory-agent.cfg",
        "/etc/ocsinventory-agent/ocsinventory-agent.cfg",
        "/usr/local/etc/ocsinventory/ocsinventory-agent.cfg",
        # Ajouter d'autres chemins potentiels si nécessaire
    ]
    DEFAULT_AGENT_LOG_PATH = "/var/log/ocsinventory-agent/ocsinventory-agent.log"

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire OCS."""
        super().__init__(logger, target_ip)
        self._agent_cmd_path = self._find_agent_command()
        self._agent_config_path = self._find_agent_config()
        if not REQUESTS_AVAILABLE:
            self.log_warning("Le module 'requests' est requis pour utiliser l'API REST OCS. "
                           "Installer via pip si nécessaire. Les fonctions API échoueront.")

    def _find_agent_command(self) -> Optional[str]:
        """Trouve le chemin de l'exécutable ocsinventory-agent."""
        cmd = 'ocsinventory-agent'
        success, path, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
        if success and path.strip():
            path_str = path.strip()
            self.log_debug(f"Commande '{cmd}' trouvée: {path_str}")
            return path_str
        else:
            self.log_warning(f"Commande '{cmd}' non trouvée.")
            return None

    def _find_agent_config(self) -> Optional[str]:
        """Trouve le chemin du fichier de configuration de l'agent."""
        for path in self.DEFAULT_AGENT_CONFIG_PATHS:
            if os.path.exists(path):
                self.log_debug(f"Fichier de configuration agent trouvé: {path}")
                return path
        self.log_warning(f"Aucun fichier de configuration agent trouvé aux emplacements par défaut.")
        return None

    def _parse_agent_config(self, config_path: Optional[str] = None) -> Dict[str, str]:
        """Parse le fichier de configuration de l'agent (format XML)."""
        path_to_parse = config_path or self._agent_config_path
        config = {}
        if not path_to_parse or not os.path.exists(path_to_parse):
            self.log_error(f"Fichier de configuration agent introuvable: {path_to_parse}")
            return config

        try:
            tree = ET.parse(path_to_parse)
            root = tree.getroot()
            # Le format typique est <CONF> <PARAM>VALUE</PARAM> </CONF>
            # Ou parfois des sections. On essaie une approche simple.
            for element in root:
                 if element.tag and element.text:
                      # Clé en majuscules, valeur sensible à la casse
                      config[element.tag.upper()] = element.text.strip()
            self.log_debug(f"Configuration agent parsée depuis {path_to_parse}: {config}")
        except ET.ParseError as e:
             self.log_error(f"Erreur de parsing XML pour {path_to_parse}: {e}")
        except Exception as e:
            self.log_error(f"Erreur inattendue lors du parsing de {path_to_parse}: {e}", exc_info=True)
        return config

    # --- Opérations Agent (CLI) ---

    def run_inventory(self,
                      force: bool = False,
                      tag: Optional[str] = None,
                      server_url: Optional[str] = None,
                      local_path: Optional[str] = None,
                      options: Optional[List[str]] = None,
timeout: int = 600, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Déclenche un inventaire OCS avec l'agent local. Nécessite root.

        Args:
            force: Forcer l'envoi même si l'inventaire n'a pas changé (--force).
            tag: Assigner un TAG à cette machine.
            server_url: URL du serveur OCS à contacter (remplace celle de la config).
            local_path: Chemin pour sauvegarder l'inventaire localement au lieu de l'envoyer.
            options: Liste d'options brutes supplémentaires pour l'agent.
            timeout: Timeout pour l'exécution de l'agent.

        Returns:
            bool: True si l'agent s'est exécuté sans erreur majeure.
                  (Ne garantit pas que le serveur a accepté l'inventaire).
        """
        if not self._agent_cmd_path:
            self.log_error("Commande 'ocsinventory-agent' non trouvée.")
            return False

        self.log_info("Déclenchement de l'inventaire OCS via l'agent...")
        cmd = [self._agent_cmd_path]
        if force: cmd.append('--force'); self.log_info("  - Mode forcé activé.")
        if tag: cmd.extend(['--tag', tag]); self.log_info(f"  - Tag: {tag}")
        if server_url: cmd.extend(['--server', server_url]); self.log_info(f"  - Serveur cible: {server_url}")
        if local_path: cmd.extend(['--local', local_path]); self.log_info(f"  - Sortie locale: {local_path}")
        if options: cmd.extend(options)

        # L'agent nécessite souvent root
        success, stdout, stderr = self.run(cmd, check=False, needs_sudo=True, timeout=timeout)

        # Analyser la sortie pour un succès plus précis
        output = stdout + stderr
        if success and "[error]" not in output.lower() and "[critical]" not in output.lower():
             if "[info] Inventory saved in" in output.lower() and local_path:
                  self.log_success(f"Inventaire OCS généré localement avec succès: {local_path}")
                  return True
             elif "inventory successfully sent" in output.lower() or "no inventory generated" in output.lower(): # No inventory peut être normal si pas de changement
                  self.log_success(f"Inventaire OCS exécuté avec succès (envoyé ou pas de changement).")
                  return True
             else:
                  # Commande réussie mais sortie suspecte
                  self.log_warning(f"L'agent OCS s'est terminé sans erreur critique, mais la sortie est inhabituelle.")
                  self.log_debug(f"Sortie Agent OCS:\n{output}")
                  return True # Considérer comme succès si code retour 0
        else:
            self.log_error(f"Échec de l'exécution de l'agent OCS. Code retour: {process.returncode if 'process' in locals() else 'N/A'}")
            if stderr: self.log_error(f"Stderr:\n{stderr}")
            if stdout: self.log_info(f"Stdout:\n{stdout}")
            return False

    def get_agent_config(self, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Lit et parse la configuration de l'agent OCS."""
        self.log_info("Lecture de la configuration de l'agent OCS")
        return self._parse_agent_config()

    def get_agent_log_path(self, log_levels: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Tente de déterminer le chemin du fichier log de l'agent."""
        config = self.get_agent_config()
        log_path = config.get('LOGFILE', self.DEFAULT_AGENT_LOG_PATH) # Clé typique dans le XML/cfg
        self.log_debug(f"Chemin du log de l'agent déterminé: {log_path}")
        return log_path

    def check_last_run_status_from_log(self, log_path: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[bool]:
        """
        Analyse le fichier log de l'agent pour déterminer le succès de la dernière exécution.

        Args:
            log_path: Chemin vers le fichier log (auto-détecté si None).

        Returns:
            True si succès, False si erreur, None si impossible de déterminer.
        """
        path = log_path or self.get_agent_log_path()
        if not path or not os.path.exists(path):
            self.log_error(f"Fichier log de l'agent introuvable: {path}")
            return None

        self.log_info(f"Analyse du log de l'agent OCS: {path}")
        try:
            # Lire les dernières lignes du log (ex: 100 dernières)
            # Utiliser 'tail' est plus efficace pour les gros fichiers
            cmd_tail = ['tail', '-n', '100', path]
            success_tail, stdout_tail, _ = self.run(cmd_tail, check=False, no_output=True)
            if not success_tail:
                 self.log_warning(f"Impossible de lire la fin du fichier log {path} via tail.")
                 # Fallback: lire tout le fichier (peut être lent)
                 with open(path, 'r', encoding='utf-8', errors='replace') as f:
                      log_content = f.read()
            else:
                 log_content = stdout_tail

            # Rechercher des indicateurs de succès ou d'erreur récents
            # Les messages exacts peuvent varier selon la version de l'agent
            if re.search(r'inventory successfully sent', log_content, re.IGNORECASE):
                self.log_info("Dernier inventaire envoyé avec succès (détecté dans les logs).")
                return True
            elif re.search(r'\[error\]', log_content, re.IGNORECASE) or \
                 re.search(r'\[critical\]', log_content, re.IGNORECASE) or \
                 re.search(r'Cannot establish communication', log_content, re.IGNORECASE):
                self.log_warning("Erreurs détectées dans les dernières lignes du log OCS.")
                return False
            elif re.search(r'no inventory generated', log_content, re.IGNORECASE):
                self.log_info("Aucun inventaire généré lors de la dernière exécution (pas de changement).")
                return True # Considéré comme un succès fonctionnel
            else:
                 self.log_warning("Impossible de déterminer le statut de la dernière exécution OCS à partir des logs.")
                 return None

        except Exception as e:
            self.log_error(f"Erreur lors de l'analyse du log {path}: {e}", exc_info=True)
            return None

    # --- Opérations Serveur (API REST) ---

    def _get_api_client(self, server_url: str, user: Optional[str], password: Optional[str], timeout: int = 10) -> Optional['requests.Session']:
        """Crée un client HTTP pour l'API REST OCS."""
        if not REQUESTS_AVAILABLE:
            self.log_error("Le module 'requests' est nécessaire pour utiliser l'API REST OCS.")
            return None
        if not server_url:
             self.log_error("L'URL du serveur OCS est requise pour l'API REST.")
             return None

        session = requests.Session()
        # L'API OCS utilise souvent l'authentification Basic
        if user and password:
            session.auth = (user, password)
        session.headers.update({'Accept': 'application/json'}) # Préférer JSON
        session.timeout = timeout
        # Gérer la vérification SSL (désactiver si nécessaire, mais non recommandé)
        session.verify = True # Activer par défaut
        # Pour désactiver: session.verify = False
        # import urllib3
        # urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Nettoyer l'URL (enlever /ocsinventory si présent car l'API est à la racine)
        base_url = server_url.replace('/ocsinventory', '').rstrip('/')
        session.base_url = base_url # Stocker l'URL de base pour usage ultérieur

        self.log_debug(f"Client API REST OCS initialisé pour: {base_url}")
        return session

    def _api_request(self, method: str, endpoint: str, client: 'requests.Session', params: Optional[Dict] = None, data: Optional[Dict] = None) -> Tuple[bool, Optional[Any]]:
        """Effectue une requête API REST et gère les réponses/erreurs."""
        if not client: return False, None
        url = f"{client.base_url}{endpoint}"
        self.log_debug(f"Requête API REST: {method.upper()} {url} Params: {params} Data: {data}")

        try:
            response = client.request(method, url, params=params, json=data)
            response.raise_for_status() # Lève une exception pour les codes 4xx/5xx

            # Essayer de parser la réponse JSON
            try:
                json_response = response.json()
                self.log_debug(f"Réponse API ({response.status_code}) reçue: {json.dumps(json_response, indent=2)}")
                return True, json_response
            except json.JSONDecodeError:
                 # Si pas JSON, retourner le texte brut (peut être un message d'erreur HTML)
                 self.log_warning(f"Réponse API ({response.status_code}) non JSON: {response.text[:100]}...")
                 return True, response.text # Succès HTTP mais contenu inattendu

        except requests.exceptions.HTTPError as e:
            self.log_error(f"Erreur HTTP {e.response.status_code} pour {method.upper()} {url}: {e.response.text}")
            return False, {"error": f"HTTP {e.response.status_code}", "message": e.response.text}
        except requests.exceptions.ConnectionError as e:
            self.log_error(f"Erreur de connexion API vers {url}: {e}")
            return False, {"error": "ConnectionError", "message": str(e)}
        except requests.exceptions.Timeout:
            self.log_error(f"Timeout API pour {method.upper()} {url}")
            return False, {"error": "Timeout", "message": "Request timed out"}
        except requests.exceptions.RequestException as e:
            self.log_error(f"Erreur API générique pour {method.upper()} {url}: {e}", exc_info=True)
            return False, {"error": "RequestException", "message": str(e)}
        except Exception as e:
             self.log_error(f"Erreur inattendue lors de la requête API: {e}", exc_info=True)
             return False, {"error": "UnexpectedError", "message": str(e)}

    def get_computer_id(self, deviceid: str, server_url: str, user: Optional[str], password: Optional[str], log_levels: Optional[Dict[str, str]] = None) -> Optional[int]:
        """Trouve l'ID interne OCS d'une machine via son DEVICEID."""
        self.log_info(f"Recherche de l'ID OCS pour DEVICEID={deviceid}")
        client = self._get_api_client(server_url, user, password)
        if not client: return None

        # L'endpoint peut varier, essayer les plus courants
        # /computers/deviceid/{deviceid} est documenté mais peut nécessiter /api/v1/
        endpoints_to_try = [
            f"/api/v1/computers/deviceid/{deviceid}",
            f"/computers/deviceid/{deviceid}"
        ]

        for endpoint in endpoints_to_try:
            success, data = self._api_request('GET', endpoint, client)
            if success and isinstance(data, dict) and 'id' in data:
                ocs_id = data['id']
                self.log_info(f"ID OCS trouvé pour {deviceid}: {ocs_id}")
                return int(ocs_id)
            elif success:
                 self.log_debug(f"Réponse inattendue pour {endpoint}: {data}")
            # Si échec, essayer l'endpoint suivant

        self.log_error(f"Impossible de trouver l'ID OCS pour DEVICEID={deviceid} via l'API.")
        return None

    def get_computer_details(self, ocs_id: int, section: Optional[str] = None, **api_kwargs, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict]:
        """Récupère les détails d'un ordinateur via son ID OCS."""
        action = f"la section '{section}'" if section else "les détails"
        self.log_info(f"Récupération {action} pour l'ordinateur OCS ID={ocs_id}")
        client = self._get_api_client(**api_kwargs)
        if not client: return None

        endpoint = f"/api/v1/computers/{ocs_id}"
        if section:
            endpoint += f"/{section}"

        success, data = self._api_request('GET', endpoint, client)
        return data if success and isinstance(data, dict) else None

    def check_administrative_data(self, ocs_id: int, data_key: str, expected_value: str, **api_kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si une donnée administrative spécifique a la valeur attendue sur le serveur OCS.

        Args:
            ocs_id: ID interne OCS de l'ordinateur.
            data_key: Nom de la donnée administrative (TAG ou clé personnalisée).
            expected_value: Valeur attendue pour cette donnée.
            **api_kwargs: Arguments pour la connexion API (server_url, user, password).

        Returns:
            bool: True si la donnée existe et a la valeur attendue.
        """
        self.log_info(f"Vérification de la donnée administrative '{data_key}'='{expected_value}' pour OCS ID={ocs_id}")
        admin_data = self.get_computer_details(ocs_id, section="administrative_data", **api_kwargs)

        if not admin_data:
            self.log_error("Impossible de récupérer les données administratives via l'API.")
            return False

        # Les données admin sont souvent une liste de dictionnaires {'TAG': '...', 'TVALUE': '...'}
        # ou directement un dictionnaire clé/valeur selon l'API et la version
        found = False
        actual_value = None

        if isinstance(admin_data, list): # Format liste de dicts
            for item in admin_data:
                if isinstance(item, dict) and item.get('TAG') == data_key:
                    actual_value = item.get('TVALUE')
                    found = True
                    break
        elif isinstance(admin_data, dict): # Format dict direct
             if data_key in admin_data:
                  actual_value = admin_data[data_key]
                  found = True

        if not found:
            self.log_warning(f"La donnée administrative '{data_key}' n'a pas été trouvée pour OCS ID={ocs_id}.")
            return False

        if str(actual_value) == str(expected_value):
            self.log_success(f"La donnée administrative '{data_key}' a bien la valeur attendue '{expected_value}' pour OCS ID={ocs_id}.")
            return True
        else:
            self.log_error(f"La donnée administrative '{data_key}' a une valeur différente ('{actual_value}') de celle attendue ('{expected_value}') pour OCS ID={ocs_id}.")
            return False
