"""Genera un plan de manana orientado a una META DE GASTO diaria que pone
el usuario (MXN), con una proyeccion de cuanto ahorra en proporcion a su
uso actual. Sigue la misma filosofia que plan_llm.py: los numeros duros
(recibo por escalones, escenarios, agenda) los calcula codigo Python, el LLM
local solo los ordena y explica en espanol.

Tarifa: CFE 1C de Monterrey (ver tariff.py). CFE no cobra por hora sino por
ESCALONES de consumo del mes, asi que:
- lo caro no es una hora del dia, son los kWh que caen en el escalon
  excedente (~4 veces el basico);
- mover la lavadora o el calentador de hora NO ahorra nada; lo unico que
  ahorra es gastar menos kWh;
- el riesgo grande es que el promedio de 12 meses pase de 850 kWh/mes y CFE
  reclasifique la casa a tarifa DAC (se pierde todo el subsidio).

"Gasto diario" = recibo del mes (con IVA) entre los dias del mes, si todos
los dias fueran como manana. Es la forma honesta de repartir una tarifa por
escalones en dias.

Metodologia (aproximada a proposito, es una DEMO: los aparatos que no son el
aire tienen historial simulado por demo_backfill.py):
- Aparatos que no son aire: perfil horario promedio (0-23) de los ultimos
  7 dias completos de la tabla telemetry.
- Aire acondicionado: se MODELA con el pronostico real de manana y
  config.AC_POTENCIA_W (ciclo de trabajo segun que tanto pasa la
  temperatura del umbral de confort). No se usa la telemetria de la fila
  'ac' porque ese enchufe en realidad mide el servidor.
- "Habitos actuales": aire prendido toda hora que pase del confort.
- "Plan": el aire sigue el plan por reglas (decision_engine.scheduler): si el
  mes ya cae en el excedente, solo se enfria en las horas de calor fuerte.
- Escenarios extra (umbral de confort +1C/+2C) para que el LLM pueda
  sugerir ajustes con numeros reales en vez de inventarlos.

Cada corrida se guarda en la tabla `goal_plans` para que quede historial
consultable (por la IA o a mano) mas adelante.

Se corre bajo demanda (boton en el dashboard -> POST /plan/meta/generar).
"""
import calendar
import json
import sys
from datetime import date, timedelta

import analytics
import config
import db
import publish_ha
import tariff
import weather
from decision_engine.scheduler import generar_plan_manana
from plan_llm import OLLAMA_MODEL, OLLAMA_URL

import requests

DIAS_HISTORIAL = 7


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


def kwh(perfil_w: list[float]) -> float:
    return sum(perfil_w) / 1000.0  # W promedio durante 1 hora = Wh


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


def escenario(kwh_dia: float, fecha: date, dias_mes: int) -> dict:
    """Recibo del mes si todos los dias gastan `kwh_dia`, y riesgo DAC."""
    kwh_mes = kwh_dia * dias_mes
    recibo = tariff.recibo_mensual(kwh_mes, fecha)
    excedente = next((e for e in recibo["escalones"] if e["escalon"] == "excedente"), None)
    promedio_12m = config.CONSUMO_PROMEDIO_12M_KWH + (kwh_mes - config.CONSUMO_PROMEDIO_12M_KWH) / 12
    return {
        "kwh_dia": round(kwh_dia, 2),
        "kwh_mes": round(kwh_mes, 1),
        "recibo": recibo,
        "gasto_diario": round(recibo["total"] / dias_mes, 2),
        "kwh_excedente": excedente["kwh"] if excedente else 0.0,
        "importe_excedente": round(excedente["importe"] * (1 + tariff.IVA), 2) if excedente else 0.0,
        "promedio_12m_estimado": round(promedio_12m, 1),
    }


def armar_agenda(d: dict) -> list[str]:
    """Agenda de manana en orden de hora, calculada en codigo (el LLM la
    redacta, no la decide)."""
    items = []
    encender = [p["hora"] for p in d["plan_ac"] if p["accion_sugerida"] == "encender"]
    for i, f in bloques(encender):
        t_max = max(d["pronostico"][i:f])
        items.append((i, f"{i:02d}:00-{f % 24:02d}:00 aire encendido (afuera llega a {t_max}C)"))
    for i, f in bloques(d["sin_aire_con_calor"]):
        t_max = max(d["pronostico"][i:f])
        items.append((i, f"{i:02d}:00-{f % 24:02d}:00 aire APAGADO, usar ventilador (calor leve, maximo {t_max}C)"))
    for a in d["aparatos"][1:]:
        for i, f in a["bloques"]:
            horario = "todo el dia" if (i, f) == (0, 24) else f"{i:02d}:00-{f % 24:02d}:00"
            items.append((i + 0.2, f"{horario} {a['nombre'].lower()}: uso normal, sin cambios"))
    return [texto for _, texto in sorted(items)]


