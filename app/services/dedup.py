import re
from rapidfuzz import fuzz
from app.models.company import Company, CompanyStatus
from app.models.company_sap_ids import CompanySapId
from app.models.opportunity import Opportunity
from app.models.order import Order
from app.models.contact import Contact
from app.models.note import Note
from app.models.radar import RadarSegnalazione
from app.models.dedup import DeduplicaAlert


def _normalize_name(s: str) -> str:
    if not s:
        return ""
    s = s.upper().strip()
    s = re.sub(r'[\.\s]+', ' ', s)
    for suffix in [" S.R.L.", " SRL", " S.P.A.", " SPA", " S.N.C.", " SNC",
                   " S.A.S.", " SAS", " DITTA", " DI "]:
        s = s.replace(suffix, "")
    return s.strip()


def _normalize_via(s: str) -> str:
    if not s:
        return ""
    s = s.upper().strip()
    s = re.sub(r'\b(VIA|VIALE|V\.LE|CORSO|C\.SO|PIAZZA|P\.ZA|P\.ZZA|LARGO|LOC\.|LOCALITA\'|STR\.|STRADA)\b', '', s)
    s = re.sub(r'[\s,\.]+', ' ', s).strip()
    return s


def score_match(a: Company, b: Company) -> tuple[str | None, float, float | None]:
    """
    Returns (reason, score_nome, score_via) or (None, score_nome, score_via) if no match.
    reason: "piva_identica" | "nome_e_via_identici" | "alert_simile"

    Gerarchia:
      0. sap_customer_id identico → gestito a monte nell'import, non arriva qui
      1. P.IVA identica + nome >= 60%              → merge automatica
      2. Nome >= 98% + indirizzo >= 95% + paese uguale → merge automatica
      3. Nome >= 80% + paese uguale + provincia uguale + indirizzo >= 70% → alert
      4. Nome >= 98% + paese uguale + indirizzo mancante su uno → alert
      5. Paese diverso (entrambi presenti)          → ignora
      6. Tutto il resto                             → ignora
    """
    piva_a = (a.partita_iva or "").strip()
    piva_b = (b.partita_iva or "").strip()
    nome_a = _normalize_name(a.ragione_sociale or "")
    nome_b = _normalize_name(b.ragione_sociale or "")
    via_a = _normalize_via(a.indirizzo or "")
    via_b = _normalize_via(b.indirizzo or "")
    paese_a = (a.paese or "").upper().strip()
    paese_b = (b.paese or "").upper().strip()
    prov_a = (a.provincia or "").upper().strip()
    prov_b = (b.provincia or "").upper().strip()

    score_nome = fuzz.token_sort_ratio(nome_a, nome_b) if nome_a and nome_b else 0
    score_via = fuzz.ratio(via_a, via_b) if via_a and via_b else None

    # Regola 5: paese diverso → ignora sempre
    if paese_a and paese_b and paese_a != paese_b:
        return None, score_nome, score_via

    paese_ok = (not paese_a or not paese_b or paese_a == paese_b)
    prov_ok = (not prov_a or not prov_b or prov_a == prov_b)

    # Regola 1: P.IVA identica + nome simile
    if piva_a and piva_b and piva_a == piva_b and score_nome >= 60:
        return "piva_identica", score_nome, score_via

    # Regola 2: Nome identico + via identica + paese compatibile
    if score_nome >= 98 and score_via is not None and score_via >= 95 and paese_ok:
        return "nome_e_via_identici", score_nome, score_via

    # Regola 3: Nome alto + paese uguale + provincia uguale + via simile
    if score_nome >= 80 and paese_ok and prov_ok and score_via is not None and score_via >= 70:
        return "alert_simile", score_nome, score_via

    # Regola 4: Nome identico + paese compatibile + via mancante su uno
    if score_nome >= 98 and paese_ok and score_via is None:
        return "alert_simile", score_nome, score_via

    return None, score_nome, score_via


_STATUS_RANK = {"cliente": 2, "prospect": 1, None: 0}


def _rank(company: Company) -> int:
    val = company.status.value if company.status else None
    return _STATUS_RANK.get(val, 0)


