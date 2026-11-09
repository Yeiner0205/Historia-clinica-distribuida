-- ============================================================================
-- Esquema del sistema legado de UNA sede (se aplica igual a las tres).
--
-- Parte de las tablas del repositorio de referencia (usuario, atencion,
-- tecnologia_salud, diagnostico, egreso, profesional_salud) y añade lo que
-- pide el parcial:
--   * observacion      → resultados de laboratorio (Observation / LOINC)
--   * cie10            → diagnóstico codificado (Condition)
--   * fhir_*_id        → vínculo con el recurso FHIR (cobertura de migración)
--   * sede_id, visita  → trazabilidad de la sede y del encuentro
--
-- Las tablas de la plataforma (mensaje_bus, evento_auditoria,
-- ref_terminologia) NO viven aquí: están en el almacén central, para que el
-- bus y la auditoría sigan en pie si una sede cae.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Identidad de la sede (la fija el script 02_sede*.sql de cada nodo)
CREATE TABLE IF NOT EXISTS sede_info (
    sede_id      INT PRIMARY KEY,
    codigo       VARCHAR(10)  NOT NULL,
    nombre       VARCHAR(100) NOT NULL,
    municipio    VARCHAR(100),
    actualizado  TIMESTAMP DEFAULT NOW()
);

-- ─────────────────────────────── Pacientes ──────────────────────────────────
CREATE TABLE IF NOT EXISTS usuario (
    documento_id            BIGINT PRIMARY KEY,
    tipo_documento          VARCHAR(10),
    pais_nacionalidad       VARCHAR(100),
    nombre_completo         VARCHAR(255) NOT NULL,
    fecha_nacimiento        DATE,
    edad                    INT,
    unidad_edad             VARCHAR(5)   DEFAULT '1',
    sexo                    VARCHAR(10),
    genero                  VARCHAR(50),
    ocupacion               VARCHAR(100),
    voluntad_anticipada     BOOLEAN      DEFAULT FALSE,
    categoria_discapacidad  VARCHAR(50),
    pais_residencia         VARCHAR(100),
    municipio_residencia    VARCHAR(100),
    etnia                   VARCHAR(50),
    comunidad_etnica        VARCHAR(100),
    zona_residencia         VARCHAR(50),
    sede_id                 INT,
    -- NULL = el paciente todavía no fue normalizado a FHIR.
    -- La cobertura FHIR por sede es COUNT(fhir_patient_id)/COUNT(*).
    fhir_patient_id         VARCHAR(64),
    created_at              TIMESTAMP    DEFAULT NOW(),
    updated_at              TIMESTAMP    DEFAULT NOW()
);

-- La clave de distribución es el documento del paciente: es la columna por la
-- que consultan todas las vistas (historia de un paciente), así que el índice
-- y la fragmentación coinciden con el patrón de acceso.
CREATE INDEX IF NOT EXISTS idx_usuario_nombre ON usuario (LOWER(nombre_completo));
CREATE INDEX IF NOT EXISTS idx_usuario_fhir   ON usuario (fhir_patient_id);

-- Alias con el nombre que usa el laboratorio de las 3 sedes.
CREATE OR REPLACE VIEW pacientes AS
    SELECT documento_id AS documento,
           tipo_documento,
           nombre_completo,
           fecha_nacimiento,
           sexo,
           sede_id,
           fhir_patient_id
      FROM usuario;

-- ─────────────────────────────── Atenciones ─────────────────────────────────
CREATE TABLE IF NOT EXISTS atencion (
    atencion_id          SERIAL PRIMARY KEY,
    documento_id         BIGINT NOT NULL,
    sede_id              INT,
    visita               VARCHAR(40),
    entidad_salud        VARCHAR(255),
    fecha_ingreso        TIMESTAMP,
    modalidad_entrega    VARCHAR(50),
    entorno_atencion     VARCHAR(50),
    via_ingreso          VARCHAR(50),
    causa_atencion       TEXT,
    fecha_triage         TIMESTAMP,
    clasificacion_triage VARCHAR(10),
    profesional_codigo   VARCHAR(20),
    mensaje_id           BIGINT,
    fhir_encounter_id    VARCHAR(64),
    created_at           TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (documento_id) REFERENCES usuario(documento_id)
);

-- El número de visita identifica el encuentro en el sistema legado: con él la
-- reentrega del mismo mensaje actualiza la fila en lugar de crear otra.
-- El índice no es parcial a propósito: PostgreSQL trata los NULL como
-- distintos, así que admite atenciones sin visita, y `ON CONFLICT (visita)`
-- puede inferirlo (con un índice parcial habría que repetir su predicado).
CREATE UNIQUE INDEX IF NOT EXISTS uq_atencion_visita ON atencion (visita);
CREATE INDEX IF NOT EXISTS idx_atencion_documento ON atencion (documento_id);

