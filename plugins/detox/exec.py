#!/usr/bin/env python3
"""
Plugin pour renommer récursivement les fichiers d'un dossier avec Detox.
Vérifie la présence du dossier, installe Detox si nécessaire, puis applique le renommage.
"""
import os
import sys
import traceback
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta

# Configuration du chemin d'import pour trouver les modules communs
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import apt

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Point d'entrée du plugin. Vérifie les prérequis puis applique Detox sur un répertoire donné.
        """
        try:
            log.set_total_steps(3)
            src_dir = config['config'].get('src_dir')
            if not src_dir:
                log.error("Chemin source non fourni dans la configuration.")
                return False

            path = Path(src_dir)
            if not path.exists():
                log.error(f"Le dossier {src_dir} n'existe pas")
                return False
            log.info(f"Le dossier {src_dir} existe")
            log.next_step()

            apt_cmd = apt.AptCommands(log, target_ip)
            if not apt_cmd.is_installed("detox"):
                log.info("Detox non présent, tentative d'installation...")
                if not apt_cmd.install("detox", no_recommends=True):
                    log.error("Erreur dans l'installation de Detox")
                    return False
            else:
                log.info("Detox déjà installé")
            log.next_step()

            log.info("Exécution de Detox sur le dossier")
            success, stdout, stderr = apt_cmd.run(f"detox -r -v {src_dir}", needs_sudo=True)
            if not success:
                log.error(f"Erreur durant le renommage : {stderr}")
                return False

            log.next_step()
            log.success("Renommage des fichiers exécuté avec succès")
            return True

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
