"""Genera un plan de manana orientado a una META DE GASTO diaria que pone
el usuario (MXN), con una proyeccion de cuanto ahorra en proporcion a su
uso actual. Sigue la misma filosofia que plan_llm.py: los numeros duros
(costos, escenarios, agenda) los calcula codigo Python, el LLM local solo
los ordena y explica en espanol.

Metodologia (aproximada a proposito, es una DEMO -- tariff.py es una tarifa
"ilustrativa", los aparatos simulados tienen historial inventado por
demo_backfill.py y el pronostico puede ser el de demo, ver config.DEMO_CLIMA):

- Aparatos que no son aire: perfil horario promedio (0-23) de los ultimos
  7 dias completos de la tabla telemetry.
- Aire acondicionado: se MODELA con el pronostico de manana y
  config.AC_POTENCIA_W (ciclo de trabajo segun que tanto pasa la
  temperatura del umbral de confort). No se usa la telemetria de la fila
  'ac' porque ese enchufe en realidad mide el servidor.
- "Uso actual" = el habito sin EnerIQ: aire prendido toda hora que pase del
  confort (horario punta incluido) y los aparatos a su hora de siempre.
- "Proyeccion de manana" = lo mismo, con los cambios que salen del horario
  punta (las horas caras):
    * el aire sigue el plan por reglas (decision_engine.scheduler): no se
      prende en punta; parte de esa energia (PREENFRIADO_FRACCION) se gasta
      antes en horario base para pre-enfriar la casa;
    * las cargas desplazables (DESPLAZABLES: lavadora, calentador con
      tanque) mueven su consumo de punta a las horas base justo antes.
- Escenarios extra (umbral de confort +1C/+2C) para que el LLM pueda
  sugerir ajustes con numeros reales en vez de inventarlos.

Cada corrida se guarda en la tabla `goal_plans` para que quede historial
consultable (por la IA o a mano) mas adelante.

Se corre bajo demanda (boton en el dashboard -> POST /plan/meta/generar).
"""
import json
import sys
from datetime import date, timedelta

import config
import db
import publish_ha
import tariff
import weather
from decision_engine.scheduler import generar_plan_manana
from plan_llm import OLLAMA_MODEL, OLLAMA_URL

import requests

DIAS_HISTORIAL = 7

# Cargas que se pueden correr fuera del horario punta sin perder nada: la
# lavadora se programa antes, el calentador (con tanque) calienta antes.
DESPLAZABLES = {"lavadora", "calentador"}
HORAS_PUNTA = [h for h in range(24) if tariff.periodo_actual(h) == "punta"]
# a donde se mueve el consumo desplazable: las horas base justo antes de punta
HORAS_DESTINO = sorted((HORAS_PUNTA[0] - 1 - i) % 24 for i in range(len(HORAS_PUNTA))) if HORAS_PUNTA else []
# parte de la energia del aire que se evita en punta que se gasta antes, en
# las 2 horas base previas, para pre-enfriar la casa
PREENFRIADO_FRACCION = 0.4
HORAS_PREENFRIADO = HORAS_DESTINO[-2:]


