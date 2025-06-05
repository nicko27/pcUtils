import os
import ast
import shutil
from pathlib import Path
from typing import Union, Optional, Dict, List, Tuple, Any
import logging

# Configuration simple du logging pour cette fonction
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Le paramètre à ajouter et sa forme textuelle exacte
LOG_LEVELS_PARAM_TEXT = "log_levels: Optional[Dict[str, str]] = None"
LOG_LEVELS_PARAM_NAME = "log_levels"

class FunctionDefVisitor(ast.NodeVisitor):
    """Visiteur AST pour trouver les définitions de fonctions publiques."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.functions_to_modify: List[Tuple[ast.FunctionDef, int]] = [] # (node, line_number)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Ignorer les fonctions privées/protégées et __init__
        if node.name.startswith('_'):
            logging.debug(f"  Ignoré (privé/init): def {node.name}(...)")
            self.generic_visit(node) # Visiter les fonctions imbriquées si nécessaire
            return

        logging.debug(f"  Trouvé fonction publique: def {node.name}(...) à la ligne {node.lineno}")

        # Vérifier si le paramètre log_levels existe déjà
        has_log_levels = False
        if node.args.args: # Vérifier les arguments positionnels/clés
            last_arg = node.args.args[-1]
            if last_arg.arg == LOG_LEVELS_PARAM_NAME:
                has_log_levels = True
        if not has_log_levels and node.args.kwonlyargs: # Vérifier les arguments keyword-only
             last_kw_arg = node.args.kwonlyargs[-1]
             if last_kw_arg.arg == LOG_LEVELS_PARAM_NAME:
                  has_log_levels = True

        if not has_log_levels:
            logging.info(f"    -> Nécessite ajout de '{LOG_LEVELS_PARAM_NAME}' dans {self.filepath.name}")
            self.functions_to_modify.append((node, node.lineno))
        else:
            logging.debug(f"    -> Paramètre '{LOG_LEVELS_PARAM_NAME}' déjà présent.")

        # Continuer la visite pour les fonctions imbriquées
        self.generic_visit(node)

def add_log_levels_to_signatures(directory: Union[str, Path]) -> Dict[str, str]:
    """
    Parcourt un dossier, analyse les fichiers Python et ajoute le paramètre log_levels
    aux fonctions publiques qui ne l'ont pas.

    Args:
        directory: Chemin du dossier à analyser.

    Returns:
        Dictionnaire où les clés sont les chemins des fichiers modifiés
        et les valeurs sont le contenu modifié du fichier.
    """
    target_dir = Path(directory)
    modified_files_content: Dict[str, str] = {}

    if not target_dir.is_dir():
        logging.error(f"Le chemin fourni n'est pas un dossier valide: {directory}")
        return modified_files_content

    logging.info(f"Analyse des fichiers Python dans: {target_dir}")

    for filepath in target_dir.rglob("*.py"):
        logging.info(f"Traitement du fichier: {filepath}")
        try:
            original_content = filepath.read_text(encoding='utf-8')
            tree = ast.parse(original_content, filename=str(filepath))

            visitor = FunctionDefVisitor(filepath)
            visitor.visit(tree)

            if not visitor.functions_to_modify:
                logging.info("  Aucune fonction à modifier dans ce fichier.")
                continue

            # Si des modifications sont nécessaires, travailler sur les lignes
            lines = original_content.splitlines()
            lines_to_modify_indices = {lineno - 1 for _, lineno in visitor.functions_to_modify} # Lignes 0-based

            new_lines = []
            in_multiline_def = False
            paren_level = 0

            for i, line in enumerate(lines):
                stripped_line = line.strip()

                # Gérer les définitions de fonction multilignes
                if stripped_line.startswith("def ") or in_multiline_def:
                    if not in_multiline_def:
                         # Vérifier si c'est une fonction à modifier
                         is_target_line = i in lines_to_modify_indices
                         in_multiline_def = '(' in stripped_line and '):' not in stripped_line.replace(' ','')

                    if is_target_line:
                        open_paren = line.find('(')
                        close_paren = line.rfind(')')

                        if open_paren != -1 and close_paren != -1 and close_paren > open_paren:
                             # Définition sur une seule ligne ou fin de définition multiligne
                             args_part = line[open_paren + 1:close_paren].strip()
                             if args_part.endswith(',') and not args_part.endswith(', '):
                                 args_part += " " # Ajouter espace après virgule si nécessaire

                             # Insérer le paramètre
                             # Gérer les cas: (), (arg1), (arg1,), (*args), (**kwargs)
                             if not args_part: # def func():
                                 insertion = LOG_LEVELS_PARAM_TEXT
                             elif args_part.endswith(','): # def func(a,):
                                 insertion = f"{args_part} {LOG_LEVELS_PARAM_TEXT}"
                             else: # def func(a): ou def func(a, b):
                                 insertion = f"{args_part}, {LOG_LEVELS_PARAM_TEXT}"

                             # Reconstruire la ligne
                             modified_line = line[:open_paren + 1] + insertion + line[close_paren:]
                             new_lines.append(modified_line)
                             logging.debug(f"    Ligne {i+1} modifiée: {modified_line.strip()}")
                             in_multiline_def = False # Fin de la modification pour cette fonction
                             is_target_line = False # Ne plus traiter cette ligne

                        elif open_paren != -1:
                             # Début d'une définition multiligne à modifier
                             # On ne modifie pas ici, on attend la parenthèse fermante
                             new_lines.append(line)
                             paren_level += line.count('(') - line.count(')')
                             in_multiline_def = True

                        elif close_paren != -1 and in_multiline_def:
                              # Fin de la définition multiligne à modifier
                              paren_level += line.count('(') - line.count(')')
                              if paren_level == 0: # Assurer que c'est la bonne parenthèse fermante
                                    args_part = line[:close_paren].strip()
                                    if args_part.endswith(','):
                                         insertion = f"{args_part} {LOG_LEVELS_PARAM_TEXT}"
                                    else:
                                         insertion = f"{args_part}, {LOG_LEVELS_PARAM_TEXT}"

                                    modified_line = insertion + line[close_paren:]
                                    new_lines.append(modified_line)
                                    logging.debug(f"    Ligne {i+1} (fin multiligne) modifiée: {modified_line.strip()}")
                                    in_multiline_def = False
                                    is_target_line = False
                              else:
                                  # Parenthèse fermante intermédiaire
                                   new_lines.append(line)
                        elif in_multiline_def:
                             # Ligne intermédiaire dans une définition multiligne
                             new_lines.append(line)
                             paren_level += line.count('(') - line.count(')')


                    else: # Fonction non modifiée ou ligne hors fonction
                        new_lines.append(line)
                        # Suivre les parenthèses même pour les lignes non modifiées
                        if '(' in line:
                             paren_level += line.count('(')
                        if ')' in line:
                             paren_level -= line.count(')')
                             if paren_level <= 0:
                                  in_multiline_def = False
                                  paren_level = 0 # Réinitialiser au cas où

                else: # Ligne normale hors définition
                    new_lines.append(line)

            # Stocker le contenu modifié
            modified_content = "\n".join(new_lines)
            modified_files_content[str(filepath)] = modified_content
            logging.info(f"  -> Fichier marqué pour modification.")


        except SyntaxError as e:
            logging.error(f"Erreur de syntaxe Python dans {filepath}: {e}")
        except Exception as e:
            logging.error(f"Erreur inattendue lors du traitement de {filepath}: {e}", exc_info=True)

    return modified_files_content

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    # Remplacer par le chemin de votre dossier 'plugins_utils'
    target_directory = Path("./plugins/plugins_utils")

    if not target_directory.is_dir():
        print(f"Erreur: Le dossier '{target_directory}' n'existe pas.")
    else:
        modified_content_dict = add_log_levels_to_signatures(target_directory)

        if not modified_content_dict:
            print("\nAucun fichier n'a été modifié.")
        else:
            print(f"\n{len(modified_content_dict)} fichier(s) ont été modifiés en mémoire.")
            # print("Contenu modifié:")
            # for file_path, content in modified_content_dict.items():
            #     print(f"\n--- {file_path} ---")
            #     print(content[:500] + "..." if len(content) > 500 else content) # Afficher un extrait

            # Optionnel : Écrire les modifications dans les fichiers (ATTENTION)
            write_changes = input("Voulez-vous écrire les modifications dans les fichiers originaux ? (oui/NON): ").lower()
            if write_changes == 'oui':
                print("Écriture des modifications...")
                for file_path, content in modified_content_dict.items():
                    try:
                        p = Path(file_path)
                        # Créer une sauvegarde
                        backup_path = p.with_suffix(p.suffix + ".bak_loglevels")
                        logging.info(f"Sauvegarde de {p} vers {backup_path}")
                        shutil.copy2(p, backup_path)
                        # Écrire le nouveau contenu
                        p.write_text(content, encoding='utf-8')
                        logging.info(f"Fichier {p} mis à jour.")
                    except Exception as e:
                        logging.error(f"Erreur lors de l'écriture de {file_path}: {e}")
                print("Modifications écrites.")
            else:
                print("Modifications non écrites.")
