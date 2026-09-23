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
from datetime import datetime

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


def simular_consumo_dispositivo_w(device_id: str, momento: datetime) -> float:
    """Perfil de DEMO por aparato (W), segun la hora local de `momento`.

    Inventado a proposito para que la demo tenga habitos realistas de una
    casa en Monterrey (lavadora y calentador electrico de tanque, los que mas
    kWh suman fuera del aire). Lo usa tanto la ingesta cada 5 min como
    demo_backfill.py (historial inventado), asi las dos cuadran.
    """
    h = momento.hour + momento.minute / 60.0
    dia = momento.weekday()  # 0 = lunes
    r = random.random

    if device_id == "refrigerador":
        # compresor ciclando; trabaja mas en la tarde (cocina caliente)
        ciclo = 0.35 + (0.15 if 13 <= h < 20 else 0.0)
        return round(45 + (140 if r() < ciclo else 0) + random.uniform(-5, 5), 1)

    if device_id == "lavadora":
        # lun/mie/sab/dom, al volver del trabajo
        if dia in (0, 2, 5, 6) and 19 <= h < 20.5:
            return round(random.uniform(450, 700) if h >= 20 else random.uniform(350, 550), 1)
        return 2.0

    if device_id == "calentador":
        # calentador electrico de tanque: regaderas en la manana y recuperacion
        # en la noche; fuera de eso solo mantiene temperatura
        if 6 <= h < 7.5 or 19 <= h < 21:
            return round(random.uniform(1400, 1550), 1)
        return round(1500.0 if r() < 0.04 else 3.0, 1)

    if device_id == "luces":
        if 18.5 <= h < 23.5:
            return round(random.uniform(170, 260), 1)
        if 6 <= h < 7.5:
            return round(random.uniform(80, 120), 1)
        return round(random.uniform(10, 20), 1)

    return _simular_consumo_w()


def _simular_temp_interior_c() -> float:
    """Curva de temperatura interior simulada, alrededor de 28C (clima calido
    tipico de una casa en Nuevo Leon sin AC), mas alta al mediodia/tarde.

    Deliberadamente NO depende del clima exterior real -- si el dia real esta
    frio/atipico, restarle un offset a esa temperatura deja la interior
    siempre por debajo del umbral de confort (26C) y el motor de decision
    nunca sugiere 'encender', lo cual no sirve para demostrar el sistema.
    """
    hora = time.localtime().tm_hour
    base = 26.0 + 4.0 * max(0, math.sin((hora - 6) / 24 * 2 * math.pi))  # ~26-30C
    ruido = random.uniform(-1.0, 1.0)
    return round(base + ruido, 1)


def leer_telemetria(ha_entity_id: str | None, temp_exterior_c: float, device_id: str | None = None) -> dict:
    """Regresa {'consumo_w', 'temp_interior_c', 'fuente'} para un dispositivo.

    `ha_entity_id` es el sensor de TELEMETRIA (ej. el enchufe inteligente una
    vez conectado) -- no tiene relacion con como se controla el dispositivo.
    `temp_exterior_c` ya no se usa para la simulacion de temperatura interior
    (ver `_simular_temp_interior_c`), se deja en la firma por compatibilidad
    con los llamadores existentes (ingest.py pasa el clima real por si algun
    dia se usa de nuevo como insumo).
    """
    if ha_entity_id:
        valor = _leer_ha(ha_entity_id)
        if valor is not None:
            return {
                "consumo_w": valor,
                "temp_interior_c": _simular_temp_interior_c(),
                "fuente": "home_assistant",
            }
    return {
        "consumo_w": simular_consumo_dispositivo_w(device_id, datetime.now()) if device_id else _simular_consumo_w(),
        "temp_interior_c": _simular_temp_interior_c(),
        "fuente": "simulada",
    }
