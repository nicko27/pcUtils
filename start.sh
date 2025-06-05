#!/bin/bash
# Traiter les paramètres
# Utiliser le répertoire où le script est exécuté comme valeur par défaut
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
EXTRACT_DIR="$SCRIPT_DIR"
DEBUG=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --extract_dir=*)
            EXTRACT_DIR="${1#*=}"
            ;;
        --debug)
            DEBUG=1
            set -xv
            ;;
    esac
    shift
done


if [ -z "$EXTRACT_DIR" ]; then
    echo "Error: --extract_dir parameter is required"
    exit 1
fi

cd $SCRIPT_DIR
# Créer le dossier logs s'il n'existe pas
mkdir -p "$EXTRACT_DIR/logs"
rm -rf "$EXTRACT_DIR/libs/*"
mkdir -p "$EXTRACT_DIR/libs"

# Code intégré de libsExtract.sh
# Dossier où se trouvent les fichiers .whl
WHL_DIR="$EXTRACT_DIR/whl"

# Parcourir tous les fichiers .whl dans le dossier spécifié
for whl in "$WHL_DIR"/*.whl; do
    # Extraire le nom du paquet (sans l'extension)
    pakname=$(basename "$whl" .whl)

    # Créer un sous-dossier pour chaque paquet
    mkdir -p "$EXTRACT_DIR/libs/$pakname"

    # Dézipper le fichier .whl dans son dossier
    unzip -q "$whl" -d "$EXTRACT_DIR/libs/$pakname" 2>/dev/null
done


# Vérifier si le binaire textual est disponible
if [ "$DEBUG" -eq 1 ]; then
    if command -v textual &> /dev/null; then
        echo "Lancement de l'application en mode debug avec textual"
        textual run "$EXTRACT_DIR/main.py" --dev
    else
        python3 -m textual "$EXTRACT_DIR/main.py"
    fi
else
    python3 "$EXTRACT_DIR/main.py"
fi
