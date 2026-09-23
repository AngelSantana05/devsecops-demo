"""EnerIQ Gateway -- API de solo lectura sobre las decisiones/telemetria,
mas 1 endpoint de accion (/plan/llm/generar).

Expuesta en la red interna de LXCs (10.10.10.0/24, bridge vmbr0) -- NO en
la LAN de casa, no hay DNAT hacia afuera. HA (10.10.10.10) le pega directo
sin necesidad de regla de firewall nueva, mismo patron que el gateway de IA
(ver services/ai-stack.md). Los sensores push (ver publish_ha.py) siguen
siendo la via normal de consulta; esta API es para depuracion/inspeccion
directa, integraciones futuras, y el trigger bajo demanda del plan con IA.

Correr con: uvicorn main:app --host 0.0.0.0 --port 8091
"""
from datetime import date

from fastapi import FastAPI

import db
import plan_llm

app = FastAPI(title="EnerIQ Gateway")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/decisions/recent")
def decisiones_recientes(limit: int = 20):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tiempo, device_id, tipo_decision, accion, razon, datos
                   FROM decisions_log ORDER BY tiempo DESC LIMIT %s""",
                (limit,),
            )
            filas = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "tiempo": t.isoformat(),
            "device_id": d,
            "tipo": ti,
            "accion": a,
            "razon": r,
            "datos": datos,
        }
        for t, d, ti, a, r, datos in filas
    ]


@app.get("/schedule/{fecha}")
def plan_del_dia(fecha: date):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT device_id, hora, accion_sugerida, razon
                   FROM schedules WHERE fecha = %s ORDER BY hora""",
                (fecha,),
            )
            filas = cur.fetchall()
    finally:
        conn.close()
    return [
        {"device_id": d, "hora": h, "accion_sugerida": a, "razon": r}
        for d, h, a, r in filas
    ]


@app.post("/plan/llm/generar")
def generar_plan_llm():
    """Dispara la generacion del plan de manana explicado por el LLM local
    (bajo demanda, ej. boton del dashboard -> rest_command de HA). Sincrono
    a proposito -- el modelo local tarda unos segundos, no minutos, y asi
    el boton puede mostrar de una vez si funciono o no.
    """
    try:
        plan_llm.main()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/telemetry/{device_id}/latest")
def telemetria_reciente(device_id: str, limit: int = 50):
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT tiempo, consumo_w, temp_interior_c, fuente FROM telemetry
                   WHERE device_id = %s ORDER BY tiempo DESC LIMIT %s""",
                (device_id, limit),
            )
            filas = cur.fetchall()
    finally:
        conn.close()
    return [
        {"tiempo": t.isoformat(), "consumo_w": c, "temp_interior_c": ti, "fuente": f}
        for t, c, ti, f in filas
    ]
