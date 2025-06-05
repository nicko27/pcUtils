# install/plugins/plugins_utils/ssl_certs.py
#!/usr/bin/env python3
"""
Module utilitaire pour la gestion basique des certificats SSL/TLS.
Utilise la commande système 'openssl'.
"""

from plugins_utils.plugins_utils_base import PluginsUtilsBase
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Union, Optional, List, Dict, Any, Tuple

class SslCertCommands(PluginsUtilsBase):
    """
    Classe pour effectuer des opérations basiques sur les certificats SSL/TLS via openssl.
    Hérite de PluginUtilsBase pour l'exécution de commandes.
    """

    def __init__(self, logger=None, target_ip=None):
        """Initialise le gestionnaire de certificats."""
        super().__init__(logger, target_ip)
        self._check_commands()

    def _check_commands(self):
        """Vérifie si la commande openssl est disponible."""
        cmds = ['openssl']
        missing = []
        for cmd in cmds:
            success, _, _ = self.run(['which', cmd], check=False, no_output=True, error_as_warning=True)
            if not success:
                missing.append(cmd)
        if missing:
            self.log_error(f"Commande 'openssl' non trouvée. Ce module ne fonctionnera pas. "
                           f"Installer le paquet 'openssl'.", log_levels=log_levels)

    def _parse_openssl_date(self, date_str: str) -> Optional[datetime]:
        """Parse une date retournée par openssl (ex: 'notAfter=Mar 30 12:00:00 2025 GMT')."""
        try:
            # Extraire la date après le '='
            date_part = date_str.split('=', 1)[1].strip()
            # Format attendu: Mmm DD HH:MM:SS YYYY TZ (ex: Apr  6 12:34:56 2025 GMT)
            # Gérer le double espace potentiel après le mois
            date_part_cleaned = re.sub(r' +', ' ', date_part)
            # Spécifier le format et le fuseau horaire (souvent GMT)
            # Note: Le parsing de fuseau horaire peut être complexe. On suppose GMT ici.
            # Utiliser timezone.utc pour créer un objet datetime conscient du fuseau horaire.
            dt = datetime.strptime(date_part_cleaned, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
            return dt
        except (IndexError, ValueError, Exception) as e:
            self.log_warning(f"Impossible de parser la date openssl '{date_str}': {e}", log_levels=log_levels)
            return None

    def check_cert_expiry(self,
                          cert_path: Optional[Union[str, Path]] = None,
                          host: Optional[str] = None,
                          port: int = 443,
days_warning: int = 30, log_levels: Optional[Dict[str, str]] = None) -> Tuple[str, Optional[datetime], Optional[int]]:
        """
        Vérifie la date d'expiration d'un certificat SSL/TLS (local ou distant).

        Args:
            cert_path: Chemin vers le fichier certificat local (PEM).
            host: Nom d'hôte ou IP du serveur distant (si cert_path n'est pas fourni).
            port: Port du serveur distant (défaut 443).
            days_warning: Seuil en jours pour déclencher un avertissement.

        Returns:
            Tuple (status: str, expiry_date: Optional[datetime], days_left: Optional[int]).
            Status peut être 'OK', 'WARNING', 'EXPIRED', 'ERROR', 'NOT_FOUND'.
        """
        target = str(cert_path) if cert_path else f"{host}:{port}"
        self.log_info(f"Vérification de l'expiration du certificat pour: {target}", log_levels=log_levels)

        openssl_cmd: List[str] = []
        input_data: Optional[str] = None

        if cert_path:
            cert_path_obj = Path(cert_path)
            if not cert_path_obj.is_file():
                self.log_error(f"Fichier certificat non trouvé: {cert_path}", log_levels=log_levels)
                return "NOT_FOUND", None, None
            openssl_cmd = ['openssl', 'x509', '-in', str(cert_path_obj), '-noout', '-enddate']
        elif host:
            # Utiliser s_client pour récupérer le certificat du serveur
            # Envoyer 'quit' ou fermer stdin rapidement pour terminer la connexion s_client
            # L'option -servername est importante pour SNI
            s_client_cmd = ['openssl', 's_client', '-connect', f"{host}:{port}", '-servername', host]
            # Exécuter s_client et piper vers x509
            # Utiliser check=False car s_client peut échouer pour diverses raisons
            s_success, s_stdout, s_stderr = self.run(s_client_cmd, input_data="quit\n", check=False, timeout=10)
            if not s_success or 'BEGIN CERTIFICATE' not in s_stdout:
                 self.log_error(f"Impossible de récupérer le certificat de {target}. Stderr: {s_stderr}", log_levels=log_levels)
                 if "connect:errno=" in s_stderr: self.log_error("  -> Vérifier connectivité et pare-feu.", log_levels=log_levels)
                 if "getaddrinfo: Name or service not known" in s_stderr: self.log_error("  -> Hôte ou port invalide.", log_levels=log_levels)
                 return "ERROR", None, None
            # Passer le certificat récupéré à x509
            openssl_cmd = ['openssl', 'x509', '-noout', '-enddate']
            input_data = s_stdout # Utiliser la sortie de s_client comme input pour x509
        else:
            self.log_error("Il faut fournir soit cert_path soit host.", log_levels=log_levels)
            return "ERROR", None, None

        # Exécuter la commande openssl x509
        success, stdout, stderr = self.run(openssl_cmd, input_data=input_data, check=False, no_output=True)

        if not success:
            self.log_error(f"Échec de la commande openssl pour récupérer la date d'expiration. Stderr: {stderr}", log_levels=log_levels)
            return "ERROR", None, None

        # Parser la date
        expiry_date = self._parse_openssl_date(stdout.strip())
        if not expiry_date:
            self.log_error(f"Impossible de parser la date d'expiration: {stdout.strip()}", log_levels=log_levels)
            return "ERROR", None, None

        # Calculer les jours restants
        now = datetime.now(timezone.utc)
        delta = expiry_date - now
        days_left = delta.days

        # Déterminer le statut
        if days_left < 0:
            status = "EXPIRED"
            self.log_error(f"Certificat pour {target} a EXPIRÉ le {expiry_date.strftime('%Y-%m-%d')}.", log_levels=log_levels)
        elif days_left < days_warning:
            status = "WARNING"
            self.log_warning(f"Certificat pour {target} expire bientôt ({days_left} jours restants, le {expiry_date.strftime('%Y-%m-%d')}). Seuil={days_warning}j.", log_levels=log_levels)
        else:
            status = "OK"
            self.log_info(f"Certificat pour {target} est valide jusqu'au {expiry_date.strftime('%Y-%m-%d')} ({days_left} jours restants).", log_levels=log_levels)

        return status, expiry_date, days_left

    def get_cert_info(self,
                      cert_path: Optional[Union[str, Path]] = None,
                      host: Optional[str] = None,
port: int = 443, log_levels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations détaillées d'un certificat (Sujet, Issuer, Dates, etc.).

        Args:
            cert_path: Chemin vers le fichier certificat local (PEM).
            host: Nom d'hôte ou IP du serveur distant (si cert_path n'est pas fourni).
            port: Port du serveur distant (défaut 443).

        Returns:
            Dictionnaire contenant les informations du certificat ou None si erreur.
        """
        target = str(cert_path) if cert_path else f"{host}:{port}"
        self.log_info(f"Récupération des informations du certificat pour: {target}", log_levels=log_levels)

        openssl_cmd: List[str] = []
        input_data: Optional[str] = None
        cert_data: Optional[str] = None

        if cert_path:
            cert_path_obj = Path(cert_path)
            if not cert_path_obj.is_file():
                self.log_error(f"Fichier certificat non trouvé: {cert_path}", log_levels=log_levels)
                return None
            # Lire directement le contenu pour le passer à openssl via stdin
            try:
                with open(cert_path_obj, 'r') as f:
                     cert_data = f.read()
                openssl_cmd = ['openssl', 'x509', '-noout', '-subject', '-issuer', '-dates', '-serial', '-fingerprint', 'sha256']
                input_data = cert_data
            except Exception as e:
                 self.log_error(f"Erreur lors de la lecture de {cert_path}: {e}", log_levels=log_levels)
                 return None

        elif host:
            s_client_cmd = ['openssl', 's_client', '-connect', f"{host}:{port}", '-servername', host]
            s_success, s_stdout, s_stderr = self.run(s_client_cmd, input_data="quit\n", check=False, timeout=10)
            if not s_success or 'BEGIN CERTIFICATE' not in s_stdout:
                 self.log_error(f"Impossible de récupérer le certificat de {target}. Stderr: {s_stderr}", log_levels=log_levels)
                 return None
            # Utiliser la sortie de s_client comme input
            openssl_cmd = ['openssl', 'x509', '-noout', '-subject', '-issuer', '-dates', '-serial', '-fingerprint', 'sha256']
            input_data = s_stdout
        else:
            self.log_error("Il faut fournir soit cert_path soit host.", log_levels=log_levels)
            return None

        # Exécuter la commande openssl x509
        success, stdout, stderr = self.run(openssl_cmd, input_data=input_data, check=False, no_output=True)

        if not success:
            self.log_error(f"Échec de la commande openssl pour récupérer les informations. Stderr: {stderr}", log_levels=log_levels)
            return None

        # Parser la sortie
        info: Dict[str, Any] = {}
        for line in stdout.splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                key_norm = key.strip().lower().replace(' ', '_').replace('sha256_fingerprint','fingerprint_sha256')
                value_strip = value.strip()

                # Parser les dates
                if key_norm in ['notbefore', 'notafter']:
                     info[key_norm] = self._parse_openssl_date(line)
                # Parser Sujet et Issuer (peuvent être complexes)
                elif key_norm in ['subject', 'issuer']:
                     info[key_norm] = self._parse_dn(value_strip)
                else:
                     info[key_norm] = value_strip

        self.log_debug(f"Informations certificat pour {target}: {info}", log_levels=log_levels)
        return info

    def _parse_dn(self, dn_str: str) -> Dict[str, str]:
        """Parse une chaîne de Distinguished Name (DN) en dictionnaire."""
        # Format: /TYPE0=value0/TYPE1=value1/TYPE2=... ou CN=..., OU=..., O=...
        dn_dict = {}
        # Essayer le format avec /
        if dn_str.startswith('/'):
            parts = [p for p in dn_str.split('/') if p]
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    dn_dict[key.strip()] = value.strip()
        # Essayer le format CN=, OU=
        else:
             # Utiliser regex pour mieux gérer les virgules et espaces
             # Ex: CN = my.host.com, OU = IT, O = My Org
             pattern = re.compile(r'([a-zA-Z0-9]+)\s*=\s*((\".*?\")|[^,]+)')
             matches = pattern.findall(dn_str)
             for match in matches:
                  key = match[0].strip()
                  # La valeur peut être entre guillemets ou non
                  value = match[1].strip()
                  if value.startswith('"') and value.endswith('"'):
                       value = value[1:-1]
                  dn_dict[key] = value
        return dn_dict

    def generate_self_signed_cert(self,
                                  key_path: Union[str, Path],
                                  cert_path: Union[str, Path],
                                  days: int = 365,
                                  common_name: str = 'localhost',
                                  bits: int = 2048,
                                  key_type: str = 'rsa', # rsa, ec
overwrite: bool = False, log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Génère une clé privée et un certificat auto-signé simple.

        Args:
            key_path: Chemin pour enregistrer la clé privée.
            cert_path: Chemin pour enregistrer le certificat.
            days: Durée de validité du certificat en jours.
            common_name: CN (Common Name) à utiliser dans le sujet.
            bits: Taille de la clé RSA (si key_type='rsa').
            key_type: Type de clé ('rsa' ou 'ec').
            overwrite: Écraser les fichiers existants.

        Returns:
            bool: True si succès.
        """
        key_path_obj = Path(key_path)
        cert_path_obj = Path(cert_path)
        self.log_info(f"Génération d'un certificat auto-signé pour '{common_name}'", log_levels=log_levels)
        self.log_info(f"  Clé privée: {key_path_obj}", log_levels=log_levels)
        self.log_info(f"  Certificat: {cert_path_obj} (Valide {days} jours)", log_levels=log_levels)

        if not overwrite and (key_path_obj.exists() or cert_path_obj.exists()):
            self.log_error(f"Les fichiers de clé ou de certificat existent déjà. Utiliser overwrite=True.", log_levels=log_levels)
            return False

        # Créer les dossiers parents si nécessaire
        try:
            key_path_obj.parent.mkdir(parents=True, exist_ok=True)
            cert_path_obj.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log_error(f"Impossible de créer les dossiers parents: {e}", log_levels=log_levels)
            return False

        # 1. Générer la clé privée
        self.log_info("Génération de la clé privée...", log_levels=log_levels)
        if key_type.lower() == 'rsa':
            cmd_genkey = ['openssl', 'genpkey', '-algorithm', 'RSA',
                          '-out', str(key_path_obj),
                          '-pkeyopt', f'rsa_keygen_bits:{bits}']
        elif key_type.lower() == 'ec':
             # Utiliser une courbe standard comme prime256v1
             cmd_genkey = ['openssl', 'genpkey', '-algorithm', 'EC',
                           '-out', str(key_path_obj),
                           '-pkeyopt', 'ec_paramgen_curve:prime256v1']
        else:
             self.log_error(f"Type de clé non supporté: {key_type}. Utiliser 'rsa' ou 'ec'.", log_levels=log_levels)
             return False

        # Définir umask pour que la clé privée soit créée avec des permissions restreintes (ex: 600)
        old_umask = os.umask(0o077) # Lire et écrire seulement pour le propriétaire
        success_key, _, stderr_key = self.run(cmd_genkey, check=False, needs_sudo=True)
        os.umask(old_umask) # Restaurer l'umask

        if not success_key:
            self.log_error(f"Échec de la génération de la clé privée. Stderr: {stderr_key}", log_levels=log_levels)
            if key_path_obj.exists(): key_path_obj.unlink() # Nettoyage
            return False
        self.log_success("Clé privée générée.", log_levels=log_levels)

        # 2. Générer le certificat auto-signé directement (sans CSR séparé)
        self.log_info("Génération du certificat auto-signé...", log_levels=log_levels)
        # Construire le sujet
        subject = f"/CN={common_name}"
        # Ajouter d'autres champs si nécessaire: /C=FR/ST=State/L=City/O=Org/OU=Unit
        cmd_req = [
            'openssl', 'req', '-new', '-x509', # -x509 pour auto-signer
            '-key', str(key_path_obj),
            '-out', str(cert_path_obj),
            '-days', str(days),
            '-subj', subject,
            '-nodes' # Ne pas chiffrer la clé privée sur disque (si passphrase non gérée ici)
        ]
        # Ajouter l'algo de hash (sha256 est recommandé)
        cmd_req.extend(['-sha256'])

        success_cert, _, stderr_cert = self.run(cmd_req, check=False, needs_sudo=True)

        if success_cert:
            self.log_success(f"Certificat auto-signé généré: {cert_path_obj}", log_levels=log_levels)
            # Définir permissions sur le certificat (ex: 644)
            self.set_permissions(cert_path_obj, mode="644")
            return True
        else:
            self.log_error(f"Échec de la génération du certificat. Stderr: {stderr_cert}", log_levels=log_levels)
            # Nettoyage
            if key_path_obj.exists(): key_path_obj.unlink()
            if cert_path_obj.exists(): cert_path_obj.unlink()
            return False

    def verify_cert_chain(self, cert_path: Union[str, Path], ca_bundle_path: Union[str, Path], log_levels: Optional[Dict[str, str]] = None) -> bool:
        """
        Vérifie si un certificat est signé par une autorité présente dans un bundle CA.

        Args:
            cert_path: Chemin vers le certificat à vérifier.
            ca_bundle_path: Chemin vers le fichier contenant les certificats CA de confiance.

        Returns:
            bool: True si la vérification réussit.
        """
        cert_path_obj = Path(cert_path)
        ca_bundle_path_obj = Path(ca_bundle_path)
        self.log_info(f"Vérification de la chaîne de confiance pour {cert_path_obj} avec {ca_bundle_path_obj}", log_levels=log_levels)

        if not cert_path_obj.is_file():
            self.log_error(f"Fichier certificat introuvable: {cert_path_obj}", log_levels=log_levels)
            return False
        if not ca_bundle_path_obj.is_file():
            self.log_error(f"Fichier CA bundle introuvable: {ca_bundle_path_obj}", log_levels=log_levels)
            return False

        cmd = ['openssl', 'verify', '-CAfile', str(ca_bundle_path_obj), str(cert_path_obj)]
        success, stdout, stderr = self.run(cmd, check=False) # Pas besoin de sudo pour verify

        # openssl verify retourne 0 si OK
        if success:
             # La sortie contient souvent "OK"
             if "OK" in stdout:
                  self.log_success(f"La vérification du certificat {cert_path_obj} a réussi.", log_levels=log_levels)
                  return True
             else:
                  # Succès mais sortie inattendue? Log et considérer comme échec prudent
                  self.log_warning(f"openssl verify a retourné 0 mais la sortie est inattendue: {stdout}", log_levels=log_levels)
                  return False
        else:
             self.log_error(f"Échec de la vérification du certificat {cert_path_obj}. Sortie:\n{stdout}\nStderr:\n{stderr}", log_levels=log_levels)
             return False