## Règles du mode ATELIER (actif)

Ce bloc **remplace** les sections 2 à 4 de WORKFLOW.md là où elles se contredisent.
Le reste (compréhension, design, pilotage, garde-fous, fin de réponse) s'applique.

**Principe : tu fais l'ouvrage. `dsk` ne reçoit que les corvées.** Ce mode optimise la
qualité et le nombre d'allers-retours, au prix de plus de quota Anthropic.

**Toi-même :**
- Lire : jusqu'à ~15 fichiers, ou ~1500 lignes par fichier, sans déléguer.
- Chercher : librement tant que la recherche reste ciblée (~8 opérations par question).
- Écrire : toute logique, structure, UI, correction, tout refactor de moins de ~10 fichiers.
- Déboguer directement, sans passer d'abord par `dsk`.
- Relire ton propre diff avec un regard neuf : relis les fichiers modifiés, relance les tests.
  Pas de 1ʳᵉ passe `dsk` obligatoire.
- Garde-fous inchangés : lire avant d'éditer, tests lancés et sortie lue avant de dire « c'est fait ».

**Encore sur `dsk` / `dskf`, et seulement ça :**

| Corvée | Qui |
|---|---|
| balayage massif : plus de 30 fichiers, tout un dépôt, inventaire exhaustif | `dskf` |
| résumer une longue doc externe, un gros log, un dump de plus de 2000 lignes | `dskf` |
| édition mécanique répétée sur plus de 10 fichiers, renommage de masse | `dsk`, puis tu relis le diff |
| génération de volume sans intelligence : fixtures, données de test, traductions | `dsk` |
| seconde opinion ponctuelle sur un diff risqué | `dsk` (optionnel) |

Règle de bascule : si tu hésites entre faire et déléguer, **fais-le**.
Sous-agents Claude : toujours limités aux trois cas de la section 4. Mode atelier ne veut
pas dire plus de sous-agents, il veut dire que **la session principale** travaille plus.
Pas d'équipe `team` sauf demande explicite.
