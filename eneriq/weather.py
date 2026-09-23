"""Cliente de clima via Open-Meteo (sin API key)."""
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


def pronostico_manana_c() -> list[float]:
    """Temperaturas horarias pronosticadas para el dia siguiente (24 valores)."""
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
