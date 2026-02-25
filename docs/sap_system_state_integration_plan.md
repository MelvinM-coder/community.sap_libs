# Plan d'intégration — Module `sap_system_state`

## Branche : `feature/system`

## 1. Objectif

Créer un module Ansible `community.sap_libs.sap_system_state` permettant de **démarrer ou arrêter une instance SAP** de manière idempotente, en communiquant via l'API SOAP sapcontrol (Unix socket local ou HTTP).

### Fonctionnalités clés

| Fonctionnalité | Description |
|----------------|-------------|
| **Idempotence** | Check état avant action → `changed: false` si déjà dans l'état cible |
| **Vérification ciblée** | Vérifie **uniquement l'instance demandée** via `GetProcessList` local |
| **Timeout fiable** | Timeout clair en secondes, `poll_interval` configurable |
| **Gestion des états** | Gestion explicite des 4 états (GREEN, YELLOW, GRAY, RED) |

---

## 2. Fichiers à créer

> **Règle absolue** : on ne modifie AUCUN fichier existant des autres contributeurs.

| # | Fichier | Rôle |
|---|---------|------|
| 1 | `plugins/module_utils/sap_soap.py` | Classes SOAP communes (connexion Unix socket / HTTP, conversion suds → dict) |
| 2 | `plugins/module_utils/sapcontrol.py` | Client sapcontrol haut niveau (wrapper des fonctions SOAP) |
| 3 | `plugins/modules/sap_system_state.py` | Module Ansible — paramètres, idempotence, wait loop |

### Arbre de dépendances

```
plugins/modules/sap_system_state.py
    └── plugins/module_utils/sapcontrol.py
            └── plugins/module_utils/sap_soap.py
                    └── suds (bibliothèque externe, déjà requise par le projet)
```

---

## 3. Phase 1 — `module_utils/sap_soap.py`

### Objectif
Factoriser le code SOAP commun déjà présent (et dupliqué) dans `sap_control_exec.py` et `sap_hostctrl_exec.py`, sans modifier ces fichiers.

### Contenu

```python
# Classes de connexion Unix socket
class LocalSocketHttpConnection(HTTPConnection)    # connexion HTTP via socket Unix
class LocalSocketHandler(HTTPHandler)              # handler HTTP pour socket Unix
class LocalSocketHttpAuthenticated(HttpAuthenticated)  # transport suds authentifié via socket

# Utilitaires
def recursive_dict(suds_object) -> dict            # conversion récursive suds → dict Python
def check_suds_library(module)                     # vérification de la disponibilité de suds

# Factory de connexion
def create_soap_client(wsdl_url, socket_path=None, username=None, password=None) -> Client
```

### Origine du code

| Classe / Fonction | Source originale | Lignes |
|-------------------|-----------------|--------|
| `LocalSocketHttpConnection` | `sap_control_exec.py` | Identique dans les 2 modules |
| `LocalSocketHandler` | `sap_control_exec.py` | Identique dans les 2 modules |
| `LocalSocketHttpAuthenticated` | `sap_control_exec.py` | Identique dans les 2 modules |
| `recursive_dict()` | `sap_control_exec.py` | Identique dans les 2 modules |

> **Note** : ce code est du code communautaire existant, réutilisé pour éviter la duplication. Les modules existants ne sont pas modifiés et continuent à utiliser leur propre copie.

---

## 4. Phase 2 — `module_utils/sapcontrol.py`

### Objectif
Fournir une classe `SAPControl` encapsulant les appels SOAP sapcontrol nécessaires au module `sap_system_state`.

### Interface

```python
class SAPControl:
    def __init__(self, instance_number, hostname="localhost", username=None, password=None)
    
    def connect(self)
        """Établit la connexion SOAP (socket Unix ou HTTP)."""
    
    def get_process_list(self) -> list[dict]
        """Retourne la liste des processus de l'instance avec leurs statuts."""
    
    def get_instance_status(self) -> str
        """Analyse GetProcessList et retourne l'état global : GREEN, YELLOW, GRAY, RED."""
    
    def start(self) -> dict
        """Démarre l'instance (sapcontrol Start)."""
    
    def stop(self, soft_timeout=0) -> dict
        """Arrête l'instance (sapcontrol Stop)."""
    
    def get_system_instance_list(self) -> list[dict]
        """Retourne la liste de toutes les instances du système SAP."""
```

