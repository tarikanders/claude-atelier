# claude-atelier

**Un workflow Claude Code prêt à l'emploi : Claude comprend ton projet tout seul,
délègue le gros du travail à DeepSeek pour épargner ton quota, relit chaque diff
et bloque les commandes irréversibles.** Rien à activer : pas de slash-commande, pas de
skill à charger. Tu lances `claude` (ou `c`) dans un projet, et tout est en place.

```bash
git clone https://github.com/tarikanders/claude-atelier.git
cd claude-atelier && ./install.sh
```

---

## Ce que ça change, concrètement

| Sans | Avec l'Atelier |
|---|---|
| Tu réexpliques le projet à chaque session | Au démarrage, Claude reçoit le dépôt, la branche, la stack, la commande de test et les documents de pilotage en cours |
| Un prompt dicté à la voix est pris au pied de la lettre | Claude corrige les erreurs de transcription et reformule le besoin réel avant d'agir |
| Tout brûle ton quota Claude | Recherche, lecture de masse et écriture de code partent sur `dsk` (Claude Code branché sur DeepSeek, ~0,01 $ la tâche). Opus garde les décisions et la relecture |
| « C'est fait » sans preuve | Règle dure : tests lancés et sortie lue avant d'annoncer quoi que ce soit, relecteur distinct du bâtisseur |
| Un agent lance `git push --force` ou `rm -rf ~` | Refusé par le garde-fou, y compris dans les agents DeepSeek |
| Une grosse feature part en vrille | Document de pilotage (lots, tests, recette manuelle) validé **avant** la première ligne de code |
| Réponse qui s'arrête au code | Section « À noter » en fin de tâche : risque repéré, décision prise à ta place, prochaine étape utile. Seulement quand ça vaut le coup |

## Les trois modes

| Mode | Lancement | Qui fait quoi | Quand |
|---|---|---|---|
| **normal** | `c` ou `claude` | DeepSeek cherche et écrit, Opus orchestre et relit chaque diff | par défaut si une clé DeepSeek est configurée. Le plus économe en quota |
| **atelier** | `co` | Opus fait l'ouvrage, DeepSeek ne prend que les corvées (balayages massifs, éditions répétitives, fixtures) | travail délicat, tu veux moins d'allers-retours. Consomme plus de quota |
| **solo** | automatique | Tout sur Claude, sous-agents légers pour les gros balayages | pas de clé DeepSeek. Fonctionne sans rien configurer |

Le mode est choisi tout seul (`auto`). Pour forcer : `CLAUDE_MODE=atelier claude`, ou
`atelier mode atelier` pour en faire le défaut.

## Installation

