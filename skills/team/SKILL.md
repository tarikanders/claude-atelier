---
name: team
description: Monte une equipe d'agents specialises (eclaireur, builder, reviewer, testeur, chercheur) sur DeepSeek et la pilote en parallele avec revue croisee. A utiliser quand une tache depasse le one-liner - feature a plusieurs fichiers, refactor, audit, investigation - et qu'on veut du travail parallele sans bruler de quota. Declenche par /team.
---

# team : piloter l'equipe

> Indisponible en mode solo (pas de cle DeepSeek) : le bloc [Atelier] du demarrage
> te dit si c'est le cas. Commandes `team`, `dsk`, `dskf` : dans `~/.claude/atelier/bin/`.

Tu es le MANAGER. Tu ne codes pas, tu ne fouilles pas. Tu decoupes, tu brieffes, tu lis
les rapports, **tu relis les diffs toi-meme**, tu tranches.

Les executants sont des `dsk` (DeepSeek) : 0 token de quota Anthropic, ~$0,01 la tache.
Ils tournent en parallele et se parlent par fichiers, jamais par ton contexte.

## Le cycle

### 1. Cadrer : avant de lancer quoi que ce soit

```bash
team start <nom-du-run>      # -> .team/<nom-du-run>/, affiche le chemin
```

Puis **ecris `CONTEXTE.md`**. C'est l'etape qui decide de tout le reste. `dsk` n'a ni
CLAUDE.md, ni la memoire projet, ni les skills, ni cette conversation. Tout ce qui
compte doit y etre :

- le depot et le chemin exact du code concerne
- la stack et les conventions a respecter
- **la commande de test/lint a lancer**, litteralement
- ce qu'on sait deja (pour que personne ne le redecouvre)
- ce qui est explicitement hors perimetre

Un CONTEXTE.md vague donne cinq rapports vagues. C'est la seule facon dont ce
dispositif echoue.

### 2. Eclairer

Un `eclaireur` seul d'abord, si tu ne sais pas encore quels fichiers sont concernes.
Son rapport te donne la matiere pour decouper. Saute cette etape si tu connais deja
le terrain.

### 3. Decouper en chunks

Un brief = un fichier markdown = une unite de travail. Il **commence** par son front
matter, puis contient : **objectif en une phrase**, **ce qu'il doit verifier**,
**ce qu'il ne doit pas faire**, **critere "fait quand"** binaire.

```markdown
paths: src/panier.ts, src/panier.test.ts
risk: normal

# Objectif
...
```

- `paths:` : les fichiers ou dossiers que l'agent a le droit de toucher. **Obligatoire
  pour `builder` et `testeur`** ; inutile pour `eclaireur`, `chercheur` et `reviewer`,
  qui ne font que lire. Chemins relatifs au depot, sans glob, sans `..`.
- `risk:` : `normal` par defaut. Mets `sensitive` si les chemins touchent l'auth, un
  paiement, une migration, un `.env` ou un `.sql`.

Regle dure : **deux briefs ne touchent jamais les memes fichiers.** Les lectures en
parallele, oui. Les ecritures concurrentes sur un meme fichier, jamais.

Cette regle n'est plus a ta charge : `wave` et `run` lancent `valide.py` **avant** de
demarrer le moindre agent, et refusent la vague : rien n'est lance : en cas de
chevauchement de `paths`, de `paths:` manquant sur un ecrivain, de zone sensible non
declaree, de placeholder oublie, de `CONTEXTE.md` vide ou de role en double. Lis le
`REFUS:`, corrige le brief, relance. N'utilise jamais `TEAM_NO_VALIDATION=1`.

### 4. La vague

**Un seul agent par role par vague** : `cmd_run` ecrit toujours dans `.team/<run>/<role>.md`,
donc deux `builder` dans la meme vague s'ecraseraient mutuellement rapport et statut. Pour
deux lots de code en parallele, lance deux vagues, ou repartis sur `builder` et `testeur`.

```bash
team wave <run> builder:.team/<run>/lot-a.md testeur:.team/<run>/tests.md
```

Tout part en meme temps, la commande rend la main quand tout est fini, et
n'affiche qu'une ligne STATUT par agent. Les rapports detailles restent sur disque.

### 5. Revue croisee : le point qui compte

**Jamais le meme agent pour construire et valider.** Une invocation `reviewer` est
distincte du `builder`, meme si c'est le meme modele derriere.

```bash
git diff > .team/<run>/diff.patch
team run <run> reviewer .team/<run>/brief-review.md
```

Le brief de review pointe vers `diff.patch` et vers le rapport du builder. Les agents
peuvent lire les fichiers des autres dans le dossier du run : c'est comme ca qu'ils
se signalent les incoherences.

### 6. Verdict : c'est toi, et personne d'autre

La passe `reviewer` de DeepSeek est un **filtre**, pas une validation. Tu lis le diff
toi-meme avant d'integrer. C'est la contrepartie de tout le reste : si tu delegues
ca aussi, plus rien ne garantit la qualite.

## Ce que tu lis, et ce que tu ne lis pas

| Tu lis | Tu ne lis pas |
|---|---|
| les lignes STATUT | les `.log` (sauf en cas d'echec) |
| les rapports `<role>.md` | le code que les agents ont lu |
| **le diff, integralement** | les fichiers explores par l'eclaireur |

Si tu te surprends a lire un dump de code dans ton contexte, le dispositif fuit.

## Quand escalader vers un agent Claude (quota)

Trois cas, et trois seulement :

1. **Zone sensible** : le diff touche auth, paiement, migration SQL, secrets, entree
   utilisateur non filtree -> un sous-agent relecteur securite ou base de donnees,
   **en plus** de la passe dsk.
2. **Escalade** : le reviewer dsk remonte un CRITICAL/HIGH que tu ne peux pas trancher
   sur le diff -> sous-agent relecteur sur ce point precis.
3. **Architecture** : concevoir la structure d'une feature standard/large ->
   un sous-agent architecte (Plan). C'est une decision, pas de l'execution.

**UI/design : toujours cote Claude.** `dsk` n'a pas les skills de design. Tu
charges le skill toi-meme, tu arretes la direction, puis tu ecris les decisions
**explicitement** dans le brief du builder. Il ne les devinera pas.

Un diff anodin (renommage, CSS, copie, ajout de test) ne declenche aucun sous-agent Claude.

## Diagnostic

- `team status <run>` : l'etat de chaque agent
- Un STATUT `BLOQUE - AUTH ou SOLDE` -> le solde DeepSeek est vide. `dsksolde` pour
  verifier. **Dis-le a l'utilisateur** au lieu de repartir en silence sur des agents Claude.
- Un STATUT `?` -> l'agent n'a pas respecte le contrat de sortie. Lis son `.log`.
- Ne crois jamais un "c'est fait" : c'est la sortie de test dans le rapport qui fait foi.
