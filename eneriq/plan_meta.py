"""Genera un plan de manana orientado a una META DE GASTO diaria que pone
el usuario (MXN), con una proyeccion de cuanto ahorra en proporcion a su
uso actual. Sigue la misma filosofia que plan_llm.py: los numeros duros
los calcula codigo Python, el LLM local solo los explica en espanol.

Metodologia (aproximada a proposito, consistente con las demas
simplificaciones del proyecto -- tariff.py es una tarifa "ilustrativa", la
telemetria de 4/5 dispositivos ya es simulada):

- "Uso actual" = promedio real de gasto diario de los ultimos 7 dias
  completos (tabla telemetry, sin inventar nada).
- "Proyeccion de manana" = mismo consumo horario promedio historico por
  dispositivo, EXCEPTO el/los dispositivo(s) tipo 'ac': para esos se usa
  su consumo promedio historico solo en las horas donde el plan por
  reglas (tabla schedules) dice 'encender', y 0 en el resto -- es decir,
  el ahorro viene de desplazar el uso del aire a horas mas baratas /
  evitarlo cuando no hace falta, no de inventar una reduccion general.

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


def gasto_por_dia(cur, dias: int = DIAS_HISTORIAL) -> list[float]:
    """Gasto total MXN de cada uno de los ultimos `dias` dias completos
    (sin incluir hoy), mismo calculo que analytics.calcular_consumo_gasto_hoy
    pero agrupado por fecha en vez de solo hoy."""
    cur.execute(
        """SELECT tiempo, sum(consumo_w) AS consumo_total_w
           FROM telemetry
           WHERE tiempo >= date_trunc('day', now()) - (%s || ' days')::interval
             AND tiempo < date_trunc('day', now())
           GROUP BY tiempo
           ORDER BY tiempo""",
        (dias,),
    )
    kwh_por_corte = 5.0 / 60.0 / 1000.0
    gasto_por_fecha: dict = {}
    for tiempo, consumo_total_w in cur.fetchall():
        local = tiempo.astimezone()
        kwh = (consumo_total_w or 0.0) * kwh_por_corte
        costo = kwh * tariff.precio_kwh(local.hour)
        gasto_por_fecha[local.date()] = gasto_por_fecha.get(local.date(), 0.0) + costo
    return list(gasto_por_fecha.values())


def uso_actual_promedio_mxn(cur, dias: int = DIAS_HISTORIAL) -> float:
    valores = gasto_por_dia(cur, dias)
    if not valores:
        return 0.0
    return round(sum(valores) / len(valores), 2)


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


def proyectar_manana(cur) -> tuple[float, float, list[dict]]:
    """Proyecta el consumo/gasto de manana: los dispositivos no controlables
    mantienen su perfil horario promedio historico; el/los dispositivo(s)
    'ac' solo aportan consumo en las horas donde el plan de manana
    (tabla schedules) sugiere 'encender'."""
    cur.execute("SELECT id FROM devices")
    todos = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT id FROM devices WHERE tipo = 'ac'")
    dispositivos_ac = {r[0] for r in cur.fetchall()}

    enciende_hora = set()
    if dispositivos_ac:
        manana = date.today() + timedelta(days=1)
        cur.execute(
            """SELECT device_id, hora FROM schedules
               WHERE fecha = %s AND device_id = ANY(%s) AND accion_sugerida = 'encender'""",
            (manana, list(dispositivos_ac)),
        )
        enciende_hora = {(d, h) for d, h in cur.fetchall()}

    perfil_total_w = [0.0] * 24
    for device_id in todos:
        perfil = perfil_horario_promedio(cur, device_id)
        for h in range(24):
            if device_id in dispositivos_ac:
                perfil_total_w[h] += perfil[h] if (device_id, h) in enciende_hora else 0.0
            else:
                perfil_total_w[h] += perfil[h]

    kwh_total = 0.0
    costo_total = 0.0
    for h, w in enumerate(perfil_total_w):
        kwh = w / 1000.0  # perfil ya es por hora (1 muestra representativa por hora)
        kwh_total += kwh
        costo_total += kwh * tariff.precio_kwh(h)

    perfil = [{"hora": h, "consumo_w": round(w, 1)} for h, w in enumerate(perfil_total_w)]
    return round(kwh_total, 3), round(costo_total, 2), perfil


def construir_prompt(
    meta_gasto_mxn: float,
    uso_actual_mxn: float,
    gasto_proyectado_mxn: float,
    ahorro_mxn: float,
    ahorro_pct: float,
    cumple_meta: bool,
    plan_manana: list[dict],
) -> str:
    horas_encender = [p["hora"] for p in plan_manana if p["accion_sugerida"] == "encender"]
    resumen_plan = "\n".join(
        f"- {p['hora']:02d}:00 -> {p['accion_sugerida']} ({p['razon']})" for p in plan_manana
    ) or "(el plan de manana todavia no se genero -- avisa que falta correr el scheduling)"
    estado_meta = "SI la cumple" if cumple_meta else "NO la cumple"

    return f"""Sos el asistente de EnerIQ, un orquestador de energia domestica.
