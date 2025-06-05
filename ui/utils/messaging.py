"""
Système unifié de messaging pour PCUtils.
Définit un format standardisé pour toutes les communications entre plugins et UI.
"""

import re
import json
import logging
import time
import traceback
from enum import Enum, auto
from typing import Any, Dict, Optional, Tuple, Union

# Configuration du logger
logger = logging.getLogger('pcutils.messaging')

class MessageType(Enum):
    """Types de messages standardisés dans l'application"""
    INFO = auto()        # Information générale
    WARNING = auto()     # Avertissement
    ERROR = auto()       # Erreur
    SUCCESS = auto()     # Action réussie
    PROGRESS = auto()    # Mise à jour de progression
    DEBUG = auto()       # Information de débogage
    UNKNOWN = auto()     # Type non reconnu
    PROGRESS_TEXT = auto()  # Barre de progression textuelle
    START = auto()
    END = auto()

class Message:
    """Conteneur pour un message standardisé"""

    def __init__(
        self,
        type: MessageType,
        content: str,
        source: str = None,
        progress: float = None,
        step: int = None,
        total_steps: int = None,
        data: Dict[str, Any] = None,
        instance_id: int = None,
        target_ip: str = None
    ):
        """
        Initialise un message standardisé

        Args:
            type: Type de message (INFO, ERROR, etc.)
            content: Contenu textuel du message
            source: Source du message (nom du plugin, composant, etc.)
            progress: Valeur de progression (0.0 à 1.0) si applicable
            step: Étape actuelle si applicable
            total_steps: Nombre total d'étapes si applicable
            data: Données supplémentaires spécifiques au message
            instance_id: ID d'instance du plugin si applicable
            target_ip: Adresse IP cible pour les plugins SSH si applicable
        """
        self.type = type
        self.content = content
        self.source = source
        self.progress = progress
        self.step = step
        self.total_steps = total_steps
        self.data = data or {}
        self.instance_id = instance_id
        self.target_ip = target_ip

    def to_string(self) -> str:
        """
        Convertit le message en chaîne formatée

        Returns:
            str: Message formaté selon le standard PCUtils
        """
        if self.type == MessageType.PROGRESS:
            # Format spécial pour les messages de progression
            plugin_part = f" {self.source}" if self.source else ""
            return f"[PROGRESS] {int(self.progress * 100)} {self.step or 0} {self.total_steps or 1}{plugin_part}"
        elif self.type == MessageType.PROGRESS_TEXT:
            # Format spécial pour les barres de progression textuelles
            status = self.data.get('status', 'running')
            return f"[PROGRESS_TEXT] {status} {self.content}"
        else:
            # Format standard pour les autres types de messages
            return f"[LOG] [{self.type.name}] {self.content}"

    @classmethod
    def from_string(cls, message: str) -> 'Message':
        """
        Analyse une chaîne formatée pour créer un objet Message

        Args:
            message: Chaîne à analyser

        Returns:
            Message: Objet Message créé à partir de la chaîne
        """
        # Vérifier le format de progression
        # Format: [PROGRESS] percent step total_steps [plugin_name]
        progress_match = re.match(r'^\[PROGRESS\] (\d+) (\d+) (\d+) (\S+) (\d+)$', message)
        if progress_match:
            percent, step, total, plugin_name, instance_id = progress_match.groups()
            print(f"DEBUG: Message de progression détecté: percent={percent}, step={step}, total={total}, plugin_name={plugin_name}")
            try:
                msg = cls(
                    type=MessageType.PROGRESS,
                    content=f"Progression: {percent}%",
                    progress=int(percent) / 100.0,
                    step=int(step),
                    total_steps=int(total),
                    source=plugin_name,  # Utiliser source pour stocker le nom du plugin
                    instance_id=instance_id
                    )
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f"Failed to create progress message from string: {message}")
                return None
            # Ajouter un attribut plugin_name pour la compatibilité avec le code existant
            if plugin_name:
                msg.plugin_name = plugin_name
                print(f"DEBUG: Attribut plugin_name ajouté: {msg.plugin_name}")
            return msg

        # Vérifier le format de progression textuelle
        # Format: [PROGRESS_TEXT] status content
        progress_text_match = re.match(r'^\[PROGRESS_TEXT\] (\w+) (.+)$', message)
        if progress_text_match:
            status, content = progress_text_match.groups()
            return cls(
                type=MessageType.PROGRESS_TEXT,
                content=content,
                data={'status': status}
            )

        # Vérifier le format de log standard
        log_match = re.match(r'^\[LOG\] \[(\w+)\] (.+)$', message)
        if log_match:
            level, content = log_match.groups()
            try:
                msg_type = MessageType[level]
            except KeyError:
                msg_type = MessageType.INFO
            return cls(type=msg_type, content=content)

        # Format alternatif pour les anciennes versions
        alt_match = re.match(r'\[(.*?)\] \[(\w+)\] (.+)', message)
        if alt_match:
            timestamp, level, content = alt_match.groups()
            try:
                msg_type = MessageType[level.upper()]
            except KeyError:
                msg_type = MessageType.INFO
            return cls(type=msg_type, content=content)

        # Message non reconnu
        return cls(type=MessageType.UNKNOWN, content=message)

    @staticmethod
    def detect_message_type(content: str) -> MessageType:
        """
        Détecte automatiquement le type d'un message en fonction de son contenu

        Args:
            content: Contenu du message

        Returns:
            MessageType: Type détecté
        """
        if not content:
            return MessageType.INFO

        content_lower = content.lower()

        # Détection des erreurs
        if any(term in content_lower for term in [
            'error', 'erreur', 'failed', 'failure', 'échec', 'exception',
            'failed to', 'unable to', 'impossible de', 'permission denied'
        ]):
            return MessageType.ERROR

        # Détection des avertissements
        if any(term in content_lower for term in [
            'warning', 'warn', 'attention', 'avertissement', 'caution'
        ]):
            return MessageType.WARNING

        # Détection des succès
        if any(term in content_lower for term in [
            'success', 'succès', 'successful', 'completed', 'terminé',
            'réussi', 'installé avec succès', 'configuré avec succès'
        ]):
            return MessageType.SUCCESS

        # Détection des messages de débogage
        if any(term in content_lower for term in [
            'debug', 'trace', 'verbose'
        ]):
            return MessageType.DEBUG

        # Par défaut
        return MessageType.INFO


