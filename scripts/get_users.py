import os
import pwd
import grp
import traceback
from typing import Tuple, List, Dict, Union, Any
import sys
import os.path

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

sys.path.insert(0, os.path.join(project_root,"plugins"))

from plugins_utils import ldap

# Configurer le logging
try:
    # Importer directement depuis le chemin absolu
    sys.path.insert(0, os.path.join(project_root, 'ui'))
    from utils.logging import get_logger
    logger = get_logger('get_users')
except ImportError as e:
    # Fallback en cas d'erreur d'importation
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger('get_users')
    logger.error(f"Erreur d'importation du module de logging: {e}")

def get_users(home_dir: str = '',cuSort: bool = False, cu_list: str = "", execute: bool = True) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """
    Récupère la liste des utilisateurs à partir d'un répertoire home spécifique.

    Args:
        home_dir (str): Chemin du répertoire contenant les dossiers des utilisateurs
                       Par défaut : '/home'
        cuList (str): Liste des codes unités
        execute (bool): Si True, exécute la fonction, sinon retourne une liste vide

    Returns:
        tuple(bool, list/str): Tuple contenant:
            - True et la liste des utilisateurs en cas de succès
            - False et un message d'erreur en cas d'échec
    """
    logger.debug(f"get_users called with home_dir={home_dir}")
    logger.debug(f"Script path: {__file__}")
    logger.debug(f"Current working directory: {os.getcwd()}")
    
    if not execute:
        return True, []

    # Vérifier que le répertoire home existe
    if not os.path.exists(home_dir):
        error_msg = f"Le répertoire {home_dir} n'existe pas"
        logger.error(error_msg)
        return False, error_msg

    if not os.path.isdir(home_dir):
        error_msg = f"{home_dir} n'est pas un répertoire"
        logger.error(error_msg)
        return False, error_msg

    ldapCmd= ldap.LdapCommands(None, None)
    base_dn="dmdName=Personnes,dc=gendarmerie,dc=defense,dc=gouv,dc=fr"
    server="ldap.gendarmerie.fr"


    ldap_user_list=[]
    if cuSort == True:
        if 'cu_list' in locals():
            for cu in cu_list.split(","):
                cuSearch=f"(codeUnite={cu})"
                returnValue,resultats=ldapCmd.search(base_dn,server=server,attributes=None,filter_str=cuSearch)
                for r in resultats:
                    ldap_user_list.append(r['uid'])


    try:
        users = []
        # Liste uniquement les répertoires dans home_dir
        for username in os.listdir(home_dir):
            user_home = os.path.join(home_dir, username)

            # Ignorer les fichiers et les liens symboliques
            if not os.path.isdir(user_home):
                continue

            # Ignorer les dossiers cachés (commençant par un point)
            if username.startswith('.'):
                continue

            # Informations de base
            user_info = {
                'username': username,
                'home_path': user_home,
                'description': username  # Valeur par défaut pour l'affichage
            }

            # Essayer d'obtenir des informations supplémentaires du système
            try:
                pwd_info = pwd.getpwnam(username)
                user_info['uid'] = pwd_info.pw_uid
                user_info['gid'] = pwd_info.pw_gid
                user_info['shell'] = pwd_info.pw_shell
                user_info['enabled']= False
                user_info['full_name']= username
                if username in ldap_user_list:
                    user_info['enabled']= True
                # Informations sur le groupe principal
                try:
                    group_info = grp.getgrgid(pwd_info.pw_gid)
                    user_info['group'] = group_info.gr_name
                except KeyError:
                    user_info['group'] = str(pwd_info.pw_gid)

                # Enrichir la description avec le nom complet si disponible
                if pwd_info.pw_gecos:
                    gecos_parts = pwd_info.pw_gecos.split(',')
                    full_name = gecos_parts[0] if gecos_parts else pwd_info.pw_gecos 
                    if full_name and full_name != username:
                        user_info['description'] = f"{username} ({full_name})"
                        user_info['full_name']= full_name

            except KeyError:
                # L'utilisateur existe sur le disque mais pas dans /etc/passwd
                # C'est normal dans certains cas (ex: utilisateurs d'un autre système)
                logger.debug(f"Utilisateur {username} trouvé sur le disque mais absent de /etc/passwd")

            users.append(user_info)

        # Trier par nom d'utilisateur (insensible à la casse)
        try:
            users.sort(key=lambda x: x['full_name'].lower())
        except Exception as e:
            pass

        logger.debug(f"get_users found {len(users)} users: {[u['username'] for u in users]}")

        return True, users

    except PermissionError:
        error_msg = f"Permission refusée pour accéder au répertoire {home_dir}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Erreur lors de la récupération des utilisateurs: {str(e)}"
        logger.error(error_msg)
        logger.debug(traceback.format_exc())
        return False, error_msg