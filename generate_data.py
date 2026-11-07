#!/usr/bin/env python3
"""Génère un relevé bancaire et un compte 512 FICTIFS pour une PME imaginaire (« Atelier Démo SAS », mars 2025).

Aucune donnée réelle. Graine fixe : le résultat est reproductible.
Sorties dans data/ :
  releve_bancaire.csv  : id, date, libelle, montant   (encaissement > 0, décaissement < 0)
  compta_512.csv       : id, date, piece, libelle, montant
  verite_terrain.csv   : les rapprochements attendus (pour mesurer le moteur), jamais lus par le moteur
  soldes.json          : solde initial commun au relevé et à la comptabilité

Cas injectés : paiements 1 pour 1 avec décalage de date et libellé bruité, remises de chèques (1 ligne bancaire pour
plusieurs écritures), frais présents seulement à la banque, écritures présentes seulement en comptabilité (en transit),
deux clients au même montant, deux lignes au libellé trop pauvre pour être départagées, une erreur de saisie (chiffres
inversés).
"""
import csv
import json
import os
import random
from datetime import date, timedelta
from typing import Dict, List, Tuple

HERE: str = os.path.dirname(os.path.abspath(__file__))
SEED: int = 2026
DEBUT: date = date(2025, 3, 1)
SOLDE_INITIAL_CENTIMES: int = 2_500_000
CLIENTS: List[str] = ["Boulangerie Moreau", "Cabinet Lefort", "Garage Delmas", "Pharmacie du Port", "Menuiserie Roux",
                      "Atelier Vasseur", "Hôtel Belvédère", "Librairie Fontaine", "Cave Marchand", "Studio Perrin"]
FOURNISSEURS: List[str] = ["Papeterie Duval", "Énergie Sud", "Transports Garnier", "Informatique Pellet",
                           "Assurances Marin", "Nettoyage Clair", "Imprimerie Colin"]


def euros(centimes: int) -> str:
    return f"{centimes / 100:.2f}"


def sans_accents(texte: str) -> str:
    table = str.maketrans("éèêëàâîïôùûüçÉÈÊËÀÂÎÏÔÙÛÜÇ", "eeeeaaiiouuucEEEEAAIIOUUUC")
    return texte.translate(table)


def jour(numero: int) -> date:
    return DEBUT + timedelta(days=numero - 1)


class Jeu:
    """Accumule les lignes du relevé, de la comptabilité et la vérité terrain."""

    def __init__(self) -> None:
        self.banque: List[Dict[str, str]] = []
        self.compta: List[Dict[str, str]] = []
        self.verite: List[Tuple[str, str, str]] = []
        self.montants_pris: set = set()

    def montant_libre(self, rng: random.Random, bas: int = 30_000, haut: int = 450_000) -> int:
        while True:
            valeur = rng.randrange(bas, haut)
            if valeur not in self.montants_pris:
                self.montants_pris.add(valeur)
                return valeur

    def ajouter_banque(self, quand: date, libelle: str, montant: int) -> str:
        identifiant = f"B{len(self.banque) + 1:03d}"
        self.banque.append({"id": identifiant, "date": quand.isoformat(), "libelle": libelle, "montant": euros(montant)})
        return identifiant

    def ajouter_compta(self, quand: date, piece: str, libelle: str, montant: int) -> str:
        identifiant = f"E{len(self.compta) + 1:03d}"
        self.compta.append({"id": identifiant, "date": quand.isoformat(), "piece": piece, "libelle": libelle,
                            "montant": euros(montant)})
        return identifiant


def un_pour_un(jeu: Jeu, rng: random.Random, nombre: int) -> None:
    for i in range(nombre):
        quand = rng.randint(1, 26)
        avec_reference = rng.random() < 0.7
        if rng.random() < 0.6:
            tiers = rng.choice(CLIENTS)
            piece = f"FAC-2025-{100 + i:03d}"
            montant = jeu.montant_libre(rng)
            libelle_compta = f"Règlement {tiers} {piece}"
            libelle_banque = f"VIR SEPA {sans_accents(tiers).upper()}" + (f" {piece}" if avec_reference else "")
        else:
            tiers = rng.choice(FOURNISSEURS)
            piece = f"ACH-2025-{200 + i:03d}"
            montant = -jeu.montant_libre(rng)
            libelle_compta = f"Paiement {tiers} {piece}"
            libelle_banque = f"PRLV {sans_accents(tiers).upper()}" + (f" {piece}" if avec_reference else "")
        e = jeu.ajouter_compta(jour(quand), piece, libelle_compta, montant)
        b = jeu.ajouter_banque(jour(quand + rng.randint(0, 3)), libelle_banque, montant)
        jeu.verite.append(("1_pour_1", b, e))


def remises_de_cheques(jeu: Jeu, rng: random.Random, nombre: int) -> None:
    for i in range(nombre):
        taille = rng.choice([2, 3])
        ecritures: List[str] = []
        total = 0
        dernier = 1
        fin = rng.randint(12, 24)   # les chèques d'une remise sont reçus dans les 8 jours qui précèdent le dépôt
        for k in range(taille):
            quand = rng.randint(fin - 8, fin)
            dernier = max(dernier, quand)
            montant = jeu.montant_libre(rng, 20_000, 200_000)
            total += montant
            tiers = rng.choice(CLIENTS)
            ecritures.append(jeu.ajouter_compta(jour(quand), f"CHQ-{300 + i * 4 + k}", f"Chèque {tiers}", montant))
        b = jeu.ajouter_banque(jour(dernier + rng.randint(1, 2)), f"REMISE CHEQUES {i + 1:04d}", total)
        jeu.verite.append(("regroupement", b, ";".join(ecritures)))