### Conventions de connexion sapcontrol

| Mode | Socket | URL WSDL | Condition |
|------|--------|----------|-----------|
| Local (Unix socket) | `/tmp/.sapstream5{NN}13` | `http://localhost/sapcontrol?wsdl` | `hostname == localhost` et pas de user/password |
| HTTP | — | `http://{host}:5{NN}13/sapcontrol?wsdl` | hostname distant ou user/password fournis |
| HTTPS (fallback) | — | `http://{host}:5{NN}14/sapcontrol?wsdl` | tentée en premier si HTTP échoue |

> `{NN}` = `instance_number` zero-padded (ex: `01`)

---

## 5. Phase 3 — `modules/sap_system_state.py`

### Paramètres du module

| Paramètre | Type | Requis | Défaut | Description |
|-----------|------|--------|--------|-------------|
| `state` | `str` (choices: `started`, `stopped`) | ✅ | — | État cible de l'instance SAP |
| `instance_number` | `str` | ✅ | — | Numéro de l'instance SAP (ex: `"01"`) |
| `wait` | `bool` | ❌ | `true` | Attendre que l'instance atteigne l'état cible |
| `wait_timeout` | `int` | ❌ | `300` | Timeout d'attente en secondes |
| `poll_interval` | `int` | ❌ | `5` | Intervalle entre les vérifications (secondes) |
| `hostname` | `str` | ❌ | `localhost` | Hostname du sapstartsrv |
| `username` | `str` | ❌ | — | Utilisateur (si pas de socket local) |
| `password` | `str` | ❌ | — | Mot de passe (si pas de socket local) |

### Logique d'exécution

```
┌──────────────────────────────────────────────────┐
│  ① Connexion SOAP                                │
│     SAPControl(instance_number, hostname, ...)    │
│     → socket Unix /tmp/.sapstream5{NN}13          │
│       ou HTTP si hostname distant                 │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  ② État actuel                                   │
│     GetProcessList → analyse des dispstatus      │
│     → GREEN / YELLOW / GRAY / RED                │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  ③ Check idempotence                             │
│                                                  │
│     state=started :                              │
│     ├── Tous GREEN    → changed=false, exit OK   │
│     ├── GRAY/YELLOW   → action Start nécessaire  │
│     └── RED           → action Start nécessaire  │
│                                                  │
│     state=stopped :                              │
│     ├── Tous GRAY     → changed=false, exit OK   │
│     ├── GREEN/YELLOW  → action Stop nécessaire   │
│     └── RED           → action Stop nécessaire   │
└──────────────────┬───────────────────────────────┘
                   │ (si action nécessaire)
                   ▼
┌──────────────────────────────────────────────────┐
│  ④ Action                                        │
│     state=started → sapcontrol Start             │
│     state=stopped → sapcontrol Stop              │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  ⑤ Wait loop (si wait=true)                     │
│                                                  │
│     Toutes les {poll_interval} secondes :        │
│     → GetProcessList (instance locale UNIQUEMENT)│
│     → Vérifier si état cible atteint             │
│     → Timeout après {wait_timeout} secondes      │
│                                                  │
│     ⚠️  NE vérifie PAS les autres instances      │
│        du même SID (correction du bug connu)     │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  ⑥ Retour                                       │
│     changed: true/false                          │
│     msg: description de l'action                 │
│     system: liste des processus et statuts       │
│     state: état final (GREEN/YELLOW/GRAY/RED)    │
└──────────────────────────────────────────────────┘
```

### Gestion des états — Matrice d'idempotence

