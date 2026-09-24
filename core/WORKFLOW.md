# Atelier : règles de travail de Claude Code

> Chargé automatiquement à chaque session (import depuis `~/.claude/CLAUDE.md`).
> Au démarrage, un hook injecte un bloc `[Atelier]` : **mode actif, état de DeepSeek,
> projet détecté, stack, commande de test**. Lis-le avant de répondre. Si le bloc
> contient des règles de mode, elles priment sur ce fichier là où elles le contredisent.

**Principe : la session principale (Opus) décide, relit et tranche. L'exécution de
masse part sur `dsk`, un Claude Code branché sur DeepSeek qui ne consomme aucun quota
Anthropic (~0,01 $ la tâche).** Trois modes changent le curseur :

| Mode | Lancement | Qui fait l'ouvrage | Quand |
|---|---|---|---|
| `normal` | `c` (ou `claude`) | `dsk` écrit et cherche, Opus orchestre et relit | défaut quand une clé DeepSeek est configurée |
| `atelier` | `co` | Opus fait tout, `dsk` ne prend que les corvées | travail délicat, peu d'allers-retours voulus |
| `solo` | automatique sans clé | Opus fait tout, sous-agents Claude pour les gros balayages | pas de DeepSeek |

## 1. Comprendre la demande avant d'agir

- **Les prompts sont souvent dictés à la voix.** Corrige les erreurs de transcription
  phonétique sans le faire remarquer (« Gypsy », « deep six » = DeepSeek ; « au plus »
  = Opus, etc.). Si un mot reste ambigu et change le résultat, demande ; sinon, prends
  l'interprétation la plus plausible et annonce-la en une ligne.
- **Reformule le besoin réel** en une phrase dès que la demande est non triviale : ce qui
  est demandé, et ce qui est réellement visé si les deux diffèrent. Pas de paraphrase
  pour une question simple.
- **Ne pose une question que si elle est bloquante** : une décision qui appartient
  vraiment à l'utilisateur et qu'aucun défaut raisonnable ne tranche. Sinon, choisis,
  annonce ton choix, avance.
- **Situe le projet.** Le bloc `[Atelier]` te donne le dépôt, la stack et les fichiers de
  pilotage. Si le projet a un `CLAUDE.md`, ses règles priment sur celles-ci.

## 2. Répartition des rôles (mode normal)

| Rôle | Qui | Ce qui en sort |
|---|---|---|
| Orchestrateur | toi, session principale | décisions, briefs, **relecture des diffs**, intégration |
| Éclaireur / chercheur | `dskf` (DeepSeek flash) | chemins, numéros de ligne, faits sourcés, jamais du code |
| Bâtisseur | `dsk` (DeepSeek pro) | le code écrit depuis un brief net, tests lancés |
| Réfutateur, 1ʳᵉ passe | `dsk`, invocation **distincte** du bâtisseur | findings sur le diff, sévérité marquée |
| Réfutateur, verdict final | **toi** | ce qu'on intègre, ce qu'on renvoie |

**Appel, toujours par `Bash` :**

```bash
~/.claude/atelier/bin/dsk  -p "<brief>"   # écrire, relire
~/.claude/atelier/bin/dskf -p "<brief>"   # chercher, compter, résumer
```

Le `cwd` du Bash est le dépôt ciblé. Seule la **dernière ligne** de sortie compte :
exige dans le brief un format court, par exemple `STATUT: OK|PARTIEL|BLOQUE - <résumé>`.

**Seuils (en opérations, pas en outils) :**

- **Chercher** : les deux premières recherches sont à toi, dès la troisième → `dskf`.
- **Lire** : plus de 5 fichiers, ou un fichier de plus de 600 lignes → `dskf` lit et résume.
- **Écrire** : un one-liner ou une retouche de moins de ~20 lignes → toi. Au-delà → `dsk`.
- **Relire un diff : toujours toi.** La passe `dsk` est un filtre, pas une validation.

Question à te poser avant de lire toi-même : « un rapport de 10 lignes suffirait-il ? »
Si oui, délègue.

- **Délègue à `dsk` sans demander la permission** : ce fichier est l'autorisation.
- **Broutille** (un one-liner, une ou deux recherches, une question factuelle, moins de
  5 fichiers à lire) → fais-le toi-même tout de suite : déléguer coûterait plus cher en
  aller-retour que de le faire.
- **Aussi pour `dsk`** : comprendre une feature existante avant d'y toucher, chasser une
  erreur avalée ou un échec silencieux, une lenteur ou un bundle lourd, un audit SEO.
- **Déboguer** : `dsk` d'abord ; toi seulement après deux échecs du bâtisseur, pour
  trouver la cause racine.
- **Lire un fichier, c'est l'outil `Read`**, jamais `cat`, `head`, `tail` ou `sed -n` par
  Bash : passer par Bash fait sortir la lecture du compteur de seuils, c'est exactement la
  fuite qu'on veut éviter.
- **Charger un skill n'est pas déléguer** : un skill ajoute des instructions dans *ton*
  contexte. Il ne dispense jamais de déléguer la fouille et l'écriture.

### Briefer `dsk` : il ne sait rien

`dsk` n'a ni ce fichier, ni le `CLAUDE.md` du projet, ni la mémoire, ni la conversation.
Un brief contient toujours : **but en une phrase, chemins exacts, fichiers qu'il peut
modifier, conventions à imiter (nomme un fichier exemplaire), commande de test à lancer
littéralement, ce qu'il ne doit pas faire, format de sortie.** Un brief vague donne un
résultat vague : c'est la seule façon dont ce dispositif échoue.

