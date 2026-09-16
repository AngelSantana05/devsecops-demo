# devsecops-demo

Simulación de gestión segura de un bucket de almacenamiento compatible con S3
(vía [LocalStack](https://www.localstack.cloud/)), usada como base para una
auditoría de seguridad DevSecOps: SAST ([Bandit](https://bandit.readthedocs.io/)),
SCA ([pip-audit](https://pypi.org/project/pip-audit/)) y secret scanning
([Gitleaks](https://github.com/gitleaks/gitleaks)) integrados como quality
gate en CI (GitHub Actions).

Proyecto final — materia *Herramientas de tecnologías de la información*,
Tecmilenio. El plan de auditoría completo y el informe con los hallazgos
reales están en [`REPORTE_FINAL.md`](REPORTE_FINAL.md).

**Este repo también hospeda [`eneriq/`](eneriq/)**, la aplicación real del
proyecto EnerIQ (orquestador de energía/automatización doméstica sobre Home
Assistant) — la metodología de auditoría de arriba (Bandit/pip-audit/
Gitleaks/CI) se aplica también a ese código. Ver la sección
["EnerIQ"](#eneriq) más abajo.

## Estructura

```
app-ejemplo/           codigo de la aplicacion (gestion del bucket S3)
  config_malo.py         config de acceso (credenciales via variables de entorno)
  s3_bucket_manager.py    crear bucket / subir / listar / respaldo local
  demo_flujo.py           script de demo end-to-end
scripts/
  scan_secrets.py         escaner casero de secretos (arbol de trabajo, no historial)
  gatekeeper.py            puerta de control dev->production (secretos + politica)
infra/
  bucket_policy_publico.json   Caso 1 (malo): acceso publico, no se usa en el flujo real
  bucket_policy_privado.json   Caso 2 (bueno): politica que gatekeeper.py valida
reports/                evidencias de las corridas de Bandit/pip-audit/Gitleaks
.github/workflows/      pipeline de CI (security-audit.yml)
pipeline_audit.log      bitacora de cada corrida de gatekeeper.py
REPORTE_FINAL.md        informe completo de la auditoria (hallazgos, remediacion, CI)
```

## Cómo correr la demo localmente

Requiere Docker.

```bash
docker compose up -d          # levanta LocalStack (S3 en :4566)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd app-ejemplo && python3 demo_flujo.py
```

## Cómo correr la auditoría localmente

```bash
python3 -m venv .venv-audit && source .venv-audit/bin/activate
pip install -r requirements-audit.txt

bandit -r app-ejemplo scripts -f json -o reports/bandit-report.json   # SAST, reporte completo
bandit -r app-ejemplo scripts -lll                                     # SAST, gate (solo alta severidad)
pip-audit -r requirements.txt -f json -o reports/pip-audit-report.json # SCA

# Gitleaks es un binario Go, no un paquete pip -- instalar desde
# https://github.com/gitleaks/gitleaks/releases (pineado a v8.21.2 en este repo)
gitleaks detect --source . -v --report-format json --report-path reports/gitleaks-report.json

python3 scripts/gatekeeper.py   # puerta de control local (secretos + politica de bucket)
```

El pipeline de CI (`.github/workflows/security-audit.yml`) corre exactamente
estos mismos comandos en cada push a `dev`/`production` y en cada PR hacia
`production`. Ver `REPORTE_FINAL.md` sección de evidencia de pipeline para
las corridas reales.

## Generar/empaquetar esto para otros usuarios

Este repo es una demostración académica, no un producto instalable de un
clic -- reproducirlo completo requiere que otro usuario tenga: Docker (para
LocalStack), Python 3.12+, y una cuenta de GitHub con Actions habilitado si
quiere ver el pipeline correr. No existe (ni tiene sentido crear) un
instalador/paquete `pip install devsecops-demo` porque el valor del proyecto
no es la app en sí (`app-ejemplo/` es deliberadamente mínima) sino el
**proceso de auditoría** alrededor de ella.

Para adaptar este mismo proceso a un proyecto Python real:

1. **Cambios obligatorios** (sin esto no corre):
   - Reemplazar `requirements.txt` por las dependencias reales del proyecto.
   - Ajustar las rutas en `.github/workflows/security-audit.yml`
     (`bandit -r app-ejemplo scripts`) a los directorios de código reales.
   - Si el proyecto ya tiene historial de git con secretos reales expuestos y
     removidos, **rotar esas credenciales antes de correr Gitleaks por
     primera vez** -- Gitleaks los va a encontrar (es el propósito), pero
     encontrarlos no los invalida.
2. **Cambios recomendados** (mejoran la señal, no son obligatorios):
   - Adaptar `scripts/gatekeeper.py` si el proyecto no usa buckets S3 --
     la lógica de "secretos + política de infraestructura" es genérica,
     pero el chequeo de `bucket_policy_privado.json` es específico de este
     demo.
   - Fijar (`pin`) las versiones de Bandit/pip-audit/Gitleaks en
     `requirements-audit.txt` a las mismas que use el equipo, no las últimas
     -- evita que un hallazgo nuevo aparezca por un upgrade silencioso de
     la herramienta en vez de por un cambio real de código.
3. **Complejidad de adopción:** baja para un repo Python con `requirements.txt`
   estándar (es prácticamente copiar `.github/workflows/security-audit.yml`
   + `requirements-audit.txt` y ajustar las dos rutas del paso 1). Sube si el
   proyecto usa otro gestor de paquetes (Poetry/Pipenv -- pip-audit soporta
   ambos exportando a `requirements.txt` primero, o usando `pip-audit` sin
   `-r` sobre el entorno ya instalado) o si el equipo quiere que el gate
   bloquee severidades más bajas que "alta" (requiere decidir un umbral de
   tolerancia a ruido, ver `REPORTE_FINAL.md` sección de remediación).

## Nota sobre las credenciales de ejemplo

`config_malo.py` en el historial de git (commit inicial) contiene una
credencial de AWS **sintética, generada para esta demo** -- no es una clave
real, no está asociada a ninguna cuenta de AWS, y su único propósito es que
coincida con el patrón que Bandit/Gitleaks buscan. Si GitHub marca una alerta
de secret scanning sobre este repo, es exactamente el comportamiento
esperado (y parte de la evidencia de la auditoría).

## EnerIQ

Orquestador de energía y automatización doméstica: cruza tarifa eléctrica
(CFE DAC, modelada localmente), clima ([Open-Meteo](https://open-meteo.com/))
e historial de consumo para decidir cuándo encender/esperar el aire
acondicionado, detectar anomalías de consumo, priorizar qué apagar si se
acerca el presupuesto mensual, y generar un plan del día siguiente. Corre de
verdad, en producción, en el homelab del autor -- no es solo un mockup.

### Arquitectura desplegada

- **Backend:** Python (`eneriq/`), FastAPI (`main.py`, solo `127.0.0.1:8091`,
  no expuesto a la LAN) + 3 jobs por systemd timer:
  `ingest.py` (telemetría, cada 5 min) · `decide.py` (motor de decisión AC +
  anomalías, cada 15 min) · `schedule_daily.py` (plan del día siguiente,
  04:30 AM). Ver `eneriq/systemd/`.
- **Base de datos:** PostgreSQL 17 + TimescaleDB (hypertable `telemetry`).
- **Salida hacia Home Assistant:** sensores "push" vía la API REST de HA
  (`sensor.eneriq_decision_ac`, `sensor.eneriq_anomalias`,
  `sensor.eneriq_bitacora`, `sensor.eneriq_plan_manana`) + panel en el
  dashboard de HA (sección "EnerIQ", 4 tarjetas con pop-up de detalle).
- **Control real del AC:** ya existe una automatización IR real en HA
  (`remote.papu_aire_v`, scripts `encender_aire`/`apagar_aire`) -- el motor
  de decisión llama esos scripts, pero **`auto_control_enabled` arranca en
  `false`** en la tabla `devices`: por defecto solo registra/alerta, nunca
  prende el AC solo. Se activa manualmente cuando se confirme el
  comportamiento: `UPDATE devices SET auto_control_enabled = true WHERE id = 'ac';`

### Sobre el enchufe inteligente pendiente

La telemetría de consumo/temperatura interior es **simulada pero
etiquetada como tal** (`fuente = 'simulada'` en la base de datos) mientras
no exista un sensor real. En cuanto se conecte el enchufe:

```sql
UPDATE devices SET ha_entity_id = 'sensor.<tu_enchufe>_power' WHERE id = 'ac';
```

No hace falta tocar ningún código -- `telemetry_source.py` ya intenta leer
de ese `ha_entity_id` primero y solo cae a simulación si no existe o no
responde.

### Motor de decisiones (lógica propia, con pruebas)

`eneriq/decision_engine/` -- 4 módulos, 12 pruebas con pytest
(`eneriq/tests/`), sin dependencias externas:

- `ac_decision.py` -- ¿encender el AC ahora o esperar a tarifa base?
- `anomaly_detection.py` -- ¿el consumo actual es anómalo vs. su histórico?
- `load_priority.py` -- ¿qué apagar primero si se excede el presupuesto?
- `scheduler.py` -- plan de 24h cruzando pronóstico de clima + tarifa.

### Cómo correrlo / reproducirlo

```bash
cd eneriq
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python3 -m pytest tests/ -v          # el motor de decision no necesita BD

cp .env.example .env                  # llenar credenciales de Postgres + token de HA
psql -d eneriq -f schema.sql          # requiere Postgres con extension timescaledb

python3 ingest.py                     # una corrida manual de cada job
python3 decide.py
python3 schedule_daily.py
uvicorn main:app --reload --port 8091 # API de solo lectura, para inspeccionar
```
