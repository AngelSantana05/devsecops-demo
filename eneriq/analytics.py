"""Analitica de consumo/gasto -- corre cada 5 min (ver eneriq-analytics.timer).

Suma el consumo instantaneo de TODOS los dispositivos (reales + simulados)
para aproximar el consumo total de "la casa completa" y lo integra a kWh.
El gasto se calcula con la tarifa real de CFE (Tarifa 1C, ver tariff.py): el
precio de cada kWh depende de cuanto se lleva consumido en el mes (escalones),
asi que el gasto de hoy se cobra "encima" del consumo acumulado del mes.

Publica 2 sensores en HA pensados para graficarse con el card nativo
"history-graph" (sin HACS), con el escalon actual y la proyeccion del recibo.
"""
import calendar
import sys
from datetime import datetime

import db
import publish_ha
import tariff

MINUTOS_POR_CORTE = 5.0  # ingest.py corre cada 5 min


def kwh_entre(cur, desde: datetime, hasta: datetime) -> float:
    """kWh consumidos por toda la casa entre dos instantes (cada lectura
    representa un corte de 5 min de ese dispositivo)."""
    cur.execute(
        "SELECT coalesce(sum(consumo_w), 0) FROM telemetry WHERE tiempo >= %s AND tiempo < %s",
        (desde, hasta),
    )
    return float(cur.fetchone()[0]) * (MINUTOS_POR_CORTE / 60.0) / 1000.0


def consumo_mes(cur, ahora: datetime | None = None) -> dict:
    """Consumo del mes en curso: acumulado hasta antes de hoy, hoy, y la
    proyeccion al cierre del mes a este ritmo."""
    ahora = ahora or datetime.now().astimezone()
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    previo = kwh_entre(cur, inicio_mes, inicio_hoy)
    hoy = kwh_entre(cur, inicio_hoy, ahora)
    dias_mes = calendar.monthrange(ahora.year, ahora.month)[1]
    dias_transcurridos = max((ahora - inicio_mes).total_seconds() / 86400.0, 1 / 24)
    return {
        "kwh_previo": previo,
        "kwh_hoy": hoy,
        "kwh_mes": previo + hoy,
        "kwh_mes_proyectado": (previo + hoy) / dias_transcurridos * dias_mes,
        "dias_mes": dias_mes,
    }


def main():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            c = consumo_mes(cur)

        hoy = datetime.now().date()
        costo_mxn_hoy = round(tariff.costo_incremental(c["kwh_previo"], c["kwh_hoy"], hoy), 2)
        escalon, precio_marginal = tariff.escalon_actual(c["kwh_mes"], hoy)
        temporada = tariff.temporada(hoy)
        recibo = tariff.recibo_mensual(c["kwh_mes_proyectado"], hoy)

        publish_ha.publicar_consumo_gasto(
            round(c["kwh_hoy"], 3),
            costo_mxn_hoy,
            f"{temporada}, escalon {escalon}",
            precio_marginal,
            {
                "tarifa": "CFE 1C (Monterrey)",
                "escalon_actual": escalon,
                "consumo_mes_kwh": round(c["kwh_mes"], 1),
                "consumo_mes_proyectado_kwh": round(c["kwh_mes_proyectado"], 1),
                "limite_subsidiado_kwh": tariff.limite_subsidiado_kwh(hoy),
                "recibo_mes_proyectado_mxn": recibo["total"],
            },
        )
        print(f"analytics: hoy={c['kwh_hoy']:.2f}kWh ${costo_mxn_hoy} mes={c['kwh_mes']:.1f}kWh "
              f"escalon={escalon} (${precio_marginal}/kWh) recibo_proyectado=${recibo['total']}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
