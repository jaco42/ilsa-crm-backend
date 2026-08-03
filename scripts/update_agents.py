"""Update agent names and remove obsolete agents. Run with prod DATABASE_URL."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.user import User

NAMES = {
    '01':    'CLIENTI NON COMM.',
    'EST00': '00 DIREZ ZAGO',
    'EST03': '03 HAHMANN',
    'EST04': '04 MENIN',
    'EST08': '08 NEMETE',
    'EST09': '09 MARCUZZI',
    'ITA00': '00 DIREZ MARCUZZI',
    'ITA04': '04 CHIARINI',
    'ITA06': '06 ORTU',
    'ITA07': '07 PEPE',
    'ITA09': '09 MOCCI',
    'ITA11': '11 STAINLESS',
    'ITA13': '13 DE BIASE',
    'ITA14': '14 CAVICCHI',
    'ITA15': '15 CALABRETTA',
    'ITA16': '16 MONTEFORTE',
    'ITA18': '18 DAINI',
    'ITA21': '21 PAGLIALUNGA',
    'ITA22': '22 AGENZIA PZ',
    'ITA24': '24 PORTO',
}

DELETE_ZONES = {'08', 'EST02', 'EST05', 'EST06', 'EST07', 'ITA01', 'ITA02', 'ITA03', 'ITA12', 'ITA19', 'ITA20'}

# Marcuzzi ha EST09 + ITA00
MARCUZZI_EXTRA = {'ITA00': 'EST09'}  # zona_secondaria: zona_principale (che tiene il login)

db = SessionLocal()
try:
    renamed = deleted = merged = 0

    for u in db.query(User).all():
        zones = u.zone_assegnate or []
        primary = zones[0] if zones else None

        # Elimina obsoleti
        if primary in DELETE_ZONES:
            db.delete(u)
            deleted += 1
            continue

        # Rinomina
        if primary in NAMES:
            u.nome = NAMES[primary]
            renamed += 1

        # Marcuzzi: ITA00 viene assorbito in EST09
        if primary == 'ITA00':
            # trova utente EST09 e aggiungi ITA00 alle sue zone
            est09 = db.query(User).filter(User.zone_assegnate.contains(['EST09'])).first()
            if est09:
                est09.zone_assegnate = list(dict.fromkeys(['EST09', 'ITA00']))
                db.delete(u)
                merged += 1
                continue

    db.commit()
    print(f"Rinominati: {renamed}, Eliminati: {deleted}, Uniti (Marcuzzi): {merged}")
finally:
    db.close()
