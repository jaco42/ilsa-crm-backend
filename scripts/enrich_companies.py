#!/usr/bin/env python3
"""
Enrichment: cerca website, email, telefono per le aziende via DDG + fetch pagina contatti + Groq.

Pipeline per ogni azienda:
  1. Pulisce il nome SAP
  2. Ricerca DuckDuckGo per trovare il sito ufficiale
  3. Tenta di scaricare la pagina contatti (prova path comuni in tutte le lingue)
  4. Passa il testo della pagina a Groq per estrarre email e telefono

Utilizzo:
    python scripts/enrich_companies.py                    # batch 30
    python scripts/enrich_companies.py --batch 5
    python scripts/enrich_companies.py --dry-run
    python scripts/enrich_companies.py --company-id <id>

Richiede: GROQ_API_KEY nel .env
Output: scripts/enrich_log_YYYYMMDD_HHMMSS.json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.database import SessionLocal
from app.models.company import Company

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

CONFIDENCE_THRESHOLD = 0.75
SLEEP_BETWEEN_COMPANIES = 3
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

CONTACT_PATHS = [
    "/contatti", "/contact", "/kontakt", "/contacto",
    "/contact-us", "/contacts", "/nous-contacter",
    "/chi-siamo", "/about", "/about-us", "/impressum",
    "/info", "/informazioni",
]

EXTRACT_PROMPT = """\
You are a B2B data enrichment agent. Extract the official website, a commercial email, and a commercial phone number for this company.

Company:
- Name: {name}
- Address: {address}
- Country: {country}
- VAT: {vat}

{content_section}

Rules:
- WEBSITE: must be the company's own domain (not directories like paginegialle, linkedin, facebook, tripadvisor etc.)
- EMAIL: prefer sales/commercial address (sales@, info@, commerciale@, vendite@, vertrieb@). No personal addresses.
- PHONE: prefer a commercial/sales number. Use a generic number only if no specific commercial one exists. Include country prefix if present.
- confidence > 0.85 = found directly on company's page; 0.7-0.85 = found in snippet but plausible; < 0.7 = uncertain.
- If a field cannot be reliably found, return null and confidence 0.

Respond ONLY with valid JSON, no markdown:
{{"website": {{"value": "https://...", "confidence": 0.0}}, "email": {{"value": "...", "confidence": 0.0}}, "telefono": {{"value": "...", "confidence": 0.0}}}}
"""


def clean_sap_name(name: str) -> str:
    if not name:
        return ""
    cleaned = re.sub(r'"+', ' ', name).strip()
    return re.sub(r'\s+', ' ', cleaned)


def extract_domain(url: str) -> str | None:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return None


def fetch_contact_page(website_url: str) -> tuple[str | None, str | None]:
    """Prova i path contatti comuni, restituisce (url_trovato, testo_pulito)."""
    import httpx
    from bs4 import BeautifulSoup

    base = extract_domain(website_url)
    if not base:
        return None, None

    headers = {"User-Agent": "Mozilla/5.0 (compatible; enrichment-bot/1.0)"}

    def fetch_text(url: str) -> str | None:
        try:
            resp = httpx.get(url, timeout=8, follow_redirects=True, headers=headers)
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)
                return re.sub(r'\s+', ' ', text)[:3000]
        except Exception:
            pass
        return None

    def has_contact(text: str) -> bool:
        return bool(
            re.search(r'[\w.+-]+@[\w-]+\.\w+', text) or
            re.search(r'(\+?\d[\d\s\-./]{6,}\d)', text)
        )

    # 1. Prova prima i path contatti specifici
    for path in CONTACT_PATHS:
        url = base + path
        text = fetch_text(url)
        if text and has_contact(text):
            log.info(f"  📄 Pagina contatti: {url}")
            return url, text

    # 2. Fallback: homepage (può avere contatti nel footer)
    text = fetch_text(website_url)
    if text:
        log.info(f"  📄 Homepage (fallback): {website_url}")
        return website_url, text

    return None, None


def build_search_queries(company: Company) -> list[str]:
    name = clean_sap_name(company.ragione_sociale)
    location = company.citta or company.provincia or ""
    country = company.paese or ""

    base = f'"{name}"'
    if location:
        base += f" {location}"

    queries = [f"{base} sito ufficiale contatti"]
    if country and country.upper() not in ("IT", ""):
        queries.append(f'"{name}" {location} official website contact')

    return queries[:2]


def search_ddg(queries: list[str], max_results: int = 5) -> list[dict]:
    from ddgs import DDGS
    seen_urls = set()
    all_results = []
    for query in queries:
        try:
            results = DDGS().text(query, max_results=max_results)
            for r in (results or []):
                if r["href"] not in seen_urls:
                    seen_urls.add(r["href"])
                    all_results.append(r)
        except Exception as e:
            log.warning(f"  [DDG] '{query}': {e}")
        time.sleep(0.5)
    return all_results[:8]


def extract_website_from_results(ddg_results: list[dict], company_name: str) -> str | None:
    """Identifica l'URL più probabile come sito ufficiale dai risultati DDG."""
    SKIP_DOMAINS = {
        "linkedin.com", "facebook.com", "instagram.com", "tripadvisor",
        "paginegialle", "tuttitalia", "infobel", "coredossier", "registroimprese",
        "youtube.com", "twitter.com", "yelp.com", "google.com", "wikipedia.org",
        "virgilio.it", "kompass.com", "europages.", "dnb.com", "opencorporates",
        "booking.com", "trustpilot", "yelp.", "foursquare.",
    }
    for r in ddg_results:
        url = r["href"]
        if not any(skip in url for skip in SKIP_DOMAINS):
            return url
    return None


