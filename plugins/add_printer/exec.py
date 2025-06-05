#!/usr/bin/env python3
"""
Plugin pour l'ajout d'imprimantes à un système Linux via CUPS.
Configure les imprimantes selon divers paramètres extraits de la configuration fournie.
"""
import os
import sys
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import printers
from plugins_utils import utils_cmd

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Point d'entrée du plugin. Vérifie si la machine doit être traitée puis lance l'installation.
        """
        try:
            log.debug("Début de l'exécution du plugin add_printer")
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                return False

            return self._install_printers(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _install_printers(self, config: dict, log: Any, target_ip: str) -> bool:
        """
        Lance le processus d'installation des imprimantes en fonction de la configuration.
        """
        printer_conf = config.get('config')
        if not printer_conf:
            log.error("Aucune configuration d’imprimante fournie")
            return False

        model_content = printer_conf['printer_model_content']
        printer_name = printer_conf.get('printer_name')
        printer_ip = printer_conf.get('printer_ip')
        base_name = model_content.get('nom', '')
        mode = model_content.get('mode', '')
        socket = model_content.get('socket', '')
        ppd_file = model_content.get('ppdFile', '') if mode in ("ppd", "-P") else None
        model = None if ppd_file else ppd_file
        uri = f"{socket}{printer_ip}"

        utils = utils_cmd.UtilsCommands(log, target_ip)
        options_map = utils.get_all_options_dicts(model_content)

        couleurs = int(model_content.get('couleurs', 0))
        rectoverso = int(model_content.get('rectoverso', 0))
        agraffes = int(model_content.get('agraffes', 0))
        a3 = printer_conf.get('printer_a3')
        all_modes = printer_conf.get('printer_all')

        printer_cmd = printers.PrinterCommands(log, target_ip)

        total_steps = self._calculate_total_steps(all_modes, couleurs, rectoverso, agraffes, a3)
        log.set_total_steps(total_steps)

        printer_cmd.remove_viewer_configs(all_users=True)

        log.info(f"Installation de l'imprimante {printer_name} avec IP {printer_ip}")
        log.next_step()

        return self._execute_printer_installations(
            log, printer_cmd, utils, printer_name, base_name, uri,
            ppd_file, model, couleurs, rectoverso, agraffes, a3, all_modes, options_map
        )

    def _calculate_total_steps(self, all_modes, couleurs, rectoverso, agraffes, a3):
        """
        Calcule le nombre total d'étapes de l'installation.
        """
        steps = 4
        if not all_modes:
            if couleurs:
                steps += 1 + rectoverso
            if rectoverso:
                steps += 1
            if agraffes:
                steps += 2 + rectoverso + (1 if rectoverso and couleurs else 0)
            if a3:
                steps += 2 + rectoverso + (1 if rectoverso and couleurs else 0)
        return steps

    def _execute_printer_installations(self, log, printer_cmd, utils, name, base, uri,
                                       ppd, model, couleurs, recto, agraffes, a3, all_modes, opt):
        """
        Effectue l'installation des différentes variantes d'imprimantes selon les options.
        """
        success = True
        def install(nom_suffix, *dicts):
            nonlocal success
            if not success:
                return
            full_name = f"{base}_{name}_{nom_suffix}"
            log.info(f"Installation de {full_name}")
            opts = utils.merge_dictionaries(opt['ocommun'], *dicts)
            success = printer_cmd.add_printer(full_name, uri, ppd_file=ppd, model=model, options=opts)
            log.next_step()

        if all_modes:
            install("Recto_NB", opt['orecto'], opt['oa4'], opt['onb'])
            if couleurs: install("Recto_Couleurs", opt['orecto'], opt['oa4'], opt['ocouleurs'])
            if recto: install("RectoVerso_NB", opt['orectoverso'], opt['oa4'], opt['onb'])
            if couleurs and recto: install("RectoVerso_Couleurs", opt['orectoverso'], opt['oa4'], opt['ocouleurs'])
            if agraffes:
                install("Recto_NB_Agraffes", opt['orecto'], opt['oagraffes'], opt['onb'])
                if recto: install("RectoVerso_NB_Agraffes", opt['orectoverso'], opt['oagraffes'], opt['oa4'], opt['onb'])
                if couleurs: install("Recto_Couleurs_Agraffes", opt['orecto'], opt['oagraffes'], opt['oa4'], opt['ocouleurs'])
                if couleurs and recto: install("RectoVerso_Couleurs_Agraffes", opt['orectoverso'], opt['oagraffes'], opt['oa4'], opt['ocouleurs'])
            if a3:
                install("Recto_NB_A3", opt['orecto'], opt['oagraffes'], opt['oa3'], opt['onb'])
                if recto: install("RectoVerso_NB_A3", opt['orectoverso'], opt['oa3'], opt['onb'])
                if couleurs: install("Recto_Couleurs_A3", opt['orecto'], opt['oa3'], opt['ocouleurs'])
                if couleurs and recto: install("RectoVerso_Couleurs_A3", opt['orectoverso'], opt['oa3'], opt['ocouleurs'])
        else:
            if not couleurs:
                install("Recto_NB", opt['orecto'], opt['oa4'], opt['onb'])
            elif agraffes:
                install("RectoVerso_Couleurs_Agraffes", opt['orectoverso'], opt['oa4'], opt['ocouleurs'], opt['oagraffes'])
            else:
                install("RectoVerso_Couleurs", opt['orectoverso'], opt['oa4'], opt['ocouleurs'])

        msg = "Ajout de l'imprimante effectué avec succès" if success else "Erreur lors de l'ajout de l'imprimante"
        log.success(msg) if success else log.error(msg)
        return success

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