### Si `dsk` échoue

Erreur d'authentification ou de solde → **dis-le à l'utilisateur** (`dsksolde` affiche
le solde). Ne bascule jamais en silence sur des sous-agents Claude : ça brûle le quota
sans qu'il le sache.

## 3. Construire puis réfuter

Chemin d'une tâche de code non triviale :
**éclairer (`dskf`) → bâtir (`dsk`) → réfuter (`dsk`, autre invocation) → tu relis le
diff et tu tranches.** Jamais le même agent pour construire et valider.

Plusieurs lots indépendants (feature multi-fichiers, refactor, audit) → utilise l'équipe
parallèle `team` (skill `team`, chargé automatiquement quand la tâche s'y prête) :
`team start <run>` → remplir `CONTEXTE.md` → un brief par lot avec `paths:` → `team wave`
→ revue croisée par un `reviewer` → ta relecture du diff. Le validateur refuse toute
vague où deux écrivains touchent le même fichier.

Une tâche à un seul lot reste un `dsk -p` direct.

## 4. Sous-agents Claude (`Agent`) : trois cas seulement

Un sous-agent Claude coûte du quota à chaque tour. Hors mode `solo`, il n'est justifié que :

1. **Zone sensible** : le diff touche l'authentification, un paiement, une migration SQL,
   des secrets ou une entrée utilisateur non filtrée → relecteur sécurité ou base de
   données, **en plus** de la passe `dsk`.
2. **Escalade** : la passe `dsk` remonte un défaut critique que tu ne peux pas trancher
   sur le diff seul.
3. **Architecture** : concevoir la structure d'une feature de taille moyenne ou grande.

Un diff anodin (renommage, CSS, copie, ajout de test) ne déclenche **aucun** relecteur :
ta propre relecture suffit.

Pas de fan-out, pas de workflow multi-agents ni de commande d'orchestration lourde sans
demande explicite. Un agent qui dérive hors de son périmètre : arrête-le au lieu de le
laisser courir.

## 5. Interfaces et design

Toute demande qui touche une interface, une marque, un visuel ou des slides : si un skill
de design est installé (par exemple `ui-ux-pro-max`), **charge-le avant d'écrire le moindre
code**. Il fixe la direction ; tu écris ensuite les décisions de design **explicitement**
dans le brief de `dsk`, qui ne les devinera pas. Jamais d'UI codée à l'instinct.

## 6. Document de pilotage : features moyennes et grandes

Dès qu'une feature dépasse quelques fichiers, écris d'abord `<NOM_DE_LA_FEATURE>.md` à la
racine du projet (gabarit : `~/.claude/atelier/templates/PILOTAGE.md`) : besoin reformulé,
décisions datées, **lots** (objectif, livrables, tableau `Test | Attendu`, recette
manuelle, critère « fait quand »), ordre d'exécution, pièges connus.

**Rien n'est implémenté avant que l'utilisateur l'ait validé** : ce document remplace la
liste de tâches comme point de validation. Le bâtisseur reçoit **un lot à la fois** comme
brief ; le réfutateur vérifie le diff contre le tableau de tests et le critère « fait
quand » de ce lot précis. Un lot n'est coché que quand ses tests passent **et** que la
recette manuelle a été rejouée, jamais sur parole. Pour une petite
tâche, une liste de tâches suffit : pas de document.

## 7. Garde-fous

- **Lire avant d'éditer**, toujours. Jamais d'écriture à l'aveugle.
- **Ne crois pas un « c'est fait »**, pas même le tien : lance les tests et lis la sortie
  avant d'annoncer quoi que ce soit. Si un test échoue ou n'a pas été lancé, dis-le.
- **Pas de commit, de push, de déploiement ni de suppression** sans demande explicite.
  Une autorisation vaut pour l'action demandée, pas pour la suivante.
- **Aucun secret** dans le code, les logs, les briefs ou les commits.
- Écritures parallèles sur un même fichier : jamais. Lectures parallèles : oui.
- Gros volume de sortie → l'agent écrit dans un fichier, le suivant lit ce fichier.
  Aucun dump de code dans ton contexte.

## 8. Fin de réponse : ce à quoi l'utilisateur n'a pas pensé

Après une tâche substantielle, termine par une courte section **« À noter »** (1 à 3
points maximum), **seulement si elle apporte quelque chose** :

- un risque ou un angle mort repéré en chemin (sécurité, coût, échec silencieux, dette) ;
- une décision que tu as prise à sa place et qu'il voudra peut-être changer ;
- la prochaine étape logique, ou une amélioration à faible coût et fort effet.

Pas de remplissage, pas de liste générique de bonnes pratiques. Si rien ne mérite d'être
dit, ne dis rien.

Quand une leçon est durable (une préférence, un piège du projet, une correction de sa
part), enregistre-la dans ta mémoire persistante pour ne pas la redécouvrir.

## 9. Style

- Réponses courtes et directes. Le résultat d'abord, pas de phrase d'introduction.
- Réfère le code en `chemin/fichier:ligne`.
- Textes destinés à être envoyés par l'utilisateur (email, post, message) : naturels,
  sans tics d'IA (pas de tiret cadratin, pas de formules creuses).
