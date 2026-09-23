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


def publicar_consumo_gasto(
    consumo_kwh_hoy: float, costo_mxn_hoy: float, periodo: str, precio_kwh_actual: float, extra: dict | None = None
):
    _set_state(
        "sensor.eneriq_consumo_hoy_kwh",
        consumo_kwh_hoy,
        {
            "friendly_name": "EnerIQ - Consumo hoy",
            "icon": "mdi:lightning-bolt",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
        },
    )
    _set_state(
        "sensor.eneriq_gasto_hoy_mxn",
        costo_mxn_hoy,
        {
            "friendly_name": "EnerIQ - Gasto hoy",
            "icon": "mdi:cash",
            "unit_of_measurement": "MXN",
            "state_class": "total_increasing",
            "periodo_tarifa_actual": periodo,
            "precio_kwh_actual_mxn": precio_kwh_actual,
            **(extra or {}),
        },
    )


def publicar_plan_llm(plan_texto: str, backend: str, gasto_hoy_mxn: float):
    _set_state(
        "sensor.eneriq_plan_llm",
        "generado",
        {
            "friendly_name": "EnerIQ - Plan de mañana (IA)",
            "icon": "mdi:robot",
            "plan_texto": plan_texto,
            "backend": backend,
            "gasto_hoy_mxn": gasto_hoy_mxn,
        },
    )


def publicar_plan_meta(
    meta_gasto_mxn: float,
    uso_actual_mxn: float,
    gasto_proyectado_mxn: float,
    ahorro_mxn: float,
    ahorro_pct: float,
    cumple_meta: bool,
    plan_texto: str,
    detalle_punta: dict | None = None,
):
    _set_state(
        "sensor.eneriq_plan_meta",
        "generado",
        {
            "friendly_name": "EnerIQ - Plan con meta de gasto",
            "icon": "mdi:target",
            "meta_gasto_mxn": meta_gasto_mxn,
            "uso_actual_mxn": uso_actual_mxn,
            "gasto_proyectado_mxn": gasto_proyectado_mxn,
            # clamp a 0 para que la grafica de pastel nunca reciba un
            # valor negativo; el ahorro real (puede ser negativo si el
            # plan sale mas caro) queda en ahorro_mxn_real para el texto.
            "ahorro_mxn": max(ahorro_mxn, 0.0),
            "ahorro_mxn_real": ahorro_mxn,
            "ahorro_pct": ahorro_pct,
            "cumple_meta": cumple_meta,
            "plan_texto": plan_texto,
            # gasto en horario punta vs base (actual/proyectado) y cargas desplazadas
            **(detalle_punta or {}),
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
