"""Cliente de clima via Open-Meteo (sin API key)."""
import math
import random
from datetime import date, timedelta

import requests

import config

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def temperatura_actual_c() -> float:
    """Temperatura exterior actual (C) para la ubicacion configurada."""
    resp = requests.get(
        BASE_URL,
        params={
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "current": "temperature_2m",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["current"]["temperature_2m"]


def pronostico_demo_c(fecha: date) -> list[float]:
    """Pronostico INVENTADO de un dia caluroso de Monterrey: ~27C de
    madrugada, ~37C a las 16h. Determinista por fecha (mismo dia -> mismos
    valores), asi el scheduler y el plan con meta ven el mismo pronostico."""
    rnd = random.Random(fecha.toordinal())
    extra = rnd.uniform(-1.0, 1.5)  # dias un poco mas o menos calurosos
    return [
        round(32.0 + extra + 5.0 * math.sin((h - 10) / 24 * 2 * math.pi) + rnd.uniform(-0.4, 0.4), 1)
        for h in range(24)
    ]


def pronostico_manana_c() -> list[float]:
    """Temperaturas horarias pronosticadas para el dia siguiente (24 valores)."""
    if config.DEMO_CLIMA:
        return pronostico_demo_c(date.today() + timedelta(days=1))
    resp = requests.get(
        BASE_URL,
        params={
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "hourly": "temperature_2m",
            "forecast_days": 2,
            # sin esto Open-Meteo regresa horas UTC y el plan queda corrido
            # respecto al horario punta local
            "timezone": config.TIMEZONE,
        },
        timeout=10,
    )
    resp.raise_for_status()
    datos = resp.json()["hourly"]["temperature_2m"]
    # El API regresa 48 horas (hoy + manana); las ultimas 24 son "manana".
    return datos[-24:]
