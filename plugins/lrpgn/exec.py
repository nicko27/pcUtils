#!/usr/bin/env python3
"""
Plugin pour la suppression et la reinstallation de LRPGN
Gère les dépôts, vérifie la présence de versions antérieures, et utilise apt.
"""
import json
import time
import traceback
import sys
import os
from typing import Any
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins_utils import main
from plugins_utils import metier
from plugins_utils import apt
from plugins_utils import dpkg
from plugins_utils import files
from plugins_utils import utils_cmd

SRCS=["configuration","configurationutilisateurs","sos","procedures","temp","utilisateurs"]
TRAVAIL="/usr/lib/lrpgn/travail"
DEST="/root/lrpgn"
log_levels = {
    'info': 'info',    # Niveau de log par défaut pour les informations
    'warning': 'info',   # Niveau de log pour les avertissements
    'error': 'error', # Niveau de log pour les erreurs
    'debug': 'none'       # Niveau de log pour les messages de débogage
}
PACKAGES=[
    "ca-certificates-java",           # Certificats d'autorité de certification Java
    "gend-base-config-java-certs",    # Configuration de base des certificats Java
    "gir1.2-javascriptcoregtk-4.1:amd64", # Bindings GIR pour JavaScriptCore GTK 4.1
    "gir1.2-javascriptcoregtk-6.0:amd64", # Bindings GIR pour JavaScriptCore GTK 6.0
    "java-common",                    # Fichiers communs pour l'environnement Java
    "javascript-common",              # Infrastructure commune pour les interpréteurs JavaScript
    "libactivation-java",             # Bibliothèque d'activation Java
    "libapache-pom-java",             # Modèle d'objet de projet Apache pour Java
    "libatinject-jsr330-api-java",    # API d'injection de dépendances Java
    "libbcmail-java",                 # Bibliothèque BouncyCastle pour emails
    "libbcpkix-java",                 # Bibliothèque BouncyCastle pour PKI
    "libbcprov-java",                 # Bibliothèque de cryptographie BouncyCastle
    "libbcutil-java",                 # Utilitaires BouncyCastle
    "libcommons-io-java",             # Bibliothèque Apache Commons IO
    "libcommons-lang3-java",          # Bibliothèque utilitaire Apache Commons Lang
    "libcommons-parent-java",         # POM parent pour les projets Apache Commons
    "libel-api-java",                 # API Expression Language
    "libfontawesomefx-java",          # Icônes et polices pour JavaFX
    "libfontbox2-java",               # Bibliothèque de manipulation de polices
    "libgeronimo-validation-1.0-spec-java", # Spécifications de validation Geronimo 1.0
    "libgeronimo-validation-1.1-spec-java", # Spécifications de validation Geronimo 1.1
    "libgettext-commons-java",        # Bibliothèque pour l'internationalisation
    "libhibernate-validator4-java",   # Bibliothèque de validation Hibernate
    "libhsqldb1.8.0-java",            # Base de données HSQLDB
    "libjackson2-core-java",          # Bibliothèque de traitement JSON Jackson
    "libjackson2-jr-java",            # Version junior de Jackson
    "libjavascriptcoregtk-4.1-0:amd64", # Bibliothèque JavaScriptCore GTK 4.1
    "libjavascriptcoregtk-6.0-1:amd64", # Bibliothèque JavaScriptCore GTK 6.0
    "libjaxb-api-java",               # API pour la liaison XML Java
    "libjboss-jdeparser2-java",       # Générateur de code JBoss
    "libjboss-logging-java",          # Système de logging JBoss
    "libjboss-logging-tools-java",    # Outils de logging JBoss
    "libjsp-api-java",                # API JSP
    "liblibreoffice-java",            # Bibliothèques Java pour LibreOffice
    "liblogback-java",                # Bibliothèque de logging Logback
    "libmail-java",                   # Bibliothèque de gestion d'emails
    "libmetadata-extractor-java",     # Extracteur de métadonnées
    "libofficebean-java",             # Beans Office pour Java
    "libopenjfx-java",                # Bibliothèques JavaFX open-source
    "libreoffice-java-common",        # Composants Java communs pour LibreOffice
    "libsambox-java",                 # Bibliothèque de manipulation PDF
    "libsejda-commons-java",          # Bibliothèques communes Sejda
    "libsejda-eventstudio-java",      # Bibliothèque d'événements Sejda
    "libsejda-injector-java",         # Injecteur de dépendances Sejda
    "libsejda-io-java",               # Utilitaires d'E/S Sejda
    "libsejda-java",                  # Bibliothèques principales Sejda
    "libservlet-api-java",            # API Servlet
    "libservlet3.1-java",             # Implémentation Servlet 3.1
    "libslf4j-java",                  # Bibliothèque de logging SLF4J
    "libthumbnailator-java",          # Bibliothèque de création de vignettes
    "libtwelvemonkeys-java",          # Extensions pour le traitement d'images
    "libunoloader-java",              # Chargeur UNO pour LibreOffice
    "libwebsocket-api-java",          # API WebSocket
    "libxmpcore-java",                # Bibliothèque de gestion de métadonnées XMP
    "oracle-java8-bin",               # Binaires Java 8 d'Oracle
    "oracle-java8-jre",               # Environnement d'exécution Java 8 d'Oracle
    "ure-java",                       # Environnement de runtime universel
    "gend-libreoffice",               # Configuration générale pour LibreOffice
    "liblibreoffice-java",            # Bibliothèques Java pour LibreOffice
    "libreoffice",                    # Suite bureautique LibreOffice
    "libreoffice-base",               # Module Base de LibreOffice
    "libreoffice-base-core",          # Composants de base de LibreOffice Base
    "libreoffice-base-drivers",       # Pilotes de base de données pour LibreOffice
    "libreoffice-calc",               # Tableur LibreOffice
    "libreoffice-common",             # Fichiers communs LibreOffice
    "libreoffice-core",               # Composants principaux de LibreOffice
    "libreoffice-draw",               # Outil de dessin LibreOffice
    "libreoffice-gnome",              # Intégration GNOME pour LibreOffice
    "libreoffice-grammalecte-fr",     # Correcteur grammatical français
    "libreoffice-gtk3",               # Support GTK3 pour LibreOffice
    "libreoffice-help-common",        # Aide commune LibreOffice
    "libreoffice-help-en-us",         # Aide en anglais (US)
    "libreoffice-help-fr",            # Aide en français
    "libreoffice-impress",            # Logiciel de présentation LibreOffice
    "libreoffice-java-common",        # Composants Java communs
    "libreoffice-l10n-fr",            # Localisation française
    "libreoffice-math",               # Éditeur d'équations
    "libreoffice-officebean",         # Composant Bean pour intégration
    "libreoffice-pdfimport",          # Importation de PDF
    "libreoffice-report-builder-bin", # Générateur de rapports
    "libreoffice-sdbc-hsqldb",        # Pilote de base de données HSQLDB
    "libreoffice-style-colibre",      # Style Colibre
    "libreoffice-style-yaru",         # Style Yaru
    "libreoffice-uiconfig-base",      # Configuration UI pour Base
    "libreoffice-uiconfig-calc",      # Configuration UI pour Calc
    "libreoffice-uiconfig-common",    # Configuration UI commune
    "libreoffice-uiconfig-draw",      # Configuration UI pour Draw
    "libreoffice-uiconfig-impress",   # Configuration UI pour Impress
    "libreoffice-uiconfig-math",      # Configuration UI pour Math
    "libreoffice-uiconfig-writer",    # Configuration UI pour Writer
    "libreoffice-writer",             # Traitement de texte
    "lrpgn",                          # Paquet LRPGN (fonction non identifiée)
    "lrpgn-doupality",                # Extension LRPGN
    "lrpgn-jre",                      # Runtime Java pour LRPGN
    "lrpgn-mediatools"               # Outils média LRPGN
]

