#!/usr/bin/env python3
"""
Script per testare la logica dedup senza bisogno dei CSV SAP.

Crea un lead nel CRM, poi simula un import SAP con varianti del nome/indirizzo
e verifica che la logica di match funzioni correttamente.

Utilizzo:
    python scripts/test_dedup.py

Alla fine stampa il risultato atteso e cosa è successo realmente.
Pulisce i dati di test automaticamente (a meno che non passi --keep).
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.company import Company, CompanyOrigin, CompanyStatus
from app.models.dedup import DeduplicaAlert
from app.services.dedup import find_and_handle_duplicate, score_match

RESET = '\033[0m'
GREEN = '\033[92m'
RED   = '\033[91m'
YELLOW = '\033[93m'
BOLD  = '\033[1m'

def ok(msg): print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg): print(f"  {RED}✗{RESET} {msg}")
def info(msg): print(f"  {YELLOW}→{RESET} {msg}")


CASI = [
    {
        "nome": "P.IVA identica → merge automatica",
        "lead": dict(ragione_sociale="Rossi Mario SRL", partita_iva="12345678901", paese="IT", provincia="MI", indirizzo="Via Roma 5"),
        "sap":  dict(ragione_sociale="MARIO ROSSI S.R.L.", partita_iva="12345678901", paese="IT", provincia="MI", indirizzo="Via Roma 5"),
        "atteso": "auto_merge",
    },
    {
        "nome": "Nome identico + via identica → merge automatica",
        "lead": dict(ragione_sociale="Trattoria Da Pino", paese="IT", provincia="RM", indirizzo="Corso Vittorio 12"),
        "sap":  dict(ragione_sociale="TRATTORIA DA PINO", paese="IT", provincia="RM", indirizzo="Corso Vittorio 12"),
        "atteso": "auto_merge",
    },
    {
        "nome": "Nome simile + via simile → alert inbox",
        "lead": dict(ragione_sociale="Gelateria Fiore", paese="IT", provincia="TO", indirizzo="Via Garibaldi 8"),
        "sap":  dict(ragione_sociale="GELATERIA DEL FIORE", paese="IT", provincia="TO", indirizzo="Via Garibaldi 8/A"),
        "atteso": "alert",
    },
    {
        "nome": "Nome uguale + nessun indirizzo su lead → alert inbox",
        "lead": dict(ragione_sociale="Bianchi Forniture", paese="IT"),
        "sap":  dict(ragione_sociale="BIANCHI FORNITURE SRL", paese="IT", provincia="BO", indirizzo="Via Po 3"),
        "atteso": "alert",
    },
    {
        "nome": "Aziende diverse → nessun match",
        "lead": dict(ragione_sociale="Pizzeria Roma", paese="IT", provincia="MI", indirizzo="Via Dante 1"),
        "sap":  dict(ragione_sociale="Ferramenta Bianchi", paese="DE", indirizzo="Hauptstrasse 10"),
        "atteso": "nessuno",
    },
    {
        "nome": "Nome identico ma paese diverso → ignora (regola 5)",
        "lead": dict(ragione_sociale="Rossi SRL", paese="IT", provincia="MI", indirizzo="Via Po 1"),
        "sap":  dict(ragione_sociale="Rossi SRL", paese="DE", indirizzo="Via Po 1"),
        "atteso": "nessuno",
    },
    {
        "nome": "Nome alto + provincia uguale + via simile → alert (regola 3)",
        "lead": dict(ragione_sociale="Bar Centrale", paese="IT", provincia="VR", indirizzo="Piazza Bra 3"),
        "sap":  dict(ragione_sociale="BAR CENTRALE SRL", paese="IT", provincia="VR", indirizzo="Piazza Bra 3/A"),
        "atteso": "alert",
    },
]


def run_case(caso, db, keep=False):
    print(f"\n{BOLD}{caso['nome']}{RESET}")

    # Crea lead
    lead_data = {**caso["lead"], "origin": CompanyOrigin.crm_manual, "status": CompanyStatus.prospect}
    lead = Company(**lead_data)
    db.add(lead)
    db.flush()

    # Prepara dati SAP
    sap_data = {
        **caso["sap"],
        "sap_customer_id": "TEST_" + caso["nome"][:10].replace(" ", "_"),
        "origin": CompanyOrigin.sap_sync,
        "status": CompanyStatus.prospect,
    }

    # Score
    temp = Company(**{k: v for k, v in sap_data.items() if k != "status"})
    reason, s_nome, s_via = score_match(lead, temp)
    via_str = f"{s_via:.1f}" if s_via is not None else "N/A"
    info(f"score nome={s_nome:.1f}  via={via_str}  reason={reason}")

    # Esegui logica
    handled, match = find_and_handle_duplicate(sap_data, db)

    if caso["atteso"] == "auto_merge":
        if handled:
            ok("merge automatica eseguita")
        else:
            fail(f"atteso auto_merge, ottenuto: handled={handled} match={match}")

    elif caso["atteso"] == "alert":
        if not handled and match is not None:
            ok("alert generato correttamente")
        elif handled:
            fail("atteso alert, ma è stata fatta merge automatica")
        else:
            fail("atteso alert, ma nessun match trovato")

    elif caso["atteso"] == "nessuno":
        if not handled and match is None:
            ok("nessun match, corretto")
        else:
            fail(f"atteso nessun match, ottenuto: handled={handled} match={match}")

    db.rollback()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="Non fare rollback (lascia i dati nel DB)")
    args = parser.parse_args()

    db = SessionLocal()
    print(f"\n{BOLD}=== Test dedup ==={RESET}")
    try:
        for caso in CASI:
            run_case(caso, db, keep=args.keep)
        if not args.keep:
            db.rollback()
            print(f"\n{GREEN}Tutti i dati di test rimossi (rollback){RESET}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
