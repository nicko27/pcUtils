#!/usr/bin/env python3
"""
Plugin pour ajouter un utilisateur de scan et configurer un dossier de scan partagé via Samba.
"""
import os
import sys
import traceback
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import users_groups
from plugins_utils import interactive_commands
from plugins_utils import security

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            self.metier_cmd = metier.MetierCommands(log, target_ip, config)
            self.users_cmd = users_groups.UserGroupCommands(log, target_ip)
            self.interactive_cmd = interactive_commands.InteractiveCommands(log, target_ip)
            self.security_cmd = security.SecurityCommands(log, target_ip)
            self.config = config.get("config", {})
            self.log = log

            if not self.metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._configure()

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _configure(self) -> bool:
        self._init_steps()
        if not self._add_user(): return False
        if not self._setup_samba(): return False
        if self.config.get("create_scan_dir") and not self._setup_directory(): return False
        self.log.success("Configuration effectuée avec succès")
        return True

    def _init_steps(self):
        steps = 3
        if self.config.get("create_scan_dir"):
            steps += 4
            if not os.path.isdir(self.config.get("scan_directory")):
                steps += 1
        self.log.set_total_steps(steps)

    def _add_user(self) -> bool:
        user = self.config.get("user")
        password = self.config.get("password")
        self.log.info("Ajout de l'utilisateur scan")
        error = self.users_cmd.add_user(user, password, home_dir=None, create_home=False)
        self.log.next_step()
        if error:
            self.log.error(f"Erreur lors de l'ajout de l'utilisateur {user}")
            return False
        return True

    def _setup_samba(self) -> bool:
        user = self.config.get("user")
        password = self.config.get("password")
        scenario = [("New SMB password:", password, None), ("Retype new SMB password:", password, None)]
        success, _ = self.interactive_cmd.run_scenario(f"/usr/bin/smbpasswd -a {user}", scenario)
        self.log.next_step()
        if not success:
            self.log.error(f"Erreur lors de l'ajout de l'utilisateur {user} pour samba")
            return False
        success, _, _ = self.interactive_cmd.run(["/usr/bin/smbpasswd", "-e", user])
        self.log.next_step()
        if not success:
            self.log.error(f"Erreur lors de l'activation samba de l'utilisateur {user}")
            return False
        self.log.info(f"Activation samba de l'utilisateur {user} effectuée avec succès")
        self.log.next_step()
        return True

    def _setup_directory(self) -> bool:
        path = self.config.get("scan_directory")
        if not os.path.isdir(path):
            try:
                os.makedirs(path, mode=0o777)
                self.log.info(f"Création du dossier {path} effectuée avec succès")
            except Exception:
                self.log.error(f"Erreur lors de la création du dossier {path}")
                return False
            self.log.next_step()

        if not self.security_cmd.set_permissions(path, mode="u+t", recursive=True):
            self.log.error(f"Erreur lors de la mise en place des droits sur {path}")
            return False
        self.log.next_step()

        if not self.security_cmd.set_ownership(path, "nobody", "nogroup", recursive=True):
            self.log.error(f"Erreur lors de l'affectation de nobody:nogroup sur {path}")
            return False
        self.log.next_step()

        if not self.security_cmd.set_acl(path, "u::rwx", recursive=True, modify=True):
            self.log.error(f"Erreur lors de la mise en place des ACLs récursives sur {path}")
            return False
        self.log.next_step()

        if not self.security_cmd.set_acl(path, "u::rx", recursive=False, modify=True):
            self.log.error(f"Erreur lors de la mise en place des ACLs non récursives sur {path}")
            return False
        self.log.next_step()
        return True

if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)
