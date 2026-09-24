# <NOM DE LA FEATURE>

> Document de pilotage. Rien n'est implémenté avant validation de ce fichier.
> Un lot n'est coché que quand ses tests passent **et** que sa recette a été rejouée.

## 1. Le besoin réel, reformulé

Ce qui a été demandé : ...
Ce qui est réellement visé : ...
(Si l'ordre des lots ne suit pas l'ordre de la demande, dire pourquoi.)

## 2. Décisions tranchées

| Date | Décision | Pourquoi | Rejeté |
|---|---|---|---|
| AAAA-MM-JJ | ... | ... | ... |

## 3. Les lots

### Lot A : <titre>

- **Objectif** : une phrase.
- **Livrables** : `chemin/fichier.ts` (fonction `x`), ...
- **Tests**

  | Test | Attendu |
  |---|---|
  | ... | ... |

- **Recette manuelle** : le parcours à refaire à la main.
- **Fait quand** : critère binaire.
- [ ] tests verts  - [ ] recette rejouée

## 4. Ordre d'exécution

A → B ; C en parallèle de B (fichiers disjoints).

## 5. Pièges connus

- Ce qui a été mesuré ou découvert pendant le cadrage et qu'il ne faut pas redécouvrir.
