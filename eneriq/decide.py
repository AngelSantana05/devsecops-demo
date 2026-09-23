"""Corre el motor de decision del AC + deteccion de anomalias sobre la
telemetria mas reciente. Pensado para correr cada 15 min (ver
eneriq-decide.timer).
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import analytics
import config
import db
import publish_ha
import tariff
from decision_engine.ac_decision import decidir_ac
from decision_engine.anomaly_detection import detectar_anomalia


def ultima_lectura(cur, device_id: str):
    cur.execute(
        """SELECT tiempo, consumo_w, temp_interior_c FROM telemetry
           WHERE device_id = %s ORDER BY tiempo DESC LIMIT 1""",
        (device_id,),
    )
    return cur.fetchone()


def promedio_historico(cur, device_id: str, dias: int = 7):
    cur.execute(
        """SELECT avg(consumo_w) FROM telemetry
           WHERE device_id = %s AND tiempo > now() - interval '%s days'""",
        (device_id, dias),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else 0.0


def registrar_decision(cur, device_id, tipo, accion, razon, datos):
    cur.execute(
        """INSERT INTO decisions_log (device_id, tipo_decision, accion, razon, datos)
           VALUES (%s, %s, %s, %s, %s)""",
        (device_id, tipo, accion, razon, json.dumps(datos)),
    )


def main():
    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, ha_entity_id, control_on_service, control_off_service, auto_control_enabled
               FROM devices WHERE tipo = 'ac'"""
        )
        dispositivos_ac = cur.fetchall()
        kwh_mes = analytics.consumo_mes(cur)["kwh_mes"]

        anomalias = []
        for device_id, ha_entity_id, control_on, control_off, auto_control in dispositivos_ac:
            lectura = ultima_lectura(cur, device_id)
            if lectura is None:
                continue
            _, consumo_w, temp_interior_c = lectura

            escalon, precio = tariff.escalon_actual(kwh_mes)

            accion, razon = decidir_ac(
                temp_interior_c, config.TEMP_CONFORT_MAX_C, escalon, precio
            )
            evidencia = {
                "temp_interior_c": temp_interior_c,
                "periodo_tarifa": f"{tariff.temporada()}, escalon {escalon}",
                "escalon_tarifa": escalon,
                "consumo_mes_kwh": round(kwh_mes, 1),
                "precio_kwh_mxn": precio,
                "umbral_confort_c": config.TEMP_CONFORT_MAX_C,
            }
            registrar_decision(cur, device_id, "ac", accion, razon, evidencia)
            publish_ha.publicar_decision_ac(accion, razon, evidencia)

            if not auto_control:
                print(f"decide: {device_id} -> {accion} (auto_control_enabled=false, "
                      f"NO se toca el AC de verdad -- solo registro/alerta)")
            elif accion == "encender" and control_on:
                try:
                    publish_ha.llamar_servicio(control_on)
                except Exception as e:
                    print(f"decide: no se pudo llamar {control_on}: {e}")
            # accion == "esperar" nunca fuerza un apagado -- evita pelear con
            # control manual del usuario. Ver REPORTE_FINAL.md / README para el
            # razonamiento.

            promedio = promedio_historico(cur, device_id)
            es_anomalia, razon_anomalia = detectar_anomalia(
                consumo_w, promedio, config.ANOMALIA_UMBRAL_PCT
            )
            if es_anomalia:
                datos_anomalia = {
                    "consumo_actual_w": consumo_w,
                    "promedio_historico_w": promedio,
                }
                registrar_decision(cur, device_id, "anomalia", "alertar", razon_anomalia, datos_anomalia)
                anomalias.append({"device_id": device_id, "razon": razon_anomalia, **datos_anomalia})

            print(f"decide: {device_id} -> {accion} ({razon})")

        cur.execute(
            """SELECT tiempo, device_id, tipo_decision, accion, razon FROM decisions_log
               WHERE tiempo > now() - interval '24 hours'
               ORDER BY tiempo DESC LIMIT 20"""
        )
        bitacora = [
            {"tiempo": t.isoformat(), "device_id": d, "tipo": ti, "accion": a, "razon": r}
            for t, d, ti, a, r in cur.fetchall()
        ]
        publish_ha.publicar_bitacora(bitacora)
        publish_ha.publicar_anomalias(anomalias)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