def call_groq(client, company: Company, ddg_results: list[dict], page_text: str | None, page_url: str | None) -> dict:
    address_parts = [p for p in [company.indirizzo, company.citta, company.cap, company.provincia] if p]

    if page_text:
        content_section = f"Contact page content (from {page_url}):\n{page_text}"
    elif ddg_results:
        snippets = "\n".join(
            f"[{i+1}] {r['title']}\n    URL: {r['href']}\n    {r['body'][:200]}"
            for i, r in enumerate(ddg_results)
        )
        content_section = f"Web search results:\n{snippets}"
    else:
        content_section = "No web data available."

    prompt = EXTRACT_PROMPT.format(
        name=clean_sap_name(company.ragione_sociale),
        address=", ".join(address_parts) if address_parts else "N/A",
        country=company.paese or "N/A",
        vat=company.partita_iva or "N/A",
        content_section=content_section,
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=300,
    )

    text = completion.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def select_companies(db, batch: int, company_id: str | None) -> list:
    if company_id:
        c = db.query(Company).filter(Company.id == company_id).first()
        return [c] if c else []
    return (
        db.query(Company)
        .filter(Company.sap_customer_id.isnot(None), Company.website.is_(None))
        .order_by(Company.ragione_sociale)
        .limit(batch)
        .all()
    )


def write_via_api(company_id: str, fields: dict, service_key: str, sap_customer_id: str | None = None) -> dict:
    import httpx
    if sap_customer_id:
        url = f"{BACKEND_URL}/companies/enrich-by-sap/{sap_customer_id}"
    else:
        url = f"{BACKEND_URL}/companies/{company_id}/enrich"
    resp = httpx.patch(url, json=fields, headers={"x-service-key": service_key}, timeout=10)
    resp.raise_for_status()
    return resp.json().get("updated", {})