def costo_perfil(perfil_w: list[float]) -> dict:
    """Costo (MXN) y kWh de un perfil de 24 horas (W promedio por hora),
    separado en horario punta y base."""
    punta = base = kwh = kwh_punta = 0.0
    for h, w in enumerate(perfil_w):
        kwh_h = w / 1000.0  # W promedio durante 1 hora = Wh
        kwh += kwh_h
        if h in HORAS_PUNTA:
            kwh_punta += kwh_h
            punta += kwh_h * tariff.precio_kwh(h)
        else:
            base += kwh_h * tariff.precio_kwh(h)
    return {
        "kwh": round(kwh, 2),
        "kwh_punta": round(kwh_punta, 2),
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


def consumo_ac_w(temp_c: float, confort_c: float) -> float:
    """Consumo promedio del minisplit en una hora: ciclo de trabajo que sube
    con lo que la temperatura pasa del umbral de confort."""
    if temp_c < confort_c:
        return 0.0
    ciclo = min(1.0, 0.3 + 0.07 * (temp_c - confort_c))
    return config.AC_POTENCIA_W * ciclo


def perfil_ac(pronostico: list[float], confort_c: float, seguir_plan: bool) -> tuple[list[float], list[dict]]:
    """Perfil del aire: habito (prendido toda hora sobre el confort) o
    siguiendo el plan por reglas (nada en punta + pre-enfriado)."""
    habito = [consumo_ac_w(t, confort_c) for t in pronostico]
    plan = generar_plan_manana(pronostico, confort_c)
    if not seguir_plan:
        return habito, plan

    perfil = [habito[p["hora"]] if p["accion_sugerida"] == "encender" else 0.0 for p in plan]
    evitado_punta = sum(habito[h] for h in HORAS_PUNTA if perfil[h] == 0.0)
    for h in HORAS_PREENFRIADO:
        perfil[h] += evitado_punta * PREENFRIADO_FRACCION / len(HORAS_PREENFRIADO)
    return perfil, plan


def desplazar_fuera_de_punta(perfil: list[float]) -> list[float]:
    en_punta = sum(perfil[h] for h in HORAS_PUNTA)
    nuevo = [0.0 if h in HORAS_PUNTA else perfil[h] for h in range(24)]
    for h in HORAS_DESTINO:
        nuevo[h] += en_punta / len(HORAS_DESTINO)
    return nuevo


def sumar(*perfiles: list[float]) -> list[float]:
    return [sum(p[h] for p in perfiles) for h in range(24)]


def horas_de_uso(perfil: list[float], relativo: bool = True) -> list[int]:
    """Horas en las que el aparato de verdad trabaja. `relativo`: >= 40% de
    su hora pico, para no contar picos sueltos de mantenimiento como 'uso'
    (el aire se evalua con > 0, su consumo ya sale del modelo)."""
    umbral_w = max(20.0, 0.4 * max(perfil)) if relativo else 0.001
    return [h for h in range(24) if perfil[h] >= umbral_w]


def bloques(horas: list[int]) -> list[tuple[int, int]]:
    """[6, 7, 19, 20] -> [(6, 8), (19, 21)] (fin exclusivo)."""
    if not horas:
        return []
    out, ini, prev = [], horas[0], horas[0]
    for h in horas[1:] + [None]:
        if h is not None and h == prev + 1:
            prev = h
            continue
        out.append((ini, prev + 1))
        if h is not None:
            ini = prev = h
    return out


def rangos(horas: list[int]) -> str:
    """[6, 7, 19, 20] -> '06:00-08:00 y 19:00-21:00'."""
    if not horas:
        return "ninguna"
    if len(horas) == 24:
        return "todo el dia"
    return " y ".join(f"{i:02d}:00-{f % 24:02d}:00" for i, f in bloques(horas))


def armar_agenda(d: dict) -> list[str]:
    """Agenda de manana en orden de hora, calculada en codigo (el LLM la
    redacta, no la decide)."""
    items = []
    encender = [p["hora"] for p in d["plan_ac"] if p["accion_sugerida"] == "encender"]
    for i, f in bloques(encender):
        t_max = max(d["pronostico"][i:f])
        items.append((i, f"{i:02d}:00-{f % 24:02d}:00 aire encendido (afuera llega a {t_max}C)"))
    if d["pospuesto"]:
        i = d["pospuesto"][0]
        items.append((HORAS_PREENFRIADO[0], f"{rangos(HORAS_PREENFRIADO)} pre-enfriar la casa (bajar el aire un par de grados)"))
        items.append((i + 0.1, f"{rangos(d['pospuesto'])} aire APAGADO por horario punta, aunque haga calor"))
    for a in d["aparatos"][1:]:
        if a["desplazable"] and a["horas_actual"] != a["horas_plan"]:
            nuevas = [b for b in a["bloques_plan"] if b[0] in HORAS_DESTINO]
            for i, f in nuevas:
                items.append((i + 0.2, f"{i:02d}:00-{f % 24:02d}:00 {a['nombre'].lower()} (antes lo usabas en horario punta)"))
            for i, f in a["bloques_plan"]:
                if (i, f) not in nuevas:
                    items.append((i + 0.2, f"{i:02d}:00-{f % 24:02d}:00 {a['nombre'].lower()} (igual que siempre)"))
        elif a["nombre"].lower().startswith("luces"):
            for i, f in a["bloques_plan"]:
                items.append((i + 0.3, f"{i:02d}:00-{f % 24:02d}:00 {a['nombre'].lower()}: solo las necesarias"))
    return [texto for _, texto in sorted(items)]


def calcular(cur, meta_gasto_mxn: float) -> dict:
    confort = config.TEMP_CONFORT_MAX_C
    pronostico = weather.pronostico_manana_c()

    cur.execute("SELECT id, nombre, tipo, peso_prioridad FROM devices WHERE tipo <> 'ac' ORDER BY id")
    aparatos = []
    for device_id, nombre, _, prioridad in cur.fetchall():
        actual = perfil_horario_promedio(cur, device_id)
        desplazable = device_id in DESPLAZABLES
        proyectado = desplazar_fuera_de_punta(actual) if desplazable else actual
        aparatos.append({
            "id": device_id,
            "nombre": nombre,
            "prioridad": prioridad,
            "desplazable": desplazable,
            "perfil_actual": actual,
            "perfil_proyectado": proyectado,
        })

    ac_habito, _ = perfil_ac(pronostico, confort, seguir_plan=False)
    ac_plan, plan_ac = perfil_ac(pronostico, confort, seguir_plan=True)
    otros_actual = sumar(*[a["perfil_actual"] for a in aparatos]) if aparatos else [0.0] * 24
    otros_proyectado = sumar(*[a["perfil_proyectado"] for a in aparatos]) if aparatos else [0.0] * 24

    actual_w = sumar(ac_habito, otros_actual)
    proyectado_w = sumar(ac_plan, otros_proyectado)

    escenarios = []
    for delta in (1, 2):
        ac_esc, _ = perfil_ac(pronostico, confort + delta, seguir_plan=True)
        escenarios.append({
            "descripcion": f"subir el confort a {confort + delta:.0f}C",
            **costo_perfil(sumar(ac_esc, otros_proyectado)),
        })

    detalle_aparatos = [
        {
            "nombre": "Aire acondicionado",
            "desplazable": False,
            "prioridad": None,
            "horas_actual": rangos(horas_de_uso(ac_habito, relativo=False)),
            "horas_plan": rangos(horas_de_uso(ac_plan, relativo=False)),
            "bloques_plan": bloques(horas_de_uso(ac_plan, relativo=False)),
            "actual": costo_perfil(ac_habito),
            "proyectado": costo_perfil(ac_plan),
        }
    ] + [
        {
            "nombre": a["nombre"],
            "desplazable": a["desplazable"],
            "prioridad": a["prioridad"],
            "horas_actual": rangos(horas_de_uso(a["perfil_actual"])),
            "horas_plan": rangos(horas_de_uso(a["perfil_proyectado"])),
            "bloques_plan": bloques(horas_de_uso(a["perfil_proyectado"])),
            "actual": costo_perfil(a["perfil_actual"]),
            "proyectado": costo_perfil(a["perfil_proyectado"]),
        }
        for a in aparatos
    ]

    pospuesto = [
        p["hora"] for p in plan_ac
        if p["accion_sugerida"] != "encender" and pronostico[p["hora"]] >= confort
    ]

    d = {
        "meta_gasto_mxn": meta_gasto_mxn,
        "confort_c": confort,
        "pronostico": pronostico,
        "plan_ac": plan_ac,
        "actual": costo_perfil(actual_w),
        "proyectado": costo_perfil(proyectado_w),
        "aparatos": detalle_aparatos,
        "escenarios": escenarios,
        "perfil": [
            {"hora": h, "actual_w": round(actual_w[h], 1), "proyectado_w": round(proyectado_w[h], 1)}
            for h in range(24)
        ],
        "pospuesto": pospuesto,
    }
    d["agenda"] = armar_agenda(d)
    return d


def construir_prompt(d: dict, ahorro_mxn: float, ahorro_pct: float, cumple_meta: bool) -> str:
    actual, proyectado = d["actual"], d["proyectado"]
    punta_ini, punta_fin = tariff.PERIODO_PUNTA
    pct_punta = (actual["punta_mxn"] / actual["total_mxn"] * 100) if actual["total_mxn"] else 0.0
    diferencia_meta = round(proyectado["total_mxn"] - d["meta_gasto_mxn"], 2)

    pronostico = ", ".join(f"{h:02d}h {t}C" for h, t in enumerate(d["pronostico"]))
    aparatos = "\n".join(
        f"- {a['nombre']}: hoy usa {a['horas_actual']} ({a['actual']['kwh']} kWh, "
        f"${a['actual']['total_mxn']:.2f}, de eso ${a['actual']['punta_mxn']:.2f} en horario punta) "
        f"-> con el plan {a['horas_plan']} (${a['proyectado']['total_mxn']:.2f}, "
        f"${a['proyectado']['punta_mxn']:.2f} en punta)"
        + (" [se puede mover de horario]" if a["desplazable"] else "")
        for a in d["aparatos"]
    )
    encender = [p["hora"] for p in d["plan_ac"] if p["accion_sugerida"] == "encender"]
    ahorro_punta = round(actual["punta_mxn"] - proyectado["punta_mxn"], 2)
    agenda = "\n".join(f"- {x}" for x in d["agenda"])
    sacados = [a["nombre"] for a in d["aparatos"] if a["proyectado"]["punta_mxn"] < a["actual"]["punta_mxn"]]
    se_quedan = [a["nombre"] for a in d["aparatos"] if a["proyectado"]["punta_mxn"] > 0]
    escenarios = "\n".join(
        f"- Si ademas se decide {e['descripcion']}: gasto de ${e['total_mxn']:.2f} MXN "
        f"({'cumple' if e['total_mxn'] <= d['meta_gasto_mxn'] else 'no cumple'} la meta)"
        for e in d["escenarios"]
    )

    return f"""Eres el asistente de EnerIQ, un orquestador de energia para una casa en Monterrey.
Tu trabajo: escribir el PLAN COMPLETO de manana para que el dueno de la casa
cumpla su meta de gasto de luz. Todos los numeros ya estan calculados abajo:
usalos tal cual, no calcules ni inventes numeros nuevos.

## Tarifa
- Horario punta (horas caras): {punta_ini:02d}:00 a {punta_fin:02d}:00, ${tariff.PRECIOS_MXN_KWH['punta']:.2f} por kWh.
- Resto del dia (horario base): ${tariff.PRECIOS_MXN_KWH['base']:.2f} por kWh.
- Un kWh en punta cuesta {tariff.PRECIOS_MXN_KWH['punta'] / tariff.PRECIOS_MXN_KWH['base']:.1f} veces mas que en base.

## Meta y resultado
- Meta de gasto diario: ${d['meta_gasto_mxn']:.2f} MXN
- Gasto con los habitos actuales: ${actual['total_mxn']:.2f} MXN ({actual['kwh']} kWh); ${actual['punta_mxn']:.2f} de eso ({pct_punta:.0f}%) en horario punta
- Gasto siguiendo el plan: ${proyectado['total_mxn']:.2f} MXN ({proyectado['kwh']} kWh); ${proyectado['punta_mxn']:.2f} en horario punta
- Ahorro total: ${ahorro_mxn:.2f} MXN ({ahorro_pct:.1f}%)
- Ahorro solo en horario punta: ${ahorro_punta:.2f} MXN (de ${actual['punta_mxn']:.2f} a ${proyectado['punta_mxn']:.2f})
- Aparatos que se sacan del horario punta: {', '.join(sacados) or 'ninguno'}
- Aparatos que siguen consumiendo en horario punta (no se pueden mover): {', '.join(se_quedan) or 'ninguno'}
- {'CUMPLE la meta, sobran $' + f'{-diferencia_meta:.2f}' if cumple_meta else 'NO cumple la meta, faltan $' + f'{diferencia_meta:.2f}'} MXN

## Pronostico de manana (umbral de confort {d['confort_c']:.0f}C)
{pronostico}

## Aparatos: horario de siempre -> horario con el plan
{aparatos}

## Aire acondicionado segun el plan
- Encendido: {rangos(encender)}
- Apagado aunque haga calor (para no pagar horario punta): {rangos(d['pospuesto'])}
- Pre-enfriado: se enfria la casa de mas en {rangos(HORAS_PREENFRIADO)} para aguantar el horario punta

## Agenda de manana (ya calculada, en orden)
{agenda}

## Ajustes opcionales
{escenarios}

## Formato de tu respuesta (markdown, en espanol, tono directo y amigable)
**Resumen**: la meta, el gasto con habitos actuales, el gasto con el plan, el ahorro total y, muy claro, si CUMPLE o NO CUMPLE la meta (y por cuanto).
**Horas caras ({punta_ini:02d}:00-{punta_fin:02d}:00)**: que aparatos se sacan de ese horario y el ahorro solo en horario punta.
**Agenda de manana**: la agenda ya calculada de arriba, en el mismo orden, cada punto con una explicacion corta de por que.
**Si quieres ahorrar mas**: usa SOLO los ajustes opcionales de arriba.
Reglas: nunca sugieras mover algo HACIA las {punta_ini:02d}:00-{punta_fin:02d}:00; no agregues
aparatos, horas ni montos que no esten arriba; nada fuera de esas 4 secciones;
no envuelvas la respuesta en bloques de codigo."""


def main(meta_gasto_mxn: float):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            d = calcular(cur, meta_gasto_mxn)

        uso_actual = d["actual"]["total_mxn"]
        gasto_proyectado = d["proyectado"]["total_mxn"]
        ahorro_mxn = round(uso_actual - gasto_proyectado, 2)
        ahorro_pct = round((ahorro_mxn / uso_actual * 100), 1) if uso_actual > 0 else 0.0
        cumple_meta = gasto_proyectado <= meta_gasto_mxn

        prompt = construir_prompt(d, ahorro_mxn, ahorro_pct, cumple_meta)
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                # prompt largo + poca creatividad: que no se invente numeros
                "options": {"num_ctx": 8192, "temperature": 0.3},
            },
            timeout=180,
        )
        resp.raise_for_status()
        plan_texto = resp.json()["message"]["content"].strip()
        # los modelos chicos a veces envuelven todo en ```markdown aunque se les pida que no
        plan_texto = "\n".join(l for l in plan_texto.splitlines() if not l.strip().startswith("```")).strip()

        detalle_punta = {
            "horario_punta": f"{tariff.PERIODO_PUNTA[0]:02d}:00-{tariff.PERIODO_PUNTA[1]:02d}:00",
            "gasto_punta_actual_mxn": d["actual"]["punta_mxn"],
            "gasto_punta_proyectado_mxn": d["proyectado"]["punta_mxn"],
            "gasto_base_actual_mxn": d["actual"]["base_mxn"],
            "gasto_base_proyectado_mxn": d["proyectado"]["base_mxn"],
            "aparatos": [
                {
                    "nombre": a["nombre"],
                    "horas_actual": a["horas_actual"],
                    "horas_plan": a["horas_plan"],
                    "actual_mxn": a["actual"]["total_mxn"],
                    "proyectado_mxn": a["proyectado"]["total_mxn"],
                }
                for a in d["aparatos"]
            ],
            "escenarios": [
                {"descripcion": e["descripcion"], "total_mxn": e["total_mxn"]} for e in d["escenarios"]
            ],
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
                    json.dumps({**detalle_punta, "pronostico": d["pronostico"], "perfil": d["perfil"]}),
                ),
            )
        conn.commit()

        print(
            f"plan_meta: meta={meta_gasto_mxn} uso_actual={uso_actual} "
            f"proyectado={gasto_proyectado} ahorro_pct={ahorro_pct} cumple={cumple_meta} "
            f"punta_actual={d['actual']['punta_mxn']} punta_proyectado={d['proyectado']['punta_mxn']}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 40.0))
