#!/usr/bin/env python3
"""
Plugin pour vérifier la conformité de la configuration du poste avec Ubiquity.
Utilise un script système spécifique.
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

            return self._check_conformity()

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _check_conformity(self) -> bool:
        self.log.set_total_steps(1)

        success, stdout, _ = self.metier_cmd.run(
            "/bin/bash /usr/lib/gend-ubiquity/ubiquity_conformity.sh",
            no_output=True,
            needs_sudo=True
        )

        conformity = any("Configuration du poste conforme [OK]" in line.strip() for line in stdout.split("\n"))

        if conformity:
            self.log.success("Ubiquity : configuration du poste conforme")
            return True
        else:
            self.log.error("Ubiquity : configuration du poste non conforme")
            return False

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)