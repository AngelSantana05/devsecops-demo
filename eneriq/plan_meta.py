"""Genera un plan de manana orientado a una META DE GASTO diaria que pone
el usuario (MXN), con una proyeccion de cuanto ahorra en proporcion a su
uso actual. Sigue la misma filosofia que plan_llm.py: los numeros duros
los calcula codigo Python, el LLM local solo los explica en espanol.

Metodologia (aproximada a proposito, consistente con las demas
simplificaciones del proyecto -- tariff.py es una tarifa "ilustrativa", la
telemetria de 4/5 dispositivos ya es simulada):

- Se arma el perfil horario promedio (0-23) de cada dispositivo con los
  ultimos 7 dias completos de la tabla telemetry.
- "Uso actual" = costo de ese perfil tal cual, precio por hora de
  tariff.py (horario punta incluido).
- "Proyeccion de manana" = el MISMO perfil, con dos cambios que salen del
  horario punta (las horas caras):
    * el/los dispositivo(s) tipo 'ac' solo consumen en las horas donde el
      plan por reglas (tabla schedules) dice 'encender' -- el scheduler ya
      nunca enciende en punta;
    * las cargas desplazables (DESPLAZABLES: lavadora, calentador con
      tanque) mueven su consumo de horario punta a las horas base
      inmediatamente anteriores.
  Uso actual y proyeccion salen del mismo perfil, asi que la diferencia
  es solo el efecto del plan (antes se comparaba un promedio real de dias
  con menos dispositivos contra una proyeccion con todos -> "ahorro"
  negativo absurdo).

Cada corrida se guarda en la tabla `goal_plans` para que quede historial
consultable (por la IA o a mano) mas adelante.

Se corre bajo demanda (boton en el dashboard -> POST /plan/meta/generar).
"""
import json
import sys
from datetime import date, timedelta

import db
import publish_ha
import tariff
from plan_llm import OLLAMA_MODEL, OLLAMA_URL

import requests

DIAS_HISTORIAL = 7


# Cargas que se pueden correr fuera del horario punta sin perder nada: la
# lavadora se programa antes, el calentador (con tanque) calienta antes.
DESPLAZABLES = {"lavadora", "calentador"}
HORAS_PUNTA = [h for h in range(24) if tariff.periodo_actual(h) == "punta"]
# a donde se mueve el consumo desplazable: las horas base justo antes de punta
HORAS_DESTINO = [(HORAS_PUNTA[0] - 1 - i) % 24 for i in range(len(HORAS_PUNTA))] if HORAS_PUNTA else []


def costo_perfil(perfil_w: list[float]) -> dict:
    """Costo (MXN) y kWh de un perfil de 24 horas (W promedio por hora),
    separado en horario punta y base."""
    punta = base = kwh = 0.0
    for h, w in enumerate(perfil_w):
        kwh_h = w / 1000.0  # W promedio durante 1 hora = Wh
        kwh += kwh_h
        if h in HORAS_PUNTA:
            punta += kwh_h * tariff.precio_kwh(h)
        else:
            base += kwh_h * tariff.precio_kwh(h)
    return {
        "kwh": round(kwh, 3),
        "total_mxn": round(punta + base, 2),
        "punta_mxn": round(punta, 2),
        "base_mxn": round(base, 2),
    }


def perfil_horario_promedio(cur, device_id: str, dias: int = DIAS_HISTORIAL) -> list[float]:
    """Promedio de consumo_w por hora del dia (0-23), ultimos `dias` dias completos."""
    cur.execute(
        """SELECT tiempo, consumo_w FROM telemetry
           WHERE device_id = %s
             AND tiempo >= date_trunc('day', now()) - (%s || ' days')::interval
             AND tiempo < date_trunc('day', now())""",
        (device_id, dias),
    )
    acumulado = [0.0] * 24
    cuentas = [0] * 24
    for tiempo, consumo_w in cur.fetchall():
        h = tiempo.astimezone().hour
        acumulado[h] += consumo_w or 0.0
        cuentas[h] += 1
    return [acumulado[h] / cuentas[h] if cuentas[h] else 0.0 for h in range(24)]


