#!/usr/bin/env python3
"""
Plugin pour déployer le script dovecot-autoadd.sh et lancer la commande de mise à jour si l'ordinateur est concerné.
"""
import os
import sys
import re
import traceback
from typing import Any
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            return_value = True
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.set_total_steps(1)
                log.info("Lancement de la mise à jour des paquets...")
                return_value, stdout, stderr = metier_cmd.run("/usr/local/sbin/install-update --force")
                if return_value:
                    output_msg = "Mise à jour effectuée avec succès"
                else:
                    output_msg = "Échec lors de la mise à jour des paquets"
            else:
                output_msg = "Ordinateur non concerné"

        except Exception as e:
            output_msg = f"Erreur inattendue: {str(e)}"
            log.debug(traceback.format_exc())
            return_value = False

        finally:
            if return_value:
                log.success(output_msg)
            else:
                log.error(output_msg)
            return return_value

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
