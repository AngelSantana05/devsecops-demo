"""Genera el plan del dia siguiente -- corre cada madrugada (ver
eneriq-schedule.timer). Cruza pronostico de clima + tarifa por hora.
"""
import sys
from datetime import date, timedelta

import config
import db
import publish_ha
import weather
from decision_engine.scheduler import generar_plan_manana


def main():
    pronostico = weather.pronostico_manana_c()
    plan = generar_plan_manana(pronostico, config.TEMP_CONFORT_MAX_C)

    conn = db.get_connection()
    manana = date.today() + timedelta(days=1)
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
    print(f"schedule_daily: plan generado para {manana} ({len(plan)} horas)")


if __name__ == "__main__":
    sys.exit(main())
