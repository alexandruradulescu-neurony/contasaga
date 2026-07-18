-- seed de test: 2 cabinete, 3 firme, 4 utilizatori
SET client_min_messages = warning;

INSERT INTO cabinete_contabilitate (id, denumire) VALUES
  ('11111111-1111-1111-1111-111111111111', 'Cabinet Alpha'),
  ('22222222-2222-2222-2222-222222222222', 'Cabinet Beta');

INSERT INTO firme (id, cabinet_id, cui, denumire) VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'RO111', 'Firma A (Alpha)'),
  ('aaaaaaaa-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'RO222', 'Firma B (Alpha)'),
  ('bbbbbbbb-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'RO333', 'Firma C (Beta)');

INSERT INTO utilizatori (id, cabinet_id, nume, email, parola_hash, rol) VALUES
  ('99999999-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'Admin Alpha',    'admin@alpha.ro',    'x', 'admin_cabinet'),
  ('99999999-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'Contabil Ana',   'ana@alpha.ro',      'x', 'contabil'),
  ('99999999-0000-0000-0000-000000000003', NULL,                                    'Client FirmaA',  'client@firma-a.ro', 'x', 'client_admin'),
  ('99999999-0000-0000-0000-000000000004', '22222222-2222-2222-2222-222222222222', 'Admin Beta',     'admin@beta.ro',     'x', 'admin_cabinet');

-- Ana e alocată DOAR la Firma A; clientul la Firma A
INSERT INTO utilizator_firma (utilizator_id, firma_id, rol_in_firma) VALUES
  ('99999999-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000001', 'contabil_alocat'),
  ('99999999-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-000000000001', 'reprezentant_client');

-- Conturi: Firma A are bancă + casă + card
INSERT INTO conturi_financiare (id, firma_id, tip, denumire, banca, iban) VALUES
  ('cccccccc-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'banca', 'ING RON', 'ING', 'RO49INGB0000999901'),
  ('cccccccc-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000001', 'casa',  'Casierie', NULL, NULL),
  ('cccccccc-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-000000000001', 'card',  'Revolut EUR', 'Revolut', 'RO49REVO0000999902');

-- Configurare Firma A: factura obligatorie, extras obligatoriu,
-- registru_casa obligatoriu, comanda NEOBLIGATORIE
INSERT INTO configurare_documente_firma (firma_id, tip_document_id, obligatoriu)
SELECT 'aaaaaaaa-0000-0000-0000-000000000001', id,
       CASE WHEN cod IN ('factura','extras_cont','registru_casa') THEN true ELSE false END
FROM tipuri_document WHERE cod IN ('factura','extras_cont','registru_casa','comanda');

INSERT INTO perioade_contabile (id, firma_id, luna, an) VALUES
  ('dddddddd-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 6, 2026);
