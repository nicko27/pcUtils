# install/plugins/plugins_utils/firewall.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour les fonctions métier
"""
from plugins_utils.plugins_utils_base import PluginsUtilsBase
from plugins_utils.dpkg import DpkgCommands
from plugins_utils.config_files import ConfigFileCommands
import traceback
LRPGN_CONFIG_FILE = "/usr/lib/lrpgn/travail/configuration/conf.ini"


class MetierCommands(PluginsUtilsBase):
    """
    Classe pour gérer les fonctions métier.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None, config={}):
        super().__init__(logger, target_ip)
        self.dpkg = DpkgCommands(logger,target_ip)
        self.cfc = ConfigFileCommands(logger,target_ip)
        self.config = config
        self.is_ssh = config.get('ssh_mode', False)
        self.ssh_sms = config.get("ssh_sms", "ggd027sf012027")
        self.ssh_sms_enabled = config.get("ssh_sms_enabled",False)
        self.ssh_lrpgn_enabled = config.get("ssh_lrpgn_enabled",False)
        self.ssh_lrpgn = config.get("ssh_lrpgn","travail/commun/Icare/Configuration/")
    #debug
        self.is_ssh = True
        self.ssh_sms_enabled = True
        self.ssh_lrpgn_enabled = True
    #fin debug

    def get_lrpgn_config_line(self):
        try:
            return self.cfc.get_ini_value(LRPGN_CONFIG_FILE,"DEFAULT", "dossier.configuration")
        except Exception as e:
            return ""

    def get_lrpgn_procedures_line(self):
        try:
            return self.cfc.get_ini_value(LRPGN_CONFIG_FILE,"DEFAULT", "dossier.procedures")
        except Exception as e:
            return ""

    def is_good_lrpgn(self):
        if self.ssh_lrpgn_enabled:
            lrpgn_configuration=self.get_lrpgn_config_line()
            if lrpgn_configuration is not None:
                if self.ssh_lrpgn in lrpgn_configuration:
                    return True
                else:
                    return False
            else:
                return False
        else:
            return True

    def is_good_sms(self) -> bool:
        """Vérifie si la bonne SMS est choisi."""
        if self.is_ssh and self.ssh_sms_enabled:
            current_sms_tbl=self.get_sms()
            if self.ssh_sms in current_sms_tbl:
                return True
            else:
                return False
        else:
            return True

    def get_sms(self):
        try:
            current_sms=self.dpkg.get_debconf_value("gend-base-config-debconf","gendebconf/srfic")
            if current_sms is None:
                return []
            current_sms_tbl=current_sms.split(';')
            return current_sms_tbl
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            return []

    def should_process(self) -> bool:
            return not self.config.get('ssh_mode', False) or (self.is_good_sms() and self.is_good_lrpgn())