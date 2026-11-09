-- ============================================================================
-- Datos sintéticos del sistema legado de la SEDE 1 (Sincelejo).
-- PROHIBIDO cargar datos reales de pacientes (regla del parcial).
--
-- Todos los pacientes entran con fhir_patient_id NULL: la cobertura FHIR de
-- la sede arranca en 0 % y sube cuando el HSB los normaliza.
-- El paciente 1001 tiene atenciones en las tres sedes: es el caso de la
-- consulta unificada.
-- ============================================================================

INSERT INTO profesional_salud (codigo, nombre, especialidad, registro_medico, entidad_salud) VALUES
    ('MED-01', 'Laura Vega Ortiz',  'Medicina interna', 'RM-10021', 'IPS Red Sabana - Sincelejo'),
    ('MED-02', 'Mateo Ruiz Barrios','Urgencias',        'RM-10045', 'IPS Red Sabana - Cartagena')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO usuario (documento_id, tipo_documento, nombre_completo, fecha_nacimiento, edad,
                     sexo, pais_nacionalidad, pais_residencia, municipio_residencia,
                     zona_residencia, ocupacion, sede_id, fhir_patient_id) VALUES
    (1001, 'CC', 'Carlos Perez Ruiz',   '1980-04-12', 46, 'M', 'CO', 'CO', '70001', 'Urbana', 'Conductor',  1, NULL),
    (1002, 'CC', 'Marta Gomez Tovar',   '1975-09-30', 51, 'F', 'CO', 'CO', '70001', 'Urbana', 'Comerciante',1, NULL),
    (1005, 'TI', 'Andres Lora Diaz',    '2001-03-17', 25, 'M', 'CO', 'CO', '70001', 'Rural',  'Estudiante', 1, NULL)
ON CONFLICT (documento_id) DO NOTHING;

INSERT INTO atencion (documento_id, sede_id, visita, entidad_salud, fecha_ingreso,
                      entorno_atencion, via_ingreso, causa_atencion, fecha_triage,
                      clasificacion_triage, profesional_codigo) VALUES
    (1001, 1, 'V-S1-0150', 'IPS Red Sabana - Sincelejo', '2026-10-02 08:20',
     'Urgencias', 'Remitido',  'Cefalea y cifras tensionales altas', '2026-10-02 08:25', '2', 'MED-01'),
    (1002, 1, 'V-S1-0151', 'IPS Red Sabana - Sincelejo', '2026-10-05 10:00',
     'Consulta externa', 'Propio', 'Tos y fiebre de 3 dias',          '2026-10-05 10:05', '3', 'MED-01'),
    (1005, 1, 'V-S1-0152', 'IPS Red Sabana - Sincelejo', '2026-10-11 15:40',
     'Consulta externa', 'Propio', 'Control de cefalea',              NULL,               '4', 'MED-02')
ON CONFLICT (visita) DO NOTHING;

INSERT INTO diagnostico (atencion_id, dx_local, cie10, descripcion_cie10,
                         tipo_diagnostico_ingreso, diagnostico_ingreso)
SELECT a.atencion_id, d.dx_local, d.cie10, d.descripcion, 'Impresion diagnostica', d.descripcion
  FROM atencion a
  JOIN (VALUES
        ('V-S1-0150', 'HIPERTENSION', 'I10',   'Hipertension esencial'),
        ('V-S1-0151', 'NEUMONIA',     'J18.9', 'Neumonia'),
        ('V-S1-0152', 'CEFALEA',      'R51',   'Cefalea')
       ) AS d(visita, dx_local, cie10, descripcion) ON a.visita = d.visita
ON CONFLICT DO NOTHING;

INSERT INTO observacion (atencion_id, documento_id, loinc, descripcion, valor, unidad, fecha)
SELECT a.atencion_id, a.documento_id, o.loinc, o.descripcion, o.valor, o.unidad, a.fecha_ingreso
  FROM atencion a
  JOIN (VALUES
        -- La hemoglobina de la visita V-S1-0150 NO viene en el legado: llega
        -- por el mensaje ORU^R01 de ejemplo (718-7 = 13,8 g/dL).
        ('V-S1-0150', '8480-6', 'Tension arterial sistolica',   '158',  'mm[Hg]'),
        ('V-S1-0151', '6690-2', 'Leucocitos',                   '12.4', '10*3/uL')
       ) AS o(visita, loinc, descripcion, valor, unidad) ON a.visita = o.visita
ON CONFLICT DO NOTHING;

INSERT INTO tecnologia_salud (atencion_id, descripcion_medicamento, dosis, via_administracion,
                              frecuencia, dias_tratamiento, unidades_aplicadas, finalidad_tecnologia)
SELECT a.atencion_id, 'Losartan 50 mg', '50 mg', 'Oral', 'Cada 24 horas', 30, 30, 'Control de hipertension'
  FROM atencion a WHERE a.visita = 'V-S1-0150';
