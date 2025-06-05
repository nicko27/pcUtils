import socket
import traceback
import sys
import os

# Ajouter le répertoire parent au chemin de recherche Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from utils.logging import get_logger
    logger = get_logger('get_ip')
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('get_ip')

def get_local_ip():
    """
    Récupère l'adresse IP locale de la machine.
    
    Returns:
        tuple(bool, dict) ou tuple(bool, str): Tuple contenant:
            - True et un dictionnaire avec l'adresse IP en cas de succès
            - False et un message d'erreur en cas d'échec
    """
    # Crée un socket pour obtenir l'adresse IP locale
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # Essaie de se connecter à un hôte externe, mais sans envoyer de données.
        s.connect(('10.254.254.254', 1))  # Adresse IP non-routable (en dehors de ton réseau local)
        local_ip = s.getsockname()[0]     # Récupère l'adresse IP locale de l'interface
        octet_1, octet_2, octet_3, octet_4 = local_ip.split('.')
        
        # Règles spécifiques pour certaines plages d'IP
        if octet_1 == '128' and octet_2 == '81' and octet_3 in ['2','3']:
            local_ip = '128.81.2.184'
        elif octet_1 == '128' and octet_2 == '81' and octet_3 in ['4','5']:
            local_ip = '128.81.4.184'
        else:
            local_ip = f"{octet_1}.{octet_2}.{octet_3}.220"
        
        # Retourne un dictionnaire au lieu d'un tuple simple valeur
        return True, {"ip": local_ip}
        
    except Exception as e:
        error_msg = f"Erreur lors de la récupération de l'IP locale: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return False, error_msg
    
    finally:
        try:
            s.close()
        except:
            pass