#!/usr/bin/env python3
"""
Plugin pour l'ajout d'imprimantes à un système Linux.
Utilise CUPS via lpadmin pour configurer différentes options d'impression.
"""
import json
import time
import traceback
# Configuration du chemin d'import pour trouver les modules communs
import sys
import os

# Ajouter le répertoire parent au chemin de recherche Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Maintenant on peut importer tous les éléments du module utils
from plugins_utils import main
from plugins_utils import metier
from plugins_utils import ldap

# Initialiser le logger du plugin
#log = PluginUtilsBase("add_printer")

# Initialiser les gestionnaires de commandes
#printer_manager = PrinterCommands(log)
#service_manager = ServiceCommands(log)

class Plugin:
    def run(self,config,log,target_ip):
        try:
            log.debug(f"Début de l'exécution du plugin add_printer")
            metierCmd = metier.MetierCommands(log,target_ip,config)
            ldapCmd = ldap.LdapCommands(log, target_ip)
            src_dir=config['src_dir']
            user_select=config.get('user_select',{})
            user_all = config.get('user_all',True)
            dst_dir = config.get('dst_dir')
            mount_if_needed = config.get('mount_if_needed')
            machine_dir = config.get('machine_dir')



        except Exception as e:
            error_msg = f"Erreur inattendue: {str(e)}"
            log.error(error_msg)
            log.debug(traceback.format_exc())
            return False, error_msg

if __name__ == "__main__":
    plugin=Plugin()
    m=main.Main(plugin)
    m.start()