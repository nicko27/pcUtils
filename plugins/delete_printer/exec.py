#!/usr/bin/env python3
"""
Plugin de suppression d'imprimantes réseau sur un système Linux via CUPS.
Peut supprimer toutes les imprimantes ou seulement celles liées à une adresse IP donnée.
"""
import os
import sys
import traceback
from typing import Any

# Ajouter le répertoire parent au chemin de recherche Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import des modules internes
from plugins_utils import main
from plugins_utils import metier
from plugins_utils import printers
from plugins_utils import utils_cmd

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Point d'entrée du plugin. Vérifie si la machine doit être traitée puis lance la suppression.
        """
        try:
            log.debug("Début de l'exécution du plugin remove_printer")
            log.set_total_steps(1)

            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._remove_printers(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _remove_printers(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Supprime toutes les imprimantes réseau ou celles associées à une IP spécifique.
        """
        printer_cmd = printers.PrinterCommands(log, target_ip)
        printer_config = config.get('config', {})
        printer_ip = printer_config.get('printer_ip')
        remove_all = printer_config.get('printer_all', False)

        if remove_all:
            success,_ = printer_cmd.remove_all_network_printers()
        else:
            success,_ = printer_cmd.remove_printer_by_ip(printer_ip)

        log.next_step()
        if success:
            log.success("Suppression(s) effectué(es) avec succès")
        else:
            log.error("Erreur lors de la suppression")
        return success

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
