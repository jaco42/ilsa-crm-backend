"""Create or reset an admin user. Run with: python scripts/create_admin.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.user import User, RuoloUtente
from app.auth import hash_password

EMAIL = os.getenv("ADMIN_EMAIL", "admin@ilsa.it")
PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme123!")
NOME = os.getenv("ADMIN_NOME", "Admin")

db = SessionLocal()
try:
    user = db.query(User).filter(User.email == EMAIL).first()
    if user:
        user.password_hash = hash_password(PASSWORD)
        user.ruolo = RuoloUtente.admin
        user.attivo = True
        db.commit()
        print(f"Password aggiornata per {EMAIL}")
    else:
        user = User(nome=NOME, email=EMAIL, ruolo=RuoloUtente.admin, password_hash=hash_password(PASSWORD))
        db.add(user)
        db.commit()
        print(f"Utente admin creato: {EMAIL}")
finally:
    db.close()
