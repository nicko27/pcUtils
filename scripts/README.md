# Utilitaires Python

Ce répertoire contient des scripts utilitaires Python qui suivent une convention de retour standardisée.

## Convention de retour

Toutes les fonctions dans ces scripts doivent suivre le format de retour suivant :

```python
def get_something():
    try:
        # Code qui récupère les données
        data = {...}  # Un dictionnaire ou une liste de dictionnaires
        return True, data
    except Exception as e:
        error_msg = f"Message d'erreur explicite: {str(e)}"
        return False, error_msg
```

### Format de retour

1. **En cas de succès** :
   - Premier élément : `True`
   - Second élément : Un dictionnaire ou une liste de dictionnaires contenant les données

2. **En cas d'erreur** :
   - Premier élément : `False`
   - Second élément : Une chaîne de caractères décrivant l'erreur

### Exemple d'utilisation

```python
success, result = get_something()
if success:
    # result contient les données sous forme de dict
    print(f"Données récupérées : {result}")
else:
    # result contient le message d'erreur
    print(f"Erreur : {result}")
```

## Scripts disponibles

- `get_users.py` : Récupère la liste des utilisateurs du système
- `get_usb.py` : Récupère la liste des périphériques USB
- `system_info.py` : Récupère diverses informations système