def calcular(cur, meta_gasto_mxn: float) -> dict:
    confort = config.TEMP_CONFORT_MAX_C
    manana = date.today() + timedelta(days=1)
    dias_mes = calendar.monthrange(manana.year, manana.month)[1]
    pronostico = weather.pronostico_manana_c()

    cur.execute("SELECT id, nombre, peso_prioridad FROM devices WHERE tipo <> 'ac' ORDER BY id")
    aparatos = [
        {"id": device_id, "nombre": nombre, "prioridad": prioridad, "perfil": perfil_horario_promedio(cur, device_id)}
        for device_id, nombre, prioridad in cur.fetchall()
    ]
    otros_w = sumar(*[a["perfil"] for a in aparatos]) if aparatos else [0.0] * 24

    def perfil_ac(confort_c: float) -> tuple[list[float], list[dict], str]:
        """Aire siguiendo el plan por reglas con el escalon en el que caeria
        el mes con los habitos actuales."""
        habito = [consumo_ac_w(t, confort_c) for t in pronostico]
        kwh_mes_habito = (kwh(habito) + kwh(otros_w)) * dias_mes
        escalon, precio = tariff.escalon_actual(kwh_mes_habito, manana)
        plan = generar_plan_manana(pronostico, confort_c, escalon, precio)
        perfil = [habito[p["hora"]] if p["accion_sugerida"] == "encender" else 0.0 for p in plan]
        return perfil, plan, escalon

    ac_habito = [consumo_ac_w(t, confort) for t in pronostico]
    ac_plan, plan_ac, escalon_mes = perfil_ac(confort)

    actual = escenario(kwh(ac_habito) + kwh(otros_w), manana, dias_mes)
    proyectado = escenario(kwh(ac_plan) + kwh(otros_w), manana, dias_mes)

    escenarios = []
    for delta in (1, 2):
        ac_esc, _, _ = perfil_ac(confort + delta)
        e = escenario(kwh(ac_esc) + kwh(otros_w), manana, dias_mes)
        escenarios.append({"descripcion": f"subir el confort a {confort + delta:.0f}C", **e})

    # costo de cada aparato = cuanto bajaria el recibo si no existiera (sus kWh
    # se cobran en el escalon mas alto que tocan, no al precio promedio)
    total_plan = proyectado["recibo"]["total"]
    detalle_aparatos = []
    for nombre, perfil, relativo in [("Aire acondicionado", ac_plan, False)] + [
        (a["nombre"], a["perfil"], True) for a in aparatos
    ]:
        sin_el = tariff.recibo_mensual(proyectado["kwh_mes"] - kwh(perfil) * dias_mes, manana)["total"]
        detalle_aparatos.append({
            "nombre": nombre,
            "horas": rangos(horas_de_uso(perfil, relativo)),
            "bloques": bloques(horas_de_uso(perfil, relativo)),
            "kwh_dia": round(kwh(perfil), 2),
            "costo_mes": round(total_plan - sin_el, 2),
        })

    sin_aire_con_calor = [
        p["hora"] for p in plan_ac
        if p["accion_sugerida"] != "encender" and pronostico[p["hora"]] >= confort
    ]

    c = analytics.consumo_mes(cur)
    d = {
        "meta_gasto_mxn": meta_gasto_mxn,
        "confort_c": confort,
        "fecha": manana,
        "dias_mes": dias_mes,
        "temporada": tariff.temporada(manana),
        "escalones_tarifa": tariff.escalones(manana),
        "limite_subsidiado": tariff.limite_subsidiado_kwh(manana),
        "escalon_mes": escalon_mes,
        "pronostico": pronostico,
        "plan_ac": plan_ac,
        "sin_aire_con_calor": sin_aire_con_calor,
        "horas_aire_habito": rangos(horas_de_uso(ac_habito, relativo=False)),
        "actual": actual,
        "proyectado": proyectado,
        "escenarios": escenarios,
        "aparatos": detalle_aparatos,
        "mes_en_curso": {
            "kwh_mes": round(c["kwh_mes"], 1),
            "escalon": tariff.escalon_actual(c["kwh_mes"])[0],
        },
        "perfil": [
            {"hora": h, "habito_w": round(ac_habito[h] + otros_w[h], 1), "plan_w": round(ac_plan[h] + otros_w[h], 1)}
            for h in range(24)
        ],
    }
    d["agenda"] = armar_agenda(d)
    return d


