#!/usr/bin/env python3
"""
Plugin pour effectuer une mise à jour des paquets si la machine est concernée.
Inclut un nettoyage des fichiers journaux trop volumineux, la désactivation d'AppArmor pour sssd,
ainsi que la gestion de l'enrôlement de la clé MOK via un script local.
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
            is_ssh = config.get('ssh_mode', False)

            if not is_ssh or (metier_cmd.is_good_sms() and metier_cmd.is_good_lrpgn()):
                return_value = True
                log.set_total_steps(6)

                log.info("Suppression des fichiers de logs de plus de 100Mo")
                logs_cmd.purge_large_logs(directories=["/var/log"], patterns=["*.log", "*.journal"], size_threshold_mb=100, dry_run=True)
                log.next_step()

                log.info("Désactivation de AppArmor pour sssd")
                return_value, stdout, stderr = logs_cmd.run("ln -sf /etc/apparmor.d/usr.sbin.sssd /etc/apparmor.d/disable/", print_command=True, needs_sudo=True)

                if return_value:
                    return_value, stdout, stderr = logs_cmd.run("apparmor_parser -R /etc/apparmor.d/usr.sbin.sssd", print_command=True, needs_sudo=True, error_as_warning=True)
                    if not return_value:
                        if re.search("Profil inexistant", stderr):
                            log.warning("L'opération semble déjà avoir été effectuée précédemment")
                            return_value = True
                        else:
                            output_msg = "Erreur avec apparmor_parser"
                else:
                    output_msg = "Impossible de créer le lien pour AppArmor"
                log.next_step()

                log.info("Exécution du script d'enrôlement de la clé MOK")
                return_value, stdout, stderr = metier_cmd.run("/bin/bash /usr/local/sbin/create-mok-gend", needs_sudo=True)
                mok_created = False

                for line in stdout.split('\n'):
                    if "Il est maintenant nécessaire de redémarrer afin de finir l'importation de la clé MOK." in line.strip():
                        return_value = True
                        mok_created = True
                    elif "MOK-JAMMY déjà enrôlée et bi-clé correspondante dans /var/lib/shim-signed/mok." in line.strip():
                        return_value = True

                if return_value:
                    output_msg = "MOK créé avec succès, ne pas oublier de redémarrer pour finir la configuration" if mok_created else "MOK déjà présent, inutile de redémarrer"
                else:
                    output_msg = "Problème avec la mise à jour MOK"
                log.next_step()

            else:
                return_value = False
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
    sys.exit(return_value)#!/usr/bin/env python3
"""
Plugin pour effectuer une mise à jour des paquets si la machine est concernée.
Inclut un nettoyage des fichiers journaux trop volumineux, la désactivation d'AppArmor pour sssd,
ainsi que la gestion de l'enrôlement de la clé MOK via un script local.
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

            return self._execute_updates(log, metier_cmd, logs_cmd)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _execute_updates(self, log: Any, metier_cmd: Any, logs_cmd: Any) -> bool:
        log.set_total_steps(6)

        self._purge_logs(log, logs_cmd)
        if not self._disable_apparmor(log, logs_cmd):
            return False
        return self._run_mok_script(log, metier_cmd)

    def _purge_logs(self, log: Any, logs_cmd: Any):
        log.info("Suppression des fichiers de logs de plus de 100Mo")
        logs_cmd.purge_large_logs(directories=["/var/log"], patterns=["*.log", "*.journal"], size_threshold_mb=100, dry_run=True)
        log.next_step()

    def _disable_apparmor(self, log: Any, logs_cmd: Any) -> bool:
        log.info("Désactivation de AppArmor pour sssd")
        success, _, _ = logs_cmd.run("ln -sf /etc/apparmor.d/usr.sbin.sssd /etc/apparmor.d/disable/", print_command=True, needs_sudo=True)
        if not success:
            log.error("Impossible de créer le lien pour AppArmor")
            return False

        success, _, stderr = logs_cmd.run("apparmor_parser -R /etc/apparmor.d/usr.sbin.sssd", print_command=True, needs_sudo=True, error_as_warning=True)
        if not success:
            if re.search("Profil inexistant", stderr):
                log.warning("L'opération semble déjà avoir été effectuée précédemment")
            else:
                log.error("Erreur avec apparmor_parser")
                return False
        log.next_step()
        return True

    def _run_mok_script(self, log: Any, metier_cmd: Any) -> bool:
        log.info("Exécution du script d'enrôlement de la clé MOK")
        success, stdout, _ = metier_cmd.run("/bin/bash /usr/local/sbin/create-mok-gend", needs_sudo=True)

        mok_created = False
        for line in stdout.split("\n"):
            if "Il est maintenant nécessaire de redémarrer afin de finir l'importation de la clé MOK." in line.strip():
                mok_created = True
                success = True
            elif "MOK-JAMMY déjà enrôlée et bi-clé correspondante dans /var/lib/shim-signed/mok." in line.strip():
                success = True

        log.next_step()
        if success:
            message = "MOK créé avec succès, ne pas oublier de redémarrer pour finir la configuration" if mok_created else "MOK déjà présent, inutile de redémarrer"
            log.success(message)
        else:
            log.error("Problème avec la mise à jour MOK")
        return success

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
