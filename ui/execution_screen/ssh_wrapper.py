#!/usr/bin/env python3
"""
Script wrapper pour l'exécution SSH des plugins - Version corrigée.
Ce script est exécuté sur la machine distante et gère l'exécution du plugin avec sudo si nécessaire.
Version avec sortie en temps réel.
"""

import os
import sys
import json
import tempfile
import traceback
import subprocess
import threading
import queue
import select
import time
from datetime import datetime


# Ajouter le répertoire parent au chemin de recherche pour trouver les modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Configurer le répertoire de logs
def ensure_log_dir():
    # Utiliser un répertoire temporaire accessible en écriture
    log_dir = os.path.join(tempfile.gettempdir(), 'pcUtils_logs')
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"Répertoire de logs créé: {log_dir}", flush=True)
        except Exception as e:
            print(f"Erreur lors de la création du répertoire de logs: {e}", flush=True)
            # Utiliser /tmp comme fallback
            log_dir = tempfile.gettempdir()

    # Définir la variable d'environnement pour que les plugins puissent trouver le répertoire de logs
    os.environ['PCUTILS_LOG_DIR'] = log_dir
    return log_dir

log_dir = ensure_log_dir()
os.environ['PCUTILS_LOG_DIR'] = log_dir
print(f"Variable d'environnement PCUTILS_LOG_DIR définie à: {log_dir}", flush=True)

# Importer les modules après avoir configuré les chemins
try:
    # Importer les classes nécessaires directement
    from plugins_utils.plugin_logger import PluginLogger

    # Initialiser le logger pour le wrapper
    log = PluginLogger(plugin_name="ssh_wrapper", instance_id=0, ssh_mode=True)
    log.init_logs()

except ImportError as e:
    print(f"[LOG] [ERROR] Impossible d'importer les modules nécessaires: {e}", flush=True)
    print(f"[LOG] [ERROR] {traceback.format_exc()}", flush=True)
    sys.exit(1)

