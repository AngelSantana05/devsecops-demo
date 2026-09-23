-- Modelo de datos de EnerIQ.
-- Correr una sola vez contra la base `eneriq` (ya tiene la extension timescaledb habilitada):
--   psql -d eneriq -f schema.sql

CREATE TABLE IF NOT EXISTS devices (
    id                   TEXT PRIMARY KEY,
    nombre               TEXT NOT NULL,
    tipo                 TEXT NOT NULL CHECK (tipo IN ('ac', 'enchufe', 'otro')),
    ha_entity_id         TEXT,              -- sensor de TELEMETRIA en HA (NULL = fuente simulada)
    control_on_service   TEXT,              -- servicio HA a llamar para "encender" (ej. 'script.encender_aire')
    control_off_service  TEXT,              -- servicio HA a llamar para "apagar" (ej. 'script.apagar_aire')
    auto_control_enabled BOOLEAN NOT NULL DEFAULT false,  -- si false: solo se registra/alerta, nunca se actua de verdad
    peso_prioridad       INTEGER NOT NULL DEFAULT 5,  -- 1 (sacrificar primero) - 10 (nunca apagar)
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS telemetry (
    tiempo          TIMESTAMPTZ NOT NULL,
    device_id       TEXT NOT NULL REFERENCES devices(id),
    consumo_w       DOUBLE PRECISION,       -- consumo instantaneo en watts
    temp_interior_c DOUBLE PRECISION,       -- solo aplica a dispositivos tipo 'ac'
    fuente          TEXT NOT NULL DEFAULT 'simulada' CHECK (fuente IN ('simulada', 'home_assistant'))
);
SELECT create_hypertable('telemetry', by_range('tiempo'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_telemetry_device ON telemetry (device_id, tiempo DESC);

CREATE TABLE IF NOT EXISTS tariffs (
    id              SERIAL PRIMARY KEY,
    nombre          TEXT NOT NULL,          -- ej. 'CFE DAC - base', 'CFE DAC - punta'
    hora_inicio     INTEGER NOT NULL CHECK (hora_inicio BETWEEN 0 AND 23),
    hora_fin        INTEGER NOT NULL CHECK (hora_fin BETWEEN 0 AND 23),
    precio_kwh_mxn  NUMERIC(6,3) NOT NULL,
    dias_semana     INTEGER[] NOT NULL DEFAULT '{0,1,2,3,4,5,6}'  -- 0=lunes .. 6=domingo
);

CREATE TABLE IF NOT EXISTS decisions_log (
    id              BIGSERIAL PRIMARY KEY,
    tiempo          TIMESTAMPTZ NOT NULL DEFAULT now(),
    device_id       TEXT NOT NULL REFERENCES devices(id),
    tipo_decision   TEXT NOT NULL CHECK (tipo_decision IN ('ac', 'anomalia', 'priorizacion', 'scheduling')),
    accion          TEXT NOT NULL,          -- 'encender' | 'esperar' | 'apagar' | 'alertar' | 'plan_generado'
    razon           TEXT NOT NULL,          -- explicacion legible, para auditoria
    datos           JSONB                   -- evidencia cruda que motivo la decision
);
CREATE INDEX IF NOT EXISTS idx_decisions_tiempo ON decisions_log (tiempo DESC);

CREATE TABLE IF NOT EXISTS schedules (
    id              BIGSERIAL PRIMARY KEY,
    fecha           DATE NOT NULL,
    device_id       TEXT NOT NULL REFERENCES devices(id),
    hora            INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    accion_sugerida TEXT NOT NULL CHECK (accion_sugerida IN ('encender', 'apagar', 'sin_cambio')),
    razon           TEXT NOT NULL,
    UNIQUE (fecha, device_id, hora)
);

CREATE TABLE IF NOT EXISTS goal_plans (
    id                   BIGSERIAL PRIMARY KEY,
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
    meta_gasto_mxn       NUMERIC(10,2) NOT NULL,
    uso_actual_mxn       NUMERIC(10,2) NOT NULL,   -- promedio real ultimos 7 dias
    gasto_proyectado_mxn NUMERIC(10,2) NOT NULL,   -- proyectado para manana siguiendo el plan
    ahorro_mxn           NUMERIC(10,2) NOT NULL,   -- uso_actual - gasto_proyectado (puede ser negativo)
    ahorro_pct           NUMERIC(6,2) NOT NULL,
    cumple_meta          BOOLEAN NOT NULL,
    plan_texto           TEXT NOT NULL,            -- explicacion del LLM
    perfil_json          JSONB                     -- consumo_w proyectado por hora (auditoria)
);
CREATE INDEX IF NOT EXISTS idx_goal_plans_creado ON goal_plans (creado_en DESC);

-- Dispositivo real: el AC ya se controla hoy via IR (remote.papu_aire_v, scripts
-- encender_aire/apagar_aire). auto_control_enabled arranca en FALSE a proposito --
-- el motor de decision corre, registra y publica en HA, pero NO prende/apaga el AC
-- de verdad hasta que se confirme manualmente:
--   UPDATE devices SET auto_control_enabled = true WHERE id = 'ac';
--
-- La TELEMETRIA (consumo/temp interior) sigue simulada hasta conectar el enchufe:
--   UPDATE devices SET ha_entity_id = 'sensor.<tu_enchufe>_power' WHERE id = 'ac';
INSERT INTO devices (id, nombre, tipo, ha_entity_id, control_on_service, control_off_service, auto_control_enabled, peso_prioridad)
VALUES ('ac', 'Aire acondicionado', 'ac', NULL, 'script.encender_aire', 'script.apagar_aire', false, 8)
ON CONFLICT (id) DO NOTHING;
