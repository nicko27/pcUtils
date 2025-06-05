#!/usr/bin/env python3
"""
Plugin pour l'ajout d'imprimantes à un système Linux via CUPS.
Configure les imprimantes selon divers paramètres extraits de la configuration fournie.
"""
import os
import sys
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import printers
from plugins_utils import utils_cmd

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Point d'entrée du plugin. Vérifie si la machine doit être traitée puis lance l'installation.
        """
        try:
            log.debug("Début de l'exécution du plugin add_printer")
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._clean_printers_config(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _clean_printers_config(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Lance le processus de nettoyage des configurations d'imprimantes
        """
        printer_cmd = printers.PrinterCommands(log, target_ip)
        log.set_total_steps(1)
        log.info(f"Nettoyage des fichiers de configuration")

        printer_cmd.remove_viewer_configs(all_users=True)
        log.next_step()




        return True


if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