def proyectar_manana(cur) -> dict:
    """Perfil actual vs. proyectado de manana (ver docstring del modulo)."""
    cur.execute("SELECT id, tipo FROM devices")
    dispositivos = cur.fetchall()
    dispositivos_ac = [d for d, tipo in dispositivos if tipo == "ac"]

    enciende_hora = set()
    if dispositivos_ac:
        manana = date.today() + timedelta(days=1)
        cur.execute(
            """SELECT device_id, hora FROM schedules
               WHERE fecha = %s AND device_id = ANY(%s) AND accion_sugerida = 'encender'""",
            (manana, dispositivos_ac),
        )
        enciende_hora = {(d, h) for d, h in cur.fetchall()}

    actual_w = [0.0] * 24
    proyectado_w = [0.0] * 24
    desplazado_kwh = {}
    for device_id, _ in dispositivos:
        perfil = perfil_horario_promedio(cur, device_id)
        for h in range(24):
            actual_w[h] += perfil[h]

        if device_id in dispositivos_ac:
            for h in range(24):
                proyectado_w[h] += perfil[h] if (device_id, h) in enciende_hora else 0.0
        elif device_id in DESPLAZABLES and HORAS_DESTINO:
            en_punta = sum(perfil[h] for h in HORAS_PUNTA)
            for h in range(24):
                proyectado_w[h] += 0.0 if h in HORAS_PUNTA else perfil[h]
            for h in HORAS_DESTINO:
                proyectado_w[h] += en_punta / len(HORAS_DESTINO)
            if en_punta > 0:
                desplazado_kwh[device_id] = round(en_punta / 1000.0, 3)
        else:
            for h in range(24):
                proyectado_w[h] += perfil[h]

    return {
        "actual": costo_perfil(actual_w),
        "proyectado": costo_perfil(proyectado_w),
        "desplazado_kwh": desplazado_kwh,
        "perfil": [
            {"hora": h, "actual_w": round(actual_w[h], 1), "proyectado_w": round(proyectado_w[h], 1)}
            for h in range(24)
        ],
    }


def construir_prompt(
    meta_gasto_mxn: float,
    proyeccion: dict,
    ahorro_mxn: float,
    ahorro_pct: float,
    cumple_meta: bool,
    plan_manana: list[dict],
) -> str:
    actual, proyectado = proyeccion["actual"], proyeccion["proyectado"]
    horas_encender = [p["hora"] for p in plan_manana if p["accion_sugerida"] == "encender"]
    resumen_plan = "\n".join(
        f"- {p['hora']:02d}:00 -> {p['accion_sugerida']} ({p['razon']})" for p in plan_manana
    ) or "(el plan de manana todavia no se genero -- avisa que falta correr el scheduling)"
    estado_meta = "SI la cumple" if cumple_meta else "NO la cumple"
    desplazadas = ", ".join(
        f"{d} ({kwh} kWh)" for d, kwh in proyeccion["desplazado_kwh"].items()
    ) or "ninguna (no consumen en horario punta)"
    punta_ini, punta_fin = tariff.PERIODO_PUNTA
    pct_punta = (actual["punta_mxn"] / actual["total_mxn"] * 100) if actual["total_mxn"] else 0.0

    return f"""Sos el asistente de EnerIQ, un orquestador de energia domestica.
El usuario puso una meta de gasto DIARIO de ${meta_gasto_mxn:.2f} MXN.

Tarifa: horario punta (horas caras) de {punta_ini:02d}:00 a {punta_fin:02d}:00 a
${tariff.PRECIOS_MXN_KWH['punta']:.2f}/kWh; el resto del dia es horario base a
${tariff.PRECIOS_MXN_KWH['base']:.2f}/kWh.

Datos duros ya calculados (no los inventes ni los cambies):
- Gasto diario actual (perfil promedio de los ultimos {DIAS_HISTORIAL} dias): ${actual['total_mxn']:.2f} MXN
  de los cuales ${actual['punta_mxn']:.2f} MXN ({pct_punta:.0f}%) se van en horario punta
- Gasto proyectado para manana siguiendo el plan: ${proyectado['total_mxn']:.2f} MXN
  (${proyectado['punta_mxn']:.2f} MXN en horario punta)
- Ahorro estimado: ${ahorro_mxn:.2f} MXN ({ahorro_pct:.1f}% respecto al uso actual)
- Cargas movidas fuera del horario punta: {desplazadas}
- La proyeccion {estado_meta} la meta.

Plan de manana hora por hora (aire acondicionado):
{resumen_plan}

Horas en las que el plan enciende el aire: {horas_encender if horas_encender else 'ninguna'}

Escribe en espanol, en 4-6 lineas: explica si se cumple o no la meta, el
ahorro en pesos y en porcentaje respecto al uso actual, y cuanto del gasto
cae en horario punta. Si NO se cumple la meta, sugiere que ajustar (ej.
sacar mas consumo del horario punta, subir el umbral de confort). Tono
directo, como si le hablaras al dueno de la casa. No uses markdown, no
inventes numeros nuevos."""