def process(companies, client, dry_run: bool, db=None) -> list[dict]:
    results = []

    for i, c in enumerate(companies):
        entry = {
            "id": str(c.id),
            "ragione_sociale": c.ragione_sociale,
            "nome_pulito": clean_sap_name(c.ragione_sociale),
            "paese": c.paese,
            "sap_customer_id": c.sap_customer_id,
            "prima_del_run": {"website": c.website, "email": c.email, "telefono": c.telefono},
            "pagina_contatti": None,
            "groq": None,
            "aggiornato": {},
            "errore": None,
        }

        log.info(f"[{i+1}/{len(companies)}] {clean_sap_name(c.ragione_sociale)} ({c.paese})")

        if dry_run:
            results.append(entry)
            continue

        try:
            queries = build_search_queries(c)
            log.info(f"  🔍 {queries[0]}")
            ddg_results = search_ddg(queries)
            log.info(f"  → {len(ddg_results)} risultati DDG")

            # Se il sito è già noto usalo direttamente, altrimenti lo cerca nei risultati DDG
            website_url = c.website or extract_website_from_results(ddg_results, clean_sap_name(c.ragione_sociale))
            page_url, page_text = None, None
            if website_url:
                page_url, page_text = fetch_contact_page(website_url)

            entry["pagina_contatti"] = page_url
            data = call_groq(client, c, ddg_results, page_text, page_url)
            entry["groq"] = data

            to_write = {}
            for field in ("website", "email", "telefono"):
                item = data.get(field, {})
                value = item.get("value")
                confidence = item.get("confidence", 0)
                if value and confidence >= CONFIDENCE_THRESHOLD:
                    to_write[field] = value
                    log.info(f"  ✓ {field}: {value} (conf {confidence:.2f})")
                else:
                    log.info(f"  — {field}: conf {confidence:.2f}, skip")

            if to_write:
                service_key = os.environ.get("SERVICE_API_KEY", "").strip()
                written = write_via_api(str(c.id), to_write, service_key, sap_customer_id=c.sap_customer_id)
                entry["aggiornato"] = {k: {"value": v, "confidence": data[k]["confidence"]} for k, v in written.items()}
                if written:
                    if db:
                        for field, value in written.items():
                            setattr(c, field, value)
                        db.commit()
                else:
                    log.info("  → tutti i campi già presenti, nessun aggiornamento")
                    if db and not c.website:
                        c.website = "__enriched__"
                        db.commit()
            else:
                # niente trovato — segna come tentata per skippare al prossimo run
                log.info("  → niente trovato, segno come tentata")
                if db and not c.website:
                    c.website = "__enriched__"
                    db.commit()

        except json.JSONDecodeError as e:
            entry["errore"] = f"JSON parse error: {e}"
            log.warning(f"  [WARN] risposta non JSON: {e}")
        except Exception as e:
            err = str(e)
            entry["errore"] = err
            if "rate_limit_exceeded" in err or "tokens per day" in err or "429" in err:
                log.error(f"  [GROQ RATE LIMIT] token giornalieri esauriti — stop.")
                results.append(entry)
                break
            log.error(f"  [ERROR] {e}")

        results.append(entry)

        if i < len(companies) - 1:
            time.sleep(SLEEP_BETWEEN_COMPANIES)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--company-id", type=str, default=None)
    args = parser.parse_args()

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key and not args.dry_run:
        log.error("GROQ_API_KEY non trovata nel .env")
        sys.exit(1)

    client = None
    if not args.dry_run:
        from groq import Groq
        client = Groq(api_key=api_key)

    db = SessionLocal()
    try:
        companies = select_companies(db, args.batch, args.company_id)
        if not companies:
            log.info("Nessuna azienda da processare.")
            return

        log.info(f"\n{'='*60}")
        log.info(f"Aziende selezionate ({len(companies)}):")
        for i, c in enumerate(companies):
            log.info(f"  {i+1:2}. [{c.sap_customer_id}] {clean_sap_name(c.ragione_sociale)} — {c.paese}")
        log.info(f"{'='*60}\n")

        if args.dry_run:
            log.info("DRY RUN — nessuna ricerca, nessun aggiornamento DB.")

        results = process(companies, client, args.dry_run, db=db)

    finally:
        db.close()

    log_path = Path(__file__).parent / f"enrich_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\nLog: {log_path}")

    aggiornati = [r for r in results if r["aggiornato"]]
    errori = [r for r in results if r["errore"]]
    log.info(f"Riepilogo: {len(aggiornati)}/{len(results)} aggiornate, {len(errori)} errori")


if __name__ == "__main__":
    main()
