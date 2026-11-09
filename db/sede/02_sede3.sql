-- Identidad del nodo: sede 3 — Corozal
INSERT INTO sede_info (sede_id, codigo, nombre, municipio)
VALUES (3, 'SEDE3', 'Corozal', '70215')
ON CONFLICT (sede_id) DO UPDATE SET nombre = EXCLUDED.nombre;

ALTER TABLE usuario  ALTER COLUMN sede_id SET DEFAULT 3;
ALTER TABLE atencion ALTER COLUMN sede_id SET DEFAULT 3;
