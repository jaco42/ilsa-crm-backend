import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
from apscheduler.schedulers.background import BackgroundScheduler
from app.routers import companies, contacts, users, agenti, opportunities, prodotti, notes, orders, reminders, radar, auth, imports, import_log, feedback, dashboard, activity

from app.database import SessionLocal
from app.config import settings


def _scheduler_job():
    db = SessionLocal()
    try:
        reminders.run_pending_reminders(db)
    finally:
        db.close()


def _mark_scadute_job():
    from datetime import date, timedelta, datetime, timezone
    from sqlalchemy import or_, and_
    from app.models.opportunity import Opportunity
    db = SessionLocal()
    try:
        today = date.today()
        un_mese_fa = today - timedelta(days=30)
        db.query(Opportunity).filter(
            Opportunity.stage == 'Offerta Mandata',
            or_(
                Opportunity.data_scadenza < today,
                and_(
                    Opportunity.data_scadenza == None,
                    Opportunity.data_creazione_sap != None,
                    Opportunity.data_creazione_sap < un_mese_fa,
                )
            )
        ).update(
            {"stage": "Scaduta", "stage_changed_at": datetime.now(timezone.utc)},
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    db.execute(text("UPDATE opportunities SET data_scadenza = NULL WHERE EXTRACT(YEAR FROM data_scadenza) > 2100"))
    db.commit()
    db.close()

    scheduler = BackgroundScheduler()
    scheduler.add_job(_scheduler_job, "interval", minutes=1)
    scheduler.add_job(_mark_scadute_job, "interval", hours=24)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="ILSA CRM API", version="1.0.0", lifespan=lifespan)

allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(contacts.router)
app.include_router(users.router)
app.include_router(agenti.router)
app.include_router(opportunities.router)
app.include_router(prodotti.router)
app.include_router(notes.router)
app.include_router(orders.router)
app.include_router(reminders.router)
app.include_router(reminders.internal_router)
app.include_router(radar.router)
app.include_router(imports.router)
app.include_router(import_log.router)
app.include_router(feedback.router)
app.include_router(dashboard.router)
app.include_router(activity.router)


@app.get("/health")
def health():
    return {"status": "ok"}
