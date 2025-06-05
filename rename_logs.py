import os
import ast
import shutil
from pathlib import Path
from typing import Union, Optional, Dict, List, Tuple, Any, Set
import logging
import re

# Configuration simple du logging pour cette fonction
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Le paramètre à ajouter aux fonctions de log
LOG_LEVELS_PARAM_NAME = "log_levels"
LOG_LEVELS_PARAM_TEXT = "log_levels=log_levels"

# Noms des méthodes de log à modifier
LOG_METHOD_NAMES = ['log_info', 'log_debug', 'log_warning', 'log_error', 'log_success', 'log_critical']

class LogCallVisitor(ast.NodeVisitor):
    """Visiteur AST pour trouver les appels aux fonctions de log."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.log_calls_to_modify: Dict[int, ast.Call] = {}  # {line_number: node}
        self.self_methods: Set[str] = set()  # Pour stocker les méthodes liées à 'self'
        
    def visit_ClassDef(self, node: ast.ClassDef):
        """Enregistre les méthodes définies dans la classe."""
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name in LOG_METHOD_NAMES:
                    logging.debug(f"  Trouvé définition méthode log: {item.name} dans classe")
                    self.self_methods.add(item.name)
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call):
        """Visite les appels de fonction pour trouver ceux qui appellent des méthodes de log."""
        func = node.func
        
        # Cas 1: appel de méthode sur 'self': self.log_info(...)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'self':
            if func.attr in LOG_METHOD_NAMES:
                # Vérifier si le paramètre log_levels est déjà présent
                has_log_levels = False
                for keyword in node.keywords:
                    if keyword.arg == LOG_LEVELS_PARAM_NAME:
                        has_log_levels = True
                        break
                
                if not has_log_levels:
                    logging.debug(f"  Ligne {node.lineno}: Appel à self.{func.attr}() sans log_levels")
                    self.log_calls_to_modify[node.lineno] = node
        
        # Cas 2: appel direct de fonction: log_info(...)
        elif isinstance(func, ast.Name) and func.id in LOG_METHOD_NAMES:
            # Vérifier si le paramètre log_levels est déjà présent
            has_log_levels = False
            for keyword in node.keywords:
                if keyword.arg == LOG_LEVELS_PARAM_NAME:
                    has_log_levels = True
                    break
            
            if not has_log_levels:
                logging.debug(f"  Ligne {node.lineno}: Appel à {func.id}() sans log_levels")
                self.log_calls_to_modify[node.lineno] = node
        
        # Continuer à visiter les noeuds enfants
        self.generic_visit(node)


def add_log_levels_to_calls(directory: Union[str, Path]) -> Dict[str, str]:
    """
    Parcourt un dossier, analyse les fichiers Python et ajoute le paramètre log_levels
    aux appels des fonctions de log qui ne l'ont pas.

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

            visitor = LogCallVisitor(filepath)
            visitor.visit(tree)

            if not visitor.log_calls_to_modify:
                logging.info("  Aucun appel de fonction log à modifier dans ce fichier.")
                continue

            # Si des modifications sont nécessaires, travailler sur les lignes
            lines = original_content.splitlines()
            
            # Tri des lignes en ordre décroissant pour éviter de décaler les numéros de ligne
            line_numbers = sorted(visitor.log_calls_to_modify.keys(), reverse=True)
            
            for lineno in line_numbers:
                if lineno <= len(lines):
                    line_idx = lineno - 1
                    line = lines[line_idx]
                    
                    # Trouver l'appel de méthode dans la ligne
                    # Chercher les motifs comme "self.log_info(" ou "log_warning("
                    log_call_patterns = [
                        (f"self.{method_name}(", f"self.{method_name}(") for method_name in LOG_METHOD_NAMES
                    ] + [
                        (f"{method_name}(", f"{method_name}(") for method_name in LOG_METHOD_NAMES
                    ]
                    
                    modified_line = line
                    for pattern, replacement_base in log_call_patterns:
                        if pattern in modified_line:
                            # Trouver la position de la dernière parenthèse fermante correspondante
                            start_pos = modified_line.find(pattern) + len(pattern) - 1  # Position après la parenthèse ouvrante
                            current_pos = start_pos + 1
                            paren_level = 1
                            
                            while current_pos < len(modified_line) and paren_level > 0:
                                if modified_line[current_pos] == '(':
                                    paren_level += 1
                                elif modified_line[current_pos] == ')':
                                    paren_level -= 1
                                current_pos += 1
                            
                            if paren_level == 0:
                                # La position correcte de la parenthèse fermante
                                close_pos = current_pos - 1
                                
                                # Vérifier s'il y a déjà des arguments
                                args_part = modified_line[start_pos + 1:close_pos].strip()
                                
                                if not args_part:  # Aucun argument
                                    insert_pos = close_pos
                                    modified_part = LOG_LEVELS_PARAM_TEXT
                                elif args_part.endswith(','):  # Se termine déjà par une virgule
                                    insert_pos = close_pos
                                    modified_part = f" {LOG_LEVELS_PARAM_TEXT}"
                                else:  # Des arguments existent sans virgule à la fin
                                    insert_pos = close_pos
                                    modified_part = f", {LOG_LEVELS_PARAM_TEXT}"
                                
                                # Insérer le paramètre log_levels
                                modified_line = modified_line[:insert_pos] + modified_part + modified_line[insert_pos:]
                                break  # Sortir après la première modification pour éviter les problèmes avec plusieurs appels sur la même ligne
                    
                    if modified_line != line:
                        logging.debug(f"    Ligne {lineno} modifiée: {modified_line.strip()}")
                        lines[line_idx] = modified_line
            
            # Stocker le contenu modifié
            modified_content = "\n".join(lines)
            if modified_content != original_content:
                modified_files_content[str(filepath)] = modified_content
                logging.info(f"  -> Fichier marqué pour modification avec {len(line_numbers)} appels modifiés.")
            else:
                logging.warning(f"  -> Aucune modification effective dans le fichier malgré {len(line_numbers)} appels détectés.")

        except SyntaxError as e:
            logging.error(f"Erreur de syntaxe Python dans {filepath}: {e}")
        except Exception as e:
            logging.error(f"Erreur inattendue lors du traitement de {filepath}: {e}", exc_info=True)

    return modified_files_content