def texto_recibo(e: dict) -> str:
    lineas = [f"    - {x['escalon']}: {x['kwh']} kWh x ${x['precio']} = ${x['importe']:.2f}" for x in e["recibo"]["escalones"]]
    return "\n".join(lineas + [f"    - IVA 16%: ${e['recibo']['iva']:.2f}", f"    - TOTAL: ${e['recibo']['total']:.2f}"])


def construir_prompt(d: dict, ahorro_mxn: float, ahorro_pct: float, cumple_meta: bool) -> str:
    actual, proyectado = d["actual"], d["proyectado"]
    diferencia_meta = round(proyectado["gasto_diario"] - d["meta_gasto_mxn"], 2)
    tabla_tarifa = "\n".join(
        f"- {nombre}: {'primeros ' if i == 0 else 'siguientes '}{tam} kWh a ${precio}/kWh" if tam else
        f"- {nombre}: todo lo que pase de {d['limite_subsidiado']:.0f} kWh a ${precio}/kWh"
        for i, (nombre, tam, precio) in enumerate(d["escalones_tarifa"])
    )
    pronostico = ", ".join(f"{h:02d}h {t}C" for h, t in enumerate(d["pronostico"]))
    aparatos = "\n".join(
        f"- {a['nombre']}: {a['horas']}, {a['kwh_dia']} kWh al dia, le cuesta ${a['costo_mes']:.2f} al recibo del mes"
        for a in d["aparatos"]
    )
    agenda = "\n".join(f"- {x}" for x in d["agenda"])
    escenarios = "\n".join(
        f"- Si ademas se decide {e['descripcion']}: ${e['gasto_diario']:.2f} por dia, recibo de "
        f"${e['recibo']['total']:.2f} al mes ({'cumple' if e['gasto_diario'] <= d['meta_gasto_mxn'] else 'no cumple'} la meta)"
        for e in d["escenarios"]
    )
    dac = (
        f"Con el plan, el promedio de 12 meses quedaria en ~{proyectado['promedio_12m_estimado']} kWh/mes "
        f"(limite DAC: {tariff.LIMITE_DAC_KWH_MES}). "
        + ("PELIGRO: pasaria el limite y CFE cambiaria la casa a tarifa DAC, "
           f"donde ese mismo mes costaria ${tariff.recibo_dac(proyectado['kwh_mes']):.2f}."
           if proyectado["promedio_12m_estimado"] > tariff.LIMITE_DAC_KWH_MES else "Queda por debajo del limite.")
    )

    return f"""Eres el asistente de EnerIQ, un orquestador de energia para una casa en Monterrey.
Tu trabajo: escribir el PLAN COMPLETO de manana para que el dueno de la casa
cumpla su meta de gasto de luz. Todos los numeros ya estan calculados abajo:
usalos tal cual, no calcules ni inventes numeros nuevos.

## Como cobra CFE en Monterrey (tarifa 1C, temporada {d['temporada']})
CFE NO cobra por hora del dia: cobra por escalones segun cuantos kWh lleva la casa en el mes.
{tabla_tarifa}
- Mas IVA de 16%.
- Lo caro es el escalon excedente: cada kWh ahi cuesta unas 4 veces el basico.
- Mover aparatos de hora NO ahorra. Lo unico que ahorra es gastar menos kWh.
- Riesgo DAC: si el promedio de consumo de 12 meses pasa de {tariff.LIMITE_DAC_KWH_MES} kWh/mes, la casa pierde el subsidio.

## Mes en curso
- Llevas {d['mes_en_curso']['kwh_mes']} kWh este mes; el siguiente kWh cae en el escalon {d['mes_en_curso']['escalon']}.

## Meta y resultado (gasto diario = recibo del mes / {d['dias_mes']} dias)
- Meta de gasto diario: ${d['meta_gasto_mxn']:.2f} MXN
- Con los habitos actuales: ${actual['gasto_diario']:.2f} por dia ({actual['kwh_dia']} kWh/dia, recibo de ${actual['recibo']['total']:.2f} al mes)
- Siguiendo el plan: ${proyectado['gasto_diario']:.2f} por dia ({proyectado['kwh_dia']} kWh/dia, recibo de ${proyectado['recibo']['total']:.2f} al mes)
- Ahorro: ${ahorro_mxn:.2f} por dia ({ahorro_pct:.1f}%), ${ahorro_mxn * d['dias_mes']:.2f} al mes
- Escalon excedente con habitos: {actual['kwh_excedente']} kWh del mes, que cuestan ${actual['importe_excedente']:.2f}
- Escalon excedente con el plan: {proyectado['kwh_excedente']} kWh del mes, que cuestan ${proyectado['importe_excedente']:.2f}
- {'CUMPLE la meta, sobran $' + f'{-diferencia_meta:.2f}' if cumple_meta else 'NO cumple la meta, faltan $' + f'{diferencia_meta:.2f}'} por dia

## Recibo del mes siguiendo el plan
{texto_recibo(proyectado)}

## Tarifa DAC
{dac}

## Pronostico real de manana en Monterrey (umbral de confort {d['confort_c']:.0f}C)
{pronostico}

## Aparatos con el plan
{aparatos}

## Aire acondicionado
- Con los habitos actuales se prende: {d['horas_aire_habito']}
- Con el plan se prende: {rangos([p['hora'] for p in d['plan_ac'] if p['accion_sugerida'] == 'encender'])}
- Con el plan NO se prende aunque pase del confort (calor leve, el mes va en escalon {d['escalon_mes']}): {rangos(d['sin_aire_con_calor'])}

## Agenda de manana (ya calculada, en orden)
{agenda}

## Ajustes opcionales
{escenarios}

## Formato de tu respuesta (markdown, en espanol, tono directo y amigable)
**Resumen**: la meta, el gasto por dia con habitos y con el plan, el ahorro y, muy claro, si CUMPLE o NO CUMPLE la meta (y por cuanto).
**Lo caro: el escalon excedente**: cuantos kWh del mes caen en el excedente con habitos y con el plan, y que pasa con la tarifa DAC.
**Agenda de manana**: la agenda ya calculada de arriba, en el mismo orden, cada punto con una explicacion corta de por que.
**Si quieres ahorrar mas**: usa SOLO los ajustes opcionales de arriba.
Reglas: no hables de horario punta ni sugieras mover aparatos de hora para ahorrar; no agregues
aparatos, horas ni montos que no esten arriba; nada fuera de esas 4 secciones;
no envuelvas la respuesta en bloques de codigo."""


