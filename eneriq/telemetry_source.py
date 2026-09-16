"""Fuente de telemetria por dispositivo.

Si `devices.ha_entity_id` apunta a un sensor real de Home Assistant (por
ejemplo el enchufe inteligente una vez conectado), se lee de ahi. Si no hay
entity_id configurado (o el sensor todavia no existe en HA), se genera una
lectura SIMULADA -- claramente marcada con `fuente='simulada'` en la base de
datos, nunca se hace pasar como dato real.

Para conectar el enchufe real: no hay que tocar este archivo, solo correr
en la base de datos:
    UPDATE devices SET ha_entity_id = 'sensor.<tu_enchufe>_power' WHERE id = 'ac_demo';
"""
import math
import random
import time

import requests

import config


def _leer_ha(entity_id: str) -> float | None:
    try:
        resp = requests.get(
            f"{config.HA_URL}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {config.HA_TOKEN}"},
            timeout=5,
        )
        resp.raise_for_status()
        estado = resp.json()["state"]
        return float(estado)
    except (requests.RequestException, KeyError, ValueError):
        return None


def _simular_consumo_w() -> float:
    """Curva de consumo simulada: mas alta al mediodia/tarde, con ruido."""
    hora = time.localtime().tm_hour
    base = 300 + 900 * max(0, math.sin((hora - 6) / 24 * 2 * math.pi))
    ruido = random.uniform(-50, 50)
    # 2% de probabilidad de un pico anomalo, para poder probar anomaly_detection.
    if random.random() < 0.02:
        base *= random.uniform(2.5, 4.0)
    return round(base + ruido, 1)


def _simular_temp_interior_c(temp_exterior_c: float) -> float:
    return round(temp_exterior_c - random.uniform(2.0, 5.0), 1)


def leer_telemetria(ha_entity_id: str | None, temp_exterior_c: float) -> dict:
    """Regresa {'consumo_w', 'temp_interior_c', 'fuente'} para un dispositivo.

    `ha_entity_id` es el sensor de TELEMETRIA (ej. el enchufe inteligente una
    vez conectado) -- no tiene relacion con como se controla el dispositivo.
    """
    if ha_entity_id:
        valor = _leer_ha(ha_entity_id)
        if valor is not None:
            return {
                "consumo_w": valor,
                "temp_interior_c": _simular_temp_interior_c(temp_exterior_c),
                "fuente": "home_assistant",
            }
    return {
        "consumo_w": _simular_consumo_w(),
        "temp_interior_c": _simular_temp_interior_c(temp_exterior_c),
        "fuente": "simulada",
    }