def merge_companies(survivor: Company, duplicate: Company, db) -> None:
    """
    Rilinka tutti i record dal duplicato al survivor, poi elimina il duplicato.
    Anagrafica: per ogni campo vince il record con status più alto
    (cliente > potenziale > lead); se quel campo è vuoto si scende al livello inferiore.
    Il codice SAP del duplicato viene salvato in company_sap_ids così i prossimi
    import SAP lo riconoscono senza creare duplicati.
    """
    sid = survivor.id
    did = duplicate.id

    # Rilink relazioni
    db.query(Opportunity).filter(Opportunity.company_id == did).update({"company_id": sid}, synchronize_session=False)
    db.query(Order).filter(Order.company_id == did).update({"company_id": sid}, synchronize_session=False)
    db.query(Contact).filter(Contact.company_id == did).update({"company_id": sid}, synchronize_session=False)
    db.query(Note).filter(Note.company_id == did).update({"company_id": sid}, synchronize_session=False)
    db.query(RadarSegnalazione).filter(RadarSegnalazione.company_id == did).update({"company_id": sid}, synchronize_session=False)

    # Rilink sap_ids_secondari del duplicato al survivor
    db.query(CompanySapId).filter(CompanySapId.company_id == did).update({"company_id": sid}, synchronize_session=False)

    # Salva il codice SAP del duplicato come secondario sul survivor
    if duplicate.sap_customer_id and duplicate.sap_customer_id != survivor.sap_customer_id:
        existing = db.query(CompanySapId).filter(CompanySapId.sap_customer_id == duplicate.sap_customer_id).first()
        if not existing:
            db.add(CompanySapId(company_id=sid, sap_customer_id=duplicate.sap_customer_id))

    # Anagrafica: ordina per rank, per ogni campo prende il primo valore non vuoto
    ordered = sorted([survivor, duplicate], key=_rank, reverse=True)

    for field in ("ragione_sociale", "partita_iva", "indirizzo", "citta", "cap",
                  "provincia", "paese", "telefono", "email", "tipo_attivita", "storico_contatti"):
        for record in ordered:
            val = getattr(record, field)
            if val:
                setattr(survivor, field, val)
                break

    # Campi SAP: prende dal record col rank più alto che li ha
    for record in ordered:
        if record.sap_customer_id:
            survivor.sap_customer_id = record.sap_customer_id
            survivor.sap_created_at = record.sap_created_at
            survivor.status = record.status
            survivor.origin = record.origin
            break

    db.delete(duplicate)


def find_and_handle_duplicate(new_company_data: dict, db) -> tuple[bool, Company | None]:
    """
    Chiamata dall'import prima di creare una nuova company.
    Ritorna (handled, survivor):
    - (True, company) se merge automatica eseguita o alert creato (non creare il record)
    - (False, None) se nessun match trovato (procedi normalmente)

    Nota: in caso di alert, la nuova company viene comunque creata come
    company_b così l'utente può vedere i dati SAP nell'alert.
    """
    candidates = db.query(Company).filter(
        Company.sap_customer_id == None
    ).all()

    temp = Company(**{k: v for k, v in new_company_data.items() if k != 'status'})
    temp.status = new_company_data.get('status', CompanyStatus.prospect)

    best_reason = None
    best_score_nome = 0
    best_score_via = 0
    best_candidate = None

    for candidate in candidates:
        reason, s_nome, s_via = score_match(candidate, temp)
        if reason and s_nome > best_score_nome:
            best_reason = reason
            best_score_nome = s_nome
            best_score_via = s_via
            best_candidate = candidate

    if not best_candidate:
        return False, None

    if best_reason in ("piva_identica", "nome_e_via_identici"):
        # Merge automatica: aggiorna il lead con i dati SAP, non creare nuovo record
        # SAP vince sempre sui campi anagrafici
        for field in ("indirizzo", "citta", "cap", "provincia", "paese", "telefono", "partita_iva"):
            val = new_company_data.get(field)
            if val is not None:
                setattr(best_candidate, field, val)
        if new_company_data.get("sap_customer_id"):
            best_candidate.sap_customer_id = new_company_data["sap_customer_id"]
            best_candidate.status = new_company_data.get("status", CompanyStatus.prospect)
            best_candidate.origin = new_company_data.get("origin", best_candidate.origin)
            best_candidate.sap_created_at = new_company_data.get("sap_created_at")

        alert = DeduplicaAlert(
            company_a_id=best_candidate.id,
            company_b_id=best_candidate.id,  # stesso record, merge già fatta
            reason=best_reason,
            score_nome=best_score_nome,
            score_via=best_score_via if best_score_via else None,
            resolved=True,
            resolved_action="auto_merged",
        )
        db.add(alert)
        return True, best_candidate

    if best_reason == "alert_simile":
        # Crea la nuova company SAP normalmente, poi crea l'alert
        return False, best_candidate  # segnale speciale: crea il record, poi crea alert

    return False, None
