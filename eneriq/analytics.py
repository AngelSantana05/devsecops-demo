"""Analitica de consumo/gasto -- corre cada 5 min (ver eneriq-analytics.timer).

Suma el consumo instantaneo de TODOS los dispositivos (reales + simulados)
en cada corte de ingesta para aproximar el consumo total de "la casa
completa", lo integra a kWh y le aplica el precio de tariff.py segun la
hora (punta/base) para acumular el gasto del dia. Publica 2 sensores en HA
pensados para graficarse con el card nativo "history-graph" (sin HACS).
"""
import sys
from datetime import datetime, timezone

import db
import publish_ha
import tariff


def lecturas_de_hoy(cur):
    """Todas las lecturas (tiempo, consumo_w) de hoy, agrupadas por tiempo
    de ingesta (todos los dispositivos se leen en el mismo instante por
    corrida de ingest.py, asi que agrupar por tiempo == "consumo total de
    la casa en ese corte").
    """
    cur.execute(
        """SELECT tiempo, sum(consumo_w) AS consumo_total_w
           FROM telemetry
           WHERE tiempo >= date_trunc('day', now())
           GROUP BY tiempo
           ORDER BY tiempo"""
    )
    return cur.fetchall()


def calcular_consumo_gasto_hoy(cur, intervalo_min: float = 5.0):
    consumo_kwh_total = 0.0
    costo_mxn_total = 0.0
    for tiempo, consumo_total_w in lecturas_de_hoy(cur):
        kwh_intervalo = (consumo_total_w or 0.0) * (intervalo_min / 60.0) / 1000.0
        precio = tariff.precio_kwh(tiempo.astimezone().hour)
        consumo_kwh_total += kwh_intervalo
        costo_mxn_total += kwh_intervalo * precio
    return round(consumo_kwh_total, 3), round(costo_mxn_total, 2)


def main():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            consumo_kwh_hoy, costo_mxn_hoy = calcular_consumo_gasto_hoy(cur)

        periodo = tariff.periodo_actual()
        precio_actual = tariff.precio_kwh()

        publish_ha.publicar_consumo_gasto(
            consumo_kwh_hoy, costo_mxn_hoy, periodo, precio_actual
        )
        print(f"analytics: consumo_hoy={consumo_kwh_hoy}kWh gasto_hoy={costo_mxn_hoy}MXN "
              f"periodo={periodo} precio_kwh={precio_actual}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
