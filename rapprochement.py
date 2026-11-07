#!/usr/bin/env python3
"""Rapprochement bancaire : relevé bancaire contre compte 512 (données fictives dans data/).

Le moteur applique des règles déterministes, explicables et testées. L'IA n'intervient qu'ensuite, sur les lignes
restantes, et ses propositions restent « à valider » (voir ia_suggestions.py).

Statuts d'un rapprochement :
  auto       règle sûre : montant identique, date proche, et un candidat clairement meilleur que les autres
  a_valider  règle plausible ou proposition de l'IA : un humain doit confirmer
Les lignes sans rapprochement sont listées comme « non rapprochées » (éléments en transit, frais, erreurs).

Usage :
    python rapprochement.py [--ia off|simule|claude]
"""
import argparse
import csv
import itertools
import json
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Set, Tuple

HERE: str = os.path.dirname(os.path.abspath(__file__))
FENETRE_JOURS: int = 5          # écart de date toléré entre la banque et la comptabilité
SEUIL_SCORE: float = 0.25       # score minimal pour accepter une paire parmi plusieurs candidats
MARGE_MINI: float = 0.15        # avance minimale sur le meilleur concurrent pour valider sans humain
FENETRE_REGROUPEMENT_JOURS: int = 10  # des chèques reçus sur plusieurs jours sont remis ensemble à la banque
TAILLE_GROUPE_MAX: int = 4      # nombre maximal d'écritures regroupées sur une ligne bancaire
CANDIDATS_GROUPE_MAX: int = 14  # borne de la recherche de regroupements


@dataclass(frozen=True)
class Operation:
    id: str
    date: date
    libelle: str
    montant: int          # en centimes ; encaissement > 0, décaissement < 0
    piece: str = ""


@dataclass
class Rapprochement:
    ids_banque: Tuple[str, ...]
    ids_compta: Tuple[str, ...]
    regle: str
    score: float
    statut: str           # "auto" ou "a_valider"
    justification: str = ""


def en_centimes(texte: str) -> int:
    """Convertit « 1 234,56 » ou « -1234.56 » en centimes, sans passer par les flottants."""
    propre = texte.replace(" ", "").replace(" ", "").replace(",", ".")
    return int((Decimal(propre) * 100).to_integral_value())


def normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", sans_accents.lower()).strip()


MOTS_GENERIQUES: Set[str] = {"vir", "sepa", "prlv", "reglement", "paiement", "cheque", "chq", "fac", "ach", "facture",
                             "virement", "prelevement", "remise", "de", "du", "la", "le", "des", "et", "recu", "emis"}


def utiles(texte: str) -> str:
    """Libellé normalisé sans mots génériques ni références chiffrées : il ne reste que le nom du tiers."""
    return " ".join(m for m in normaliser(texte).split() if m not in MOTS_GENERIQUES and not any(c.isdigit() for c in m))


def similarite(a: str, b: str) -> float:
    """Ressemblance de deux libellés entre 0 et 1 : le meilleur de la proximité de texte et des mots communs."""
    na, nb = utiles(a), utiles(b)
    if not na or not nb:
        return 0.0
    mots_a, mots_b = set(na.split()), set(nb.split())
    jaccard = len(mots_a & mots_b) / len(mots_a | mots_b)
    proximite = SequenceMatcher(None, na, nb).ratio()
    return max(proximite if proximite >= 0.6 else 0.0, jaccard)   # en dessous de 0,6, la ressemblance de texte n'est que du bruit


def piece_dans_libelle(piece: str, libelle: str) -> bool:
    cle = re.sub(r"[^a-z0-9]", "", piece.lower())
    return bool(cle) and cle in re.sub(r"[^a-z0-9]", "", libelle.lower())


def score_paire(b: Operation, e: Operation) -> float:
    proximite = 1 - abs((b.date - e.date).days) / (FENETRE_JOURS + 1)
    reference = 1.0 if piece_dans_libelle(e.piece, b.libelle) else 0.0
    return round(0.55 * similarite(b.libelle, e.libelle) + 0.30 * reference + 0.15 * proximite, 4)


def lire_operations(chemin: str, avec_piece: bool) -> List[Operation]:
    with open(chemin, newline="", encoding="utf-8") as fichier:
        return [Operation(r["id"], date.fromisoformat(r["date"]), r["libelle"], en_centimes(r["montant"]),
                          r.get("piece", "") if avec_piece else "") for r in csv.DictReader(fichier)]


