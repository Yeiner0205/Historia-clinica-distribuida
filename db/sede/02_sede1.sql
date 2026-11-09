-- Identidad del nodo: sede 1 — Sincelejo
INSERT INTO sede_info (sede_id, codigo, nombre, municipio)
VALUES (1, 'SEDE1', 'Sincelejo', '70001')
ON CONFLICT (sede_id) DO UPDATE SET nombre = EXCLUDED.nombre;

ALTER TABLE usuario  ALTER COLUMN sede_id SET DEFAULT 1;
ALTER TABLE atencion ALTER COLUMN sede_id SET DEFAULT 1;
