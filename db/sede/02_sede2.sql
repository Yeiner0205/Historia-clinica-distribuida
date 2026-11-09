-- Identidad del nodo: sede 2 — Cartagena
INSERT INTO sede_info (sede_id, codigo, nombre, municipio)
VALUES (2, 'SEDE2', 'Cartagena', '13001')
ON CONFLICT (sede_id) DO UPDATE SET nombre = EXCLUDED.nombre;

ALTER TABLE usuario  ALTER COLUMN sede_id SET DEFAULT 2;
ALTER TABLE atencion ALTER COLUMN sede_id SET DEFAULT 2;