| État actuel | `state=started` | `state=stopped` |
|-------------|-----------------|-----------------|
| **GREEN** (tous les processus UP) | `changed: false` — déjà démarré | Action Stop → attente GRAY |
| **YELLOW** (partiel — certains UP, certains DOWN) | Action Start → attente GREEN | Action Stop → attente GRAY |
| **GRAY** (tous les processus DOWN) | Action Start → attente GREEN | `changed: false` — déjà arrêté |
| **RED** (erreur) | Action Start → attente GREEN | Action Stop → attente GRAY |

### Gestion du YELLOW — Détail

L'état YELLOW signifie que certains processus sont UP et d'autres DOWN. Exemples courants :
- Instance D00 : `igswd_mt` (IGS Watchdog) est GREEN mais `disp+work` (Dispatcher) reste GRAY
- Instance en cours de démarrage/arrêt : transition partielle

**Comportement du module :**
- `state=started` + YELLOW → on lance Start (le SAP saura quoi faire)
- `state=stopped` + YELLOW → on lance Stop
- Dans le wait loop, YELLOW n'est **pas** un état final → on continue d'attendre GREEN ou GRAY
- Si timeout + YELLOW → on retourne un warning avec l'état des processus

### Valeur de retour

```json
{
  "changed": true,
  "msg": "Instance 01 started successfully",
  "state": "GREEN",
  "system": [
    {
      "name": "msg_server",
      "description": "MessageServer",
      "dispstatus": "SAPControl-GREEN",
      "pid": 12345,
      "starttime": "2026 02 19 10:00:00",
      "elapsedtime": "0:05:30",
      "textstatus": "Running"
    }
  ]
}
```

---

## 6. Dépendances externes

| Bibliothèque | Usage | Déjà requise par le projet |
|--------------|-------|----------------------------|
| `suds` (suds-community) | Client SOAP pour sapcontrol | ✅ Oui — utilisée par `sap_control_exec` et `sap_hostctrl_exec` |

Aucune nouvelle dépendance n'est introduite.

---

## 7. Tests unitaires (à prévoir)

| Fichier | Couverture |
|---------|-----------|
| `tests/unit/plugins/module_utils/test_sap_soap.py` | Classes de connexion, `recursive_dict()` |
| `tests/unit/plugins/module_utils/test_sapcontrol.py` | `SAPControl` : connexion, get_process_list, start, stop |
| `tests/unit/plugins/modules/test_sap_system_state.py` | Idempotence, wait loop, gestion des erreurs |

Pattern de test : suivre le pattern existant des fichiers `test_sap_control_exec.py` et `test_sap_hostctrl_exec.py` (mock suds, `AnsibleModule`).

---

## 8. Ordre d'implémentation

| Étape | Fichier | Prérequis | Livrable |
|-------|---------|-----------|----------|
| 1 | `module_utils/sap_soap.py` | — | Classes SOAP testables unitairement |
| 2 | `module_utils/sapcontrol.py` | Étape 1 | Client sapcontrol testable |
| 3 | `modules/sap_system_state.py` | Étapes 1 + 2 | Module fonctionnel |
| 4 | Tests unitaires | Étapes 1-3 | Couverture complète |
| 5 | Documentation (`DOCUMENTATION`, `EXAMPLES`, `RETURN`) | Étape 3 | Module documenté |

---

## 9. Fichiers existants NON modifiés

Les fichiers suivants ne seront **en aucun cas modifiés** :

- `plugins/modules/sap_control_exec.py`
- `plugins/modules/sap_hostctrl_exec.py`
- `plugins/modules/sap_system_facts.py`
- `plugins/module_utils/pyrfc_handler.py`
- Tous les autres fichiers existants

---

## 10. Évolutions futures (hors scope)

- **Action plugin** : orchestration côté contrôleur (ordre des instances, parallélisme)
- **Refactoring** : migration de `sap_control_exec.py` et `sap_hostctrl_exec.py` vers le `module_utils` commun (PR séparée, accord des mainteneurs requis)
- **Doc fragment** : `sap_soap_connection` pour les options communes (hostname, username, password)
