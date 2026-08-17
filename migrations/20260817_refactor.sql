-- Migration: model refactor
-- Date: 2026-08-17

BEGIN;

-- 1. Remove dead columns from agenti
ALTER TABLE agenti DROP COLUMN IF EXISTS zona_competenza;
ALTER TABLE agenti DROP COLUMN IF EXISTS telefono;
ALTER TABLE agenti DROP COLUMN IF EXISTS email;

-- 2. Remove dead columns from opportunities
ALTER TABLE opportunities DROP COLUMN IF EXISTS rep_id;
ALTER TABLE opportunities DROP COLUMN IF EXISTS agente_id;
ALTER TABLE opportunities DROP COLUMN IF EXISTS dropout_reason;

-- Fix default stage for rows that have 'Richiesta Info' (now invalid)
UPDATE opportunities SET stage = 'Offerta Mandata' WHERE stage = 'Richiesta Info';

-- 3. Split agente_sap_locked into agente_ilsa_locked + agente_desco_locked in companies
ALTER TABLE companies ADD COLUMN IF NOT EXISTS agente_ilsa_locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS agente_desco_locked BOOLEAN NOT NULL DEFAULT FALSE;

-- Migrate existing locked rows: if agente_sap_locked was true, lock both
UPDATE companies SET agente_ilsa_locked = TRUE, agente_desco_locked = TRUE WHERE agente_sap_locked = TRUE;

ALTER TABLE companies DROP COLUMN IF EXISTS agente_sap_locked;

-- 4. Add indexes
CREATE INDEX IF NOT EXISTS ix_companies_agente_ilsa  ON companies (agente_ilsa);
CREATE INDEX IF NOT EXISTS ix_companies_agente_desco ON companies (agente_desco);
CREATE INDEX IF NOT EXISTS ix_orders_org_cm          ON orders (org_cm);
CREATE INDEX IF NOT EXISTS ix_orders_sap_creato_da   ON orders (sap_creato_da);

-- 5. Create unified line_items table
CREATE TABLE IF NOT EXISTS line_items (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_type    VARCHAR NOT NULL,
    opportunity_id   UUID REFERENCES opportunities(id),
    order_id         UUID REFERENCES orders(id),
    codice_sap       VARCHAR,
    descrizione_riga VARCHAR,
    quantita         NUMERIC,
    unita_misura     VARCHAR,
    prezzo_unitario  NUMERIC,
    totale_riga      NUMERIC,
    categoria        VARCHAR,
    prodotto         VARCHAR,
    nota             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6. Migrate offer_line_items → line_items
INSERT INTO line_items (id, document_type, opportunity_id, codice_sap, descrizione_riga, quantita, unita_misura, prezzo_unitario, totale_riga, categoria, prodotto, nota, created_at)
SELECT id, 'offer', opportunity_id, codice_sap, descrizione_riga, quantita, unita_misura, prezzo_unitario, totale_riga, categoria, prodotto, nota, created_at
FROM offer_line_items;

-- 7. Migrate order_line_items → line_items
INSERT INTO line_items (id, document_type, order_id, codice_sap, descrizione_riga, quantita, unita_misura, prezzo_unitario, totale_riga, categoria, prodotto, nota, created_at)
SELECT id, 'order', order_id, codice_sap, descrizione_riga, quantita, unita_misura, prezzo_unitario, totale_riga, categoria, prodotto, nota, created_at
FROM order_line_items;

-- 8. Drop old tables
DROP TABLE IF EXISTS offer_line_items;
DROP TABLE IF EXISTS order_line_items;
DROP TABLE IF EXISTS deduplica_alerts;

COMMIT;
