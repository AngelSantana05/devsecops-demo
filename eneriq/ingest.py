"""ETL de telemetria -- corre cada 5 min (ver systemd timer eneriq-ingest.timer).

1. Ingesta MQTT/HA (o simulada) por cada dispositivo registrado.
2. Normaliza y valida la lectura.
3. Guarda en TimescaleDB (el promedio movil se calcula en consulta, no aqui).
"""
import sys
from datetime import datetime, timezone

import db
import telemetry_source
import weather


def dispositivos_activos(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, ha_entity_id FROM devices")
        return cur.fetchall()


def main():
    conn = db.get_connection()
    try:
        temp_exterior = weather.temperatura_actual_c()
    except Exception as e:
        print(f"ingest: no se pudo obtener clima ({e}), usando 25.0C de respaldo")
        temp_exterior = 25.0

    ahora = datetime.now(timezone.utc)
    dispositivos = dispositivos_activos(conn)

    with conn.cursor() as cur:
        for device_id, ha_entity_id in dispositivos:
            lectura = telemetry_source.leer_telemetria(ha_entity_id, temp_exterior)
            cur.execute(
                """INSERT INTO telemetry (tiempo, device_id, consumo_w, temp_interior_c, fuente)
                   VALUES (%s, %s, %s, %s, %s)""",
                (ahora, device_id, lectura["consumo_w"], lectura["temp_interior_c"], lectura["fuente"]),
            )
            print(f"ingest: {device_id} consumo={lectura['consumo_w']}W "
                  f"temp_int={lectura['temp_interior_c']}C fuente={lectura['fuente']}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