def frais_bancaires(jeu: Jeu) -> None:
    for quand, libelle, montant in [(31, "FRAIS TENUE DE COMPTE", -1850), (31, "COMMISSION CARTE BANCAIRE", -4230),
                                    (31, "AGIOS DEBITEURS", -3175)]:
        b = jeu.ajouter_banque(jour(quand), libelle, montant)
        jeu.verite.append(("banque_seule", b, ""))


def en_transit(jeu: Jeu, rng: random.Random) -> None:
    lignes = [(27, "CHQ-390", "Chèque émis Nettoyage Clair non débité", -jeu.montant_libre(rng, 20_000, 90_000)),
              (31, "FAC-2025-190", "Virement client Studio Perrin reçu en fin de mois", jeu.montant_libre(rng, 100_000, 300_000)),
              (30, "ACH-2025-290", "Prélèvement Assurances Marin", -jeu.montant_libre(rng, 50_000, 120_000))]
    for quand, piece, libelle, montant in lignes:
        e = jeu.ajouter_compta(jour(quand), piece, libelle, montant)
        jeu.verite.append(("compta_seule", "", e))


def meme_montant(jeu: Jeu) -> None:
    montant = 120_000
    jeu.montants_pris.add(montant)
    e1 = jeu.ajouter_compta(jour(11), "FAC-2025-150", "Règlement Cabinet Lefort FAC-2025-150", montant)
    e2 = jeu.ajouter_compta(jour(12), "FAC-2025-151", "Règlement Pharmacie du Port FAC-2025-151", montant)
    b1 = jeu.ajouter_banque(jour(13), "VIR SEPA PHARMACIE DU PORT", montant)
    b2 = jeu.ajouter_banque(jour(14), "VIR SEPA CABINET LEFORT FAC-2025-150", montant)
    jeu.verite.append(("1_pour_1", b1, e2))
    jeu.verite.append(("1_pour_1", b2, e1))


def libelles_pauvres(jeu: Jeu) -> None:
    montant = 85_000
    jeu.montants_pris.add(montant)
    e1 = jeu.ajouter_compta(jour(18), "FAC-2025-160", "Règlement Garage Delmas FAC-2025-160", montant)
    e2 = jeu.ajouter_compta(jour(19), "FAC-2025-161", "Règlement Atelier Vasseur FAC-2025-161", montant)
    b1 = jeu.ajouter_banque(jour(20), "VIR DIVERS", montant)
    b2 = jeu.ajouter_banque(jour(21), "VIR DIVERS", montant)
    jeu.verite.append(("ambigu", f"{b1};{b2}", f"{e1};{e2}"))


def chiffres_inverses(jeu: Jeu) -> None:
    jeu.montants_pris.update({145_000, 154_000})
    e = jeu.ajouter_compta(jour(15), "FAC-2025-077", "Règlement Hôtel Belvédère FAC-2025-077", 145_000)
    b = jeu.ajouter_banque(jour(16), "VIR SEPA HOTEL BELVEDERE FAC-2025-077", 154_000)
    jeu.verite.append(("ecart_montant", b, e))


def ecrire_csv(chemin: str, lignes: List[Dict[str, str]]) -> None:
    with open(chemin, "w", newline="", encoding="utf-8") as fichier:
        writer = csv.DictWriter(fichier, fieldnames=list(lignes[0].keys()))
        writer.writeheader()
        writer.writerows(lignes)


def main() -> None:
    rng = random.Random(SEED)
    jeu = Jeu()
    un_pour_un(jeu, rng, 26)
    remises_de_cheques(jeu, rng, 3)
    meme_montant(jeu)
    libelles_pauvres(jeu)
    chiffres_inverses(jeu)
    frais_bancaires(jeu)
    en_transit(jeu, rng)
    jeu.banque.sort(key=lambda r: (r["date"], r["id"]))
    jeu.compta.sort(key=lambda r: (r["date"], r["id"]))
    dossier = os.path.join(HERE, "data")
    os.makedirs(dossier, exist_ok=True)
    ecrire_csv(os.path.join(dossier, "releve_bancaire.csv"), jeu.banque)
    ecrire_csv(os.path.join(dossier, "compta_512.csv"), jeu.compta)
    ecrire_csv(os.path.join(dossier, "verite_terrain.csv"),
               [{"type": t, "ids_banque": b, "ids_compta": c} for t, b, c in jeu.verite])
    with open(os.path.join(dossier, "soldes.json"), "w", encoding="utf-8") as fichier:
        json.dump({"solde_initial": euros(SOLDE_INITIAL_CENTIMES)}, fichier)
    print(f"{len(jeu.banque)} lignes de relevé et {len(jeu.compta)} écritures écrites dans {dossier}")


if __name__ == "__main__":
    main()