def main(meta_gasto_mxn: float):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            d = calcular(cur, meta_gasto_mxn)

        uso_actual = d["actual"]["gasto_diario"]
        gasto_proyectado = d["proyectado"]["gasto_diario"]
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

        detalle = {
            "tarifa": f"CFE 1C (Monterrey), {d['temporada']}",
            "kwh_dia_actual": d["actual"]["kwh_dia"],
            "kwh_dia_proyectado": d["proyectado"]["kwh_dia"],
            "recibo_mes_actual_mxn": d["actual"]["recibo"]["total"],
            "recibo_mes_proyectado_mxn": d["proyectado"]["recibo"]["total"],
            "kwh_excedente_actual": d["actual"]["kwh_excedente"],
            "kwh_excedente_proyectado": d["proyectado"]["kwh_excedente"],
            "recibo_escalones": d["proyectado"]["recibo"]["escalones"],
            "promedio_12m_estimado_kwh": d["proyectado"]["promedio_12m_estimado"],
            "limite_dac_kwh": tariff.LIMITE_DAC_KWH_MES,
            "aparatos": [
                {"nombre": a["nombre"], "horas": a["horas"], "kwh_dia": a["kwh_dia"], "costo_mes_mxn": a["costo_mes"]}
                for a in d["aparatos"]
            ],
            "escenarios": [
                {"descripcion": e["descripcion"], "gasto_diario_mxn": e["gasto_diario"], "recibo_mes_mxn": e["recibo"]["total"]}
                for e in d["escenarios"]
            ],
        }
        publish_ha.publicar_plan_meta(
            meta_gasto_mxn, uso_actual, gasto_proyectado, ahorro_mxn, ahorro_pct,
            cumple_meta, plan_texto, detalle,
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
                    json.dumps({**detalle, "pronostico": d["pronostico"], "perfil": d["perfil"]}),
                ),
            )
        conn.commit()

        print(
            f"plan_meta: meta={meta_gasto_mxn} diario_actual={uso_actual} diario_plan={gasto_proyectado} "
            f"ahorro_pct={ahorro_pct} cumple={cumple_meta} recibo_plan={d['proyectado']['recibo']['total']} "
            f"excedente_kwh={d['proyectado']['kwh_excedente']}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 40.0))
