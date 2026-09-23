"""Rellena historial INVENTADO de telemetria para los dispositivos simulados
(ha_entity_id NULL), para que la demo tenga varios dias de habitos con los
que calcular perfiles, metas y planes. Borra primero el historial simulado
previo de esos dispositivos (venia de la curva generica vieja).

Nunca toca dispositivos con sensor real (ha_entity_id no nulo) y todo lo
que inserta va marcado fuente='simulada'.

Uso: .venv/bin/python demo_backfill.py [dias]   (default 14)
"""
import sys
from datetime import datetime, timedelta

import db
import telemetry_source

PASO = timedelta(minutes=5)


def main(dias: int = 14):
    ahora = datetime.now().astimezone().replace(second=0, microsecond=0)
    inicio = ahora - timedelta(days=dias)
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM devices WHERE ha_entity_id IS NULL OR ha_entity_id = ''")
            simulados = [r[0] for r in cur.fetchall()]
            cur.execute(
                "DELETE FROM telemetry WHERE device_id = ANY(%s) AND fuente = 'simulada'",
                (simulados,),
            )
            print(f"demo_backfill: borradas {cur.rowcount} lecturas simuladas previas")

            filas = []
            t = inicio
            while t < ahora:
                for device_id in simulados:
                    filas.append((t, device_id, telemetry_source.simular_consumo_dispositivo_w(device_id, t)))
                t += PASO
            cur.executemany(
                """INSERT INTO telemetry (tiempo, device_id, consumo_w, temp_interior_c, fuente)
                   VALUES (%s, %s, %s, NULL, 'simulada')""",
                filas,
            )
        conn.commit()
        print(f"demo_backfill: {len(filas)} lecturas inventadas ({dias} dias) para {simulados}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 14))
