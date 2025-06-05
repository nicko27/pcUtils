#!/usr/bin/env python3
"""
Plugin pour déployer le script dovecot-autoadd.sh et l'exécuter pour chaque utilisateur.
Ce script est supposé modifier les fichiers prefs.js des profils Thunderbird pour activer l'accès au namespace Dovecot.
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
from plugins_utils import utils_cmd
from plugins_utils import dpkg
from plugins_utils import apt
from plugins_utils import services
from plugins_utils import files
from plugins_utils import config_files
from plugins_utils import dovecot

DOVECOT_PROFILE_TARGET = "/etc/profile.d"
SCRIPT_FILENAME = "dovecot-autoadd.sh"

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._deploy_script(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False


    def _deploy_script(self, config: dict, log: Any, target_ip: str) -> bool:
        cfg = config.get("config", {})
        sms = cfg.get("sms", "").strip()
        if not sms or not isinstance(sms, str) or not re.match(r"^[a-zA-Z0-9._-]+$", sms):
            log.error("Champ 'sms' invalide ou manquant dans la configuration")
            return False

        files_cmd = files.FilesCommands(log, target_ip)
        log.set_total_steps(4)

        if not self._verifie_script_existant(log):
            return False
        log.next_step()

        if not self._copie_et_prepare_script(files_cmd, log, sms):
            return False
        log.next_step()

        if not self._execute_script(files_cmd, log):
            return False

        log.next_step()
        log.success("Script dovecot-autoadd déployé et exécuté avec succès")
        return True

    def _verifie_script_existant(self, log):
        script_path = Path(__file__).resolve().parent / SCRIPT_FILENAME
        if not script_path.exists():
            log.error(f"Script introuvable: {script_path}")
            return False

        with open(script_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line.startswith("#!"):
                log.warning("Le script ne contient pas de shebang")
            elif "bash" not in first_line:
                log.warning("Le shebang ne mentionne pas bash : " + first_line)
        return True

    def _copie_et_prepare_script(self, files_cmd, log, sms):
        src = Path(__file__).resolve().parent / SCRIPT_FILENAME
        dst = Path(DOVECOT_PROFILE_TARGET) / SCRIPT_FILENAME

        log.info(f"Copie de {SCRIPT_FILENAME} vers {dst}")
        if not files_cmd.copy_file(str(src), str(dst)):
            log.error("Impossible de copier le script")
            return False

        if not files_cmd.replace_in_file(str(dst), "%%DOVECOT_SMS%%", sms):
            log.error("Erreur lors du remplacement dans le script")
            return False

        return True

    def _execute_script(self, files_cmd, log):
        log.info("Exécution du script dovecot-autoadd via bash")
        success, stdout, stderr = files_cmd.run(f"/bin/bash {DOVECOT_PROFILE_TARGET}/{SCRIPT_FILENAME}", no_output=False, needs_sudo=True)
        if not success:
            log.error("Erreur à l'exécution du script :\n" + stderr)
            return False
        return True

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
