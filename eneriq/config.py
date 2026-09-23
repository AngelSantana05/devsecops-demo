"""Configuracion de EnerIQ, via variables de entorno (ver .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

DB_HOST = os.environ.get("ENERIQ_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("ENERIQ_DB_PORT", "5432"))
DB_NAME = os.environ.get("ENERIQ_DB_NAME", "eneriq")
DB_USER = os.environ.get("ENERIQ_DB_USER", "eneriq_app")
DB_PASSWORD = os.environ.get("ENERIQ_DB_PASSWORD", "")

# Ubicacion de la casa para el pronostico del clima (Open-Meteo, sin API key).
# Default: Monterrey, N.L. (misma localidad que define la Tarifa 1C de tariff.py).
LATITUDE = float(os.environ.get("ENERIQ_LAT", "25.6866"))
LONGITUDE = float(os.environ.get("ENERIQ_LON", "-100.3161"))

# Zona horaria de la casa -- el corte de dia/mes del consumo (escalones de
# tariff.py) y el pronostico del clima se interpretan en esta zona (el
# LXC/Postgres tambien la usan).
TIMEZONE = os.environ.get("ENERIQ_TZ", "America/Monterrey")

# --- Tarifa CFE (ver tariff.py) ---
# Mes en que arranca el verano de la Tarifa 1C (Nuevo Leon: abril).
VERANO_MES_INICIO = int(os.environ.get("ENERIQ_VERANO_MES_INICIO", "4"))
# Promedio mensual de consumo de los ultimos 12 meses (kWh), tal como viene en
# el historial del recibo de CFE. Sirve para saber que tan cerca esta la casa
# del limite DAC (850 kWh/mes en 1C). Default: valor de ejemplo para la demo.
CONSUMO_PROMEDIO_12M_KWH = float(os.environ.get("ENERIQ_CONSUMO_PROMEDIO_12M_KWH", "650"))

# --- Modo demo ---
# Pronostico inventado de un dia caluroso, por si el clima real no alcanza el
# umbral de confort. Apagado por default: se usa el pronostico real.
DEMO_CLIMA = os.environ.get("ENERIQ_DEMO_CLIMA", "0") == "1"
# Potencia del minisplit para modelar su consumo en el plan con meta de gasto
# (el enchufe de la fila 'ac' en realidad mide el servidor, ver memoria).
AC_POTENCIA_W = float(os.environ.get("ENERIQ_AC_POTENCIA_W", "1500"))

# Umbral de confort para el motor de decision del AC.
TEMP_CONFORT_MAX_C = float(os.environ.get("ENERIQ_TEMP_CONFORT_MAX", "26.0"))

# Presupuesto mensual (MXN) para la priorizacion de carga.
PRESUPUESTO_MENSUAL_MXN = float(os.environ.get("ENERIQ_PRESUPUESTO_MXN", "2500.0"))

# Home Assistant -- para publicar resultados y (opcionalmente) leer telemetria real.
HA_URL = os.environ.get("ENERIQ_HA_URL", "http://10.10.10.10:8123")
HA_TOKEN = os.environ.get("ENERIQ_HA_TOKEN", "")

# Umbral de anomalia: % por encima del promedio historico que dispara una alerta.
ANOMALIA_UMBRAL_PCT = float(os.environ.get("ENERIQ_ANOMALIA_UMBRAL_PCT", "30.0"))