def run_command(cmd, needs_sudo=False, root_password=None):
    """
    Exécute une commande avec ou sans sudo.

    Args:
        cmd: Commande à exécuter (liste)
        needs_sudo: Si True, utilise sudo
        root_password: Mot de passe root pour sudo

    Returns:
        Tuple (success, stdout, stderr)
    """
    try:
        if needs_sudo:
            # Ajouter sudo à la commande
            sudo_cmd = ['sudo', '-S'] + cmd

            # Préparer l'environnement
            env = os.environ.copy()
            env['DEBIAN_FRONTEND'] = 'noninteractive'

            # Exécuter avec sudo
            process = subprocess.Popen(
                sudo_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Envoyer le mot de passe si fourni
            input_data = None
            if root_password:
                input_data = root_password + '\n'

            stdout, stderr = process.communicate(input=input_data, timeout=300)

        else:
            # Exécuter sans sudo
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout, stderr = process.communicate(timeout=300)

        success = process.returncode == 0
        return success, stdout, stderr

    except subprocess.TimeoutExpired:
        if 'process' in locals():
            process.kill()
        return False, "", "Timeout d'exécution"
    except Exception as e:
        return False, "", str(e)

def emit_json_log(level, message):
    """Émet un log au format JSON avec flush immédiat."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message
    }
    print(json.dumps(log_entry), flush=True)

def run_command_realtime(cmd, needs_sudo=False, root_password=None):
    """
    Exécute une commande avec ou sans sudo en affichant la sortie en temps réel.

    Args:
        cmd: Commande à exécuter (liste)
        needs_sudo: Si True, utilise sudo
        root_password: Mot de passe root pour sudo

    Returns:
        Tuple (success, all_stdout_lines, all_stderr_lines)
    """
    try:
        if needs_sudo:
            # Ajouter sudo à la commande
            sudo_cmd = ['sudo', '-S'] + cmd
        else:
            sudo_cmd = cmd

        # Préparer l'environnement
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        # Forcer l'absence de buffering pour Python
        env['PYTHONUNBUFFERED'] = '1'

        emit_json_log("debug", f"Exécution de la commande: {' '.join(sudo_cmd)}")

        # Créer le processus avec des pipes séparés
        process = subprocess.Popen(
            sudo_cmd,
            stdin=subprocess.PIPE if needs_sudo and root_password else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Ligne par ligne
            env=env,
            universal_newlines=True
        )

        # Envoyer le mot de passe sudo si nécessaire
        if needs_sudo and root_password:
            try:
                process.stdin.write(root_password + '\n')
                process.stdin.flush()
                process.stdin.close()
            except (BrokenPipeError, IOError) as e:
                emit_json_log("warning", f"Impossible d'écrire le mot de passe sudo: {e}")

        # Collections pour stocker toutes les sorties
        all_stdout_lines = []
        all_stderr_lines = []

        # Fonction pour lire un flux en temps réel
        def read_stream(stream, is_stderr=False, stream_name=""):
            """Lit un flux ligne par ligne et l'affiche en temps réel."""
            lines_collected = []

            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break

                    line = line.rstrip('\n\r')
                    if not line:
                        continue

                    lines_collected.append(line)

                    # Afficher immédiatement la ligne
                    try:
                        # Essayer de parser comme JSON pour garder le format
                        if line.strip().startswith('{') and line.strip().endswith('}'):
                            # C'est déjà du JSON, le passer tel quel
                            print(line, flush=True)
                        else:
                            # Créer un JSON pour la ligne
                            log_entry = {
                                "timestamp": datetime.now().isoformat(),
                                "level": "error" if is_stderr else "info",
                                "message": line,
                                "plugin_name": "plugin_execution",
                                "stream": stream_name
                            }
                            print(json.dumps(log_entry), flush=True)
                    except Exception as json_err:
                        # Fallback: afficher la ligne brute
                        emit_json_log("error" if is_stderr else "info", line)

            except Exception as e:
                emit_json_log("error", f"Erreur lecture {stream_name}: {e}")

            return lines_collected

        # Lire les deux flux en parallèle avec threading
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()

        def stdout_reader():
            try:
                lines = read_stream(process.stdout, False, "stdout")
                stdout_queue.put(lines)
            except Exception as e:
                emit_json_log("error", f"Erreur thread stdout: {e}")
                stdout_queue.put([])

        def stderr_reader():
            try:
                lines = read_stream(process.stderr, True, "stderr")
                stderr_queue.put(lines)
            except Exception as e:
                emit_json_log("error", f"Erreur thread stderr: {e}")
                stderr_queue.put([])

        # Démarrer les threads de lecture
        stdout_thread = threading.Thread(target=stdout_reader, daemon=True)
        stderr_thread = threading.Thread(target=stderr_reader, daemon=True)

        stdout_thread.start()
        stderr_thread.start()

        # Attendre la fin du processus
        return_code = process.wait()

        # Attendre que les threads de lecture terminent
        stdout_thread.join(timeout=5.0)
        stderr_thread.join(timeout=5.0)

        # Récupérer les résultats
        try:
            all_stdout_lines = stdout_queue.get_nowait()
        except queue.Empty:
            all_stdout_lines = []

        try:
            all_stderr_lines = stderr_queue.get_nowait()
        except queue.Empty:
            all_stderr_lines = []

        success = return_code == 0
        emit_json_log("debug", f"Commande terminée avec code: {return_code}")

        return success, all_stdout_lines, all_stderr_lines

    except subprocess.TimeoutExpired:
        if 'process' in locals():
            process.kill()
        emit_json_log("error", "Timeout d'exécution")
        return False, [], ["Timeout d'exécution"]
    except Exception as e:
        emit_json_log("error", f"Erreur exécution commande: {e}")
        emit_json_log("error", traceback.format_exc())
        return False, [], [str(e)]

def main():
    """Fonction principale"""
    try:
        # Vérifier les arguments
        if len(sys.argv) != 2:
            log.error("Usage: python3 ssh_wrapper.py <wrapper_config_file>")
            sys.exit(1)

        wrapper_config_file = sys.argv[1]

        # Vérifier que le fichier de configuration wrapper existe
        if not os.path.exists(wrapper_config_file):
            log.error(f"Le fichier de configuration wrapper n'existe pas: {wrapper_config_file}")
            sys.exit(1)

        # Lire la configuration du wrapper
        try:
            with open(wrapper_config_file, 'r', encoding='utf-8') as f:
                wrapper_config = json.load(f)
        except json.JSONDecodeError as e:
            log.error(f"Erreur lors de la lecture du fichier de configuration wrapper: {e}")
            sys.exit(1)

        if not wrapper_config:
            log.error("Le fichier de configuration wrapper est vide")
            sys.exit(1)

        # Récupérer les paramètres de configuration du wrapper
        plugin_path = wrapper_config.get('plugin_path')
        plugin_config = wrapper_config.get('plugin_config', {})
        needs_sudo = wrapper_config.get('needs_sudo', False)
        root_password = wrapper_config.get('root_password')

        # Récupérer les identifiants SSH depuis la configuration du plugin si disponible
        ssh_config = plugin_config.get('config', {})
        ssh_user = ssh_config.get('ssh_user')
        ssh_passwd = ssh_config.get('ssh_passwd')
        ssh_root_same = ssh_config.get('ssh_root_same', True)
        ssh_root_passwd = ssh_config.get('ssh_root_passwd')

        # Si le mot de passe root n'est pas fourni mais que ssh_root_same est True, utiliser ssh_passwd
        if not root_password and needs_sudo:
            if ssh_root_same and ssh_passwd:
                log.info("Utilisation du mot de passe SSH comme mot de passe root (ssh_root_same=true)")
                root_password = ssh_passwd
            elif ssh_root_passwd:
                log.info("Utilisation du mot de passe root spécifique depuis la configuration SSH")
                root_password = ssh_root_passwd

            if root_password:
                log.info("Mot de passe root récupéré depuis la configuration")
            else:
                log.warning("Aucun mot de passe root trouvé, sudo pourrait échouer")

        if not plugin_path:
            log.error("Chemin du plugin non spécifié dans la configuration")
            sys.exit(1)

        if not os.path.exists(plugin_path):
            log.error(f"Le script du plugin n'existe pas: {plugin_path}")
            sys.exit(1)

        # Indiquer que nous sommes en mode SSH pour le plugin
        os.environ['SSH_EXECUTION'] = '1'
        if root_password:
            os.environ['SUDO_PASSWORD'] = root_password

        # Identifier le type de plugin (bash ou python)
        is_bash_plugin = plugin_path.endswith('main.sh')

        if is_bash_plugin:
            # Pour un plugin Bash, passer les paramètres de ligne de commande
            plugin_name = plugin_config.get('plugin_name', os.path.basename(os.path.dirname(plugin_path)))
            intensity = plugin_config.get('intensity', 'light')
            run_cmd = ['bash', plugin_path, plugin_name, intensity]

            log.info(f"Exécution du plugin Bash {plugin_path} avec paramètres: {plugin_name} {intensity}")
        else:
            # Pour un plugin Python, utiliser config.json qui doit déjà être créé par ssh_executor
            config_path = os.path.join(current_dir, 'config.json')

            if not os.path.exists(config_path):
                log.error(f"Le fichier de configuration du plugin n'existe pas: {config_path}")
                sys.exit(1)

            run_cmd = ['python3', plugin_path, '-c', config_path]
            log.info(f"Exécution du plugin Python {plugin_path} avec config: {config_path}")

        # Exécuter la commande avec notre fonction temps réel
        log.info(f"Exécution {'avec' if needs_sudo else 'sans'} privilèges sudo")

        success, stdout_lines, stderr_lines = run_command_realtime(run_cmd, needs_sudo, root_password)

        # Log de fin d'exécution
        if success:
            emit_json_log("success", "Exécution terminée avec succès")
            sys.exit(0)
        else:
            if stderr_lines:
                error_msg = "\n".join(stderr_lines)
            else:
                error_msg = "Erreur inconnue (aucune sortie d'erreur)"

            emit_json_log("error", f"Erreur lors de l'exécution: {error_msg}")
            sys.exit(1)

    except Exception as e:
        if 'log' in locals():
            log.error(f"Erreur inattendue: {e}")
            log.error(traceback.format_exc())
        else:
            emit_json_log("error", f"Erreur inattendue dans ssh_wrapper: {e}")
            emit_json_log("error", traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()