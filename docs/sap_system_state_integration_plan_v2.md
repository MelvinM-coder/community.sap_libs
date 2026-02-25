# Plan d’intégration détaillé — Module `sap_system_state` (v2)

## 1. Objectif
Créer un module Ansible idempotent pour démarrer/arrêter une instance SAP via l’API SOAP sapcontrol, en s’appuyant sur le module_utils factorisé, avec validation étape par étape.

---

## 2. Étapes d’intégration

### Étape 1 : Spécification
- Définir précisément les paramètres du module (`argument_spec`)
- Définir les valeurs de retour (`changed`, `msg`, `state`, `system`)
- Définir la logique d’idempotence (matrice d’états)
- Définir les cas d’erreur à gérer explicitement

### Étape 2 : Squelette du module
- Créer le fichier `plugins/modules/sap_system_state.py` avec :
  - Header, imports, docstring Ansible (`DOCUMENTATION`, `EXAMPLES`, `RETURN`)
  - Définition de l’argument_spec
  - Structure du main()

### Étape 3 : Connexion SOAP
- Importer et utiliser `connection_sapcontrol` du module_utils
- Gérer la connexion locale (socket) ou distante (HTTP) selon les paramètres

### Étape 4 : Lecture de l’état courant
- Appeler `GetProcessList` via `connection_sapcontrol`
- Analyser les statuts pour déterminer l’état global (GREEN, YELLOW, GRAY, RED)
- Implémenter la logique d’idempotence (pas d’action si déjà dans l’état cible)

### Étape 5 : Actions Start/Stop
- Appeler la fonction SOAP `Start` ou `Stop` selon l’état cible
- Gérer les erreurs de retour SAP (exceptions, statuts inattendus)

### Étape 6 : Wait loop
- Si `wait: true`, boucler avec `poll_interval` jusqu’à atteindre l’état cible ou timeout
- Gérer le cas où l’état reste YELLOW ou autre état non final

### Étape 7 : Retour et reporting
- Retourner un dictionnaire clair avec tous les champs attendus (`changed`, `msg`, `state`, `system`)
- Gérer les cas d’erreur avec un message explicite

### Étape 8 : Tests unitaires
- Créer des tests pour chaque scénario (déjà démarré, déjà arrêté, start, stop, timeout, erreur SAP)
- Mocker la couche SOAP pour tester la logique métier

### Étape 9 : Documentation
- Compléter la section `DOCUMENTATION` avec tous les paramètres, exemples, et valeurs de retour
- Ajouter des exemples réalistes

### Étape 10 : Validation finale
- Revue croisée (peer review)
- Tests sur un vrai environnement SAP si possible
- Vérification de la compatibilité ascendante avec les playbooks existants

---

## 3. Points de validation à chaque étape
- Validation de la spec et de la logique métier avant de coder
- Validation du squelette et des imports
- Validation de la connexion SOAP (local/distante)
- Validation de la logique d’état et d’idempotence
- Validation des actions Start/Stop
- Validation du wait loop et des timeouts
- Validation du reporting et des erreurs
- Validation des tests unitaires
- Validation de la documentation

---

## 4. Checklist de robustesse
- [ ] Respect de l’idempotence stricte
- [ ] Gestion explicite des erreurs SAP et réseau
- [ ] Timeout et polling configurables
- [ ] Documentation complète et exemples réalistes
- [ ] Tests unitaires couvrant tous les cas critiques
- [ ] Code relu et validé étape par étape

---

## 5. Évolutions futures (hors scope)
- Refactoring des modules existants pour utiliser le module_utils
- Ajout d’un action plugin pour l’orchestration avancée
- Factorisation d’un doc fragment pour les options de connexion SOAP