class Plugin:
    def run(self, config: dict, log: Any, target_ip: str) -> bool:
        try:
            metier_cmd = metier.MetierCommands(log, target_ip, config)
            if not metier_cmd.should_process():
                log.info("Ordinateur non concerné")
                log.success("Aucune action requise")
                return True

            return self._process_lrpgn(config, log, target_ip)

        except Exception as e:
            log.debug(traceback.format_exc())
            log.error(f"Erreur inattendue: {str(e)}")
            return False

    def _process_lrpgn(self, config: dict, log: Any, target_ip: str) -> bool:
        apt_cmd = apt.AptCommands(log, target_ip)
        dpkg_cmd = dpkg.DpkgCommands(log, target_ip)

        total_steps=5
        returnValue=self._copy_travail(TRAVAIL,DEST, log, target_ip)
        if returnValue==False:
            log.error("Erreur dans la copie des fichiers de configuration")
            return False
        log.next_step()
        java= dpkg_cmd.list_installed_packages_with_pattern("java")
        libreoffice=dpkg_cmd.list_installed_packages_with_pattern("libreoffice")
        lrpgn=dpkg_cmd.list_installed_packages_with_pattern("lrpgn")
        paquets=java+libreoffice+lrpgn
        dpkg_cmd.purge_packages(paquets,error_as_warning=True)
        log.next_step()
        if paquets==[]:
            paquets=PACKAGES
        if apt_cmd.install(paquets,no_recommends=True,log_levels=log_levels) == False:
            log.error("Erreur dans l'installation des paquets")
            return False
        log.next_step()
        returnValue=self._copy_travail(DEST,TRAVAIL, log, target_ip)
        if returnValue==False:
            log.error("Erreur dans la copie des fichiers de configuration")
            return False
        log.success("Suppression et installation de LRPGN effectuée avec succès")
        return True

    def _copy_travail(self,src,dest, log, target_ip):
        files_cmd= files.FilesCommands(log, target_ip)
        for elt in SRCS:
            directory=Path(src,elt)
            if directory.is_dir():
                if files_cmd.copy_dir(src=directory,dst=dest,task_id="copy_id") == False:
                    log.erreur("Pb de copie de ".str(directory))
                    return False
        return True


if __name__ == "__main__":
    plugin = Plugin()
    m = main.Main(plugin)
    resultat = m.start()
    return_value = 1 - resultat
    sys.exit(return_value)