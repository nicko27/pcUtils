#!/usr/bin/env python3
"""
Plugin pour effectuer un contact avec le serveur Puppet pour mise à jour.
Utilise un script local avec élévation de privilèges.
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
            metier_cmd = metier.MetierCommands(log, target_ip, config)

            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._run_puppet_inventory(log, metier_cmd)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _run_puppet_inventory(self, log: Any, metier_cmd: Any) -> bool:
        log.set_total_steps(1)
        log.info("Lancement de l'inventaire Puppet, opération longue")

        success, stdout, stderr = metier_cmd.run("/bin/bash /usr/local/sbin/puppet-contact --force", needs_sudo=True)

        contact_successful = any("Contact Puppet [OK]" in line.strip() for line in stdout.split('\n'))

        if contact_successful:
            log.success("Puppet mis à jour avec succès")
        else:
            log.error("Problème avec la mise à jour Puppet")

        return contact_successful

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)