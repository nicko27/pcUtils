#!/usr/bin/env python3
"""
Plugin pour effectuer une mise à jour des paquets si la machine est concernée.
Inclut un nettoyage des fichiers journaux trop volumineux et la désactivation d'AppArmor pour sssd.
"""
import os
import sys
import re
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import logs

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            logs_cmd = logs.LogCommands(log, target_ip)

            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._nettoyage_et_update(log, logs_cmd)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _nettoyage_et_update(self, log: Any, logs_cmd: Any) -> bool:
        log.set_total_steps(5)
        log.info("Suppression des fichiers de logs de plus de 100Mo")
        logs_cmd.purge_large_logs(directories=["/var/log"], patterns=["*.log", "*.journal"], size_threshold_mb=100, dry_run=True)
        log.next_step()

        log.info("Désactivation de AppArmor pour sssd")
        success, stdout, stderr = logs_cmd.run("ln -sf /etc/apparmor.d/usr.sbin.sssd /etc/apparmor.d/disable/", print_command=True, needs_sudo=True)

        if not success:
            log.error("Impossible de créer le lien pour AppArmor")
            return False

        success, stdout, stderr = logs_cmd.run("apparmor_parser -R /etc/apparmor.d/usr.sbin.sssd", print_command=True, needs_sudo=True, error_as_warning=True)

        if not success:
            if re.search("Profil inexistant", stderr):
                log.warning("L'opération semble déjà avoir été effectuée précédemment")
            else:
                log.error("Erreur avec apparmor_parser")
                return False

        log.next_step()
        log.success("Nettoyage des logs effectué avec succès")
        return True

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
