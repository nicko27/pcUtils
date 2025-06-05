#!/usr/bin/env python3
"""
Plugin pour exécuter un script de mise à jour de shim-signed sur les machines concernées.
"""
import os
import sys
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            self.metier_cmd = metier.MetierCommands(log, target_ip, config)
            self.log = log

            if not self.metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._update_shim()

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _update_shim(self) -> bool:
        self.log.set_total_steps(1)
        success, stdout, stderr = self.metier_cmd.run("/bin/bash /usr/local/sbin/shim-signed-maj.sh", needs_sudo=True)

        if success:
            self.log.success("Mise à jour de shim-signed effectuée avec succès, pensez bien à redémarrer")
        else:
            self.log.error("Problème avec la mise à jour de shim-signed")
        return success

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)