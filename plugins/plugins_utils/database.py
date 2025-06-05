# install/plugins/plugins_utils/database.py
#!/usr/bin/env python3
"""
Module utilitaire pour les interactions de base avec les SGBD MySQL/MariaDB et PostgreSQL.
Utilise les outils clients en ligne de commande (mysql, psql, mysqldump, pg_dump, etc.).
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase

import os
import shlex # Pour échapper les arguments
import tempfile
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class DatabaseCommands(PluginsUtilsBase):
    """
    Classe pour les interactions de base avec MySQL/MariaDB et PostgreSQL via CLI.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    DB_TYPE_MYSQL = "mysql"
    DB_TYPE_POSTGRES = "postgres"
    DB_TYPE_UNKNOWN = "unknown"

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de base de données."""
        super().__init__(logger, target_ip)
        self._check_commands()

    def _check_commands(self):
        """Vérifie si les commandes client DB sont disponibles."""
        cmds = ['mysql', 'psql', 'mysqldump', 'pg_dump', 'createdb', 'dropdb', 'createuser', 'dropuser']
        missing = []
        self._cmd_paths = {}
        for cmd in cmds:
            success, stdout, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if success and stdout.strip():
                 self._cmd_paths[cmd] = stdout.strip()
            else:
                # Ne logguer que si l'outil correspondant est probablement utilisé
                if cmd in ['mysql', 'mysqldump'] or cmd in ['psql', 'pg_dump', 'createdb', 'dropdb', 'createuser', 'dropuser']:
                     missing.append(cmd)

        if missing:
            self.log_warning(f"Commandes client de base de données potentiellement manquantes: {', '.join(missing)}. "
                             f"Installer les paquets clients appropriés (ex: 'mysql-client', 'postgresql-client').")

    def detect_db_type(self, log_levels: Optional[Dict[str, str]] = None) -> str:
        """Tente de détecter le type de SGBD principal installé."""
        if self._cmd_paths.get('mysql'):
            # Vérifier si le service est actif
            try:
                from .services import ServiceCommands
                svc = ServiceCommands(self.logger, self.target_ip)
                # Noms de service courants
                for svc_name in ['mysql', 'mariadb']:
                     if svc.is_active(svc_name):
                          self.log_info(f"SGBD détecté: {svc_name} (actif)")
                          return self.DB_TYPE_MYSQL
            except ImportError:
                 self.log_warning("Impossible de vérifier le statut du service DB (ServiceCommands non trouvé).")
            # Si la commande existe mais service non détecté, supposer MySQL/MariaDB
            self.log_info("Commande 'mysql' trouvée, suppose MySQL/MariaDB.")
            return self.DB_TYPE_MYSQL

        if self._cmd_paths.get('psql'):
            try:
                from .services import ServiceCommands
                svc = ServiceCommands(self.logger, self.target_ip)
                if svc.is_active("postgresql"):
                     self.log_info("SGBD détecté: postgresql (actif)")
                     return self.DB_TYPE_POSTGRES
            except ImportError:
                 self.log_warning("Impossible de vérifier le statut du service DB (ServiceCommands non trouvé).")
            self.log_info("Commande 'psql' trouvée, suppose PostgreSQL.")
            return self.DB_TYPE_POSTGRES

        self.log_warning("Aucun SGBD (MySQL/MariaDB ou PostgreSQL) n'a pu être détecté via les commandes client.")
        return self.DB_TYPE_UNKNOWN

    # --- Helpers pour les commandes ---

    def _build_mysql_args(self, user: Optional[str], password: Optional[str],
                          host: Optional[str], port: Optional[int],
                          db_name: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
        """Construit les arguments et l'environnement pour les commandes mysql/mysqldump."""
        args = []
        env = os.environ.copy() # Hériter de l'environnement actuel
        if user: args.extend(['-u', user])
        # Utiliser MYSQL_PWD est plus sûr que -p<password>
        if password: env['MYSQL_PWD'] = password
        if host and host not in ['localhost', '127.0.0.1']: args.extend(['-h', host]) # -h n'est pas nécessaire pour localhost par défaut
        if port and port != 3306: args.extend(['-P', str(port)])
        if db_name: args.append(db_name) # Le nom de la DB est souvent le dernier argument
        return args, env

    def _build_psql_args(self, user: Optional[str], password: Optional[str],
                         host: Optional[str], port: Optional[int],
                         db_name: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
        """Construit les arguments et l'environnement pour les commandes psql/pg_dump/etc."""
        args = []
        env = os.environ.copy()
        if user: args.extend(['-U', user])
        # Utiliser PGPASSWORD
        if password: env['PGPASSWORD'] = password
        if host: args.extend(['-h', host])
        if port and port != 5432: args.extend(['-p', str(port)])
        if db_name: args.extend(['-d', db_name])
        return args, env

    def _run_mysql_query(self, query: str, db_name: Optional[str] = None,
                         user: Optional[str] = 'root', password: Optional[str] = None,
                         host: Optional[str] = 'localhost', port: Optional[int] = 3306,
                         needs_sudo: bool = False) -> Tuple[bool, str, str]:
        """Exécute une requête SQL unique via mysql -e."""
        if not self._cmd_paths.get('mysql'):
            self.log_error("Commande 'mysql' non trouvée.")
            return False, "", "Commande mysql manquante"

        mysql_args, env = self._build_mysql_args(user, password, host, port, db_name)
        cmd = [self._cmd_paths['mysql']] + mysql_args + ['-e', query]
        # L'exécution de requêtes peut nécessiter sudo si l'authentification socket est utilisée pour root@localhost
        return self.run(cmd, env=env, check=False, needs_sudo=needs_sudo)

    def _run_psql_command(self, command: str, db_name: Optional[str] = 'postgres',
                          user: Optional[str] = 'postgres', password: Optional[str] = None,
                          host: Optional[str] = None, port: Optional[int] = 5432,
                          needs_sudo: bool = False, run_as_postgres: bool = True) -> Tuple[bool, str, str]:
        """Exécute une commande SQL unique via psql -c."""
        if not self._cmd_paths.get('psql'):
            self.log_error("Commande 'psql' non trouvée.")
            return False, "", "Commande psql manquante"

        psql_args, env = self._build_psql_args(user, password, host, port, db_name)
        cmd = [self._cmd_paths['psql']] + psql_args + ['-c', command]

        # Souvent, les commandes psql doivent être exécutées en tant qu'utilisateur postgres
        final_cmd: Union[List[str], str]
        if run_as_postgres and not self._is_root and user == 'postgres':
             # Construire une commande sudo -u postgres ...
             # Échapper la commande pour le shell
             quoted_cmd = " ".join(shlex.quote(c) for c in cmd)
             final_cmd = f"sudo -u postgres -- sh -c {shlex.quote(quoted_cmd)}"
             needs_sudo_flag = False # Le sudo est dans la commande shell
             shell_flag = True
        else:
             # Exécuter normalement (peut nécessiter sudo si l'utilisateur courant n'a pas les droits)
             final_cmd = cmd
             needs_sudo_flag = needs_sudo
             shell_flag = False

        return self.run(final_cmd, env=env, check=False, needs_sudo=needs_sudo_flag, shell=shell_flag)

    # --- Opérations MySQL / MariaDB ---

    def mysql_db_exists(self, db_name: str, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si une base de données MySQL/MariaDB existe."""
        self.log_debug(f"Vérification de l'existence de la DB MySQL: {db_name}")
        # Utiliser INFORMATION_SCHEMA est plus standard que SHOW DATABASES
        query = f"SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = '{db_name}'"
        # Exécuter sans spécifier de DB (-D information_schema est implicite)
        success, stdout, stderr = self._run_mysql_query(query, db_name=None, **kwargs)
        # La requête réussit et retourne au moins une ligne si la DB existe
        exists = success and db_name in stdout
        self.log_debug(f"DB MySQL '{db_name}' existe: {exists}")
        return exists

    def mysql_user_exists(self, username: str, host: str = 'localhost', **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si un utilisateur MySQL/MariaDB existe."""
        self.log_debug(f"Vérification de l'existence de l'utilisateur MySQL: {username}@{host}")
        query = f"SELECT User FROM mysql.user WHERE User = '{username}' AND Host = '{host}'"
        success, stdout, stderr = self._run_mysql_query(query, db_name='mysql', **kwargs)
        exists = success and username in stdout
        self.log_debug(f"Utilisateur MySQL '{username}@{host}' existe: {exists}")
        return exists

    def mysql_create_db(self, db_name: str, charset: str = 'utf8mb4', collate: str = 'utf8mb4_unicode_ci', **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée une base de données MySQL/MariaDB."""
        if self.mysql_db_exists(db_name, **kwargs):
            self.log_warning(f"La base de données MySQL '{db_name}' existe déjà.")
            return True
        self.log_info(f"Création de la base de données MySQL: {db_name} (charset={charset}, collate={collate})")
        query = f"CREATE DATABASE `{db_name}` CHARACTER SET {charset} COLLATE {collate};"
        success, stdout, stderr = self._run_mysql_query(query, **kwargs)
        if success:
            self.log_success(f"Base de données MySQL '{db_name}' créée.")
            return True
        else:
            self.log_error(f"Échec de la création de la DB MySQL '{db_name}'. Stderr: {stderr}")
            return False

    def mysql_drop_db(self, db_name: str, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime une base de données MySQL/MariaDB."""
        if not self.mysql_db_exists(db_name, **kwargs):
            self.log_warning(f"La base de données MySQL '{db_name}' n'existe pas, suppression ignorée.")
            return True
        self.log_warning(f"Suppression de la base de données MySQL: {db_name} - OPÉRATION DESTRUCTIVE !")
        query = f"DROP DATABASE `{db_name}`;"
        success, stdout, stderr = self._run_mysql_query(query, **kwargs)
        if success:
            self.log_success(f"Base de données MySQL '{db_name}' supprimée.")
            return True
        else:
            self.log_error(f"Échec de la suppression de la DB MySQL '{db_name}'. Stderr: {stderr}")
            return False

    def mysql_create_user(self, username: str, password: str, host: str = 'localhost', **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée un utilisateur MySQL/MariaDB."""
        if self.mysql_user_exists(username, host, **kwargs):
            self.log_warning(f"L'utilisateur MySQL '{username}@{host}' existe déjà.")
            # Peut-être mettre à jour le mot de passe ici ? Pour l'instant, on considère comme succès.
            return True
        self.log_info(f"Création de l'utilisateur MySQL: {username}@{host}")
        # Échapper le mot de passe pour la requête SQL ? Non, IDENTIFIED BY le gère.
        query = f"CREATE USER '{username}'@'{host}' IDENTIFIED BY '{password}';"
        success, stdout, stderr = self._run_mysql_query(query, **kwargs)
        if success:
            self.log_success(f"Utilisateur MySQL '{username}@{host}' créé.")
            return True
        else:
            self.log_error(f"Échec de la création de l'utilisateur MySQL '{username}@{host}'. Stderr: {stderr}")
            return False

    def mysql_drop_user(self, username: str, host: str = 'localhost', **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Supprime un utilisateur MySQL/MariaDB."""
        if not self.mysql_user_exists(username, host, **kwargs):
            self.log_warning(f"L'utilisateur MySQL '{username}@{host}' n'existe pas, suppression ignorée.")
            return True
        self.log_info(f"Suppression de l'utilisateur MySQL: {username}@{host}")
        query = f"DROP USER '{username}'@'{host}';"
        success, stdout, stderr = self._run_mysql_query(query, **kwargs)
        if success:
            self.log_success(f"Utilisateur MySQL '{username}@{host}' supprimé.")
            return True
        else:
            self.log_error(f"Échec de la suppression de l'utilisateur MySQL '{username}@{host}'. Stderr: {stderr}")
            return False

    def mysql_grant_privileges(self, db_name: str, username: str, host: str = 'localhost', privileges: str = 'ALL', table: str = '*', **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Accorde des privilèges à un utilisateur sur une base de données/table."""
        target = f"`{db_name}`.{table}" if db_name else '*.*' # *.* pour global
        priv_list = privileges.upper()
        self.log_info(f"Octroi des privilèges '{priv_list}' sur {target} à '{username}@{host}'")
        query_grant = f"GRANT {priv_list} ON {target} TO '{username}'@'{host}';"
        query_flush = "FLUSH PRIVILEGES;"

        success_grant, _, stderr_grant = self._run_mysql_query(query_grant, **kwargs)
        if not success_grant:
            self.log_error(f"Échec de l'octroi des privilèges. Stderr: {stderr_grant}")
            return False

        success_flush, _, stderr_flush = self._run_mysql_query(query_flush, **kwargs)
        if not success_flush:
            self.log_warning(f"Échec de FLUSH PRIVILEGES (peut ne pas être nécessaire). Stderr: {stderr_flush}")
            # Continuer même si flush échoue

        self.log_success(f"Privilèges '{priv_list}' accordés sur {target} à '{username}@{host}'.")
        return True

    def mysql_set_root_password(self, new_password: str, host: str = 'localhost', current_password: Optional[str] = None, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Tente de définir le mot de passe root MySQL/MariaDB."""
        self.log_info(f"Tentative de définition du mot de passe root@'{host}' MySQL/MariaDB.")
        self.log_warning("Cette opération peut varier selon la version de MySQL/MariaDB.")

        # Préparer les arguments de connexion initiaux (avec l'ancien mdp si fourni)
        connect_kwargs = kwargs.copy()
        connect_kwargs['user'] = 'root'
        connect_kwargs['password'] = current_password
        connect_kwargs['host'] = host

        # Essayer la méthode moderne avec ALTER USER
        query = f"ALTER USER 'root'@'{host}' IDENTIFIED BY '{new_password}';"
        self.log_info("Tentative via 'ALTER USER'")
        success, stdout, stderr = self._run_mysql_query(query, **connect_kwargs)

        if success:
            self.log_success(f"Mot de passe root@'{host}' mis à jour avec succès via ALTER USER.")
            # Essayer de vider les privilèges
            self._run_mysql_query("FLUSH PRIVILEGES;", **connect_kwargs)
            return True
        else:
            self.log_warning(f"Échec avec ALTER USER. Stderr: {stderr}")
            # Essayer d'autres méthodes si nécessaire (ex: SET PASSWORD, UPDATE mysql.user - non recommandé)
            # Pour l'instant, on s'arrête là.
            self.log_error("Impossible de définir le mot de passe root via ALTER USER.")
            return False

    def mysql_execute_script(self, script_path: Union[str, Path], db_name: Optional[str] = None, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Exécute un script SQL depuis un fichier."""
        script_p = Path(script_path)
        if not script_p.is_file():
            self.log_error(f"Fichier script SQL introuvable: {script_p}")
            return False

        self.log_info(f"Exécution du script SQL: {script_p} {'dans DB ' + db_name if db_name else ''}")
        if not self._cmd_paths.get('mysql'): return False

        mysql_args, env = self._build_mysql_args(kwargs.get('user','root'), kwargs.get('password'), kwargs.get('host','localhost'), kwargs.get('port'), db_name)
        cmd = [self._cmd_paths['mysql']] + mysql_args

        try:
            with open(script_p, 'r', encoding='utf-8') as f_script:
                # Passer le contenu du script via stdin
                success, stdout, stderr = self.run(cmd, input_data=f_script.read(), env=env, check=False, needs_sudo=kwargs.get('needs_sudo', False))

            if success:
                 self.log_success(f"Script SQL {script_p} exécuté avec succès.")
                 if stdout: self.log_info(f"Sortie mysql (script):\n{stdout}")
                 return True
            else:
                 self.log_error(f"Échec de l'exécution du script SQL {script_p}. Stderr: {stderr}")
                 if stdout: self.log_info(f"Sortie mysql (script, échec):\n{stdout}")
                 return False
        except Exception as e:
             self.log_error(f"Erreur lors de la lecture/exécution du script {script_p}: {e}", exc_info=True)
             return False

    def mysql_dump(self, db_name: str, output_file: Union[str, Path], **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Effectue une sauvegarde d'une base de données MySQL/MariaDB."""
        output_p = Path(output_file)
        self.log_info(f"Sauvegarde de la DB MySQL '{db_name}' vers: {output_p}")
        if not self._cmd_paths.get('mysqldump'):
            self.log_error("Commande 'mysqldump' non trouvée.")
            return False

        # Créer le dossier parent si nécessaire
        try:
            output_p.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log_error(f"Impossible de créer le dossier parent pour {output_p}: {e}")
            return False

        mysql_args, env = self._build_mysql_args(kwargs.get('user','root'), kwargs.get('password'), kwargs.get('host','localhost'), kwargs.get('port'), db_name)
        # Ajouter des options de dump courantes
        cmd = [self._cmd_paths['mysqldump']] + mysql_args + ['--single-transaction', '--quick', '--lock-tables=false']
        # Rediriger la sortie vers le fichier
        cmd_str = " ".join(shlex.quote(c) for c in cmd) + f" > {shlex.quote(str(output_p))}"

        # Exécuter via shell à cause de la redirection
        success, stdout, stderr = self.run(cmd_str, shell=True, env=env, check=False, needs_sudo=kwargs.get('needs_sudo', False))

        if success:
             # Vérifier si le fichier de sortie a été créé et n'est pas vide
             if output_p.exists() and output_p.stat().st_size > 0:
                  self.log_success(f"Sauvegarde MySQL de '{db_name}' terminée: {output_p}")
                  return True
             else:
                  self.log_error(f"La commande mysqldump a réussi mais le fichier de sortie est manquant ou vide: {output_p}")
                  if stderr: self.log_error(f"Stderr: {stderr}") # mysqldump peut écrire des warnings sur stderr
                  return False
        else:
             self.log_error(f"Échec de mysqldump pour '{db_name}'. Stderr: {stderr}")
             # Supprimer le fichier de sortie potentiellement incomplet
             if output_p.exists():
                  try: output_p.unlink()
                  except: pass
             return False

    # --- Opérations PostgreSQL ---

    def psql_db_exists(self, db_name: str, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si une base de données PostgreSQL existe."""
        self.log_debug(f"Vérification de l'existence de la DB PostgreSQL: {db_name}")
        # Utiliser psql pour lister les DB et grep
        # -l: list databases, -q: quiet, -t: tuples only, -A: no align
        # cut -d\| -f 1: prend la première colonne (nom)
        # grep -qw: quiet, word-regexp
        if not self._cmd_paths.get('psql'): return False
        psql_args, env = self._build_psql_args(kwargs.get('user','postgres'), kwargs.get('password'), kwargs.get('host'), kwargs.get('port'), 'template1') # Connect to template1 to list
        cmd = [self._cmd_paths['psql']] + psql_args + ['-lqtA']
        cmd_str = " ".join(shlex.quote(c) for c in cmd) + f" | cut -d\\| -f1 | grep -qw {shlex.quote(db_name)}"

        success, _, _ = self.run(cmd_str, shell=True, env=env, check=False, no_output=True, needs_sudo=kwargs.get('needs_sudo', False), run_as_postgres=kwargs.get('run_as_postgres', True))
        exists = success
        self.log_debug(f"DB PostgreSQL '{db_name}' existe: {exists}")
        return exists

    def psql_user_exists(self, username: str, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Vérifie si un rôle (utilisateur) PostgreSQL existe."""
        self.log_debug(f"Vérification de l'existence de l'utilisateur PostgreSQL: {username}")
        query = f"SELECT 1 FROM pg_roles WHERE rolname='{username}'"
        # -t: tuples only, -A: no align, -c: command
        success, stdout, _ = self._run_psql_command(query, **kwargs)
        # Si succès et stdout contient '1', l'utilisateur existe
        exists = success and stdout.strip() == '1'
        self.log_debug(f"Utilisateur PostgreSQL '{username}' existe: {exists}")
        return exists

    def psql_create_db(self, db_name: str, owner: Optional[str] = None, **kwargs, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """Crée une base de données PostgreSQL."""
        if self.psql_db_exists(db_name, **kwargs):
            self.log_warning(f"La base de données PostgreSQL '{db_name}' existe déjà.")
            return True
        self.log_info(f"Création de la base de données PostgreSQL: {db_name}{' (propriétaire: ' + owner + ')' if owner else ''}")
        # Utiliser la commande createdb est souvent plus simple
        if self._cmd_paths.get('createdb'):
            createdb_args, env = self._build_psql_args(kwargs.get('user','postgres'), kwargs.get('password'), kwargs.get('host'), kwargs.get('port'), None) # Pas de DB pour createdb
            cmd = [self._cmd_paths['createdb']] + createdb_args
            if owner: cmd.extend(['-O', owner])
            cmd.append(db_name)
            final_cmd: Union[List[str], str] = cmd
            needs_sudo_flag = kwargs.get('needs_sudo', False)
            shell_flag = False
            if kwargs.get('run_as_postgres', True) and not self._is_root and kwargs.get('user','postgres') == 'postgres':
                 quoted_cmd = " ".join(shlex.quote(c) for c in cmd)
                 final_cmd = f"sudo -u postgres -- sh -c {shlex.quote(quoted_cmd)}"
                 needs_sudo_flag = False
                 shell_flag = True
            success, stdout, stderr = self.run(final_cmd, env=env, check=False, needs_sudo=needs_sudo_flag, shell=shell_flag)
        else:
            # Fallback avec psql -c
            self.log_warning("Commande 'createdb' non trouvée, tentative via psql -c.")
            query = f"CREATE DATABASE \"{db_name}\"" # Utiliser les guillemets pour les noms
            if owner: query += f" OWNER \"{owner}\""
            query += ";"
            success, stdout, stderr = self._run_psql_command(query, **kwargs)

        if success:
            self.log_success(f"Base de données PostgreSQL '{db_name}' créée.")
            return True
        else:
            self.log_error(f"Échec de la création de la DB PostgreSQL '{db_name}'. Stderr: {stderr}")
            return False

    # ... Implémenter psql_drop_db, psql_create_user, psql_drop_user, psql_grant_privileges,
    #     psql_set_user_password, psql_execute_script, psql_dump de manière similaire,
    #     en utilisant les commandes dropdb, createuser, dropuser, psql -c, psql -f, pg_dump
    #     et en gérant l'exécution en tant qu'utilisateur postgres via sudo -u si nécessaire.
