"""Create one user per agent zone. Run with: python scripts/create_agents.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.user import User, RuoloUtente
from app.auth import hash_password

PASSWORD = "Ilsa2026!"

AGENTS = [
    '01', '08',
    'EST00', 'EST02', 'EST03', 'EST04', 'EST05', 'EST06', 'EST07', 'EST08', 'EST09',
    'ITA00', 'ITA01', 'ITA02', 'ITA03', 'ITA04', 'ITA06', 'ITA07', 'ITA09',
    'ITA11', 'ITA12', 'ITA13', 'ITA14', 'ITA15', 'ITA16', 'ITA18', 'ITA19',
    'ITA20', 'ITA21', 'ITA22', 'ITA24',
]

db = SessionLocal()
try:
    created = 0
    skipped = 0
    for zona in AGENTS:
        email = f"{zona.lower()}@ilsa.it"
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            skipped += 1
            continue
        user = User(
            nome=zona,
            email=email,
            ruolo=RuoloUtente.rep,
            zona_assegnata=zona,
            password_hash=hash_password(PASSWORD),
            attivo=True,
        )
        db.add(user)
        created += 1
    db.commit()
    print(f"Creati: {created}, già esistenti: {skipped}")
finally:
    db.close()