class MessageFormatter:
    """Utilitaire pour formater les messages pour différentes sorties"""

    @staticmethod
    def get_message_colors():
        """Retourne les couleurs standard pour les différents types de messages"""
        return {
            MessageType.INFO: "white",
            MessageType.WARNING: "yellow",
            MessageType.ERROR: "red",
            MessageType.SUCCESS: "green",
            MessageType.DEBUG: "gray70",
            MessageType.UNKNOWN: "white",
            MessageType.PROGRESS: "blue",
            MessageType.PROGRESS_TEXT: "blue",
            MessageType.START: "gray",
            MessageType.END: "gray"
        }

    @staticmethod
    def format_for_console(message: Message) -> str:
        """
        Formate un message pour la sortie console

        Args:
            message: Le message à formater

        Returns:
            str: Message formaté pour la console
        """
        return message.to_string()

    @staticmethod
    def format_for_log_file(message: Message) -> str:
        """
        Formate un message pour l'écriture dans un fichier de log

        Args:
            message: Le message à formater

        Returns:
            str: Message formaté pour le fichier de log
        """
        # Préparer le préfixe IP si disponible
        ip_prefix = ""
        if hasattr(message, 'target_ip') and message.target_ip:
            ip_prefix = f"[{message.target_ip}] "

        # Ajouter un préfixe pour les messages de succès pour les rendre plus visibles
        if message.type == MessageType.SUCCESS:
            return f"SUCCESS: {ip_prefix}{message.content}"
        elif message.type == MessageType.PROGRESS_TEXT:
            # Pour les barres de progression textuelles
            return f"PROGRESS_TEXT: {ip_prefix}{message.content}"
        else:
            return f"{ip_prefix}{message.content}"

    @staticmethod
    def format_for_textual(message: Message) -> Tuple[str, str]:
        """
        Formate un message pour l'affichage dans Textual

        Args:
            message: Le message à formater

        Returns:
            tuple: (texte_formaté, style)
        """
        # Styles pour chaque type de message
        styles = {
            MessageType.INFO: "white",
            MessageType.WARNING: "bright_yellow",
            MessageType.ERROR: "bright_red",
            MessageType.SUCCESS: "bright_green",
            MessageType.DEBUG: "dim grey",
            MessageType.PROGRESS: "bright_blue",
            MessageType.PROGRESS_TEXT: "bright_blue",
            MessageType.START: "grey",
            MessageType.END: "grey",
            MessageType.UNKNOWN: "white"
        }

        return message.content, styles.get(message.type, "white")

    @staticmethod
    def format_for_rich_textual(message: Message) -> str:
        """
        Formate un message pour l'affichage dans Textual avec des balises Rich

        Args:
            message: Le message à formater

        Returns:
            str: Message formaté avec des balises Rich pour Textual
        """
        # Obtenir les couleurs standard
        colors = MessageFormatter.get_message_colors()
        color = colors.get(message.type, "white")

        # Générer le message formaté avec des balises de couleur explicites
        timestamp = time.strftime("%H:%M:%S")
        level_str = f"{message.type.name:7}"

        # Échapper les caractères spéciaux pour le markup
        safe_content = escape_markup(message.content)

        # Ajouter l'IP si elle est disponible (attribut direct, pas via hasattr)
        ip_info = ""
        if message.target_ip:
            ip_info = f"[magenta]@{message.target_ip}[/magenta] "

        # Format spécial pour les barres de progression textuelles
        if message.type == MessageType.PROGRESS_TEXT:
            return f"[{color}]{safe_content}[/{color}]"

        # Format lisible et coloré pour les autres types de messages
        return f"[cyan]{timestamp}[/cyan]  [{color}]{level_str}[/{color}]  {ip_info}[{color}]{safe_content}[/{color}]"


