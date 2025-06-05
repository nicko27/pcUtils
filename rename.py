import os
import sys
from ruamel.yaml import YAML
from typing import Optional


def to_title_case(text: str) -> str:
    """
    Transforme une chaîne en 'Title Case' : première lettre de chaque mot en majuscule.
    """
    return ' '.join(word.capitalize() for word in text.split())


def process_yaml_file(file_path: str) -> None:
    """
    Charge un fichier YAML, modifie le champ 'Name' pour qu'il soit en 'Title Case',
    et sauvegarde le fichier sans modifier sa structure.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.load(f)

    # Vérifie que le champ 'Name' est présent et est une chaîne
    if isinstance(data, dict) and 'name' in data and isinstance(data['name'], str):
        original_name = data['name']
        updated_name = to_title_case(original_name)
        if updated_name != original_name:
            print(f"  - Champ 'Name' modifié : '{original_name}' -> '{updated_name}'")
            data['name'] = updated_name
        else:
            print(f"  - Champ 'Name' déjà correct : '{original_name}'")
    else:
        print("  - Aucun champ 'Name' valide trouvé.")

    # Traitement du champ 'printer_name'
    if 'printer_name' in data['variables'] and isinstance(data['variables']['printer_name'], str):
        if len(data['variables']['printer_name']) > 3:
            original_printer_name = data['variables']['printer_name']
            updated_printer_name = to_title_case(original_printer_name)
            if updated_printer_name != original_printer_name:
                print(f"  - Champ 'printer_name' modifié : '{original_printer_name}' -> '{updated_printer_name}'")
                data['variables']['printer_name'] = updated_printer_name
            else:
                print(f"  - Champ 'printer_name' déjà correct : '{original_printer_name}'")
        else:
            print(f"  - Champ 'printer_name' court (< 4 caractères), inchangé : '{data['variables']['printer_name']}'")

    # Réécriture du fichier
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)


def rename_file_to_lowercase(file_path: str) -> str:
    """
    Renomme un fichier en minuscules s'il contient des majuscules.
    Renvoie le chemin mis à jour du fichier.
    """
    directory, filename = os.path.split(file_path)
    lower_filename = filename.lower()

    if filename != lower_filename:
        new_path = os.path.join(directory, lower_filename)
        os.rename(file_path, new_path)
        print(f"[RENOMMÉ] {filename} -> {lower_filename}")
        return new_path
    return file_path


def process_directory(directory: str) -> None:
    """
    Parcourt tous les fichiers YAML dans le dossier (non récursivement),
    les renomme en minuscules si besoin, puis modifie le champ 'Name'.
    """
    print(f"Analyse du dossier : {directory}\n")

    for filename in os.listdir(directory):
        if filename.lower().endswith(('.yaml', '.yml')):
            file_path = os.path.join(directory, filename)
            print(f"Fichier : {filename}")
            updated_path = rename_file_to_lowercase(file_path)
            try:
                process_yaml_file(updated_path)
            except Exception as e:
                print(f"  [ERREUR] Échec de traitement : {e}")


if __name__ == "__main__":
    folder = "/media/nico/Drive/pcUtils_internet/templates/add_printer"
    process_directory(folder)
