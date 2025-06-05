import subprocess
import json
import traceback
import os
import sys
from typing import Tuple, List, Dict, Union, Any

# Déterminer le chemin absolu de la racine du projet pcUtils
# Recherche le répertoire contenant le dossier 'plugins'
def find_project_root():
    # Commencer par le répertoire courant
    current_dir = os.path.abspath(os.getcwd())

    # Remonter jusqu'à trouver le répertoire racine du projet
    while current_dir != os.path.dirname(current_dir):  # Arrêter à la racine du système
        if os.path.exists(os.path.join(current_dir, 'plugins')) and os.path.exists(os.path.join(current_dir, 'ui')):
            return current_dir
        current_dir = os.path.dirname(current_dir)

    # Si on ne trouve pas, utiliser le répertoire parent du script comme fallback
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Obtenir le chemin absolu du répertoire racine du projet
project_root = find_project_root()

# Ajouter le répertoire racine au chemin de recherche Python
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Configurer le logging
try:
    # Importer directement depuis le chemin absolu
    sys.path.insert(0, os.path.join(project_root, 'ui'))
    from utils.logging import get_logger
    logger = get_logger('get_usb')
except ImportError as e:
    # Fallback en cas d'erreur d'importation
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger('get_usb')
    logger.error(f"Erreur d'importation du module de logging: {e}")

def get_usb(include_system_disk: bool = False, only_external: bool = False, only_internal: bool = False, **kwargs) -> Tuple[bool, Union[Dict[str, Any], str]]:
    """
    Récupère la liste des périphériques de stockage et leurs points de montage.

    Args:
        include_system_disk (bool): Si True, inclut les partitions du disque système
                                    Si False, exclut les partitions du disque système
        only_external (bool): Si True, ne renvoie que les périphériques externes (USB, etc.)
        only_internal (bool): Si True, ne renvoie que les périphériques internes

        Note: Si only_external et only_internal sont tous deux True, aucun filtre n'est appliqué

    Kwargs:
        Paramètres supplémentaires pouvant être passés via le fichier settings.yml

    Returns:
        tuple(bool, dict/str): Tuple contenant:
            - True et un dictionnaire contenant la liste des périphériques en cas de succès
            - False et un message d'erreur en cas d'échec
    """
    logger.debug(f"Recherche des périphériques (include_system_disk={include_system_disk}, only_external={only_external}, only_internal={only_internal}, kwargs={kwargs})")

    # Vérifier la cohérence des paramètres
    if only_external and only_internal:
        logger.warning("Les paramètres only_external et only_internal sont tous deux True, aucun filtre ne sera appliqué")
        only_external = only_internal = False

    # Vérifier si lsblk est disponible
    if not os.path.exists('/bin/lsblk') and not os.path.exists('/usr/bin/lsblk'):
        error_msg = "La commande lsblk n'est pas disponible sur ce système"
        logger.error(error_msg)
        return False, error_msg

    try:
        # Exécuter la commande lsblk pour lister les périphériques avec des informations détaillées
        # Ajouter HOTPLUG pour identifier les périphériques amovibles
        logger.debug("Exécution de la commande lsblk")
        result = subprocess.run(
            ['lsblk', '-o', 'NAME,SIZE,TYPE,MOUNTPOINT,PATH,FSTYPE,LABEL,MODEL,HOTPLUG,TRAN', '-J'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10  # Timeout de 10 secondes
        )

        # Vérifier si la commande a réussi
        if result.returncode != 0:
            error = f"Erreur lors de l'exécution de lsblk: {result.stderr.strip()}"
            logger.error(error)
            return False, error

        # Analyser la sortie JSON
        try:
            devices_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            error = f"Erreur de décodage JSON: {str(e)}"
            logger.error(error)
            logger.debug(f"Sortie de lsblk: {result.stdout}")
            return False, error

        # Déterminer quels sont les disques système (ceux qui contiennent la partition racine /)
        system_disks = []
        for device in devices_data.get('blockdevices', []):
            if device.get('type') == 'disk':
                # Vérifier si une des partitions est montée sur /
                for child in device.get('children', []):
                    if child.get('mountpoint') == '/':
                        system_disks.append(device.get('name', ''))
                        logger.debug(f"Disque système identifié: {device.get('name', '')}")
                        break

        devices = []
        # Traiter les périphériques
        for device in devices_data.get('blockdevices', []):
            # Ne traiter que les disques
            if device.get('type') == 'disk':
                device_name = device.get('name', '')

                # Vérifier si c'est un disque système qu'on doit exclure
                if not include_system_disk and device_name in system_disks:
                    logger.debug(f"Exclusion du disque système: {device_name}")
                    continue

                # Déterminer si le disque est externe ou interne
                # HOTPLUG=1 indique généralement un périphérique amovible
                # TRAN=usb indique un périphérique connecté en USB
                hotplug = device.get('hotplug', '0') == '1'
                tran = device.get('tran', '').lower()
                is_external = hotplug or tran == 'usb'

                # Filtrer selon les critères only_external ou only_internal
                if only_external and not is_external:
                    logger.debug(f"Exclusion du disque interne: {device_name}")
                    continue

                if only_internal and is_external:
                    logger.debug(f"Exclusion du disque externe: {device_name}")
                    continue

                # Informations supplémentaires du disque
                device_model = device.get('model', '').strip()

                # Traiter les partitions du disque
                partitions_to_process = device.get('children', [])

                # Si pas de partitions, mais le disque est monté, le traiter comme une partition
                if not partitions_to_process and device.get('mountpoint'):
                    partitions_to_process = [device]

                for partition in partitions_to_process:
                    if partition.get('type') in ('part', 'disk', 'crypt'):
                        part_name = partition.get('name', '')
                        path = partition.get('path', f"/dev/{part_name}")
                        size = partition.get('size', 'Inconnu')
                        mount_point = partition.get('mountpoint')
                        fs_type = partition.get('fstype', 'inconnu')
                        label = partition.get('label', '')

                        # Ignorer les partitions swap ou sans système de fichiers
                        if fs_type in ('swap', '', None):
                            continue

                        # Créer la description formatée
                        desc_parts = []
                        if label:
                            desc_parts.append(f"{label}")

                        if device_model:
                            desc_parts.append(f"{device_model}")

                        desc_parts.append(f"{path}")

                        if mount_point:
                            desc_parts.append(f"→ {mount_point}")
                        else:
                            desc_parts.append("→ Non monté")

                        desc_parts.append(f"({fs_type}, {size})")

                        # Ajouter indication si externe ou interne
                        if is_external:
                            desc_parts.append("[Externe]")
                        else:
                            desc_parts.append("[Interne]")

                        description = " ".join(desc_parts)

                        devices.append({
                            'device': part_name,
                            'path': path,
                            'size': size,
                            'mounted': mount_point is not None,
                            'mount_point': mount_point or '',
                            'fs_type': fs_type,
                            'label': label,
                            'model': device_model,
                            'is_external': is_external,
                            'description': description,
                            'value': path
                        })

        # Trier par nom de périphérique
        devices.sort(key=lambda x: x.get('device', '').lower())

        logger.debug(f"Trouvé {len(devices)} périphériques de stockage")

        # Retourner le résultat dans un dictionnaire, similaire à get_printer_models
        return True, {"devices": devices}

    except subprocess.TimeoutExpired:
        error_msg = "Timeout lors de l'exécution de la commande lsblk"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Erreur lors de la récupération des périphériques: {str(e)}"
        logger.error(error_msg)
        logger.debug(traceback.format_exc())
        return False, error_msg
