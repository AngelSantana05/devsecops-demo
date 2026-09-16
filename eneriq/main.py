"""EnerIQ Gateway -- API de solo lectura sobre las decisiones/telemetria.

No se expone a la LAN (solo localhost) -- HA consulta los sensores push
(ver publish_ha.py), esta API es para depuracion/inspeccion directa y para
integraciones futuras (ej. un dashboard propio, si algun dia hace falta
mas que los paneles de HA).

Correr con: uvicorn main:app --host 127.0.0.1 --port 8091
"""
from datetime import date

from fastapi import FastAPI

import db

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
