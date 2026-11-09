-- ============================================================================
-- Almacén central de la plataforma (base `hsb`).
--
-- Aquí viven las tres tablas que el parcial pide añadir al modelo del
-- repositorio de referencia:
--   * mensaje_bus       → cola del HSB con estado, intentos e idempotencia
--   * evento_auditoria  → auditoría encadenada por hash
--   * ref_terminologia  → diagnóstico local → CIE-10 (tabla de referencia)
--
-- Está fuera de las sedes a propósito: si una sede cae, el bus sigue
-- recibiendo y la auditoría sigue registrando.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ───────────────────────── Cola de mensajes del bus ─────────────────────────
-- Estados (coinciden con el diagrama de estados de la Fase 1):
--   recibido → validado → transformado → entregado
--                      ↘ rechazado
--            entregado ↙ reintentando → muerto
CREATE TABLE IF NOT EXISTS mensaje_bus (
    mensaje_id          BIGSERIAL PRIMARY KEY,
    -- Clave de idempotencia: MSH-10 del HL7 o SHA-256 de la fila del CSV.
    -- El UNIQUE es lo que impide que el mismo mensaje entre dos veces, y
    -- sobrevive al reinicio del bus (no es una caché en memoria).
    clave_idempotencia  VARCHAR(128) NOT NULL UNIQUE,
    origen              VARCHAR(60),
    sede_id             INT,
    formato             VARCHAR(20)  NOT NULL,   -- hl7v2 | csv
    tipo                VARCHAR(20),             -- ADT^A01 | ORU^R01 | CSV | LEGADO
    documento           VARCHAR(20),
    estado              VARCHAR(20)  NOT NULL DEFAULT 'recibido',
    intentos            INT          NOT NULL DEFAULT 0,
    max_intentos        INT          NOT NULL DEFAULT 4,
    proximo_intento     TIMESTAMPTZ,
    motivos             JSONB        DEFAULT '[]'::jsonb,
    payload             TEXT,
    registro            JSONB,
    bundle              JSONB,
    recursos            JSONB        DEFAULT '[]'::jsonb,
    ultimo_error        TEXT,
    recibido_en         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actualizado_en      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    entregado_en        TIMESTAMPTZ,
    latencia_ms         INT,
    CONSTRAINT ck_mensaje_estado CHECK (estado IN
        ('recibido','validado','transformado','entregado','rechazado','reintentando','muerto'))
);

CREATE INDEX IF NOT EXISTS idx_mensaje_estado    ON mensaje_bus (estado);
CREATE INDEX IF NOT EXISTS idx_mensaje_sede      ON mensaje_bus (sede_id);
CREATE INDEX IF NOT EXISTS idx_mensaje_documento ON mensaje_bus (documento);
CREATE INDEX IF NOT EXISTS idx_mensaje_pendiente ON mensaje_bus (proximo_intento)
    WHERE estado IN ('recibido','validado','transformado','reintentando');

-- Cola de mensajes muertos: los que agotaron los reintentos.
CREATE OR REPLACE VIEW cola_mensajes_muertos AS
    SELECT mensaje_id, clave_idempotencia, formato, tipo, sede_id, documento,
           intentos, ultimo_error, recibido_en, actualizado_en
      FROM mensaje_bus
     WHERE estado = 'muerto'
     ORDER BY actualizado_en DESC;

-- ──────────────────── Auditoría encadenada por hash (RF5) ───────────────────
CREATE TABLE IF NOT EXISTS evento_auditoria (
    evento_id      BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actor          VARCHAR(120) NOT NULL,   -- quién
    rol            VARCHAR(40),
    accion         VARCHAR(80)  NOT NULL,   -- qué
    recurso        VARCHAR(200),            -- sobre qué
    resultado      VARCHAR(20)  NOT NULL,   -- cómo terminó
    detalle        JSONB        DEFAULT '{}'::jsonb,
    hash_anterior  CHAR(64)     NOT NULL,
    hash           CHAR(64)     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auditoria_actor   ON evento_auditoria (actor);
CREATE INDEX IF NOT EXISTS idx_auditoria_recurso ON evento_auditoria (recurso);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts      ON evento_auditoria (ts DESC);

-- ───────────────── Terminologías: diagnóstico local → CIE-10 ────────────────
CREATE TABLE IF NOT EXISTS ref_terminologia (
    dx_local    VARCHAR(120) PRIMARY KEY,
    cie10       VARCHAR(10)  NOT NULL,
    descripcion VARCHAR(255) NOT NULL,
    fuente      VARCHAR(60)  DEFAULT 'ejemplos/05_ref_terminologia.csv',
    creado_en   TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO ref_terminologia (dx_local, cie10, descripcion) VALUES
    ('DIARREA',            'A09',   'Diarrea y gastroenteritis'),
    ('HIPERTENSION',       'I10',   'Hipertensión esencial'),
    ('DIABETES',           'E11.9', 'Diabetes mellitus tipo 2'),
    ('ASMA',               'J45.9', 'Asma'),
    ('INFECCION URINARIA', 'N39.0', 'Infección de vías urinarias'),
    ('LUMBAGO',            'M54.5', 'Lumbago'),
    ('NEUMONIA',           'J18.9', 'Neumonía'),
    ('CEFALEA',            'R51',   'Cefalea')
ON CONFLICT (dx_local) DO NOTHING;

-- Pruebas de laboratorio locales → LOINC
CREATE TABLE IF NOT EXISTS ref_loinc (
    prueba_local VARCHAR(120) PRIMARY KEY,
    loinc        VARCHAR(20)  NOT NULL,
    descripcion  VARCHAR(255) NOT NULL,
    unidad       VARCHAR(30)
);

INSERT INTO ref_loinc (prueba_local, loinc, descripcion, unidad) VALUES
    ('HEMOGLOBINA',                '718-7',  'Hemoglobin [Mass/volume] in Blood', 'g/dL'),
    ('GLUCOSA',                    '2345-7', 'Glucose [Mass/volume] in Serum or Plasma', 'mg/dL'),
    ('CREATININA',                 '2160-0', 'Creatinine [Mass/volume] in Serum or Plasma', 'mg/dL'),
    ('LEUCOCITOS',                 '6690-2', 'Leukocytes [#/volume] in Blood', '10*3/uL'),
    ('PLAQUETAS',                  '777-3',  'Platelets [#/volume] in Blood', '10*3/uL'),
    ('TENSION ARTERIAL SISTOLICA', '8480-6', 'Systolic blood pressure', 'mm[Hg]'),
    ('TEMPERATURA',                '8310-5', 'Body temperature', 'Cel')
ON CONFLICT (prueba_local) DO NOTHING;

-- ───────────────── Métricas de extremo a extremo del bus ────────────────────
CREATE OR REPLACE VIEW metricas_bus AS
    SELECT estado,
           COUNT(*)::int                                   AS total,
           ROUND(AVG(latencia_ms)::numeric, 1)             AS latencia_media_ms,
           MAX(actualizado_en)                             AS ultimo_cambio
      FROM mensaje_bus
     GROUP BY estado;

-- ──────────── Contadores del bus que no se derivan de mensaje_bus ───────────
-- (duplicados detectados, mensajes reencolados: sobreviven al reinicio)
CREATE TABLE IF NOT EXISTS contador_hsb (
    nombre VARCHAR(60) PRIMARY KEY,
    valor  BIGINT NOT NULL DEFAULT 0
);

INSERT INTO contador_hsb (nombre, valor) VALUES
    ('duplicados_detectados', 0),
    ('reencolados', 0),
    ('mensajes_recibidos', 0)
ON CONFLICT (nombre) DO NOTHING;
