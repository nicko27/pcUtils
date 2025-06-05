#!/usr/bin/env python3
"""
Plugin de nettoyage des dossiers locaux Dovecot dans Thunderbird.
Supprime le script d'auto-ajout, ferme Thunderbird, puis modifie prefs.js.
"""
import os
import sys
import shutil
import traceback
from pathlib import Path
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import utils_cmd
from plugins_utils import services
from plugins_utils import mozilla_prefs
from plugins_utils import security

DOVECOT_AUTOADD = "/etc/profile.d/dovecot-autoadd.sh"
HOME_DIR = "/home"

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            log.set_total_steps(3)

            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._clean_thunderbird_config(log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False


    def _clean_thunderbird_config(self, log: Any, target_ip: str) -> bool:
        utils = utils_cmd.UtilsCommands(log, target_ip)
        mozilla = mozilla_prefs.MozillaPrefsCommands(log, target_ip)
        secur = security.SecurityCommands(log, target_ip)

        self._supprime_script_auto(log)
        log.next_step()

        if not self._ferme_thunderbird(utils, log):
            return False
        log.next_step()

        self._nettoie_profils_thunderbird(log, mozilla, secur)

        log.next_step()
        log.success("Dossiers Locaux Dovecot supprimés avec succès pour tous les utilisateurs")
        return True

    def _supprime_script_auto(self, log):
        if os.path.isfile(DOVECOT_AUTOADD):
            try:
                os.remove(DOVECOT_AUTOADD)
                log.info("Fichier d'ajout automatique supprimé")
            except Exception:
                log.warning("Impossible de supprimer le script d'ajout automatique")

    def _ferme_thunderbird(self, utils, log):
        success, _ = utils.kill_process_by_name("thunderbird")
        if not success:
            log.error("Impossible d'arrêter Thunderbird")
            return False
        return True

    def _nettoie_profils_thunderbird(self, log, mozilla, secur):
        log.info("Traitement des profils Thunderbird")

        for user_dir in Path(HOME_DIR).iterdir():
            if not user_dir.is_dir():
                continue

            tb_dir = user_dir / ".thunderbird"
            if not tb_dir.exists():
                continue

            for prefs_file in tb_dir.glob("*.default*/prefs.js"):
                log.info(f"Lecture de {prefs_file}")
                prefs = mozilla.read_prefs_file(str(prefs_file))
                if prefs is None:
                    log.warning(f"Impossible de lire le fichier {prefs_file}")
                    continue

                idx = next((i for i in range(10)
                            if prefs.get(f"mail.identity.id{i}.organization") ==
                            "Dossiers_Locaux_Unites_via_Dovecot (ne pas effacer ou modifier cette ligne)"), None)

                if idx is None:
                    continue

                keep_keys = [k for k in prefs
                             if not k.startswith(f"mail.identity.id{idx}") and
                                not k.startswith(f"mail.account.account{idx}.identities") and
                                not k.startswith(f"mail.account.account{idx}.server")]

                cleaned_prefs = {k: prefs[k] for k in keep_keys}
                if not mozilla.write_prefs_file(str(prefs_file), cleaned_prefs, backup=True):
                    log.warning(f"Impossible de modifier {prefs_file}")
                secur.set_ownership(str(prefs_file), user_dir.name, user_dir.name)

            for imap_dir in tb_dir.glob("*.default*/ImapMail"):
                for imap_subdir in imap_dir.iterdir():
                    if imap_subdir.name.startswith("ggd"):
                        shutil.rmtree(imap_subdir, ignore_errors=True)

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
