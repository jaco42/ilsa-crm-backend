import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
from apscheduler.schedulers.background import BackgroundScheduler
from app.routers import companies, contacts, users, agenti, opportunities, prodotti, notes, orders, reminders, radar, auth, imports, import_log, feedback, dashboard
from app.database import SessionLocal
from app.config import settings


def _scheduler_job():
    db = SessionLocal()
    try:
        reminders.run_pending_reminders(db)
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
app.include_router(companies.service_router)
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


@app.get("/health")
def health():
    return {"status": "ok"}
