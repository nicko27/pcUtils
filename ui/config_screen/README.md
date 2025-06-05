# Système de Templates de Configuration

Ce module gère les templates de configuration pour les plugins pcUtils.

## Structure des Fichiers

```
config_screen/
├── imports.py              # Imports centralisés
├── template_manager.py     # Gestionnaire de templates
├── template_field.py       # Champ de sélection de template
└── plugin_config_container.py  # Conteneur de configuration
```

## Composants Principaux

### TemplateManager

Gestionnaire centralisé des templates de configuration. Gère :
- Chargement des templates depuis le dossier `templates/`
- Validation selon le schéma défini
- Accès aux templates et leurs variables

```python
# Exemple d'utilisation
manager = TemplateManager()
templates = manager.get_plugin_templates("add_printer")
```

### TemplateField

Champ de sélection de template dans l'interface utilisateur. Permet :
- Sélection d'un template dans une liste
- Application automatique des variables
- Template par défaut au démarrage

```python
# Exemple d'utilisation dans un conteneur
template_field = TemplateField(plugin_name, field_id, fields_by_id)
```

### Fichier de Template

Format YAML standard :
```yaml
name: Nom du Template
description: Description détaillée
variables:
  variable1: valeur1
  variable2: valeur2
```

## Utilisation

1. **Création d'un Template**
   ```yaml
   # templates/add_printer/bureau.yml
   name: Configuration Bureau
   description: Imprimante de bureau standard
   variables:
     printer_name: Bureau_RDC
     printer_ip: 192.168.1.100
   ```

2. **Intégration dans l'Interface**
   ```python
   # Dans plugin_config_container.py
   templates = self.template_manager.get_plugin_templates(plugin_name)
   if templates:
       template_field = TemplateField(plugin_name, 'template', fields_by_id)
   ```

## Journalisation

- Messages en français
- Niveaux de log appropriés (debug, warning, error)
- Traçabilité des opérations

## Dépendances

- `textual` : Interface utilisateur
- `ruamel.yaml` : Gestion des fichiers YAML
- Composants internes pcUtils
