# install/plugins/plugins_utils/lvm.py
#!/usr/bin/env python3
"""
Fonctions utilitaires
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import json
from typing import Union, Optional, List, Dict, Any, Tuple

# Unités de taille LVM courantes
LVM_UNITS = {'k', 'm', 'g', 't', 'p', 'e'} # Kilo, Mega, Giga, Tera, Peta, Exa (puissances de 1024)

class UtilsCommands(PluginsUtilsBase):
    """
    Classe pour des fonctions utilitaires
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        super().__init__(logger, target_ip)

    def get_options_dict(self,data, log_levels: Optional[Dict[str, str]] = None):
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        elif isinstance(data, dict): # Au cas où ce serait déjà un dict
            return data
        return {} # Retourne un dict vide si ce n'est pas une liste [dict]

    def merge_dictionaries(self,*dictionaries, log_levels: Optional[Dict[str, str]] = None):
        """
        Fusionne un nombre quelconque de dictionnaires en un nouveau dictionnaire.

        Les clés des dictionnaires fournis plus tard dans la séquence d'arguments
        écraseront les clés identiques des dictionnaires précédents.

        Args:
            *dictionaries: Une séquence de zéro, un ou plusieurs dictionnaires à fusionner.

        Returns:
            dict: Un nouveau dictionnaire contenant toutes les paires clé-valeur
                des dictionnaires d'entrée. Retourne un dictionnaire vide si
                aucun argument n'est fourni.

        Raises:
            TypeError: Si l'un des arguments fournis n'est pas un dictionnaire.
        """
        merged_result = {}
        for dictionary in dictionaries:
            # Vérifier que chaque argument est bien un dictionnaire
            if not isinstance(dictionary, dict):
                raise TypeError(f"Tous les arguments doivent être des dictionnaires. "
                                f"Reçu un argument de type: {type(dictionary)}")
            # Mettre à jour le dictionnaire résultat avec le contenu du dictionnaire actuel
            # update() gère l'écrasement des clés existantes
            merged_result.update(dictionary)
        return merged_result

    def kill_process(self, process_id: Union[int, str], force: bool = False,
wait: bool = True, timeout: int = 10, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Tue un processus avec l'option de forcer l'arrêt.

        Args:
            process_id: ID du processus à tuer
            force: Si True, utilise SIGKILL (kill -9) au lieu de SIGTERM
            wait: Si True, attend que le processus soit terminé
            timeout: Temps d'attente maximum en secondes (si wait=True)

        Returns:
            bool: True si le processus a été tué avec succès, False sinon
        """
        pid = str(process_id)  # Convertir en chaîne pour la commande

        # Vérifier d'abord si le processus existe
        cmd_check = ['ps', '-p', pid, '-o', 'pid=']
        success_check, stdout_check, _ = self.run(cmd_check, check=False, no_output=True)

        if not success_check or not stdout_check.strip():
            self.log_warning(f"Le processus {pid} n'existe pas ou est déjà terminé", log_levels=log_levels)
            return True  # Considéré comme un succès puisque le processus n'existe plus

        # Commande pour tuer le processus
        if force:
            self.log_info(f"Envoi de SIGKILL au processus {pid}", log_levels=log_levels)
            cmd_kill = ['kill', '-9', pid]
        else:
            self.log_info(f"Envoi de SIGTERM au processus {pid}", log_levels=log_levels)
            cmd_kill = ['kill', pid]

        # Exécuter la commande kill
        success_kill, _, stderr_kill = self.run(cmd_kill, check=False)

        if not success_kill:
            self.log_error(f"Échec de la tentative de tuer le processus {pid}: {stderr_kill}", log_levels=log_levels)
            return False

        # Si wait=True, attendre que le processus soit terminé
        if wait:
            import time
            start_time = time.time()
            while time.time() - start_time < timeout:
                # Vérifier si le processus existe encore
                success_wait, stdout_wait, _ = self.run(cmd_check, check=False, no_output=True)
                if not success_wait or not stdout_wait.strip():
                    self.log_debug(f"Processus {pid} terminé avec succès", log_levels=log_levels)
                    return True

                # Attendre un peu avant de vérifier à nouveau
                time.sleep(0.5)

            # Si on arrive ici, le timeout a été atteint
            self.log_warning(f"Timeout atteint en attendant la fin du processus {pid}", log_levels=log_levels)

            # Essayer avec SIGKILL si on a utilisé SIGTERM initialement
            if not force:
                self.log_info(f"Tentative avec SIGKILL après échec de SIGTERM pour le processus {pid}", log_levels=log_levels)
                return self.kill_process(pid, force=True, wait=wait, timeout=timeout)

            return False  # Échec même avec SIGKILL

        return True  # Succès si on n'attendait pas la fin du processus

    def kill_process_by_name(self, process_name: str, force: bool = False,
                            all_instances: bool = False, wait: bool = True,
timeout: int = 10, log_levels: Optional[Dict[str, str]] = None) -> Tuple[bool, int]:
        """
        Tue un ou plusieurs processus par leur nom.

        Args:
            process_name: Nom du processus à tuer
            force: Si True, utilise SIGKILL (kill -9) au lieu de SIGTERM
            all_instances: Si True, tue toutes les instances correspondantes
            wait: Si True, attend que les processus soient terminés
            timeout: Temps d'attente maximum en secondes (si wait=True)

        Returns:
            Tuple[bool, int]: (Succès global, Nombre de processus tués)
        """
        # Commande pour trouver les PIDs correspondant au nom
        # Utilise pgrep qui est plus fiable que ps | grep
        cmd_find = ['pgrep', '-f', process_name]
        success_find, stdout_find, _ = self.run(cmd_find, check=False, no_output=True)

        # Si aucun processus n'est trouvé
        if not success_find or not stdout_find.strip():
            self.log_warning(f"Aucun processus trouvé avec le nom: {process_name}", log_levels=log_levels)
            return (True, 0)  # Considéré comme un succès puisque rien à tuer

        # Récupérer les PIDs trouvés
        pids = stdout_find.strip().split('\n')

        # Filtrer notre propre processus s'il apparaît dans la liste (éviter l'auto-kill)
        own_pid = str(os.getpid())
        if own_pid in pids:
            pids.remove(own_pid)

        # Si aucun processus à tuer après filtrage
        if not pids:
            self.log_warning(f"Aucun processus valide à tuer avec le nom: {process_name}", log_levels=log_levels)
            return (True, 0)

        # Limiter au premier processus si all_instances=False
        if not all_instances:
            pids = [pids[0]]
            self.log_info(f"Ciblage du processus {pids[0]} correspondant à '{process_name}'", log_levels=log_levels)
        else:
            self.log_info(f"Ciblage de {len(pids)} processus correspondant à '{process_name}'", log_levels=log_levels)

        # Tuer les processus
        success_count = 0
        for pid in pids:
            if self.kill_process(pid, force=force, wait=wait, timeout=timeout):
                success_count += 1

        # Vérifier si tous les processus ont été tués
        all_success = (success_count == len(pids))

        if all_success:
            self.log_success(f"{success_count} processus tués avec succès", log_levels=log_levels)
        else:
            self.log_warning(f"{success_count}/{len(pids)} processus tués - certains ont échoué", log_levels=log_levels)

        return (all_success, success_count)

    def get_all_options_dicts(self, options_config: dict) -> dict:
        return {
            key: self.get_options_dict(value)
            for key, value in options_config.items()
        }