def apparier_un_pour_un(banque: Sequence[Operation], compta: Sequence[Operation]) -> List[Rapprochement]:
    """Paires de même montant et de dates proches, attribuées une seule fois, de la meilleure à la moins bonne."""
    paires = [(b, e, score_paire(b, e)) for b in banque for e in compta
              if b.montant == e.montant and abs((b.date - e.date).days) <= FENETRE_JOURS]
    par_banque: Dict[str, List[float]] = defaultdict(list)
    par_compta: Dict[str, List[float]] = defaultdict(list)
    for b, e, s in paires:
        par_banque[b.id].append(s)
        par_compta[e.id].append(s)

    def meilleur_concurrent(b: Operation, e: Operation, s: float) -> Optional[float]:
        autres = list(par_banque[b.id])
        autres.remove(s)
        autres_e = list(par_compta[e.id])
        autres_e.remove(s)
        concurrents = autres + autres_e
        return max(concurrents) if concurrents else None

    resultat: List[Rapprochement] = []
    banque_prise: Set[str] = set()
    compta_prise: Set[str] = set()
    for b, e, s in sorted(paires, key=lambda p: (-p[2], abs((p[0].date - p[1].date).days), p[0].id, p[1].id)):
        if b.id in banque_prise or e.id in compta_prise:
            continue
        concurrent = meilleur_concurrent(b, e, s)
        if concurrent is None:
            statut, regle = ("auto", "montant, date et libellé") if s >= SEUIL_SCORE else ("a_valider", "montant et date seuls")
        elif s >= SEUIL_SCORE and s - concurrent >= MARGE_MINI:
            statut, regle = "auto", "départage par le libellé"
        elif s >= SEUIL_SCORE:
            statut, regle = "a_valider", "plusieurs candidats proches"
        else:
            continue   # plusieurs candidats et aucun indice : on laisse à l'étape suivante
        banque_prise.add(b.id)
        compta_prise.add(e.id)
        resultat.append(Rapprochement((b.id,), (e.id,), regle, s, statut))
    return resultat


def apparier_regroupements(banque: Sequence[Operation], compta: Sequence[Operation]) -> List[Rapprochement]:
    """Une ligne bancaire pour plusieurs écritures (remise de chèques, paiement groupé). Toujours « à valider »."""
    resultat: List[Rapprochement] = []
    prises: Set[str] = set()
    for b in sorted(banque, key=lambda x: (-abs(x.montant), x.id)):
        candidats = [e for e in compta if e.id not in prises and (e.montant > 0) == (b.montant > 0)
                     and abs((b.date - e.date).days) <= FENETRE_REGROUPEMENT_JOURS]
        candidats = sorted(candidats, key=lambda e: abs((b.date - e.date).days))[:CANDIDATS_GROUPE_MAX]
        solutions = [combo for taille in range(2, TAILLE_GROUPE_MAX + 1)
                     for combo in itertools.combinations(candidats, taille) if sum(x.montant for x in combo) == b.montant]
        if len(solutions) == 1:
            combo = solutions[0]
            prises.update(x.id for x in combo)
            resultat.append(Rapprochement((b.id,), tuple(x.id for x in combo), "regroupement d'écritures", 0.0, "a_valider",
                                          f"{len(combo)} écritures dont la somme égale la ligne bancaire"))
    return resultat


def restantes(operations: Sequence[Operation], rapprochements: Sequence[Rapprochement], cote: str) -> List[Operation]:
    prises = {i for r in rapprochements for i in (r.ids_banque if cote == "banque" else r.ids_compta)}
    return [o for o in operations if o.id not in prises]


def etat_rapprochement(banque: Sequence[Operation], compta: Sequence[Operation], rapprochements: Sequence[Rapprochement],
                       solde_initial: int) -> Dict[str, int]:
    """État de rapprochement : explique la différence entre le solde du relevé et celui de la comptabilité."""
    par_id_b = {o.id: o for o in banque}
    par_id_e = {o.id: o for o in compta}
    solde_releve = solde_initial + sum(o.montant for o in banque)
    solde_compta = solde_initial + sum(o.montant for o in compta)
    banque_seule = sum(o.montant for o in restantes(banque, rapprochements, "banque"))
    compta_seule = sum(o.montant for o in restantes(compta, rapprochements, "compta"))
    ecarts_de_montant = sum(sum(par_id_b[i].montant for i in r.ids_banque) - sum(par_id_e[i].montant for i in r.ids_compta)
                            for r in rapprochements)
    explique = banque_seule - compta_seule + ecarts_de_montant
    return {"solde_releve": solde_releve, "solde_compta": solde_compta, "difference": solde_releve - solde_compta,
            "banque_seule": banque_seule, "compta_seule": compta_seule, "ecarts_de_montant": ecarts_de_montant,
            "explique": explique, "residu": solde_releve - solde_compta - explique}


