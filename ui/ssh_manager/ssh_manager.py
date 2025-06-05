import os
from ruamel.yaml import YAML
from ..utils import setup_logging

logger = setup_logging()

class SSHManager:
    """Gestionnaire des configurations SSH pour l'exécution à distance des plugins."""

    def __init__(self):
        """Initialise le gestionnaire SSH."""
        self.config_path = os.path.join(os.path.dirname(__file__), 'ssh_fields.yml')
        self.ssh_config = self._load_config()

    def _load_config(self):
        """Charge la configuration SSH depuis le fichier YAML."""
        try:
            yaml = YAML()
            with open(self.config_path, 'r') as f:
                config = yaml.load(f)
                logger.debug(f"Configuration SSH chargée: {config}")
                return config
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la configuration SSH: {e}")
            # Configuration par défaut en cas d'erreur
            return {
                "name": "Configuration SSH globale",
                "icon": "🔒",
                "description": "Paramètres de connexion pour l'exécution distante des plugins",
                "hint": "Activez l'exécution distante sur au moins un plugin pour configurer SSH",
                "fields": {
                    "ssh_ips": {
                        "type": "text",
                        "label": "Adresses IP (séparées par des virgules)",
                        "description": "Peut inclure des caractères génériques (ex: 192.168.1.*)",
                        "placeholder": "192.168.1.*, 10.0.0.1",
                        "required": True,
                    },
                    "ssh_user": {
                        "type": "text",
                        "label": "Utilisateur SSH",
                        "default": "root",
                        "required": True,
                    },
                    "ssh_passwd": {
                        "type": "text",  # Utiliser "password" si PasswordField est disponible
                        "label": "Mot de passe SSH",
                        "required": True,
                    },
                    "ssh_sms_enabled": {
                        "type": "checkbox",
                        "label": "Authentification via la SMS",
                        "default": False,
                    },
                    "ssh_sms": {
                        "type": "text",
                        "label": "Nom de machine de la SMS",
                        "required": True,
                        "enabled_if": {
                            "field": "ssh_sms_enabled",
                            "value": True
                        },
                    }
                }
            }

    def get_ssh_fields(self):
        """Retourne la définition des champs de configuration SSH."""
        return self.ssh_config.get("fields", {})

    def get_ssh_name(self):
        """Retourne le nom de la section SSH."""
        return self.ssh_config.get("name", "Configuration SSH globale")

    def get_ssh_icon(self):
        """Retourne l'icône de la section SSH."""
        return self.ssh_config.get("icon", "🔒")

    def get_ssh_description(self):
        """Retourne la description de la section SSH."""
        return self.ssh_config.get("description", "")

    def get_ssh_hint(self):
        """Retourne l'indice à afficher pour la configuration SSH."""
        return self.ssh_config.get("hint", "")