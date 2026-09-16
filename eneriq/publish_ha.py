"""Publica resultados de EnerIQ como sensores/estados en Home Assistant.

Usa la API REST nativa de HA (POST /api/states/<entity_id>) para crear
sensores "push" -- no requieren una integracion instalada del lado de HA,
solo el token de larga duracion en ENERIQ_HA_TOKEN.
"""
import requests

import config


def _set_state(entity_id: str, state, attributes: dict):
    resp = requests.post(
        f"{config.HA_URL}/api/states/{entity_id}",
        headers={
            "Authorization": f"Bearer {config.HA_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"state": str(state), "attributes": attributes},
        timeout=10,
    )
    resp.raise_for_status()


def publicar_decision_ac(accion: str, razon: str, evidencia: dict):
    _set_state(
        "sensor.eneriq_decision_ac",
        accion,
        {
            "razon": razon,
            "friendly_name": "EnerIQ - Decisión AC",
            "icon": "mdi:air-conditioner",
            **evidencia,
        },
    )


def publicar_anomalias(anomalias_24h: list[dict]):
    _set_state(
        "sensor.eneriq_anomalias",
        len(anomalias_24h),
        {
            "friendly_name": "EnerIQ - Anomalías (24h)",
            "icon": "mdi:alert-decagram",
            "lista": anomalias_24h,
        },
    )


def publicar_bitacora(ultimas_decisiones: list[dict]):
    _set_state(
        "sensor.eneriq_bitacora",
        len(ultimas_decisiones),
        {
            "friendly_name": "EnerIQ - Bitácora de decisiones",
            "icon": "mdi:history",
            "decisiones": ultimas_decisiones,
        },
    )


def publicar_plan_manana(plan: list[dict]):
    horas_encender = [p["hora"] for p in plan if p["accion_sugerida"] == "encender"]
    _set_state(
        "sensor.eneriq_plan_manana",
        len(horas_encender),
        {
            "friendly_name": "EnerIQ - Plan de mañana",
            "icon": "mdi:calendar-clock",
            "plan": plan,
        },
    )


def llamar_servicio(servicio_ha: str):
    """Llama un servicio de HA sin entity_id -- para scripts autocontenidos
    como 'script.encender_aire' (el script ya sabe que remote/device controlar).
    """
    dominio, nombre = servicio_ha.split(".", 1)
    resp = requests.post(
        f"{config.HA_URL}/api/services/{dominio}/{nombre}",
        headers={
            "Authorization": f"Bearer {config.HA_TOKEN}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=10,
    )
    resp.raise_for_status()
