# install/plugins/plugins_utils/cron.py
#!/usr/bin/env python3
"""
Module utilitaire pour gérer les tâches planifiées (cron).
Permet de lister, ajouter et supprimer des tâches pour les utilisateurs
et dans les répertoires système (/etc/cron.d).
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import tempfile
from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple

class CronCommands(PluginsUtilsBase):
    """
    Classe pour gérer les tâches cron système et utilisateur.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire cron."""
        super().__init__(logger, target_ip)


    def _get_cron_identifier(self, job_line: str, marker: Optional[str]) -> str:
        """Génère un commentaire d'identification pour une tâche cron."""
        if marker:
            return f"# MARKER:{marker}"
        # Utiliser un hash simple de la commande comme identifiant par défaut
        import hashlib
        job_hash = hashlib.md5(job_line.encode()).hexdigest()[:8]
        return f"# ID:{job_hash}"

    # --- Gestion Crontab Utilisateur ---

    def list_user_cron(self, username: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        """
        Liste les tâches cron pour un utilisateur spécifique ou l'utilisateur courant.

        Args:
            username: Nom de l'utilisateur. Si None, utilise l'utilisateur courant.

        Returns:
            Liste des lignes de la crontab, ou None si erreur ou crontab vide.
        """
        user_log = f"pour l'utilisateur '{username}'" if username else "pour l'utilisateur courant"
        self.log_info(f"Listage des tâches cron {user_log}", log_levels=log_levels)
        cmd = ['crontab', '-l']
        needs_sudo = False
        if username:
            # Lister pour un autre utilisateur nécessite souvent root
            cmd.extend(['-u', username])
            # Vérifier si on est root ou si on liste pour soi-même
            try:
                import pwd
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                if not self._is_root and username != current_user:
                    needs_sudo = True
            except Exception:
                 # Si on ne peut pas vérifier, supposer qu'on a besoin de sudo par sécurité
                 if not self._is_root: needs_sudo = True


        # check=False car crontab -l retourne 1 si la crontab est vide
        success, stdout, stderr = self.run(cmd, check=False, no_output=True, needs_sudo=needs_sudo)

        if not success:
            # Gérer le cas "no crontab for user" qui n'est pas une erreur fatale
            if "no crontab for" in stderr.lower():
                self.log_info(f"Aucune crontab trouvée {user_log}.", log_levels=log_levels)
                return [] # Retourner liste vide
            else:
                self.log_error(f"Échec du listage de la crontab {user_log}. Stderr: {stderr}", log_levels=log_levels)
                return None # Erreur réelle

        lines = [line for line in stdout.splitlines() if line.strip() and not line.strip().startswith('#')]
        self.log_info(f"{len(lines)} tâche(s) cron trouvée(s) {user_log}.", log_levels=log_levels)
        self.log_debug(f"Crontab {user_log}:\n{stdout}", log_levels=log_levels)
        return stdout.splitlines() # Retourner toutes les lignes, y compris commentaires

    def add_user_cron_job(self,
                          job_line: str,
                          username: Optional[str] = None,
                          marker: Optional[str] = None,
replace_existing: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute ou remplace une tâche dans la crontab d'un utilisateur.

        Args:
            job_line: La ligne complète de la tâche cron à ajouter (ex: "* * * * * /usr/bin/command").
            username: Utilisateur cible (défaut: utilisateur courant).
            marker: Un marqueur unique pour identifier/remplacer cette tâche (optionnel).
                    Si non fourni, un ID basé sur le hash de la commande sera utilisé.
            replace_existing: Si True (défaut), remplace une tâche existante avec le même marqueur/ID.
                              Si False, ajoute la tâche même si une similaire existe.

        Returns:
            bool: True si l'ajout/remplacement a réussi.
        """
        user_log = f"pour l'utilisateur '{username}'" if username else "pour l'utilisateur courant"
        self.log_info(f"Ajout/Remplacement de la tâche cron {user_log}: {job_line[:50]}...", log_levels=log_levels)

        # 1. Récupérer la crontab actuelle
        current_lines = self.list_user_cron(username)
        if current_lines is None:
            # Erreur lors de la lecture, on ne peut pas continuer
            self.log_error("Impossible de lire la crontab actuelle pour ajouter la tâche.", log_levels=log_levels)
            return False
        # Si list_user_cron retourne [], c'est une crontab vide, c'est ok.

        # 2. Préparer la nouvelle ligne et son identifiant
        job_line = job_line.strip()
        identifier_comment = self._get_cron_identifier(job_line, marker)
        new_crontab_lines = []
        job_added_or_replaced = False

        # 3. Parcourir les lignes existantes
        skip_next = False
        for i, line in enumerate(current_lines):
            if skip_next:
                skip_next = False
                continue

            # Vérifier si la ligne suivante est notre identifiant
            is_identifier_line = line.strip() == identifier_comment
            is_job_line_after_identifier = False
            if is_identifier_line and i + 1 < len(current_lines):
                 is_job_line_after_identifier = current_lines[i+1].strip() == job_line

            if is_identifier_line:
                if replace_existing:
                    # Si on remplace, on ajoute notre nouvelle ligne + identifiant
                    # et on saute l'ancienne ligne de job si elle existe
                    new_crontab_lines.append(identifier_comment)
                    new_crontab_lines.append(job_line)
                    job_added_or_replaced = True
                    self.log_info(f"Tâche existante trouvée ({identifier_comment}), remplacée.", log_levels=log_levels)
                    # Sauter la ligne de job suivante (l'ancienne)
                    if i + 1 < len(current_lines) and not current_lines[i+1].strip().startswith('#'):
                         skip_next = True
                else:
                    # Si on ne remplace pas, on garde l'ancienne + identifiant
                    new_crontab_lines.append(line)
            else:
                 # Garder les autres lignes
                 new_crontab_lines.append(line)

        # 4. Si la tâche n'a pas été ajoutée/remplacée, l'ajouter à la fin
        if not job_added_or_replaced:
            # Ajouter un saut de ligne si la crontab n'est pas vide
            if new_crontab_lines and new_crontab_lines[-1].strip() != "":
                 new_crontab_lines.append("")
            new_crontab_lines.append(identifier_comment)
            new_crontab_lines.append(job_line)
            self.log_info("Nouvelle tâche ajoutée à la fin de la crontab.", log_levels=log_levels)

        # 5. Installer la nouvelle crontab
        new_crontab_content = "\n".join(new_crontab_lines) + "\n" # Assurer une fin de ligne
        self.log_debug(f"Nouveau contenu de la crontab:\n{new_crontab_content}", log_levels=log_levels)

        cmd_install = ['crontab', '-'] # Lire depuis stdin
        needs_sudo = False
        if username:
            cmd_install.extend(['-u', username])
            try:
                import pwd
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                if not self._is_root and username != current_user:
                    needs_sudo = True
            except Exception:
                 if not self._is_root: needs_sudo = True

        success, stdout, stderr = self.run(cmd_install, input_data=new_crontab_content, check=False, needs_sudo=needs_sudo)

        if success:
            self.log_success(f"Crontab {user_log} mise à jour avec succès.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la mise à jour de la crontab {user_log}. Stderr: {stderr}", log_levels=log_levels)
            # stderr peut contenir "installing new crontab" qui n'est pas une erreur
            if "installing new crontab" in stderr:
                 self.log_warning("La sortie stderr mentionne 'installing new crontab', vérifier manuellement.", log_levels=log_levels)
                 # On pourrait considérer cela comme un succès si le code retour est 0 ?
                 # Pour l'instant, on se fie au code retour.
            return False

    def remove_user_cron_job(self, job_pattern: Optional[str] = None, marker: Optional[str] = None, username: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime une ou plusieurs tâches de la crontab d'un utilisateur.

        Args:
            job_pattern: Expression régulière pour identifier les lignes de tâche à supprimer.
                         Si None, utiliser le marqueur.
            marker: Marqueur unique pour identifier la tâche à supprimer (utilisé si job_pattern est None).
            username: Utilisateur cible (défaut: utilisateur courant).

        Returns:
            bool: True si au moins une tâche a été supprimée ou si aucune tâche ne correspondait.
                  False en cas d'erreur de lecture/écriture.
        """
        if not job_pattern and not marker:
            self.log_error("Il faut fournir soit un pattern (job_pattern) soit un marqueur (marker) pour supprimer une tâche.", log_levels=log_levels)
            return False

        user_log = f"pour l'utilisateur '{username}'" if username else "pour l'utilisateur courant"
        target_id = f"marqueur '{marker}'" if marker else f"pattern '{job_pattern}'"
        self.log_info(f"Suppression des tâches cron {user_log} correspondant à {target_id}", log_levels=log_levels)

        # 1. Récupérer la crontab actuelle
        current_lines = self.list_user_cron(username)
        if current_lines is None:
            self.log_error("Impossible de lire la crontab actuelle pour supprimer la tâche.", log_levels=log_levels)
            return False
        if not current_lines:
             self.log_info("La crontab est vide, aucune tâche à supprimer.", log_levels=log_levels)
             return True

        # 2. Filtrer les lignes à garder
        new_crontab_lines = []
        removed_count = 0
        identifier_to_remove = f"# MARKER:{marker}" if marker else None
        skip_next = False # Pour sauter la ligne de commentaire associée

        for i, line in enumerate(current_lines):
            line_strip = line.strip()

            if skip_next:
                skip_next = False
                continue

            remove_this = False
            # Vérifier par marqueur
            if identifier_to_remove and i > 0 and current_lines[i-1].strip() == identifier_to_remove:
                 # La ligne précédente était le marqueur, supprimer cette ligne (la tâche)
                 remove_this = True
                 skip_next = True # Sauter aussi la ligne de commentaire (précédente)
                 # Pour sauter la ligne de commentaire, il faut la retirer de new_crontab_lines
                 if new_crontab_lines: new_crontab_lines.pop()
            # Vérifier par pattern (si pas déjà supprimée par marqueur)
            elif job_pattern and not line_strip.startswith('#') and re.search(job_pattern, line_strip):
                 remove_this = True
                 # Vérifier si la ligne précédente est un commentaire ID ou MARKER et le supprimer aussi
                 if i > 0 and current_lines[i-1].strip().startswith(("# MARKER:", "# ID:")):
                      if new_crontab_lines: new_crontab_lines.pop()

            if remove_this:
                removed_count += 1
                self.log_info(f"  - Ligne supprimée: {line_strip}", log_levels=log_levels)
            else:
                new_crontab_lines.append(line)

        # 3. Vérifier si des modifications ont été faites
        if removed_count == 0:
            self.log_info(f"Aucune tâche correspondant à {target_id} trouvée {user_log}.", log_levels=log_levels)
            return True

        # 4. Installer la nouvelle crontab
        new_crontab_content = "\n".join(new_crontab_lines) + "\n"
        self.log_debug(f"Nouveau contenu de la crontab après suppression:\n{new_crontab_content}", log_levels=log_levels)

        cmd_install = ['crontab', '-']
        needs_sudo = False
        if username:
            cmd_install.extend(['-u', username])
            try:
                import pwd
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                if not self._is_root and username != current_user:
                    needs_sudo = True
            except Exception:
                 if not self._is_root: needs_sudo = True

        success, stdout, stderr = self.run(cmd_install, input_data=new_crontab_content, check=False, needs_sudo=needs_sudo)

        if success:
            self.log_success(f"{removed_count} tâche(s) cron supprimée(s) avec succès {user_log}.", log_levels=log_levels)
            return True
        else:
            self.log_error(f"Échec de la mise à jour de la crontab après suppression {user_log}. Stderr: {stderr}", log_levels=log_levels)
            return False

    # --- Gestion /etc/cron.d ---

    def list_system_cron_d_files(self, log_levels: Optional[Dict[str, str]] = None) -> List[str]:
        """Liste les fichiers dans /etc/cron.d."""
        cron_d_path = "/etc/cron.d"
        self.log_info(f"Listage des fichiers dans {cron_d_path}", log_levels=log_levels)
        if not os.path.isdir(cron_d_path):
            self.log_warning(f"Le répertoire {cron_d_path} n'existe pas.", log_levels=log_levels)
            return []
        try:
            files = [f for f in os.listdir(cron_d_path) if os.path.isfile(os.path.join(cron_d_path, f)) and not f.startswith('.')]
            self.log_info(f"{len(files)} fichiers trouvés dans {cron_d_path}.", log_levels=log_levels)
            return files
        except Exception as e:
            self.log_error(f"Erreur lors du listage de {cron_d_path}: {e}", log_levels=log_levels)
            return []

    def read_cron_d_file(self, filename: str, log_levels: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        """Lit le contenu d'un fichier dans /etc/cron.d."""
        filepath = Path("/etc/cron.d") / filename
        self.log_info(f"Lecture du fichier cron.d: {filepath}", log_levels=log_levels)
        if not filepath.is_file():
            self.log_error(f"Le fichier {filepath} n'existe pas ou n'est pas un fichier.", log_levels=log_levels)
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return lines
        except Exception as e:
            self.log_error(f"Erreur lors de la lecture de {filepath}: {e}", log_levels=log_levels)
            return None

    def add_system_cron_d_job(self, job_line: str, filename: str, user: str = 'root', marker: Optional[str] = None, replace_existing: bool = True, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Ajoute ou remplace une tâche dans un fichier /etc/cron.d/. Nécessite root.

        Args:
            job_line: Ligne de tâche SANS l'utilisateur (ex: "* * * * * /path/to/script").
            filename: Nom du fichier dans /etc/cron.d (ex: "my-task").
            user: Utilisateur qui exécutera la tâche (défaut: root).
            marker: Marqueur unique pour identifier/remplacer.
            replace_existing: Remplacer si marqueur existant.

        Returns:
            bool: True si succès.
        """
        filepath = Path("/etc/cron.d") / filename
        self.log_info(f"Ajout/Remplacement tâche dans {filepath} (utilisateur: {user})", log_levels=log_levels)

        # Valider le nom de fichier (alphanumérique, tirets, underscores)
        if not re.match(r'^[a-zA-Z0-9_-]+$', filename):
            self.log_error(f"Nom de fichier invalide pour /etc/cron.d: {filename}. "
                           "Utiliser uniquement lettres, chiffres, tirets, underscores.", log_levels=log_levels)
            return False

        # Construire la ligne complète avec l'utilisateur
        full_job_line = f"{job_line.strip()} {user}"
        identifier_comment = self._get_cron_identifier(full_job_line, marker) # Utiliser la ligne complète pour l'ID

        # Lire le contenu existant ou initialiser
        current_lines: List[str] = []
        if filepath.exists():
            read_lines = self.read_cron_d_file(filename)
            if read_lines is None:
                self.log_error(f"Impossible de lire le fichier existant {filepath}.", log_levels=log_levels)
                return False
            current_lines = read_lines
        else:
            self.log_info(f"Le fichier {filepath} n'existe pas, il sera créé.", log_levels=log_levels)

        # Préparer les nouvelles lignes
        new_lines = []
        job_added_or_replaced = False
        skip_next = False

        for i, line in enumerate(current_lines):
            line_content = line.strip() # Garder le contenu original avec fin de ligne potentielle
            line_strip = line_content.strip() # Pour les comparaisons

            if skip_next:
                skip_next = False
                continue

            is_identifier_line = line_strip == identifier_comment
            is_job_line_after_identifier = False
            if is_identifier_line and i + 1 < len(current_lines):
                 is_job_line_after_identifier = current_lines[i+1].strip() == full_job_line

            if is_identifier_line:
                if replace_existing:
                    new_lines.append(identifier_comment + "\n")
                    new_lines.append(full_job_line + "\n")
                    job_added_or_replaced = True
                    self.log_info(f"Tâche existante trouvée ({identifier_comment}), remplacée dans {filename}.", log_levels=log_levels)
                    # Sauter l'ancienne ligne de job si elle existe et n'est pas un commentaire
                    if i + 1 < len(current_lines) and not current_lines[i+1].strip().startswith('#'):
                         skip_next = True
                else:
                    new_lines.append(line) # Garder l'ancien commentaire
            else:
                 # Garder les autres lignes
                 new_lines.append(line)

        # Ajouter si non remplacé
        if not job_added_or_replaced:
            if new_lines and new_lines[-1].strip() != "":
                 new_lines.append("\n") # Séparateur
            new_lines.append(identifier_comment + "\n")
            new_lines.append(full_job_line + "\n")
            self.log_info(f"Nouvelle tâche ajoutée à {filename}.", log_levels=log_levels)

        # Écrire le nouveau contenu dans un fichier temporaire
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=f".{filename}.tmp") as tf:
                tf.writelines(new_lines)
                tmp_file = tf.name
            self.log_debug(f"Fichier temporaire créé: {tmp_file}", log_levels=log_levels)

            # Déplacer le fichier temporaire avec les droits root
            # Utiliser `mv` est plus sûr que d'écrire directement avec tee pour les permissions
            cmd_mv = ['mv', tmp_file, str(filepath)]
            success, stdout, stderr = self.run(cmd_mv, check=False, needs_sudo=True)

            if success:
                # Assurer les bonnes permissions (typiquement 644 pour cron.d)
                cmd_chmod = ['chmod', '644', str(filepath)]
                self.run(cmd_chmod, check=False, needs_sudo=True)
                self.log_success(f"Fichier {filepath} mis à jour avec succès.", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Échec du déplacement du fichier temporaire vers {filepath}. Stderr: {stderr}", log_levels=log_levels)
                # Nettoyer le fichier temporaire si mv a échoué
                if tmp_file and os.path.exists(tmp_file): os.unlink(tmp_file)
                return False

        except Exception as e:
            self.log_error(f"Erreur lors de l'écriture dans {filepath}: {e}", exc_info=True, log_levels=log_levels)
            # Nettoyer le fichier temporaire en cas d'erreur
            if tmp_file and os.path.exists(tmp_file):
                 try: os.unlink(tmp_file)
                 except: pass
            return False

    def remove_system_cron_d_job(self, filename: str, job_pattern: Optional[str] = None, marker: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Supprime une ou plusieurs tâches d'un fichier /etc/cron.d/. Nécessite root.

        Args:
            filename: Nom du fichier dans /etc/cron.d.
            job_pattern: Expression régulière pour identifier les lignes de tâche à supprimer.
            marker: Marqueur unique pour identifier la tâche à supprimer (utilisé si job_pattern est None).

        Returns:
            bool: True si succès ou si tâche non trouvée. False si erreur.
        """
        if not job_pattern and not marker:
            self.log_error("Il faut fournir soit job_pattern soit marker.", log_levels=log_levels)
            return False

        filepath = Path("/etc/cron.d") / filename
        target_id = f"marqueur '{marker}'" if marker else f"pattern '{job_pattern}'"
        self.log_info(f"Suppression des tâches dans {filepath} correspondant à {target_id}", log_levels=log_levels)

        if not filepath.is_file():
            self.log_warning(f"Le fichier {filepath} n'existe pas, aucune suppression nécessaire.", log_levels=log_levels)
            return True

        # Lire le contenu
        current_lines = self.read_cron_d_file(filename)
        if current_lines is None:
            return False # Erreur déjà logguée

        # Filtrer
        new_lines = []
        removed_count = 0
        identifier_to_remove = f"# MARKER:{marker}" if marker else None
        skip_next = False

        for i, line in enumerate(current_lines):
            line_content = line # Garder la fin de ligne originale
            line_strip = line.strip()

            if skip_next:
                skip_next = False
                continue

            remove_this = False
            # Vérifier par marqueur (supprime commentaire + ligne suivante)
            if identifier_to_remove and i > 0 and current_lines[i-1].strip() == identifier_to_remove:
                 remove_this = True
                 skip_next = True # Sauter le commentaire précédent
                 if new_lines: new_lines.pop()
            # Vérifier par pattern (si pas déjà supprimée par marqueur)
            elif job_pattern and not line_strip.startswith('#') and re.search(job_pattern, line_strip):
                 remove_this = True
                 # Supprimer le commentaire associé si présent
                 if i > 0 and current_lines[i-1].strip().startswith(("# MARKER:", "# ID:")):
                      if new_lines: new_lines.pop()

            if remove_this:
                removed_count += 1
                self.log_info(f"  - Ligne supprimée de {filename}: {line_strip}", log_levels=log_levels)
            else:
                new_lines.append(line_content)

        # Vérifier si des modifications ont été faites
        if removed_count == 0:
            self.log_info(f"Aucune tâche correspondant à {target_id} trouvée dans {filename}.", log_levels=log_levels)
            return True

        # Écrire le nouveau contenu
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=f".{filename}.tmp") as tf:
                tf.writelines(new_lines)
                tmp_file = tf.name

            cmd_mv = ['mv', tmp_file, str(filepath)]
            success, stdout, stderr = self.run(cmd_mv, check=False, needs_sudo=True)

            if success:
                cmd_chmod = ['chmod', '644', str(filepath)] # Restaurer permissions
                self.run(cmd_chmod, check=False, needs_sudo=True)
                self.log_success(f"{removed_count} tâche(s) supprimée(s) de {filepath}.", log_levels=log_levels)
                return True
            else:
                self.log_error(f"Échec de la mise à jour de {filepath} après suppression. Stderr: {stderr}", log_levels=log_levels)
                if tmp_file and os.path.exists(tmp_file): os.unlink(tmp_file)
                return False
        except Exception as e:
            self.log_error(f"Erreur lors de la mise à jour de {filepath}: {e}", exc_info=True, log_levels=log_levels)
            if tmp_file and os.path.exists(tmp_file):
                 try: os.unlink(tmp_file)
                 except: pass
            return False