#!/usr/bin/env python3
"""
Plugin pour l'ajout d'imprimantes à un système Linux.
Utilise CUPS via lpadmin pour configurer différentes options d'impression.
"""
import sys
import os
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)

            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._send_inventory(log, metier_cmd)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _send_inventory(self, log: Any, metier_cmd: Any) -> bool:
        log.set_total_steps(1)
        log.info("Envoi d'un inventaire, opération longue")

        success, stdout, stderr = metier_cmd.run("ocsinventory-agent --force --debug", no_output=True, error_as_warning=True)

        if "Cannot establish communication" in stderr:
            log.error("Erreur 500 avec le serveur OCS")
            return False

        if "NO_ACCOUNT_UPDATE" in stderr:
            log.success("Envoi OCS effectué avec succès sans mise à jour")
        else:
            log.success("Envoi OCS effectué avec succès avec mise à jour")

        return success

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
