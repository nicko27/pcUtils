import os
import json
import platform
import subprocess
import socket
import traceback

def get_system_info():
    """
    Récupère les informations système de la machine.
    
    Returns:
        tuple(bool, list/str): Tuple contenant:
            - True et la liste des informations système en cas de succès
            - False et un message d'erreur en cas d'échec
    """
    try:
        info = []
        
        # Récupérer les informations de base sur le système
        uname = platform.uname()
        hostname = socket.gethostname()
        
        # Informations sur le système d'exploitation
        os_info = {
            'name': 'Système d\'exploitation',
            'key': 'os',
            'value': f"{uname.system} {uname.release}",
            'description': f"OS: {uname.system} {uname.release}"
        }
        info.append(os_info)
        
        # Informations sur la machine
        machine_info = {
            'name': 'Machine',
            'key': 'machine',
            'value': uname.machine,
            'description': f"Machine: {uname.machine}"
        }
        info.append(machine_info)
        
        # Nom d'hôte
        host_info = {
            'name': 'Nom d\'hôte',
            'key': 'hostname',
            'value': hostname,
            'description': f"Hostname: {hostname}"
        }
        info.append(host_info)
        
        # Informations sur le processeur
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if line.startswith('model name'):
                        cpu_model = line.split(':', 1)[1].strip()
                        cpu_info = {
                            'name': 'Processeur',
                            'key': 'cpu',
                            'value': cpu_model,
                            'description': f"CPU: {cpu_model}"
                        }
                        info.append(cpu_info)
                        break
        except:
            # Méthode alternative pour obtenir les informations CPU
            try:
                result = subprocess.run(
                    ['lscpu'], 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if 'Model name' in line:
                            cpu_model = line.split(':', 1)[1].strip()
                            cpu_info = {
                                'name': 'Processeur',
                                'key': 'cpu',
                                'value': cpu_model,
                                'description': f"CPU: {cpu_model}"
                            }
                            info.append(cpu_info)
                            break
            except:
                # Si toutes les méthodes échouent, ajouter une entrée générique
                cpu_info = {
                    'name': 'Processeur',
                    'key': 'cpu',
                    'value': uname.processor or 'Unknown',
                    'description': f"CPU: {uname.processor or 'Unknown'}"
                }
                info.append(cpu_info)
        
        # Informations sur la mémoire
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal'):
                        mem_total = int(line.split()[1]) // 1024  # Convertir en Mo
                        mem_info = {
                            'name': 'Mémoire RAM',
                            'key': 'memory',
                            'value': f"{mem_total} Mo",
                            'description': f"RAM: {mem_total} Mo"
                        }
                        info.append(mem_info)
                        break
        except:
            # Si ça échoue, ajouter une entrée générique
            mem_info = {
                'name': 'Mémoire RAM',
                'key': 'memory',
                'value': 'Unknown',
                'description': "RAM: Unknown"
            }
            info.append(mem_info)
        
        return True, info
        
    except Exception as e:
        error_msg = f"Erreur lors de la récupération des informations système: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return False, error_msg

def get_network_interfaces():
    """
    Récupère la liste des interfaces réseau.
    
    Returns:
        tuple(bool, list/str): Tuple contenant:
            - True et la liste des interfaces réseau en cas de succès
            - False et un message d'erreur en cas d'échec
    """
    try:
        interfaces = []
        
        # Utiliser /proc/net/dev pour obtenir la liste des interfaces
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()
            
        # Parcourir les lignes (sauter l'en-tête)
        for line in lines[2:]:
            parts = line.strip().split(':', 1)
            if len(parts) == 2:
                if_name = parts[0].strip()
                
                # Ignorer les interfaces loopback et non-physiques comme docker ou bridge
                if if_name == 'lo' or if_name.startswith(('docker', 'br-', 'veth')):
                    continue
                
                # Obtenir l'adresse IP (si disponible)
                ip_address = ''
                try:
                    result = subprocess.run(
                        ['ip', '-o', '-4', 'addr', 'show', if_name], 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE, 
                        text=True
                    )
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            parts = line.strip().split()
                            for i, part in enumerate(parts):
                                if part == 'inet' and i + 1 < len(parts):
                                    ip_address = parts[i + 1].split('/')[0]
                                    break
                except Exception:
                    pass
                
                # Déterminer le type (wifi, ethernet, etc.)
                if_type = 'unknown'
                if 'wlan' in if_name or 'wifi' in if_name or 'wl' in if_name:
                    if_type = 'wifi'
                elif 'eth' in if_name or 'en' in if_name:
                    if_type = 'ethernet'
                
                # Créer la description
                description = f"{if_name}"
                if ip_address:
                    description += f" ({ip_address})"
                
                interfaces.append({
                    'name': if_name,
                    'type': if_type,
                    'ip_address': ip_address,
                    'description': description
                })
        
        # Trier par nom d'interface
        interfaces.sort(key=lambda x: x['name'])
        return True, interfaces
    except Exception as e:
        error_msg = f"Erreur lors de la récupération des interfaces réseau: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return False, error_msg
