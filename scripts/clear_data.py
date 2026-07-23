"""Cancella tutti i dati tranne users. Esegui dalla Console Railway."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    db.execute(text("SET session_replication_role = replica"))  # disabilita FK temporaneamente
    tables = [
        "offer_line_items", "order_line_items", "opportunities", "orders",
        "notes", "email_reminders", "contacts", "company_sap_ids",
        "companies", "prodotti", "radar_segnalazioni", "radar_prodotti",
        "dedup_alerts", "import_logs", "feedback",
    ]
    for t in tables:
        db.execute(text(f"TRUNCATE TABLE {t} CASCADE"))
        print(f"Svuotata: {t}")
    db.execute(text("SET session_replication_role = DEFAULT"))
    db.commit()
    print("Fatto — users intatti.")
except Exception as e:
    db.rollback()
    print(f"Errore: {e}")
finally:
    db.close()
