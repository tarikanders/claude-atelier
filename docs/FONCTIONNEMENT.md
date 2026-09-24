# Fonctionnement détaillé

## Pourquoi déléguer à `dsk` plutôt qu'à des sous-agents Claude

Un sous-agent Claude (`Agent`) consomme ton quota à **chaque tour**, et tout ce qu'il
a lu est renvoyé au tour suivant : le coût croît vite avec la longueur de la tâche.
Sur une installation mesurée, les sous-agents de fouille représentaient l'essentiel de
la consommation.

`dsk` est le binaire `claude` lui-même, pointé sur l'API compatible Anthropic de
DeepSeek : mêmes outils (Read, Edit, Bash...), même boucle agentique, **zéro token de
quota Anthropic**, environ un centime par tâche. Seule sa dernière ligne remonte dans
le contexte d'Opus. Opus garde ce qui demande du jugement : découper, briefer, relire
le diff, trancher.

La contrepartie : `dsk` ne sait rien de ton projet. D'où la règle la plus importante
du workflow, **un brief complet** (but, chemins, fichiers modifiables, fichier
exemplaire, commande de test, interdits, format de sortie).

## Le cycle d'une demande

1. **Contexte** : le hook `SessionStart` a déjà injecté le bloc `[Atelier]`.
2. **Compréhension** : Opus corrige la transcription vocale, reformule le besoin réel
   si la demande est non triviale, ne pose une question que si elle est bloquante.
3. **Taille** :
   - broutille (un one-liner, une question) → Opus répond directement ;
   - tâche à un lot → `dskf` éclaire si besoin, `dsk` bâtit, une autre invocation `dsk`
     relit, Opus relit le diff ;
   - feature de plusieurs fichiers → document de pilotage validé par toi, puis `team`.
4. **Preuve** : tests lancés, sortie lue. Un « c'est fait » sans sortie de test ne
   compte pas.
5. **Fin** : section « À noter » si un risque, une décision ou une suite mérite ton
   attention.

## L'équipe `team`

```bash
team start <run>                       # crée .team/<run>/CONTEXTE.md (ignoré par git)
team wave <run> builder:lot-a.md testeur:tests.md   # agents en parallèle
team run <run> reviewer brief-review.md             # revue croisée
team status <run>
```

Chaque brief commence par un front matter :

```markdown
paths: src/panier.ts, src/panier.test.ts
risk: normal
```

Avant de lancer le moindre agent, `valide.py` **refuse la vague** si deux écrivains
visent le même fichier (casse comprise, dossiers parents compris), si un écrivain n'a
pas de `paths:`, si un chemin touche une zone sensible (auth, paiement, migration,
`.env`, `.sql`, clés) sans `risk: sensitive`, si un placeholder traîne ou si
`CONTEXTE.md` est vide.

Rôles fournis (`team/roles/`) : `eclaireur` et `chercheur` (petit modèle, lecture
seule), `builder`, `testeur`, `reviewer` (modèle pro). Chaque agent écrit son rapport
dans `.team/<run>/<role>.md` et termine par une ligne `STATUT: OK|PARTIEL|BLOQUE - ...`,
seule chose que lit Opus.

**Mode plan** pour les gros chantiers : un `PLAN.json` écrit par Opus découpe le
travail en phases et tâches (`team plan`, `team phase`, `team accept`, `team fix`,
`team close`). Une tâche ne passe en revue que si son agent a rendu `STATUT: OK`, et
n'est acceptée qu'après relecture.

## Les garde-fous

| Niveau | Mécanisme |
|---|---|
| Règles | WORKFLOW.md §7 : lire avant d'éditer, preuve par les tests, pas de commit/push/déploiement sans demande, aucun secret |
| Hook Bash | refus : `rm -rf` sur `/` ou `~`, push forcé sur main/master, identité git imposée, écriture disque brute. Confirmation : `reset --hard`, `clean -f`, `branch -D`, push forcé ailleurs, `curl \| sh` |
| Équipe | validateur de vague (fichiers disjoints, zones sensibles déclarées), builder distinct du reviewer, verdict final par Opus |
| Sous-agents Claude | limités à trois cas : zone sensible, escalade, architecture |

Le garde-fou d'identité git vient d'un vrai incident : un agent imposait une adresse de
commit non rattachée au compte GitHub, et Vercel refusait le déploiement sans le
moindre log de build.

## Ce que le hook de contexte détecte

Racine git, branche, nombre de fichiers modifiés ; stack via les manifestes (Node et
son gestionnaire, frameworks courants, Python, Go, Rust, JVM, Ruby, PHP, Flutter,
Swift, Makefile) et commandes de test associées ; présence d'un `CLAUDE.md` de projet ;
fichiers `.md` en majuscules à la racine (documents de pilotage) ; runs `team` en
cours. Aucun appel réseau, aucune écriture, moins d'une seconde. En cas d'erreur, il
rend un bloc minimal : il ne bloque jamais le démarrage.

## Limites connues

- Les ids de modèles DeepSeek évoluent : si `dsk` répond « model not found », mets à
  jour `DSK_PRO_MODEL` / `DSK_SMALL_MODEL` dans `~/.claude/atelier.env`.
- À solde nul, `dsk` échoue **sans bascule automatique** : c'est voulu, Claude te le
  signale au lieu de brûler ton quota en silence.
- Un seul agent par rôle et par vague (les rapports sont nommés par rôle).