def main(meta_gasto_mxn: float):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            proyeccion = proyectar_manana(cur)

            manana = date.today() + timedelta(days=1)
            cur.execute(
                """SELECT hora, accion_sugerida, razon FROM schedules
                   WHERE device_id = 'ac' AND fecha = %s ORDER BY hora""",
                (manana,),
            )
            plan_manana = [
                {"hora": h, "accion_sugerida": a, "razon": r} for h, a, r in cur.fetchall()
            ]

        actual, proyectado = proyeccion["actual"], proyeccion["proyectado"]
        uso_actual = actual["total_mxn"]
        gasto_proyectado = proyectado["total_mxn"]
        ahorro_mxn = round(uso_actual - gasto_proyectado, 2)
        ahorro_pct = round((ahorro_mxn / uso_actual * 100), 1) if uso_actual > 0 else 0.0
        cumple_meta = gasto_proyectado <= meta_gasto_mxn

        prompt = construir_prompt(
            meta_gasto_mxn, proyeccion, ahorro_mxn, ahorro_pct, cumple_meta, plan_manana,
        )
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        plan_texto = resp.json()["message"]["content"].strip()

        detalle_punta = {
            "horario_punta": f"{tariff.PERIODO_PUNTA[0]:02d}:00-{tariff.PERIODO_PUNTA[1]:02d}:00",
            "gasto_punta_actual_mxn": actual["punta_mxn"],
            "gasto_punta_proyectado_mxn": proyectado["punta_mxn"],
            "gasto_base_actual_mxn": actual["base_mxn"],
            "gasto_base_proyectado_mxn": proyectado["base_mxn"],
            "cargas_desplazadas_kwh": proyeccion["desplazado_kwh"],
        }
        publish_ha.publicar_plan_meta(
            meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn, ahorro_pct,
            cumple_meta, plan_texto, detalle_punta,
        )

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO goal_plans
                   (meta_gasto_mxn, uso_actual_mxn, gasto_proyectado_mxn, ahorro_mxn,
                    ahorro_pct, cumple_meta, plan_texto, perfil_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn,
                    ahorro_pct, cumple_meta, plan_texto,
                    json.dumps({**detalle_punta, "perfil": proyeccion["perfil"]}),
                ),
            )
        conn.commit()

        print(
            f"plan_meta: meta={meta_gasto_mxn} uso_actual={uso_actual} "
            f"proyectado={gasto_proyectado} ahorro_pct={ahorro_pct} cumple={cumple_meta} "
            f"punta_actual={actual['punta_mxn']} punta_proyectado={proyectado['punta_mxn']}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 40.0))
