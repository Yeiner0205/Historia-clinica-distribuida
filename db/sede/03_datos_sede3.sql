-- ============================================================================
-- Datos sintéticos del sistema legado de la SEDE 3 (Corozal).
-- Tercera pieza de la historia del paciente 1001.
-- Los pacientes 1008 a 1011 llegan por el CSV legado durante la demostración.
-- ============================================================================

INSERT INTO profesional_salud (codigo, nombre, especialidad, registro_medico, entidad_salud) VALUES
    ('MED-01', 'Laura Vega Ortiz',  'Medicina interna', 'RM-10021', 'IPS Red Sabana - Sincelejo'),
    ('MED-02', 'Mateo Ruiz Barrios','Urgencias',        'RM-10045', 'IPS Red Sabana - Cartagena')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO usuario (documento_id, tipo_documento, nombre_completo, fecha_nacimiento, edad,
                     sexo, pais_nacionalidad, pais_residencia, municipio_residencia,
                     zona_residencia, ocupacion, sede_id, fhir_patient_id) VALUES
    (1001, 'CC', 'Carlos Perez Ruiz',   '1980-04-12', 46, 'M', 'CO', 'CO', '70001', 'Urbana', 'Conductor', 3, NULL),
    (1004, 'CC', 'Elena Vargas Pino',   '1989-06-05', 37, 'F', 'CO', 'CO', '70215', 'Rural',  'Docente',   3, NULL)
ON CONFLICT (documento_id) DO NOTHING;

INSERT INTO atencion (documento_id, sede_id, visita, entidad_salud, fecha_ingreso,
                      entorno_atencion, via_ingreso, causa_atencion, fecha_triage,
                      clasificacion_triage, profesional_codigo) VALUES
    (1001, 3, 'V-S3-0045', 'IPS Red Sabana - Corozal', '2026-08-20 14:05',
     'Consulta externa', 'Propio', 'Dolor lumbar cronico', '2026-08-20 14:10', '4', 'MED-01'),
    (1004, 3, 'V-S3-0046', 'IPS Red Sabana - Corozal', '2026-10-18 08:45',
     'Urgencias', 'Propio', 'Cefalea intensa',            '2026-10-18 08:50', '3', 'MED-01')
ON CONFLICT (visita) DO NOTHING;

INSERT INTO diagnostico (atencion_id, dx_local, cie10, descripcion_cie10,
                         tipo_diagnostico_ingreso, diagnostico_ingreso)
SELECT a.atencion_id, d.dx_local, d.cie10, d.descripcion, 'Impresion diagnostica', d.descripcion
  FROM atencion a
  JOIN (VALUES
        ('V-S3-0045', 'LUMBAGO', 'M54.5', 'Lumbago'),
        ('V-S3-0046', 'CEFALEA', 'R51',   'Cefalea')
       ) AS d(visita, dx_local, cie10, descripcion) ON a.visita = d.visita
ON CONFLICT DO NOTHING;

INSERT INTO observacion (atencion_id, documento_id, loinc, descripcion, valor, unidad, fecha)
SELECT a.atencion_id, a.documento_id, '2345-7', 'Glucosa', '105', 'mg/dL', a.fecha_ingreso
  FROM atencion a WHERE a.visita = 'V-S3-0046'
ON CONFLICT DO NOTHING;
