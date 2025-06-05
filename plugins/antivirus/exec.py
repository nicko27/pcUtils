#!/usr/bin/env python3
"""
Plugin de vérification de l'installation et du bon fonctionnement
du logiciel antivirus ESET sur un système Linux.
"""
import os
import sys
import re
import traceback
from datetime import datetime, timedelta
from typing import Any

# Ajouter le répertoire parent au chemin de recherche Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import des modules internes
from plugins_utils import main
from plugins_utils import metier
from plugins_utils import printers
from plugins_utils import utils_cmd
from plugins_utils import dpkg
from plugins_utils import apt
from plugins_utils import services

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Point d'entrée du plugin. Vérifie si la machine doit être traitée puis lance le contrôle ESET.
        """
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._verify_eset(log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _verify_eset(self, log: Any, target_ip: str) -> bool:
        """
        Vérifie que les paquets ESET sont bien installés, que le service est actif
        et que les signatures virales sont à jour.
        """
        log.set_total_steps(4)
        apt_cmd = apt.AptCommands(log, target_ip)
        services_cmd = services.ServiceCommands(log, target_ip)
        utils_cmd_inst = utils_cmd.UtilsCommands(log, target_ip)

        if not apt_cmd.is_installed("eset-agent"):
            log.error("Paquet eset-agent absent")
            return False
        log.info("Paquet eset-agent bien installé")
        log.next_step()

        if not apt_cmd.is_installed("eset-endpoint-antivirus"):
            log.error("Paquet eset-endpoint-antivirus absent")
            return False
        log.info("Paquet eset-endpoint-antivirus bien installé")
        log.next_step()

        if not services_cmd.is_active("eea"):
            log.error("Service EEA n'est pas démarré")
            return False
        log.info("Service EEA bien démarré")
        log.next_step()

        success, stdout, stderr = utils_cmd_inst.run("/opt/eset/eea/bin/upd -l")
        if not success:
            log.error("Problème avec la commande UPD -l")
            return False

        date_moteur = self._extract_update_date(stdout)
        if not date_moteur:
            log.warning("Date de moteur non trouvée, tentative de mise à jour")
            return self._force_update(utils_cmd_inst, log)

        aujourd_hui = datetime.today().date()
        hier = aujourd_hui - timedelta(days=1)
        if date_moteur in (aujourd_hui, hier):
            log.info("Antivirus à jour")
            return True

        log.info("Antivirus non à jour, tentative de mise à jour")
        return self._force_update(utils_cmd_inst, log)

    def _extract_update_date(self, stdout: str) -> Any:
        """
        Extrait une date de mise à jour à partir de la sortie de la commande UPD -l.
        """
        for line in stdout.split('\n'):
            if "moteur" in line.lower():
                match = re.search(r"\b(\d{8})\b", line)
                if match:
                    try:
                        return datetime.strptime(match.group(1), "%Y%m%d").date()
                    except ValueError:
                        return None
        return None

    def _force_update(self, utils_cmd_inst, log):
        """
        Tente une mise à jour manuelle via la commande UPD -u.
        """
        success, stdout, stderr = utils_cmd_inst.run("/opt/eset/eea/bin/upd -u")
        if success:
            log.info("Mise à jour forcée effectuée")
            return True
        else:
            if re.compile("Mise à jour inutile. Les modules installés sont à jour.").match(stdout):
                return True
            else:
                log.error("Échec de la mise à jour via UPD")
                return False

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
