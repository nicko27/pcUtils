import argparse
import sys
import json
import traceback
from plugins_utils import plugin_logger



class Main:
    def __init__(self,plugin):
        self.logger = plugin_logger.PluginLogger()
        self.plugin=plugin
        self.target_ip=""

    def start(self):
        returnValue,config=self.argparse()
        if not returnValue:
            error_msg=config
            self.logger.error(error_msg)
            return returnValue

                # Vérifier si la configuration est correcte
        if 'config' not in config:
            # Pour la compatibilité avec l'exécution locale, créer la structure attendue
            # si elle n'existe pas déjà
            plugin_config = {}
            for key, value in config.items():
                if key not in ["plugin_name", "instance_id", "ssh_mode"]:
                    plugin_config[key] = value

            # Reconstruire la configuration avec la structure attendue
            config = {
                "plugin_name": config.get("plugin_name", ""),
                "instance_id": config.get("instance_id", 0),
                "text_mode": config.get("text_mode", False),
                "ssh_mode": config.get("ssh_mode", False),
                "config": plugin_config
            }
        self.logger.plugin_name = config.get('plugin_name', '')
        self.logger.instance_id = config.get('instance_id', 0)
        self.logger.ssh_mode = config.get('ssh_mode', False)
        self.logger.text_mode=config.get("text_mode", False)
        self.logger.init_logs()
        icon = config.get('icon', '')
        name = config.get('name', '')
        self.logger.start(f"Lancement du plugin {name}")
        returnValue=self.plugin.run(config,self.logger,self.target_ip)
        self.logger.end(f"Fin d'exécution du plugin {name}")
        self.logger.shutdown()

        return returnValue

    def argparse(self):
        try:
            parser = argparse.ArgumentParser()
            parser.add_argument('-c', '--config', help='Fichier de configuration JSON')
            parser.add_argument('json_config', nargs='?', help='Configuration JSON en ligne de commande')
            parser.add_argument('-t', '--text-mode', action='store_true', help='Active le mode texte des logs')  # Ajout de l'argument
            args, unknown = parser.parse_known_args()
            if args.config:
                # Lire la configuration depuis le fichier (mode SSH)
                with open(args.config, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            elif args.json_config:
                # Charger la configuration depuis l'argument positionnelle (mode local)
                config = json.loads(args.json_config)
            elif len(sys.argv) > 1 and sys.argv[1].startswith('{'):
                # Fallback: essayer de parser le premier argument comme JSON
                config = json.loads(sys.argv[1])
            else:
                raise ValueError(
                "Aucune configuration fournie. Utilisez -c/--config ou passez un JSON en argument.")


            # Ajouter text_mode à la config si spécifié en ligne de commande
            if args.text_mode:
                config['text_mode'] = True
            return True, config
        except json.JSONDecodeError as je:
            error_msg = f"Erreur: Configuration JSON invalide: {je}"
            self.logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Erreur inattendue: {e}"
            self.logger.error(error_msg)
            self.logger.debug(traceback.format_exc())
            return False, error_msg