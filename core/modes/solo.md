## Règles du mode SOLO (actif : pas de DeepSeek configuré)

`dsk`, `dskf` et `team` sont **indisponibles**. N'essaie pas de les appeler.
Ce bloc remplace les sections 2 à 4 de WORKFLOW.md ; le reste s'applique.

- **Tu fais l'ouvrage** : lecture, recherche ciblée, écriture, débogage, relecture.
- **Gros balayages** (plus de ~30 fichiers, inventaire d'un dépôt entier, longue doc
  externe) → un sous-agent `Explore` (lecture seule) qui rend une conclusion courte, pas
  des dumps. C'est ce qui protège ton contexte.
- **Construire puis réfuter** reste obligatoire pour un diff non trivial : relis ton diff
  comme s'il venait d'un autre, relance les tests. Sur une zone sensible (auth, paiement,
  migration, secrets), lance un sous-agent relecteur dédié.
- Pas de fan-out : un sous-agent à la fois, et seulement quand il épargne vraiment ton
  contexte.

À la première réponse substantielle de la session, signale en une ligne que le mode
solo est actif et que `atelier key` permet d'ajouter une clé DeepSeek pour économiser
le quota (ne le répète pas ensuite).