-- ──────────────────────────── Tecnologías en salud ──────────────────────────
CREATE TABLE IF NOT EXISTS tecnologia_salud (
    tecnologia_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    atencion_id             INT,
    descripcion_medicamento VARCHAR(255),
    dosis                   VARCHAR(50),
    via_administracion      VARCHAR(50),
    frecuencia              VARCHAR(50),
    dias_tratamiento        INT,
    unidades_aplicadas      INT,
    id_personal_salud       UUID,
    finalidad_tecnologia    VARCHAR(255),
    created_at              TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (atencion_id) REFERENCES atencion(atencion_id)
);
CREATE INDEX IF NOT EXISTS idx_tecnologia_atencion ON tecnologia_salud (atencion_id);

-- ────────────────────────────── Diagnósticos ────────────────────────────────
CREATE TABLE IF NOT EXISTS diagnostico (
    diagnostico_id           SERIAL PRIMARY KEY,
    atencion_id              INT,
    -- Interoperabilidad semántica: el diagnóstico local queda, pero lo que
    -- viaja a FHIR es el CIE-10.
    dx_local                 VARCHAR(120),
    cie10                    VARCHAR(10),
    descripcion_cie10        VARCHAR(255),
    tipo_diagnostico_ingreso VARCHAR(50),
    diagnostico_ingreso      VARCHAR(255),
    tipo_diagnostico_egreso  VARCHAR(50),
    diagnostico_egreso       VARCHAR(255),
    diagnostico_rel1         VARCHAR(255),
    diagnostico_rel2         VARCHAR(255),
    diagnostico_rel3         VARCHAR(255),
    fhir_condition_id        VARCHAR(64),
    created_at               TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (atencion_id) REFERENCES atencion(atencion_id)
);
CREATE INDEX IF NOT EXISTS idx_diagnostico_atencion ON diagnostico (atencion_id);
-- Un diagnóstico CIE-10 por atención: la reentrega actualiza, no duplica.
CREATE UNIQUE INDEX IF NOT EXISTS uq_diagnostico_atencion_cie10
    ON diagnostico (atencion_id, cie10);

-- ───────────────────── Observaciones / laboratorio (LOINC) ──────────────────
CREATE TABLE IF NOT EXISTS observacion (
    observacion_id      SERIAL PRIMARY KEY,
    atencion_id         INT,
    documento_id        BIGINT,
    loinc               VARCHAR(20),
    descripcion         VARCHAR(255),
    valor               VARCHAR(60),
    unidad              VARCHAR(30),
    fecha               TIMESTAMP,
    fhir_observation_id VARCHAR(64),
    created_at          TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (atencion_id) REFERENCES atencion(atencion_id)
);
CREATE INDEX IF NOT EXISTS idx_observacion_documento ON observacion (documento_id);
-- Un resultado por prueba LOINC y atención: la reentrega actualiza el valor.
CREATE UNIQUE INDEX IF NOT EXISTS uq_observacion_atencion_loinc
    ON observacion (atencion_id, loinc);

-- ──────────────────────────────── Egreso ────────────────────────────────────
CREATE TABLE IF NOT EXISTS egreso (
    egreso_id             SERIAL PRIMARY KEY,
    atencion_id           INT,
    fecha_salida          TIMESTAMP,
    condicion_salida      VARCHAR(100),
    diagnostico_muerte    VARCHAR(255),
    codigo_prestador      VARCHAR(20),
    tipo_incapacidad      VARCHAR(100),
    dias_incapacidad      INT,
    dias_lic_maternidad   INT,
    alergias              TEXT,
    antecedente_familiar  TEXT,
    riesgos_ocupacionales TEXT,
    responsable_egreso    VARCHAR(255),
    sello_integridad      VARCHAR(64),
    created_at            TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (atencion_id) REFERENCES atencion(atencion_id)
);
CREATE INDEX IF NOT EXISTS idx_egreso_atencion ON egreso (atencion_id);

-- ────────────────────────── Profesionales de salud ──────────────────────────
CREATE TABLE IF NOT EXISTS profesional_salud (
    id_personal_salud UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo            VARCHAR(20) UNIQUE,
    nombre            VARCHAR(255) NOT NULL,
    especialidad      VARCHAR(100),
    registro_medico   VARCHAR(50),
    entidad_salud     VARCHAR(255),
    email             VARCHAR(255),
    telefono          VARCHAR(50),
    activo            BOOLEAN   DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);
