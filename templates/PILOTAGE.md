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

## 6. Reprise

<!-- Écrite avant un /clear, à un point d'arrêt propre (étape finie, tests lancés).
     Le hook de démarrage la réinjecte dans la session suivante. Une seule question
     décide chaque ligne : la prochaine session se tromperait-elle sans ça ?
     Vider la section quand la feature est livrée (ce qui reste vrai part en §5). -->

- **Maintenant** : ... (où en est le travail à cette seconde ; réécrit en entier à chaque reprise)
- **Appris** : ... (ce qu'aucun fichier ne dit ; on ajoute, on garde tant que c'est vrai)
- **Ouvert** : ... (décisions à moitié prises, et l'option vers laquelle on penchait)
- **Touchés** : ... (fichiers modifiés hors des livrables des lots)

```ouvrir
chemin/fichier.ts:20-45   # pourquoi l'ouvrir
```
