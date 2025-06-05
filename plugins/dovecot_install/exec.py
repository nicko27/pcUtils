#!/usr/bin/env python3
"""
Plugin de configuration Dovecot pour créer un namespace public d'archivage.
Inclut sauvegarde des fichiers existants, configuration ACL et redémarrage du service.
"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

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

DOVECOT_CONFIG_PATH = "/etc/dovecot"
MAIL_ARCHIVE_PATH = "/partage/Mail_archive"

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._configure_dovecot(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _configure_dovecot(self, config: dict, log: Any, target_ip: str) -> bool:
        apt_cmd = apt.AptCommands(log, target_ip)
        files_cmd = files.FilesCommands(log, target_ip)
        services_cmd = services.ServiceCommands(log, target_ip)
        dovecot_cmd = dovecot.DovecotCommands(log, target_ip)

        cfg = config.get("config", {})
        unit = cfg.get("unite", "BT")
        archive_name = f"Archives_{unit}"
        archive_location = f"maildir:{MAIL_ARCHIVE_PATH}/{unit}"

        admin_groups = cfg.get("admin", "unite_solc.bdrij.ggd27").split(',')
        modif_groups = cfg.get("modif", "").split(',')
        user_groups = cfg.get("user", "").split(',')
        sauvegarde = bool(cfg.get("sauvegarde"))

        total_steps = 4 + sauvegarde + len(admin_groups) + len(modif_groups) + len(user_groups)
        log.set_total_steps(total_steps)

        if not self._install_dovecot(apt_cmd, log):
            return False

        if not self._sauvegarde_config(files_cmd, log, sauvegarde):
            return False

        self._apply_acls(dovecot_cmd, log, archive_name, admin_groups, modif_groups, user_groups)

        if not self._ajoute_namespace(dovecot_cmd, log, unit, archive_name, archive_location):
            return False

        if not services_cmd.restart("dovecot"):
            log.error("Impossible de redémarrer le service dovecot")
            return False

        log.next_step()
        log.success("Dovecot installé et configuré avec succès")
        return True

    def _install_dovecot(self, apt_cmd, log):
        if not apt_cmd.is_installed("dovecot-gend"):
            log.info("Installation de dovecot-gend")
            if not apt_cmd.install("dovecot-gend"):
                log.error("Impossible d'installer dovecot-gend")
                return False
        else:
            log.info("Paquet dovecot-gend bien installé")
        log.next_step()
        return True

    def _sauvegarde_config(self, files_cmd, log, sauvegarde):
        log.info("Sauvegarde des fichiers de configuration existants")
        moment = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        backup_dir = Path(f"/root/dovecot/{moment}")

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            log.next_step()
            if not files_cmd.copy_dir(DOVECOT_CONFIG_PATH, str(backup_dir), "copieDovecot"):
                log.error("Impossible de copier les fichiers Dovecot")
                return False
            log.next_step()
            if sauvegarde and not files_cmd.copy_dir(MAIL_ARCHIVE_PATH, str(backup_dir / "Mail_archive"), "copieMA"):
                log.error("Impossible de sauvegarder Mail_archive")
                return False
            if sauvegarde:
                log.next_step()
        except Exception as e:
            log.error("Erreur pendant la sauvegarde : " + str(e))
            return False

        return True

    def _apply_acls(self, dovecot_cmd, log, archive_name, admin, modif, user):
        for group in admin:
            if group:
                log.info(f"Ajout des droits admin pour {group}")
                dovecot_cmd.add_acl_entry(archive_name, f"group={group}", "lrwtipekxas")
                log.next_step()

        for group in modif:
            if group:
                log.info(f"Ajout des droits modif pour {group}")
                dovecot_cmd.add_acl_entry(archive_name, f"group={group}", "lrwtipekxs")
                log.next_step()

        for group in user:
            if group:
                log.info(f"Ajout des droits user pour {group}")
                dovecot_cmd.add_acl_entry(archive_name, f"group={group}", "lrst")
                log.next_step()

    def _ajoute_namespace(self, dovecot_cmd, log, unit, name, location):
        log.info("Ajout du namespace public d'archivage")
        ns_config = {
            "inbox": "no",
            "type": "public",
            "separator": "/",
            "prefix": name,
            "location": location,
            "subscriptions": "no",
            "list": "yes"
        }
        try:
            if not dovecot_cmd.add_namespace(unit, namespace_config=ns_config, backup="False"):
                log.error("Impossible d'ajouter le namespace")
                return False
            log.next_step()
            return True
        except Exception as e:
            log.error("Erreur dans la configuration du namespace : " + str(e))
            return False

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
