# install/plugins/plugins_utils/files.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module utilitaire pour la gestion des fichiers et répertoires.
Fournit des opérations de copie et de déplacement avec suivi de progression.
"""

import os # Ajout de l'import os
import shutil
import time
import fnmatch # Pour les motifs d'exclusion
from pathlib import Path
from typing import Union, Optional, List, Tuple, Dict, Any, Generator
import traceback # Pour le log d'erreurs détaillées

# Import de la classe de base
from plugins_utils.plugins_utils_base import PluginsUtilsBase

class FilesCommands(PluginsUtilsBase):
    """
    Classe utilitaire pour la gestion des fichiers et répertoires.
    Hérite de PluginUtilsBase pour l'exécution de commandes (si nécessaire) et la progression.
    Utilise principalement les modules standard 'os', 'shutil', 'pathlib'.
    """

    DEFAULT_CHUNK_SIZE = 1024 * 1024 # 1 Mo pour la copie de fichiers

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de fichiers."""
        super().__init__(logger, target_ip)

    def replace_in_file(self, chemin_fichier: Union[str, Path],
                        ancienne_chaine: str,
                        nouvelle_chaine: str,
encodage: str = "utf-8", log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Remplace toutes les occurrences d'une chaîne de caractères dans un fichier texte.

        :param chemin_fichier: Chemin du fichier à traiter.
        :param ancienne_chaine: Chaîne à rechercher/remplacer.
        :param nouvelle_chaine: Chaîne de remplacement.
        :param encodage: Encodage utilisé pour lire/écrire le fichier (par défaut 'utf-8').
        :return: True si l'opération a réussi, False sinon.
        """
        fichier_path = Path(chemin_fichier)
        self.log_debug(f"Remplacement de texte dans le fichier : {fichier_path}", log_levels=log_levels)

        if not fichier_path.is_file():
            self.log_error(f"Le fichier spécifié n'existe pas ou n'est pas un fichier: {fichier_path}", log_levels=log_levels)
            return False

        try:
            # Lire tout le contenu du fichier
            with fichier_path.open('r', encoding=encodage) as f:
                contenu_original = f.read()

            # Vérifier si un remplacement est nécessaire
            if ancienne_chaine not in contenu_original:
                self.log_info(f"Aucune occurrence de la chaîne '{ancienne_chaine}' trouvée dans {fichier_path}", log_levels=log_levels)
                return True

            # Remplacer les occurrences
            contenu_modifie = contenu_original.replace(ancienne_chaine, nouvelle_chaine)

            # Sauvegarde du fichier d'origine
            sauvegarde_path = fichier_path.with_suffix(fichier_path.suffix + ".bak")
            shutil.copy2(fichier_path, sauvegarde_path)
            self.log_debug(f"Fichier original sauvegardé sous: {sauvegarde_path}", log_levels=log_levels)

            # Écriture du fichier modifié
            with fichier_path.open('w', encoding=encodage) as f:
                f.write(contenu_modifie)

            self.log_success(f"Remplacement effectué avec succès dans {fichier_path}", log_levels=log_levels)
            return True

        except Exception as e:
            self.log_error(f"Erreur lors du remplacement de texte dans le fichier {fichier_path}: {e}", exc_info=True, log_levels=log_levels)
            return False


    def get_file_size(self, path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> int:
        """Retourne la taille d'un fichier en octets."""
        file_path = Path(path)
        self.log_debug(f"Récupération de la taille du fichier: {file_path}", log_levels=log_levels)
        try:
            if not file_path.is_file():
                 self.log_error(f"Le chemin n'est pas un fichier valide ou n'existe pas: {file_path}", log_levels=log_levels)
                 return -1
            size = os.path.getsize(file_path)
            self.log_debug(f"Taille du fichier {file_path}: {size} octets", log_levels=log_levels)
            return size
        except FileNotFoundError:
            self.log_error(f"Fichier non trouvé: {file_path}", log_levels=log_levels)
            return -1
        except OSError as e:
             self.log_error(f"Erreur d'accès au fichier {file_path} pour getsize: {e}", log_levels=log_levels)
             return -1
        except Exception as e:
            self.log_error(f"Erreur inattendue lors de la lecture de la taille du fichier {file_path}: {e}", exc_info=True, log_levels=log_levels)
            return -1

    def get_dir_size(self, path: Union[str, Path], follow_symlinks: bool = False, log_levels: Optional[Dict[str, str]] = None) -> int:
        """Calcule la taille totale d'un dossier en octets (récursivement)."""
        dir_path = Path(path)
        self.log_info(f"Calcul de la taille du dossier: {dir_path} (follow_symlinks={follow_symlinks})", log_levels=log_levels)
        if not dir_path.is_dir():
             self.log_error(f"Le chemin n'est pas un dossier valide: {dir_path}", log_levels=log_levels)
             return -1

        total_size = 0
        items_processed = 0
        errors_encountered = 0
        log_interval = 1000

        try:
            for dirpath, dirnames, filenames in os.walk(str(dir_path), topdown=True, followlinks=follow_symlinks, onerror=self.log_warning):
                # Traiter les fichiers
                for f in filenames:
                    items_processed += 1
                    fp = os.path.join(dirpath, f)
                    # Ne pas suivre les liens si follow_symlinks est False et fp est un lien
                    if not follow_symlinks and os.path.islink(fp):
                        continue
                    try:
                        # Utiliser lstat pour ne pas suivre les liens même si follow_symlinks=True pour getsize
                        # Mais getsize n'existe pas sur lstat. On utilise getsize classique.
                        # Le filtrage os.islink ci-dessus gère le cas follow_symlinks=False
                        total_size += os.path.getsize(fp)
                    except OSError as e:
                         if e.errno != 2: # Ignorer FileNotFoundError (peut arriver si fichier supprimé pendant scan)
                              self.log_warning(f"Erreur d'accès au fichier {fp} pendant calcul taille: {e}", log_levels=log_levels)
                              errors_encountered += 1
                         continue # Ignorer les fichiers inaccessibles/disparus

                    if items_processed % log_interval == 0:
                         self.log_debug(f"  ... {items_processed} éléments scannés, taille actuelle: {total_size / (1024*1024):.2f} Mo", log_levels=log_levels)

                # Si on ne suit pas les liens, exclure les répertoires qui sont des liens
                if not follow_symlinks:
                    original_dirs = list(dirnames) # Copier avant modification
                    # Modifier dirnames in-place pour que os.walk ne les parcoure pas
                    dirnames[:] = [d for d in original_dirs if not os.path.islink(os.path.join(dirpath, d))]
                    # Compter les liens de répertoire exclus comme traités
                    items_processed += (len(original_dirs) - len(dirnames))

            self.log_info(f"Taille totale calculée pour {dir_path}: {total_size / (1024*1024):.2f} Mo ({total_size} octets)", log_levels=log_levels)
            if errors_encountered > 0:
                 self.log_warning(f"{errors_encountered} erreur(s) d'accès rencontrée(s) pendant le calcul.", log_levels=log_levels)
            return total_size
        except Exception as e:
            self.log_error(f"Erreur majeure lors du calcul de la taille du dossier {dir_path}: {e}", exc_info=True, log_levels=log_levels)
            return -1

    def _copy_file_with_progress(self, src: Path, dst: Path, total_size: int, task_id: str, chunk_size: int = DEFAULT_CHUNK_SIZE):
        """Copie un seul fichier avec mise à jour de la progression (interne)."""
        copied_bytes = 0
        src_filename = src.name
        last_update_time = time.monotonic()
        update_interval = 0.1 # Réduit pour plus de réactivité

        # S'assurer que le logger est disponible
        if not hasattr(self, 'logger') or not self.logger:
            internal_logger = logging.getLogger(__name__) # Logger de fallback
            internal_logger.warning("Logger non disponible dans _copy_file_with_progress")
            use_logger = False
        else:
            use_logger = True

        try:
            with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:
                while True:
                    chunk = fsrc.read(chunk_size)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copied_bytes += len(chunk)
                    current_time = time.monotonic()

                    if use_logger and (current_time - last_update_time >= update_interval or copied_bytes == total_size):
                        progress_percent = (copied_bytes / total_size) * 100 if total_size > 0 else 100
                        current_step = int(progress_percent)
                        copied_mb = copied_bytes / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)

                        # Utiliser update_bar directement avec le task_id fourni
                        if self.logger.use_visual_bars:
                             self.logger.update_bar(task_id, current_step, 100,
                                                    pre_text=f"Copie {src_filename}",
                                                    post_text=f"{copied_mb:.1f}/{total_mb:.1f} Mo")
                        last_update_time = current_time

        except Exception as e:
             self.log_error(f"Erreur pendant la copie de {src} vers {dst}: {e}", log_levels=log_levels)
             raise

    def copy_file(self, src: Union[str, Path], dst: Union[str, Path],
chunk_size: int = DEFAULT_CHUNK_SIZE, task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Copie un fichier avec une barre de progression basée sur la taille.
        Préserve les métadonnées. Utilise une barre de progression spécifique.
        """
        src_path = Path(src)
        dst_path = Path(dst)
        current_task_id = task_id or f"copy_file_{src_path.name}_{int(time.time())}"
        bar_created = False

        if not src_path.is_file():
            self.log_error(f"Source n'est pas un fichier valide: {src}", log_levels=log_levels)
            return False

        if dst_path.is_dir():
            final_dst = dst_path / src_path.name
        else:
            final_dst = dst_path
            self.log_debug(f"Vérification/Création du dossier parent: {final_dst.parent}", log_levels=log_levels)
            try:
                success_mkdir, _, err_mkdir = self.run(['mkdir', '-p', str(final_dst.parent)], check=False, needs_sudo=True)
                if not success_mkdir:
                     self.log_error(f"Impossible de créer le dossier parent {final_dst.parent}. Stderr: {err_mkdir}", log_levels=log_levels)
                     return False
            except Exception as e:
                self.log_error(f"Erreur lors de la création de {final_dst.parent}: {e}", exc_info=True, log_levels=log_levels)
                return False

        total_size = self.get_file_size(src_path)
        if total_size < 0: return False

        total_mb = total_size / (1024 * 1024)
        self.log_info(f"Copie de {src_path} vers {final_dst} ({total_mb:.2f} Mo)", log_levels=log_levels)

        try:
            # Créer la barre spécifique à cette copie (progression 0-100)
            self.logger.create_bar(current_task_id, 100, description=f"Copie {src_path.name}")
            bar_created = True

            # Copier le fichier avec progression
            self._copy_file_with_progress(src_path, final_dst, total_size, current_task_id, chunk_size)

            # Copier les métadonnées
            try: shutil.copystat(str(src_path), str(final_dst))
            except OSError as e_stat: self.log_warning(f"Impossible de copier les métadonnées: {e_stat}", log_levels=log_levels)

            self.log_success(f"Fichier copié avec succès: {final_dst}", log_levels=log_levels)
            # Mettre à jour la barre à 100% avant suppression
            self.logger.update_bar(current_task_id, 100, post_text="Terminé")
            return True

        except Exception as e:
            self.log_error(f"Erreur lors de la copie de {src_path} vers {final_dst}: {e}", exc_info=True, log_levels=log_levels)
            if final_dst.exists():
                try: final_dst.unlink()
                except: pass
            return False
        finally:
            # Toujours supprimer la barre
            if bar_created:
                self.logger.delete_bar(current_task_id)

    def _is_excluded(self, relative_path: str, exclude_set: set) -> bool:
        """Vérifie si un chemin relatif correspond aux motifs d'exclusion."""
        if not exclude_set: return False
        is_excluded = relative_path in exclude_set or \
                      any(fnmatch.fnmatch(relative_path, pat) for pat in exclude_set)
        if not is_excluded:
             parts = Path(relative_path).parts
             current_parent = ""
             for i in range(len(parts) - 1): # Itérer sur les dossiers parents
                  current_parent = os.path.join(current_parent, parts[i]) if current_parent else parts[i]
                  # Vérifier si le parent exact est exclu ou correspond à un pattern type "dir/*"
                  if current_parent in exclude_set or \
                     any(fnmatch.fnmatch(current_parent, pat.replace('/*', '')) for pat in exclude_set if pat.endswith('/*')) or \
                     any(fnmatch.fnmatch(current_parent, pat) for pat in exclude_set if not pat.endswith('/*')):
                      is_excluded = True
                      break
        return is_excluded

    def copy_dir(self, src: Union[str, Path], dst: Union[str, Path],
                 exclude_patterns: Optional[List[str]] = None,
                 task_id: Optional[str] = None,
                 copy_symlinks: bool = True,
                 ignore_dangling_symlinks: bool = False
, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Copie un répertoire récursivement avec progression basée sur le nombre d'éléments.
        Utilise une barre de progression spécifique avec l'ID fourni.
        """
        src_path = Path(src)
        dst_path = Path(dst)
        current_task_id = task_id or f"copy_dir_{src_path.name}_{int(time.time())}"
        bar_created = False # Indicateur pour savoir si on doit supprimer la barre

        if not src_path.is_dir():
            self.log_error(f"Source n'est pas un dossier valide: {src}", log_levels=log_levels)
            return False

        self.log_debug(f"Copie du dossier {src_path} vers {dst_path}", log_levels=log_levels)
        if exclude_patterns: self.log_debug(f"  Exclusions: {exclude_patterns}", log_levels=log_levels)
        self.log_debug(f"  Gestion liens: copy={copy_symlinks}, ignore_dangling={ignore_dangling_symlinks}", log_levels=log_levels)

        # 1. Lister et compter les éléments
        items_to_process = []
        exclude_set = set(exclude_patterns or [])
        try:
            for root, dirs, files in os.walk(str(src_path), topdown=True, followlinks=False):
                 root_path = Path(root)
                 rel_root = root_path.relative_to(src_path)
                 # Appliquer l'exclusion aux répertoires pour éviter de les parcourir
                 original_dirs = list(dirs)
                 dirs[:] = [d for d in original_dirs if not self._is_excluded((rel_root / d).as_posix(), exclude_set)]
                 # Ajouter les dossiers (non exclus) à traiter
                 for d in dirs: items_to_process.append({'type': 'dir', 'rel_path': rel_root / d})
                 # Ajouter les fichiers (non exclus) à traiter
                 for f in files:
                      rel_path = rel_root / f
                      if not self._is_excluded(rel_path.as_posix(), exclude_set):
                           items_to_process.append({'type': 'file', 'rel_path': rel_path, 'abs_src': root_path / f})

            total_items = len(items_to_process)
            if total_items == 0:
                 self.log_info("Aucun fichier ou dossier à copier (ou tout est exclu).", log_levels=log_levels)
                 self.run(['mkdir', '-p', str(dst_path)], check=False, needs_sudo=True)
                 return True
        except Exception as e:
             self.log_error(f"Erreur lors du listage de {src_path}: {e}", exc_info=True, log_levels=log_levels)
             return False

        self.log_debug(f"{total_items} élément(s) à traiter.", log_levels=log_levels)
        self.logger.create_bar(current_task_id, total_items, description=f"Copie {src_path.name}")
        bar_created = True

        # 2. Copier/Créer les éléments
        processed_count = 0
        all_success = True
        try:
            self.run(['mkdir', '-p', str(dst_path)], check=False, needs_sudo=True)

            for item in items_to_process:
                rel_path = item['rel_path']
                abs_dst_path = dst_path / rel_path
                item_type = item['type']
                item_processed_flag = False # Indique si cet item a été traité (même si erreur)

                try:
                    if item_type == 'dir':
                        # Utiliser la méthode run pour créer, gère sudo
                        success_mkdir, _, err_mkdir = self.run(['mkdir', '-p', str(abs_dst_path)], check=False, needs_sudo=True)
                        if not success_mkdir:
                             self.log_error(f"Impossible de créer dossier {abs_dst_path}. Stderr: {err_mkdir}", log_levels=log_levels)
                             all_success = False
                        item_processed_flag = True # Marquer comme traité même si erreur
                    elif item_type == 'file':
                        abs_src_path = item['abs_src']
                        # Créer dossier parent si besoin (normalement déjà fait)
                        if not abs_dst_path.parent.exists():
                             self.run(['mkdir', '-p', str(abs_dst_path.parent)], check=False, needs_sudo=True)

                        # Gestion des liens symboliques
                        if abs_src_path.is_symlink():
                            if copy_symlinks:
                                linkto = os.readlink(str(abs_src_path))
                                # --- Correction: Utiliser os.path.lexists ---
                                if os.path.lexists(str(abs_dst_path)):
                                    os.remove(str(abs_dst_path))
                                os.symlink(linkto, str(abs_dst_path))
                                self.log_debug(f"  Lien symbolique copié: {rel_path}", log_levels=log_levels)
                            else: # Copier le contenu
                                shutil.copy2(str(abs_src_path), str(abs_dst_path), follow_symlinks=True)
                                self.log_debug(f"  Contenu du lien copié: {rel_path}", log_levels=log_levels)
                        else: # Copier fichier normal
                            shutil.copy2(str(abs_src_path), str(abs_dst_path))
                        item_processed_flag = True # Marquer comme traité

                except FileNotFoundError as e_fnf:
                    # Gérer spécifiquement les liens cassés si demandé
                    is_link = item_type == 'file' and item['abs_src'].is_symlink()
                    if is_link and ignore_dangling_symlinks:
                        try: link_target = os.readlink(str(item['abs_src']))
                        except Exception: link_target = "?"
                        self.log_warning(f"Lien symbolique cassé ignoré ({e_fnf}): {rel_path} -> {link_target}", log_levels=log_levels)
                        item_processed_flag = True # Marquer comme traité (ignoré)
                    else:
                         self.log_error(f"Erreur Fichier Non Trouvé lors du traitement de {rel_path}: {e_fnf}", log_levels=log_levels)
                         all_success = False
                         item_processed_flag = True # Marquer comme traité (erreur)
                except OSError as e_os:
                    self.log_error(f"Erreur OS lors du traitement de {rel_path}: {e_os}", log_levels=log_levels)
                    all_success = False
                    item_processed_flag = True
                except Exception as e_gen:
                    self.log_error(f"Erreur inattendue lors du traitement de {rel_path}: {e_gen}", exc_info=True, log_levels=log_levels)
                    all_success = False
                    item_processed_flag = True

                # Mettre à jour la progression seulement si l'item a été traité (avec ou sans succès)
                if item_processed_flag:
                    processed_count += 1
                    # Mettre à jour la barre spécifique (avec throttling intégré dans next_bar)
                    self.logger.next_bar(current_task_id, current_step=processed_count, post_text=f"{processed_count}/{total_items}")

            # Assurer que la barre atteint 100% à la fin (après la boucle)
            self.logger.update_bar(current_task_id, total_items, post_text=f"Terminé {processed_count}/{total_items}")

            if all_success:
                self.log_success(f"Dossier {src_path} copié avec succès vers {dst_path} ({processed_count} éléments traités).", log_levels=log_levels)
            else:
                 self.log_warning(f"Copie du dossier {src_path} terminée avec des erreurs.", log_levels=log_levels)

        except Exception as e:
            self.log_error(f"Erreur majeure lors de la copie du dossier {src_path}: {e}", exc_info=True, log_levels=log_levels)
            all_success = False
        finally:
            if bar_created:
                self.logger.delete_bar(current_task_id)
                self.logger.flush()

        return all_success

    def move_file(self, src: Union[str, Path], dst: Union[str, Path], task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Déplace un fichier. Tente `mv`, sinon copie+supprime.
        Utilise une barre spécifique si la copie est nécessaire.
        """
        src_path = Path(src)
        dst_path = Path(dst)
        current_task_id = task_id or f"move_file_{src_path.name}_{int(time.time())}"

        if not src_path.is_file():
            self.log_error(f"Source n'est pas un fichier valide: {src}", log_levels=log_levels)
            return False

        if dst_path.is_dir(): final_dst = dst_path / src_path.name
        else: final_dst = dst_path

        self.log_info(f"Déplacement de {src_path} vers {final_dst}", log_levels=log_levels)

        try:
            if not final_dst.parent.exists():
                 self.run(['mkdir', '-p', str(final_dst.parent)], check=False, needs_sudo=True)

            # Essayer mv d'abord
            cmd_mv = ['mv', str(src_path), str(final_dst)]
            success_mv, _, stderr_mv = self.run(cmd_mv, check=False, needs_sudo=True)
            if success_mv:
                self.log_success(f"Fichier déplacé avec succès (via mv): {final_dst}", log_levels=log_levels)
                return True
            else:
                self.log_info(f"mv impossible (ex: cross-device, {stderr_mv}), tentative copie+suppression...", log_levels=log_levels)
                # copy_file gère sa propre barre avec current_task_id
                copy_success = self.copy_file(src_path, final_dst, task_id=current_task_id)
                if copy_success:
                    rm_success, _, rm_stderr = self.run(['rm', '-f', str(src_path)], check=False, needs_sudo=True)
                    if rm_success:
                        self.log_success(f"Fichier déplacé avec succès (copie+suppression): {final_dst}", log_levels=log_levels)
                        return True
                    else:
                        self.log_error(f"Copie réussie mais échec suppression source {src_path}: {rm_stderr}", log_levels=log_levels)
                        return False
                else:
                    self.log_error(f"Échec de la copie lors du déplacement de {src_path}", log_levels=log_levels)
                    return False
        except Exception as e:
            self.log_error(f"Erreur lors du déplacement de {src_path}: {e}", exc_info=True, log_levels=log_levels)
            return False

    def move_dir(self, src: Union[str, Path], dst: Union[str, Path],
exclude_patterns: Optional[List[str]] = None, task_id: Optional[str] = None, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Déplace un dossier. Tente `mv`, sinon copie+supprime.
        Utilise une barre spécifique si la copie est nécessaire.
        """
        src_path = Path(src)
        dst_path = Path(dst)
        current_task_id = task_id or f"move_dir_{src_path.name}_{int(time.time())}"

        if not src_path.is_dir():
            self.log_error(f"Source n'est pas un dossier valide: {src}", log_levels=log_levels)
            return False

        self.log_info(f"Déplacement du dossier {src_path} vers {dst_path}", log_levels=log_levels)

        try:
            if not dst_path.parent.exists():
                 self.run(['mkdir', '-p', str(dst_path.parent)], check=False, needs_sudo=True)

            # Essayer mv d'abord
            cmd_mv = ['mv', str(src_path), str(dst_path)]
            success_mv, _, stderr_mv = self.run(cmd_mv, check=False, needs_sudo=True)
            if success_mv:
                self.log_success(f"Dossier déplacé avec succès (via mv): {dst_path}", log_levels=log_levels)
                return True
            else:
                self.log_info(f"mv impossible (ex: cross-device, {stderr_mv}), tentative copie+suppression...", log_levels=log_levels)
                # copy_dir gère sa propre barre avec current_task_id
                copy_success = self.copy_dir(src_path, dst_path,
                                             exclude_patterns=exclude_patterns,
                                             task_id=current_task_id,
                                             copy_symlinks=True, # Comportement mv par défaut
                                             ignore_dangling_symlinks=False) # Idem
                if copy_success:
                    cmd_rm = ['rm', '-rf', str(src_path)]
                    success_rm, _, stderr_rm = self.run(cmd_rm, check=False, needs_sudo=True)
                    if success_rm:
                        self.log_success(f"Dossier déplacé avec succès (copie+suppression): {dst_path}", log_levels=log_levels)
                        return True
                    else:
                        self.log_error(f"Copie réussie mais échec suppression source {src_path}: {stderr_rm}", log_levels=log_levels)
                        return False
                else:
                    self.log_error(f"Échec de la copie lors du déplacement de {src_path}", log_levels=log_levels)
                    return False
        except Exception as e:
            self.log_error(f"Erreur lors du déplacement du dossier {src_path}: {e}", exc_info=True, log_levels=log_levels)
            return False