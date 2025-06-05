#!/usr/bin/env python3
"""
Plugin pour l'installation ou mise à jour du paquet "lara-program" sur un système Linux.
Gère les dépôts, vérifie la présence de versions antérieures, et utilise apt.
"""
import json
import time
import traceback
import sys
import os
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import apt
from plugins_utils import utils_cmd

REPOSITORY_LARA = "deb http://gendbuntu.gendarmerie.fr/jammy/gendarmerie-dev/lara-waiting jammy main"
LARA_LIST_FILE = "lara.list"
MIN_LARA_VERSION = "22.04.3.0"

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._process_lara(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _process_lara(self, config: dict, log: Any, target_ip: str) -> bool:
        apt_cmd = apt.AptCommands(log, target_ip)
        utils_cmd_inst = utils_cmd.UtilsCommands(log, target_ip)

        log.set_total_steps(5)

        if apt_cmd.is_installed("lara-program", min_version=MIN_LARA_VERSION):
            log.success("Lara est déjà installé")
            log.next_step(current_step=5)
            return True

        log.next_step()

        if apt_cmd.is_installed("lara-program"):
            log.info("Ancien LARA installé, désinstallation...")
            if not apt_cmd.uninstall("lara-*", purge=True):
                return False
            log.next_step()
            log.set_total_steps(6)

        if not apt_cmd.remove_list_file(LARA_LIST_FILE ):
            log.debug("Erreur lors de la suppression de l'ancien dépôt, il est peut être inexistant")

        if not apt_cmd.add_repository(REPOSITORY_LARA, custom_filename=LARA_LIST_FILE):
            log.error("Impossible d'ajouter le dépôt LARA")
            return False

        log.next_step()

        if not apt_cmd.update():
            log.error("Impossible de mettre à jour les paquets")
            return False

        log.next_step()

        if not apt_cmd.install("lara-program"):
            log.error("Échec dans l'installation de LARA")
            return False

        log.next_step()
        log.success("Installation de LARA effectuée avec succès")
        return True

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)