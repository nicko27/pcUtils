from textual.app import ComposeResult
from textual.widgets import Input

from .text_field import TextField
from ..utils.logging import get_logger

logger = get_logger('password_field')

class PasswordField(TextField):
    """Password input field that masks input"""
    
    def compose(self) -> ComposeResult:
        """Create password field components"""
        yield from super().compose()
        
        # Remplacer l'input standard par un input en mode password
        self.input.password = True
        
        # Toujours initialiser à l'état activé
        self.input.disabled = False
        self.input.remove_class('disabled')
        
        if self.disabled:
            logger.debug(f"PasswordField {self.field_id} is initially disabled")
            self.input.disabled = True
            self.input.add_class('disabled')