-- ============================================================================
-- Datos sintéticos del sistema legado de la SEDE 2 (Cartagena).
-- El paciente 1001 también se atendió aquí: su historia está fraccionada.
-- El paciente 1007 NO está cargado a propósito: lo crea el mensaje
-- ejemplos/01_adt_a01_valido_sede2.hl7 durante la demostración.
-- ============================================================================

INSERT INTO profesional_salud (codigo, nombre, especialidad, registro_medico, entidad_salud) VALUES
    ('MED-01', 'Laura Vega Ortiz',  'Medicina interna', 'RM-10021', 'IPS Red Sabana - Sincelejo'),
    ('MED-02', 'Mateo Ruiz Barrios','Urgencias',        'RM-10045', 'IPS Red Sabana - Cartagena')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO usuario (documento_id, tipo_documento, nombre_completo, fecha_nacimiento, edad,
                     sexo, pais_nacionalidad, pais_residencia, municipio_residencia,
                     zona_residencia, ocupacion, sede_id, fhir_patient_id) VALUES
    (1001, 'CC', 'Carlos Perez Ruiz',  '1980-04-12', 46, 'M', 'CO', 'CO', '70001', 'Urbana', 'Conductor',   2, NULL),
    (1003, 'CC', 'Jorge Salcedo Mora', '1968-01-22', 58, 'M', 'CO', 'CO', '13001', 'Urbana', 'Pescador',    2, NULL),
    (1006, 'CC', 'Paula Nino Arrieta', '1993-11-08', 33, 'F', 'CO', 'CO', '13001', 'Urbana', 'Enfermera',   2, NULL)
ON CONFLICT (documento_id) DO NOTHING;

INSERT INTO atencion (documento_id, sede_id, visita, entidad_salud, fecha_ingreso,
                      entorno_atencion, via_ingreso, causa_atencion, fecha_triage,
                      clasificacion_triage, profesional_codigo) VALUES
    (1001, 2, 'V-S2-0090', 'IPS Red Sabana - Cartagena', '2026-09-15 07:10',
     'Urgencias', 'Propio', 'Poliuria y perdida de peso', '2026-09-15 07:15', '2', 'MED-02'),
    (1003, 2, 'V-S2-0091', 'IPS Red Sabana - Cartagena', '2026-09-28 11:30',
     'Consulta externa', 'Propio', 'Ardor al orinar',      '2026-09-28 11:35', '3', 'MED-02'),
    (1006, 2, 'V-S2-0092', 'IPS Red Sabana - Cartagena', '2026-10-09 09:00',
     'Consulta externa', 'Propio', 'Dolor lumbar',          NULL,              '4', 'MED-01')
ON CONFLICT (visita) DO NOTHING;

INSERT INTO diagnostico (atencion_id, dx_local, cie10, descripcion_cie10,
                         tipo_diagnostico_ingreso, diagnostico_ingreso)
SELECT a.atencion_id, d.dx_local, d.cie10, d.descripcion, 'Impresion diagnostica', d.descripcion
  FROM atencion a
  JOIN (VALUES
        ('V-S2-0090', 'DIABETES',           'E11.9', 'Diabetes mellitus tipo 2'),
        ('V-S2-0091', 'INFECCION URINARIA', 'N39.0', 'Infeccion de vias urinarias'),
        ('V-S2-0092', 'LUMBAGO',            'M54.5', 'Lumbago')
       ) AS d(visita, dx_local, cie10, descripcion) ON a.visita = d.visita
ON CONFLICT DO NOTHING;

INSERT INTO observacion (atencion_id, documento_id, loinc, descripcion, valor, unidad, fecha)
SELECT a.atencion_id, a.documento_id, o.loinc, o.descripcion, o.valor, o.unidad, a.fecha_ingreso
  FROM atencion a
  JOIN (VALUES
        ('V-S2-0090', '2345-7', 'Glucosa',   '186',  'mg/dL'),
        ('V-S2-0090', '718-7',  'Hemoglobina','13.1','g/dL')
       ) AS o(visita, loinc, descripcion, valor, unidad) ON a.visita = o.visita
ON CONFLICT DO NOTHING;

INSERT INTO egreso (atencion_id, fecha_salida, condicion_salida, codigo_prestador, responsable_egreso)
SELECT a.atencion_id, '2026-09-15 16:40', 'Mejoria', '13001-02', 'Mateo Ruiz Barrios'
  FROM atencion a WHERE a.visita = 'V-S2-0090';