# Fonctions utilitaires pour le formatage et l'échappement

def escape_markup(text):
    """Échapper les caractères spéciaux qui pourraient être interprétés comme du markup"""
    if text is None:
        return ""

    # Convertir en chaîne si ce n'est pas déjà le cas
    if not isinstance(text, str):
        text = str(text)

    # Échapper les caractères spéciaux Textual/Rich
    escaped = text.replace("[", "\\[").replace("]", "\\]")
    return escaped

# Fonctions utilitaires pour les modules externes

def create_info(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message d'information"""
    return Message(MessageType.INFO, content, source, target_ip=target_ip)

def create_warning(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message d'avertissement"""
    return Message(MessageType.WARNING, content, source, target_ip=target_ip)

def create_error(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message d'erreur"""
    return Message(MessageType.ERROR, content, source, target_ip=target_ip)

def create_success(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message de succès"""
    return Message(MessageType.SUCCESS, content, source, target_ip=target_ip)

def create_debug(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message de débogage"""
    return Message(MessageType.DEBUG, content, source, target_ip=target_ip)

def create_start(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message de débogage"""
    return Message(MessageType.START, content, source, target_ip=target_ip)

def create_end(content: str, source: str = None, target_ip: str = None) -> Message:
    """Crée un message de débogage"""
    return Message(MessageType.END, content, source, target_ip=target_ip)


def create_progress(progress: float, step: int = None, total_steps: int = None, source: str = None, target_ip: str = None) -> Message:
    """
    Crée un message de progression

    Args:
        progress: Progression (0.0 à 1.0)
        step: Étape actuelle (optionnel)
        total_steps: Nombre total d'étapes (optionnel)
        source: Source du message (optionnel)
        target_ip: Adresse IP cible pour les plugins SSH (optionnel)

    Returns:
        Message: Message de progression
    """
    # Calculer le pourcentage pour le contenu textuel
    percent = int(max(0, min(1, progress)) * 100)
    content = f"Progression: {percent}%"
    if step is not None and total_steps is not None:
        content += f" (étape {step}/{total_steps})"

    return Message(
        type=MessageType.PROGRESS,
        content=content,
        source=source,
        progress=progress,
        step=step,
        total_steps=total_steps,
        target_ip=target_ip
    )

def create_progress_text(content: str, status: str = "running", source: str = None, instance_id: int = None, target_ip: str = None) -> Message:
    """
    Crée un message de barre de progression textuelle

    Args:
        content: Contenu textuel de la barre de progression
        status: État de la barre ("running" ou "stop")
        source: Source du message (optionnel)
        instance_id: ID d'instance du plugin (optionnel)
        target_ip: Adresse IP cible pour les plugins SSH (optionnel)

    Returns:
        Message: Message de barre de progression textuelle
    """
    return Message(
        type=MessageType.PROGRESS_TEXT,
        content=content,
        source=source,
        instance_id=instance_id,
        target_ip=target_ip,
        data={"status": status}
    )

def parse_message(text: str) -> Message:
    """
    Parse une chaîne et retourne un objet Message

    Args:
        text: Texte à parser

    Returns:
        Message: Message résultant
    """
    return Message.from_string(text)