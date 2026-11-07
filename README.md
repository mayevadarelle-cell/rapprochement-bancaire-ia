# Rapprochement bancaire assisté par IA

Projet personnel de Darelle SIDJE (finance d'entreprise, contrôle de gestion).
**Toutes les données sont fictives** : l'entreprise « Atelier Démo SAS » est inventée, la graine aléatoire est fixe. Le projet démontre une méthode, pas des performances en conditions réelles.

## Problème
Chaque mois, le comptable compare le relevé bancaire au compte 512 de la comptabilité, ligne à ligne. La majeure partie est évidente, le reste ne l'est pas : décalages de date, libellés différents, remises de chèques qui regroupent plusieurs écritures, frais qui n'existent qu'à la banque, chèques en transit, erreurs de saisie.

## Principe : les règles d'abord, l'IA ensuite, l'humain en dernier
1. **Règles déterministes** (montant identique, date à moins de 5 jours, ressemblance des libellés, référence de pièce) : explicables, testées, sans IA.
   - Un rapprochement est **automatique** seulement si le meilleur candidat devance nettement les autres.
   - Une ligne bancaire qui regroupe plusieurs écritures (remise de chèques) est proposée **à valider**, jamais automatique.
   - Quand les libellés ne permettent pas de départager deux candidats, la ligne reste **non rapprochée** plutôt que d'être attribuée au hasard.
2. **Étape IA optionnelle** sur les lignes restantes uniquement : le modèle reçoit une ligne et 5 écritures candidates, répond en JSON (décision, écriture, justification, confiance).
   - Sa réponse est **validée** : une écriture qui n'est pas parmi les candidats est rejetée.
   - Ses propositions sont **toujours à valider** par un humain.
   - Les libellés bancaires sont des données non fiables : ils sont balisés et le modèle a pour consigne de ne jamais les suivre comme des instructions.
   - La clé d'API se lit dans `ANTHROPIC_API_KEY`, jamais dans le code.
3. **Rapport Excel** pour le comptable, avec un **état de rapprochement** : la différence entre le solde du relevé et celui de la comptabilité doit être entièrement expliquée (résidu nul).

## Résultats sur le jeu de données fictif
37 lignes de relevé, 41 écritures, 31 rapprochements attendus (vérité terrain connue du générateur, jamais lue par le moteur).

| | Résultat |
|---|---|
| Rapprochements automatiques | 28, **tous conformes** à la vérité terrain |
| Regroupements d'écritures (remises de chèques) | 3 proposés à valider, 3 corrects |
| Suggestion de l'étape IA (mode simulé) | 1 : chiffres inversés (1 540,00 € au relevé, 1 450,00 € en comptabilité), à valider |
| Restent non rapprochés | 5 lignes du relevé (3 frais bancaires, 2 « VIR DIVERS » indiscernables) et 5 écritures (3 en transit, 2 indiscernables) |
| Différence de solde expliquée | −649,71 € expliqués en totalité, résidu 0,00 € |

À lire avec prudence : le jeu de données et le moteur ont le même auteur. Ce résultat montre que la méthode fait ce qu'elle annonce sur des cas bien identifiés, pas qu'elle réussirait sur de vraies écritures.

## Utiliser
```bash
pip install -r requirements.txt
python generate_data.py                 # génère data/ (relevé, compte 512, vérité terrain)
python rapprochement.py                 # règles seules
python rapprochement.py --ia simule     # + étape IA simulée, sans réseau
python -m pytest tests/ -v
```
Le rapport est écrit dans `rapport/rapprochement.xlsx` (onglets : Synthèse, Rapprochés, À valider, Relevé non rapproché, Compta non rapprochée).

### Avec Claude pour de vrai
```bash
pip install anthropic
export ANTHROPIC_API_KEY=...            # ta clé, jamais dans le dépôt
python rapprochement.py --ia claude
```
Le modèle se règle avec `MODELE_CLAUDE` (par défaut `claude-sonnet-5-5`). **N'envoie jamais de vraies écritures comptables à une API externe sans autorisation** de l'entreprise concernée : ce dépôt n'utilise que des données fictives. Les tests de l'étape Claude utilisent un faux client ; l'appel réel n'est pas exécuté par les tests.

## Contenu
| Fichier | Rôle |
|---|---|
| `generate_data.py` | Génère les données fictives et la vérité terrain |
| `rapprochement.py` | Règles, regroupements, état de rapprochement, évaluation, ligne de commande |
| `ia_suggestions.py` | Étape IA : consigne, message balisé, validation de la réponse, mode simulé |
| `rapport_xlsx.py` | Rapport Excel |
| `tests/test_rapprochement.py` | 27 tests : règles, regroupements, validation des réponses de l'IA, jeu complet, rapport |

## Limites
- Données synthétiques et moteur réglé sur elles : une validation sur des données réelles anonymisées serait nécessaire.
- Un seul compte bancaire, une seule devise, un seul mois ; pas de gestion des rejets de prélèvement ni des écritures de régularisation.
- La recherche de regroupements est bornée (14 candidats, 4 écritures maximum).
- L'appel réel à Claude n'est pas couvert par les tests automatiques.
