# install/plugins/plugins_utils/text_utils.py
#!/usr/bin/env python3
"""
Module utilitaire pour les opérations courantes sur les chaînes de caractères et le texte.
Fournit des fonctions pour le parsing simple, la recherche et le nettoyage de texte.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
from typing import Union, Optional, List, Dict, Any, Tuple, Pattern

class TextUtils(PluginsUtilsBase):
    """
    Classe pour les opérations courantes sur le texte.
    Hérite de PluginUtilsBase principalement pour la journalisation.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise les utilitaires texte."""
        super().__init__(logger, target_ip)

    def parse_key_value(self,
                        text: str,
                        delimiter_pattern: str = r'\s*[:=]\s*', # Regex: : ou = entouré d'espaces optionnels
                        comment_char: Optional[str] = '#',
strip_quotes: bool = True, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Parse un texte multiligne contenant des paires clé-valeur.

        Args:
            text: La chaîne de caractères à parser.
            delimiter_pattern: Regex définissant le(s) délimiteur(s) entre clé et valeur.
            comment_char: Caractère indiquant un commentaire (si None, pas de gestion de commentaire).
            strip_quotes: Si True, supprime les guillemets simples ou doubles entourant les valeurs.

        Returns:
            Dictionnaire des paires clé-valeur trouvées.
        """
        self.log_debug(f"Parsing texte clé-valeur avec délimiteur '{delimiter_pattern}'", log_levels=log_levels)
        data = {}
        lines = text.splitlines()
        delimiter_re = re.compile(delimiter_pattern)

        for line_num, line in enumerate(lines):
            line = line.strip()
            # Ignorer les lignes vides ou les commentaires
            if not line or (comment_char and line.startswith(comment_char)):
                continue

            # Séparer clé et valeur en utilisant le délimiteur regex
            parts = delimiter_re.split(line, maxsplit=1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()

                # Supprimer les guillemets si demandé
                if strip_quotes:
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]

                if key: # Ne pas ajouter si la clé est vide
                     data[key] = value
                else:
                     self.log_warning(f"Ligne {line_num+1}: Clé vide détectée, ligne ignorée: '{line}'", log_levels=log_levels)

            else:
                self.log_warning(f"Ligne {line_num+1}: Format clé-valeur non reconnu ou délimiteur non trouvé: '{line}'", log_levels=log_levels)

        self.log_debug(f"{len(data)} paires clé-valeur parsées.", log_levels=log_levels)
        return data

    def parse_table(self,
                    text: str,
                    delimiter_pattern: str = r'\s+', # Regex: un ou plusieurs espaces
                    header_lines: int = 1,
                    comment_char: Optional[str] = '#',
min_columns: int = 2, log_levels: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
        """
        Parse un texte tabulaire en une liste de dictionnaires.

        Args:
            text: La chaîne de caractères contenant le tableau.
            delimiter_pattern: Regex pour séparer les colonnes.
            header_lines: Nombre de lignes d'en-tête à utiliser pour les clés du dictionnaire.
                          La dernière ligne d'en-tête est utilisée pour les clés.
            comment_char: Caractère indiquant une ligne de commentaire à ignorer.
            min_columns: Nombre minimum de colonnes attendues pour une ligne de données valide.

        Returns:
            Liste de dictionnaires, où chaque dictionnaire représente une ligne de données.
            Retourne une liste vide si le parsing échoue ou si aucune donnée n'est trouvée.
        """
        self.log_debug("Parsing de texte tabulaire...", log_levels=log_levels)
        lines = text.splitlines()
        data = []
        header: List[str] = []
        delimiter_re = re.compile(delimiter_pattern)

        current_line_num = 0
        # Lire les lignes d'en-tête
        while current_line_num < len(lines) and current_line_num < header_lines:
            line = lines[current_line_num].strip()
            current_line_num += 1
            if line and (not comment_char or not line.startswith(comment_char)):
                # Utiliser la dernière ligne non-commentaire comme en-tête
                header_raw = delimiter_re.split(line)
                # Nettoyer les noms d'en-tête (minuscules, remplacer espaces/caractères spéciaux)
                header = [re.sub(r'\W+', '_', h.strip().lower()) for h in header_raw if h.strip()]
                self.log_debug(f"En-tête détecté: {header}", log_levels=log_levels)

        if not header:
            self.log_error("Impossible de déterminer l'en-tête du tableau.", log_levels=log_levels)
            return []

        # Lire les lignes de données
        for line in lines[current_line_num:]:
            line = line.strip()
            if not line or (comment_char and line.startswith(comment_char)):
                continue

            values = delimiter_re.split(line)
            # Supprimer les éléments vides résultant de multiples délimiteurs
            values = [v.strip() for v in values if v.strip()]

            if len(values) >= min_columns:
                 # Créer un dictionnaire pour la ligne
                 row_dict = {}
                 # Associer les valeurs aux en-têtes
                 for i, h in enumerate(header):
                      if i < len(values):
                           row_dict[h] = values[i]
                      else:
                           row_dict[h] = None # Valeur manquante pour cette colonne
                 # Ajouter les colonnes supplémentaires sans en-tête si elles existent
                 if len(values) > len(header):
                      for i in range(len(header), len(values)):
                           row_dict[f'column_{i+1}'] = values[i]
                 data.append(row_dict)
            else:
                 self.log_warning(f"Ligne de données ignorée (moins de {min_columns} colonnes): '{line}'", log_levels=log_levels)

        self.log_info(f"{len(data)} lignes de données parsées du tableau.", log_levels=log_levels)
        return data

    def extract_sections(self,
                         text: str,
                         section_start_pattern: str,
include_start_line: bool = False, log_levels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Extrait des sections d'un texte basé sur un motif de début de section.
        Chaque section s'étend jusqu'au prochain motif de début ou la fin du texte.

        Args:
            text: Le texte complet à analyser.
            section_start_pattern: Regex pour identifier le début d'une section.
                                   Le groupe de capture 1 (s'il existe) sera utilisé comme clé.
                                   Sinon, la ligne de début complète sera la clé.
            include_start_line: Inclure la ligne de début dans le contenu de la section.

        Returns:
            Dictionnaire où les clés sont les identifiants de section et les valeurs
            sont le contenu textuel de chaque section.
        """
        self.log_debug(f"Extraction de sections avec le pattern: '{section_start_pattern}'", log_levels=log_levels)
        sections: Dict[str, str] = {}
        current_section_key: Optional[str] = None
        current_section_content: List[str] = []
        start_re = re.compile(section_start_pattern)

        for line in text.splitlines():
            match = start_re.match(line)
            if match:
                # Sauvegarder la section précédente
                if current_section_key is not None:
                    sections[current_section_key] = "\n".join(current_section_content)

                # Commencer une nouvelle section
                # Utiliser le groupe 1 comme clé si disponible, sinon la ligne entière
                try:
                    current_section_key = match.group(1).strip()
                except IndexError:
                    current_section_key = line.strip()

                current_section_content = []
                if include_start_line:
                    current_section_content.append(line)
                self.log_debug(f"Nouvelle section détectée: '{current_section_key}'", log_levels=log_levels)

            elif current_section_key is not None:
                # Ajouter la ligne à la section courante
                current_section_content.append(line)

        # Ajouter la dernière section
        if current_section_key is not None:
            sections[current_section_key] = "\n".join(current_section_content)

        self.log_info(f"{len(sections)} sections extraites.", log_levels=log_levels)
        return sections

    def advanced_regex_search(self,
                              text: str,
                              pattern: Union[str, Pattern],
                              group_names: Optional[List[str]] = None,
find_all: bool = True, log_levels: Optional[Dict[str, str]] = None) -> Union[Optional[Dict[str, str]], List[Dict[str, str]], None]:
        """
        Effectue une recherche regex avancée et retourne les résultats structurés.

        Args:
            text: Texte dans lequel chercher.
            pattern: Expression régulière (chaîne ou objet re.Pattern compilé).
            group_names: Liste optionnelle de noms à assigner aux groupes de capture.
                         Le nombre de noms doit correspondre au nombre de groupes dans le pattern.
            find_all: Si True, retourne toutes les correspondances, sinon seulement la première.

        Returns:
            - Si find_all=True: Liste de dictionnaires, chaque dict représentant une correspondance
              avec les groupes nommés (ou numérotés 'group_1', 'group_2'...).
            - Si find_all=False: Dictionnaire de la première correspondance ou None si pas de correspondance.
            - None si erreur regex.
        """
        self.log_debug(f"Recherche regex avancée avec pattern: {pattern}", log_levels=log_levels)
        try:
            if isinstance(pattern, str):
                regex = re.compile(pattern)
            else:
                regex = pattern

            matches_data = []
            iterator = regex.finditer(text) if find_all else [regex.search(text)]

            for match in iterator:
                if not match: continue # Ignorer si search ne trouve rien

                match_dict = {}
                # Utiliser les noms de groupes fournis s'ils existent
                if group_names:
                    if len(group_names) == len(match.groups()):
                        for i, name in enumerate(group_names):
                            match_dict[name] = match.group(i + 1) # Les groupes sont indexés à partir de 1
                    else:
                         self.log_warning("Le nombre de group_names ne correspond pas au nombre de groupes capturés dans le pattern.", log_levels=log_levels)
                         # Fallback vers les noms de groupes numérotés
                         for i, group_val in enumerate(match.groups()):
                              match_dict[f'group_{i+1}'] = group_val
                # Utiliser les noms de groupes définis dans le pattern (si (?P<name>...))
                elif match.groupdict():
                     match_dict = match.groupdict()
                # Fallback vers les groupes numérotés
                else:
                     for i, group_val in enumerate(match.groups()):
                          match_dict[f'group_{i+1}'] = group_val

                # Ajouter aussi la correspondance complète
                match_dict['full_match'] = match.group(0)
                matches_data.append(match_dict)

            if not find_all:
                return matches_data[0] if matches_data else None
            else:
                 self.log_debug(f"{len(matches_data)} correspondance(s) regex trouvée(s).", log_levels=log_levels)
                 return matches_data

        except re.error as e:
            self.log_error(f"Erreur de syntaxe dans l'expression régulière: {e}", log_levels=log_levels)
            return None
        except Exception as e:
            self.log_error(f"Erreur lors de la recherche regex: {e}", exc_info=True, log_levels=log_levels)
            return None

    def sanitize_filename(self, filename: str, replacement: str = '_', log_levels: Optional[Dict[str, str]] = None) -> str:
        """
        Nettoie une chaîne pour l'utiliser comme nom de fichier valide.
        Remplace les caractères non alphanumériques (sauf . - _) par un caractère de remplacement.

        Args:
            filename: Nom de fichier potentiel.
            replacement: Caractère utilisé pour remplacer les caractères invalides.

        Returns:
            Nom de fichier nettoyé.
        """
        # Supprimer les caractères invalides ou potentiellement dangereux
        # Garder lettres, chiffres, ., -, _
        sanitized = re.sub(r'[^\w.\-]+', replacement, filename)
        # Éviter les points ou tirets consécutifs ou en début/fin
        sanitized = re.sub(r'^[._-]+|[._-]+$', '', sanitized)
        sanitized = re.sub(r'[._-]{2,}', replacement, sanitized)
        # Limiter la longueur ? Pas ici, mais peut être pertinent.
        if not sanitized: # Si tout a été supprimé
             return f"fichier_nettoye_{int(time.time())}"
        return sanitized