El usuario puso una meta de gasto DIARIO de ${meta_gasto_mxn:.2f} MXN.

Datos duros ya calculados (no los inventes ni los cambies):
- Gasto diario promedio actual (ultimos {DIAS_HISTORIAL} dias reales): ${uso_actual_mxn:.2f} MXN
- Gasto proyectado para manana siguiendo el plan: ${gasto_proyectado_mxn:.2f} MXN
- Ahorro estimado: ${ahorro_mxn:.2f} MXN ({ahorro_pct:.1f}% respecto al uso actual)
- La proyeccion {estado_meta} la meta.

Plan de manana hora por hora (aire acondicionado):
{resumen_plan}

Horas en las que el plan enciende el aire: {horas_encender if horas_encender else 'ninguna'}

Escribe en espanol, en 4-6 lineas: explica si se cumple o no la meta, el
ahorro en pesos y en porcentaje respecto al uso actual, y si NO se cumple
la meta, sugiere que ajustar (ej. subir el umbral de confort, evitar mas
horas punta). Tono directo, como si le hablaras al dueno de la casa. No
uses markdown, no inventes numeros nuevos."""


def main(meta_gasto_mxn: float):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            uso_actual = uso_actual_promedio_mxn(cur)
            _, gasto_proyectado, perfil = proyectar_manana(cur)

            manana = date.today() + timedelta(days=1)
            cur.execute(
                """SELECT hora, accion_sugerida, razon FROM schedules
                   WHERE device_id = 'ac' AND fecha = %s ORDER BY hora""",
                (manana,),
            )
            plan_manana = [
                {"hora": h, "accion_sugerida": a, "razon": r} for h, a, r in cur.fetchall()
            ]

        ahorro_mxn = round(uso_actual - gasto_proyectado, 2)
        ahorro_pct = round((ahorro_mxn / uso_actual * 100), 1) if uso_actual > 0 else 0.0
        cumple_meta = gasto_proyectado <= meta_gasto_mxn

        prompt = construir_prompt(
            meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn, ahorro_pct,
            cumple_meta, plan_manana,
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

        publish_ha.publicar_plan_meta(
            meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn, ahorro_pct,
            cumple_meta, plan_texto,
        )

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO goal_plans
                   (meta_gasto_mxn, uso_actual_mxn, gasto_proyectado_mxn, ahorro_mxn,
                    ahorro_pct, cumple_meta, plan_texto, perfil_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn,
                    ahorro_pct, cumple_meta, plan_texto, json.dumps(perfil),
                ),
            )
        conn.commit()

        print(
            f"plan_meta: meta={meta_gasto_mxn} uso_actual={uso_actual} "
            f"proyectado={gasto_proyectado} ahorro_pct={ahorro_pct} cumple={cumple_meta}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 40.0))
