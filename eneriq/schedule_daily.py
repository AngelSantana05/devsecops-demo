"""Genera el plan del dia siguiente -- corre cada madrugada (ver
eneriq-schedule.timer). Cruza el pronostico de clima con el escalon de la
tarifa CFE en el que va el consumo del mes.
"""
import sys
from datetime import date, timedelta

import analytics
import config
import db
import publish_ha
import tariff
import weather
from decision_engine.scheduler import generar_plan_manana


def main():
    pronostico = weather.pronostico_manana_c()
    manana = date.today() + timedelta(days=1)

    conn = db.get_connection()
    with conn.cursor() as cur:
        # si manana empieza mes nuevo, el consumo arranca de cero (escalon basico)
        kwh_mes = analytics.consumo_mes(cur)["kwh_mes"] if manana.month == date.today().month else 0.0
    escalon, precio = tariff.escalon_actual(kwh_mes, manana)
    plan = generar_plan_manana(pronostico, config.TEMP_CONFORT_MAX_C, escalon, precio)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM devices WHERE tipo = 'ac'")
        dispositivos_ac = [row[0] for row in cur.fetchall()]

        for device_id in dispositivos_ac:
            for entrada in plan:
                cur.execute(
                    """INSERT INTO schedules (fecha, device_id, hora, accion_sugerida, razon)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (fecha, device_id, hora)
                       DO UPDATE SET accion_sugerida = EXCLUDED.accion_sugerida,
                                     razon = EXCLUDED.razon""",
                    (manana, device_id, entrada["hora"], entrada["accion_sugerida"], entrada["razon"]),
                )
    conn.commit()
    conn.close()

    publish_ha.publicar_plan_manana(plan)
    print(f"schedule_daily: plan generado para {manana} ({len(plan)} horas, escalon {escalon})")


if __name__ == "__main__":
    sys.exit(main())