def ensemble(texte: str) -> frozenset:
    return frozenset(x for x in texte.split(";") if x)


def evaluer(rapprochements: Sequence[Rapprochement], chemin_verite: str) -> Dict[str, float]:
    """Compare les rapprochements du moteur à la vérité terrain (jamais lue par le moteur lui-même)."""
    with open(chemin_verite, newline="", encoding="utf-8") as fichier:
        attendus = [r for r in csv.DictReader(fichier) if r["type"] in ("1_pour_1", "regroupement")]
    vrais = {(ensemble(r["ids_banque"]), ensemble(r["ids_compta"])) for r in attendus}
    trouves_auto = {(frozenset(r.ids_banque), frozenset(r.ids_compta)) for r in rapprochements if r.statut == "auto"}
    trouves_tous = {(frozenset(r.ids_banque), frozenset(r.ids_compta)) for r in rapprochements}
    return {"attendus": len(vrais), "auto": len(trouves_auto), "auto_corrects": len(trouves_auto & vrais),
            "proposes": len(trouves_tous), "proposes_corrects": len(trouves_tous & vrais)}


def rapprocher(banque: Sequence[Operation], compta: Sequence[Operation]) -> List[Rapprochement]:
    resultat = apparier_un_pour_un(banque, compta)
    resultat += apparier_regroupements(restantes(banque, resultat, "banque"), restantes(compta, resultat, "compta"))
    return resultat


def formater(centimes: int) -> str:
    return f"{centimes / 100:,.2f}".replace(",", " ").replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rapprochement bancaire (données fictives).")
    ap.add_argument("--ia", choices=["off", "simule", "claude"], default="off",
                    help="étape IA sur les lignes restantes : off (défaut), simule (sans API) ou claude (clé ANTHROPIC_API_KEY)")
    ap.add_argument("--sortie", default=os.path.join(HERE, "rapport", "rapprochement.xlsx"))
    args = ap.parse_args()

    donnees = os.path.join(HERE, "data")
    banque = lire_operations(os.path.join(donnees, "releve_bancaire.csv"), avec_piece=False)
    compta = lire_operations(os.path.join(donnees, "compta_512.csv"), avec_piece=True)
    with open(os.path.join(donnees, "soldes.json"), encoding="utf-8") as fichier:
        solde_initial = en_centimes(json.load(fichier)["solde_initial"])

    resultat = rapprocher(banque, compta)
    stats_regles = evaluer(resultat, os.path.join(donnees, "verite_terrain.csv"))
    if args.ia != "off":
        from ia_suggestions import proposer
        resultat += proposer(restantes(banque, resultat, "banque"), restantes(compta, resultat, "compta"), args.ia)

    etat = etat_rapprochement(banque, compta, resultat, solde_initial)
    nb_auto = sum(r.statut == "auto" for r in resultat)
    print(f"Lignes du relevé : {len(banque)} ; écritures : {len(compta)}")
    print(f"Règles : {stats_regles['auto']} rapprochements automatiques, dont {stats_regles['auto_corrects']} conformes à la vérité terrain "
          f"({stats_regles['attendus']} rapprochements attendus au total)")
    print(f"Au total : {nb_auto} automatiques, {len(resultat) - nb_auto} à valider")
    print(f"Solde relevé {formater(etat['solde_releve'])} € ; solde comptable {formater(etat['solde_compta'])} € ; "
          f"différence {formater(etat['difference'])} € ; expliquée {formater(etat['explique'])} € ; résidu {formater(etat['residu'])} €")

    from rapport_xlsx import ecrire_rapport
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    ecrire_rapport(args.sortie, banque, compta, resultat, etat)
    print(f"Rapport écrit : {args.sortie}")


if __name__ == "__main__":
    main()
