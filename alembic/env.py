"""
COSA FA QUESTO FILE
-------------------
Questo è il file di configurazione di Alembic. Collega i modelli Python al DB.

I modelli Python sono la fonte di verità. Alembic confronta lo schema dei modelli
con lo stato attuale del DB e genera le istruzioni SQL per allinearli.
Il DB si adegua sempre ai modelli, mai il contrario.

Ogni migration viene salvata come file in alembic/versions/ — uno storico completo
di tutte le modifiche al DB nel tempo, con cosa è cambiato ad ogni passaggio.
Questo permette di sapere esattamente in che stato era il DB in qualsiasi momento
e di tornare indietro se necessario.


COME FARE UNA MIGRATION
------------------------
Scenario: hai aggiunto il campo "zona" al modello Company.

Passo 1 — genera il file di migration:
    alembic revision --autogenerate -m "aggiunto campo zona a company"

Questo crea un file in alembic/versions/ con le istruzioni SQL.
Aprilo e verificalo prima di procedere — specialmente se hai rinominato un campo
(vedi CASO LIMITE nella funzione run_migrations_online).

Passo 2 — applica la migration al DB:
    alembic upgrade head
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
from dotenv import load_dotenv

load_dotenv()

from app.database import Base
import app.models

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Non si connette al DB e non esegue nulla. Genera un file di testo con le
    istruzioni SQL che verrebbero eseguite — il DB non viene toccato.

    Esempio — vuoi vedere cosa succederebbe prima di toccare il DB:
        alembic upgrade head --sql > migration.sql

    Apri migration.sql e trovi le istruzioni che verrebbero eseguite, tipo:
        ALTER TABLE companies ADD COLUMN zona VARCHAR;

    Usala quando il DB di produzione è gestito da un amministratore esterno
    che non ti dà accesso diretto: gli mandi il file SQL e lo esegue lui.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Si connette al DB ed esegue le migration. E' la modalità normale,
    quella che usi ogni giorno con "alembic upgrade head".

    Tutto avviene dentro una transazione — se qualcosa va storto PostgreSQL
    fa rollback automatico e il DB torna allo stato precedente senza danni.

    CASO LIMITE — rinominare un campo:
    Se nel modello rinomini "nome" in "name", Alembic non capisce che e' un rename.
    Genera invece:
        op.add_column('companies', Column('name', String))   <- crea colonna vuota
        op.drop_column('companies', 'nome')                  <- cancella i dati esistenti
    Tutti i dati in "nome" vengono persi.

    Come mitigare: apri il file in alembic/versions/ e sostituisci quelle due righe con:
        op.alter_column('companies', 'nome', new_column_name='name')
    Poi esegui "alembic upgrade head".
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