**Prérequis** : [Claude Code](https://docs.claude.com/claude-code), `git`, `python3`,
`curl`. macOS ou Linux (Windows : via WSL).

```bash
./install.sh                     # interactif : propose d'enregistrer la clé DeepSeek
./install.sh --yes               # sans question
./install.sh --key sk-xxxx       # avec la clé directement
./install.sh --skip-permissions  # c/co lancent Claude sans demander les permissions
./install.sh --uninstall         # retire tout, conserve la clé et les sauvegardes
```

L'installeur est **idempotent** (relance-le après chaque `git pull` pour mettre à jour)
et **sauvegarde** `settings.json` et `CLAUDE.md` dans `~/.claude/atelier-backups/`
avant d'y toucher. Il ne remplace rien : il ajoute un bloc balisé à ton `CLAUDE.md`,
fusionne ses hooks avec les tiens et ajoute un bloc à ton `.zshrc`/`.bashrc`.

**Clé DeepSeek** (recommandée) : crée-la sur
[platform.deepseek.com](https://platform.deepseek.com/api_keys), recharge quelques
dollars, puis `atelier key`. Elle est stockée dans `~/.claude/atelier.env` (droits 600),
jamais dans le dépôt. Sans clé, tout marche en mode solo.

Vérifier : `atelier doctor`.

## Au quotidien

```bash
cd mon-projet
c                     # et tu parles normalement
co                    # quand tu veux qu'Opus fasse le travail lui-même
atelier contexte      # ce que Claude voit en arrivant dans ce dossier
dsksolde              # solde DeepSeek (à zéro, dsk échoue et Claude te le dit)
dskstats              # la délégation a-t-elle vraiment lieu ? appels, échecs, dépense
```

Tu n'as pas à appeler `dsk` ni `team` toi-même : Claude le fait. Ils restent
disponibles si tu veux lancer un agent DeepSeek à la main (`dsk -p "..."`).

## Comment ça marche

```
 tu tapes `c` ─► Claude Code démarre
                 ├─ ~/.claude/CLAUDE.md importe atelier/WORKFLOW.md   (les règles)
                 └─ hook SessionStart ─► [Atelier] mode, DeepSeek, projet, stack,
                                         tests, docs de pilotage, règles du mode
 ta demande ───► Opus reformule, situe, découpe
                 ├─ chercher / lire en masse ──► dskf  (DeepSeek flash)
                 ├─ écrire le code ────────────► dsk   (DeepSeek pro, tests lancés)
                 ├─ plusieurs lots ────────────► team  (N agents en parallèle,
                 │                                      fichiers disjoints vérifiés)
                 ├─ 1re relecture ─────────────► dsk   (autre invocation que le bâtisseur)
                 └─ verdict final ─────────────► Opus relit le diff lui-même
 chaque commande Bash ─► hook bash_guard : refuse l'irréversible, demande pour le risqué
```

Détails : [docs/FONCTIONNEMENT.md](docs/FONCTIONNEMENT.md).

## Ce qui est installé

```
~/.claude/atelier/
  core/WORKFLOW.md        les règles (routage, seuils, garde-fous, fin de réponse)
  core/modes/             atelier.md, solo.md (injectés par le hook selon le mode)
  hooks/session_context.py  contexte projet au démarrage (aucun appel réseau, < 1 s)
  hooks/bash_guard.py     garde-fous Bash
  bin/                    dsk, dskf, dsksolde, dskstats, team, atelier
  team/                   moteur d'équipe : rôles, validateur de vague, plan par phases
  templates/              CLAUDE.projet.md, PILOTAGE.md
~/.claude/skills/team/    le skill que Claude charge seul pour piloter l'équipe
~/.claude/atelier.env     ta clé et tes réglages (privé)
~/.claude-dsk/            config isolée des agents DeepSeek (sans plugins ni mémoire)
```

## Personnaliser

- **Tes règles perso** : dans `~/.claude/CLAUDE.md`, **hors** du bloc balisé
  `claude-atelier` (le bloc est réécrit à chaque mise à jour). Ce que tu écris là prime.
- **Règles d'un projet** : un `CLAUDE.md` à la racine du projet. Claude propose d'en
  créer un (gabarit `templates/CLAUDE.projet.md`) quand il n'y en a pas.
- **Modèles DeepSeek** : `DSK_PRO_MODEL` et `DSK_SMALL_MODEL` dans `~/.claude/atelier.env`.
- **Couper un garde-fou ponctuellement** : `ATELIER_GUARD=off claude`.
- **Modifier le workflow lui-même** : forke le dépôt, édite `core/WORKFLOW.md`, relance
  `./install.sh`.

## Compléments conseillés (optionnels)

| Outil | Pourquoi |
|---|---|
| [rtk](https://github.com/rtk-ai/rtk) | compresse la sortie des commandes avant qu'elle n'entre dans le contexte : moins de tokens à chaque tour |
| plugin `ui-ux-pro-max` | direction de design : WORKFLOW.md le charge automatiquement avant toute UI s'il est installé |
| plugin ECC | des centaines de skills et d'agents. Puissant mais lourd (des dizaines de milliers de tokens par session) : à n'installer que si tu t'en sers |

## Sécurité : ce qu'il faut savoir

- Les agents `dsk` tournent **sans demander de permission** (sinon un agent headless se
  bloque). Le garde-fou Bash est installé dans leur config, mais ne lance `dsk` que dans
  des dépôts que tu maîtrises, idéalement versionnés avec git.
- Le code que `dsk` lit est envoyé à l'API DeepSeek. **Ne l'utilise pas sur du code
  soumis à confidentialité** (client, NDA) sans accord : passe en `atelier mode solo`.
- `--skip-permissions` est désactivé par défaut. Active-le en connaissance de cause.

## Tests

```bash
python3 -B -m unittest discover -s team -p 'test_*.py'   # moteur d'équipe (79 tests)
python3 -B -m unittest discover -s tests                 # hooks et installeur
```

## Licence

MIT. Inspiré par [ECC](https://github.com/affaan-m/ECC) et [rtk](https://github.com/rtk-ai/rtk).