# Gestion des appels en multilignes
def handle_multiline_calls(content: str) -> str:
    """
    Traite les appels de log qui s'étendent sur plusieurs lignes.
    Cette fonction utilise une approche par expressions régulières pour compléter
    l'analyse AST qui peut manquer certains cas complexes.
    
    Args:
        content: Contenu du fichier à traiter
        
    Returns:
        Contenu modifié
    """
    lines = content.splitlines()
    
    # Pattern pour identifier les débuts d'appels de log
    log_call_start_pattern = re.compile(r'(self\.)?(' + '|'.join(LOG_METHOD_NAMES) + r')\s*\(')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Chercher un début d'appel de log
        match = log_call_start_pattern.search(line)
        if match and LOG_LEVELS_PARAM_NAME not in line:
            # Vérifier si l'appel est complet sur cette ligne
            open_parens = line.count('(')
            close_parens = line.count(')')
            
            if open_parens > close_parens:
                # C'est un appel multiligne
                start_line = i
                paren_balance = open_parens - close_parens
                j = i + 1
                
                while j < len(lines) and paren_balance > 0:
                    paren_balance += lines[j].count('(') - lines[j].count(')')
                    j += 1
                
                if paren_balance == 0:
                    # Nous avons trouvé la fin de l'appel
                    end_line = j - 1
                    
                    # Vérifier si log_levels est déjà présent dans l'appel multilignes
                    call_text = '\n'.join(lines[start_line:end_line+1])
                    if LOG_LEVELS_PARAM_NAME not in call_text:
                        # Modifier la dernière ligne avant la parenthèse fermante
                        last_line = lines[end_line]
                        last_close_paren_pos = last_line.rfind(')')
                        
                        # Déterminer comment insérer le paramètre
                        if last_line[:last_close_paren_pos].strip():
                            # Il y a du contenu avant la dernière parenthèse
                            if last_line[:last_close_paren_pos].strip().endswith(','):
                                # Se termine déjà par une virgule
                                modified_last_line = last_line[:last_close_paren_pos] + f" {LOG_LEVELS_PARAM_TEXT}" + last_line[last_close_paren_pos:]
                            else:
                                # Pas de virgule à la fin
                                modified_last_line = last_line[:last_close_paren_pos] + f", {LOG_LEVELS_PARAM_TEXT}" + last_line[last_close_paren_pos:]
                        else:
                            # Rien avant la dernière parenthèse
                            modified_last_line = last_line[:last_close_paren_pos] + f"{LOG_LEVELS_PARAM_TEXT}" + last_line[last_close_paren_pos:]
                        
                        lines[end_line] = modified_last_line
                    
                    i = end_line  # Continuer l'analyse après cette ligne
            
        i += 1
    
    return '\n'.join(lines)

# --- Fonction principale ---
def update_log_calls_in_directory(directory: Union[str, Path], apply_changes: bool = False) -> None:
    """
    Fonction principale qui met à jour tous les appels de fonctions de log dans un répertoire.
    
    Args:
        directory: Répertoire à traiter
        apply_changes: Si True, appliquer les changements aux fichiers
    """
    modified_content_dict = add_log_levels_to_calls(directory)
    
    # Traiter les appels multilignes que l'AST pourrait avoir manqués
    for file_path in list(modified_content_dict.keys()):
        content = modified_content_dict[file_path]
        modified_content = handle_multiline_calls(content)
        if modified_content != content:
            logging.info(f"Traitement supplémentaire des appels multilignes dans {file_path}")
            modified_content_dict[file_path] = modified_content
    
    if not modified_content_dict:
        print("\nAucun fichier n'a été modifié.")
    else:
        print(f"\n{len(modified_content_dict)} fichier(s) ont été modifiés en mémoire.")
        
        if apply_changes:
            print("Application des modifications...")
            for file_path, content in modified_content_dict.items():
                try:
                    p = Path(file_path)
                    # Créer une sauvegarde
                    backup_path = p.with_suffix(p.suffix + ".bak_logcalls")
                    logging.info(f"Sauvegarde de {p} vers {backup_path}")
                    shutil.copy2(p, backup_path)
                    # Écrire le nouveau contenu
                    p.write_text(content, encoding='utf-8')
                    logging.info(f"Fichier {p} mis à jour.")
                except Exception as e:
                    logging.error(f"Erreur lors de l'écriture de {file_path}: {e}")
            print("Modifications appliquées.")
        else:
            print("Les modifications ont été préparées mais non appliquées.")

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    # Remplacer par le chemin de votre dossier 'plugins_utils'
    target_directory = Path("./plugins/plugins_utils")

    if not target_directory.is_dir():
        print(f"Erreur: Le dossier '{target_directory}' n'existe pas.")
    else:
        write_changes = input("Voulez-vous appliquer directement les modifications ? (oui/NON): ").lower()
        update_log_calls_in_directory(target_directory, apply_changes=(write_changes == 'oui'))
