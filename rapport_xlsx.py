"""Rapport Excel du rapprochement : synthèse, rapprochés, à valider, éléments non rapprochés."""
from typing import Dict, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rapprochement import Operation, Rapprochement, restantes

ENTETE = PatternFill("solid", fgColor="2F5D8A")
FORMAT_EUROS = '#,##0.00 "€";[Red]-#,##0.00 "€"'


def euros(centimes: int) -> float:
    return centimes / 100


def titre(feuille, ligne: int, textes: Sequence[str]) -> None:
    for colonne, texte in enumerate(textes, 1):
        cellule = feuille.cell(row=ligne, column=colonne, value=texte)
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = ENTETE
        cellule.alignment = Alignment(wrap_text=True, vertical="center")
    feuille.freeze_panes = f"A{ligne + 1}"   # une chaîne : passer une cellule créerait une ligne vide sous l'en-tête


def largeurs(feuille, valeurs: Sequence[int]) -> None:
    for colonne, largeur in enumerate(valeurs, 1):
        feuille.column_dimensions[get_column_letter(colonne)].width = largeur


def feuille_rapprochements(classeur: Workbook, nom: str, rapprochements: Sequence[Rapprochement],
                           par_b: Dict[str, Operation], par_e: Dict[str, Operation]) -> None:
    feuille = classeur.create_sheet(nom)
    titre(feuille, 1, ["Lignes du relevé", "Écritures", "Date banque", "Libellé banque", "Montant banque", "Montant compta",
                       "Règle", "Score", "Commentaire"])
    for r in rapprochements:
        banque = [par_b[i] for i in r.ids_banque]
        compta = [par_e[i] for i in r.ids_compta]
        feuille.append([", ".join(r.ids_banque), ", ".join(r.ids_compta), banque[0].date, banque[0].libelle,
                        euros(sum(o.montant for o in banque)), euros(sum(o.montant for o in compta)), r.regle, r.score or None,
                        r.justification])
    for ligne in feuille.iter_rows(min_row=2):
        ligne[2].number_format = "dd/mm/yyyy"
        ligne[4].number_format = FORMAT_EUROS
        ligne[5].number_format = FORMAT_EUROS
    largeurs(feuille, [16, 22, 13, 40, 16, 16, 28, 8, 70])


def feuille_non_rapprochees(classeur: Workbook, nom: str, operations: Sequence[Operation], avec_piece: bool) -> None:
    feuille = classeur.create_sheet(nom)
    entetes = ["Id", "Date", "Libellé", "Montant"] + (["Pièce"] if avec_piece else [])
    titre(feuille, 1, entetes)
    for o in operations:
        feuille.append([o.id, o.date, o.libelle, euros(o.montant)] + ([o.piece] if avec_piece else []))
    for ligne in feuille.iter_rows(min_row=2):
        ligne[1].number_format = "dd/mm/yyyy"
        ligne[3].number_format = FORMAT_EUROS
    largeurs(feuille, [8, 13, 52, 16, 16])


def ecrire_rapport(chemin: str, banque: Sequence[Operation], compta: Sequence[Operation],
                   rapprochements: Sequence[Rapprochement], etat: Dict[str, int]) -> None:
    par_b = {o.id: o for o in banque}
    par_e = {o.id: o for o in compta}
    classeur = Workbook()
    synthese = classeur.active
    synthese.title = "Synthèse"
    auto = [r for r in rapprochements if r.statut == "auto"]
    a_valider = [r for r in rapprochements if r.statut == "a_valider"]
    lignes: List[tuple] = [
        ("Rapprochement bancaire : données fictives (Atelier Démo SAS)", None),
        (None, None),
        ("Lignes du relevé", len(banque)),
        ("Écritures du compte 512", len(compta)),
        ("Rapprochements automatiques", len(auto)),
        ("Rapprochements à valider par un humain", len(a_valider)),
        ("Lignes du relevé non rapprochées", len(restantes(banque, rapprochements, "banque"))),
        ("Écritures non rapprochées", len(restantes(compta, rapprochements, "compta"))),
        (None, None),
        ("ÉTAT DE RAPPROCHEMENT", None),
        ("Solde du relevé bancaire", euros(etat["solde_releve"])),
        ("Solde du compte 512", euros(etat["solde_compta"])),
        ("Différence à expliquer", euros(etat["difference"])),
        ("+ Lignes du relevé non rapprochées (frais, encaissements non comptabilisés)", euros(etat["banque_seule"])),
        ("- Écritures non rapprochées (en transit : chèques non débités, virements reçus après la clôture)", euros(etat["compta_seule"])),
        ("+ Écarts de montant sur les rapprochements", euros(etat["ecarts_de_montant"])),
        ("Différence expliquée", euros(etat["explique"])),
        ("Résidu (doit être nul)", euros(etat["residu"])),
    ]
    for etiquette, valeur in lignes:
        synthese.append([etiquette, valeur])
    synthese["A1"].font = Font(bold=True, size=13)
    synthese["A10"].font = Font(bold=True)
    for ligne in range(11, 19):
        synthese.cell(row=ligne, column=2).number_format = FORMAT_EUROS
    synthese["A18"].font = Font(bold=True)
    synthese["B18"].font = Font(bold=True)
    largeurs(synthese, [95, 18])
    feuille_rapprochements(classeur, "Rapprochés", auto, par_b, par_e)
    feuille_rapprochements(classeur, "À valider", a_valider, par_b, par_e)
    feuille_non_rapprochees(classeur, "Relevé non rapproché", restantes(banque, rapprochements, "banque"), False)
    feuille_non_rapprochees(classeur, "Compta non rapprochée", restantes(compta, rapprochements, "compta"), True)
    classeur.save(chemin)
