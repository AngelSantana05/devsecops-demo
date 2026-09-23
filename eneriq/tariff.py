"""Tarifa electrica real de CFE para la casa: Tarifa 1C (Monterrey, N.L.).

Monterrey esta clasificada en la Tarifa 1C (localidades con temperatura media
minima en verano de 30C). Las tarifas domesticas de CFE NO cobran por hora del
dia: cobran por ESCALONES de consumo mensual. Los primeros kWh del mes salen
baratos (subsidiados) y cada escalon siguiente es mas caro; el escalon
"excedente" cuesta ~4 veces el basico. Por eso lo caro no es una hora, sino
cada kWh que ya cae en el excedente.

Fuente: CFE, "Tarifa 1C" y "Tarifa DAC", cuotas 2026 publicadas en
https://app.cfe.mx/Aplicaciones/CCFE/Tarifas/TarifasCRECasa/Tarifas/Tarifa1C.aspx
(consultado 2026-09-22, verano iniciando en abril). Las cuotas se ajustan cada
mes; aqui estan las 12 de 2026. Para otro anio se usan las del mismo mes de 2026.

Simplificaciones: los limites son mensuales (CFE factura por bimestre con los
limites al doble, el costo es equivalente); no incluye el Derecho de Alumbrado
Publico (DAP), que cobra el municipio aparte en el mismo recibo.
"""
from datetime import date

import config

IVA = 0.16

# Temporada de verano: 6 meses consecutivos. En Nuevo Leon el subsidio de
# verano arranca el 1 de abril -> abril a septiembre.
MESES_VERANO = [((config.VERANO_MES_INICIO - 1 + i) % 12) + 1 for i in range(6)]

# Escalones de la Tarifa 1C: (nombre, kWh del escalon por mes; None = sin limite)
ESCALONES_VERANO = [("basico", 150), ("intermedio bajo", 150), ("intermedio alto", 150), ("excedente", None)]
ESCALONES_FUERA_VERANO = [("basico", 75), ("intermedio", 100), ("excedente", None)]

# Cuotas 2026 en MXN/kWh, sin IVA, en el mismo orden que los escalones.
CUOTAS_2026 = {
    # fuera de verano: basico, intermedio, excedente
    1: [1.110, 1.349, 3.944],
    2: [1.113, 1.353, 3.956],
    3: [1.116, 1.357, 3.968],
    # verano: basico, intermedio bajo, intermedio alto, excedente
    4: [1.001, 1.159, 1.490, 3.980],
    5: [1.004, 1.163, 1.495, 3.992],
    6: [1.007, 1.167, 1.500, 4.004],
    7: [1.010, 1.171, 1.505, 4.016],
    8: [1.013, 1.175, 1.510, 4.028],
    9: [1.016, 1.179, 1.515, 4.041],
    # fuera de verano
    10: [1.140, 1.385, 4.054],
    11: [1.144, 1.389, 4.067],
    12: [1.148, 1.393, 4.080],
}

# Tarifa DAC (Domestica de Alto Consumo): si el PROMEDIO MOVIL de 12 meses
# supera el limite de la localidad, CFE reclasifica el servicio a DAC y se
# pierde todo el subsidio. Region "Norte y Noreste", septiembre 2026.
LIMITE_DAC_KWH_MES = 850
DAC_CARGO_FIJO_MXN = 145.85
DAC_PRECIO_KWH = 5.984


def temporada(fecha: date | None = None) -> str:
    fecha = fecha or date.today()
    return "verano" if fecha.month in MESES_VERANO else "fuera de verano"


def escalones(fecha: date | None = None) -> list[tuple[str, float | None, float]]:
    """[(nombre, kWh_del_escalon | None, precio_mxn_kwh_sin_iva), ...] del mes."""
    fecha = fecha or date.today()
    base = ESCALONES_VERANO if temporada(fecha) == "verano" else ESCALONES_FUERA_VERANO
    cuotas = CUOTAS_2026[fecha.month]
    if len(cuotas) != len(base):
        # el mes cae en otra temporada que en la tabla 2026 (VERANO_MES_INICIO
        # distinto de abril): usar las cuotas del mes mas cercano de esa temporada
        cuotas = next(
            CUOTAS_2026[m] for m in sorted(CUOTAS_2026, key=lambda m: abs(m - fecha.month))
            if len(CUOTAS_2026[m]) == len(base)
        )
    return [(nombre, kwh, precio) for (nombre, kwh), precio in zip(base, cuotas)]


def desglose(kwh_desde: float, kwh_hasta: float, fecha: date | None = None) -> list[dict]:
    """Reparte los kWh consumidos entre `kwh_desde` y `kwh_hasta` (acumulado
    del mes) en los escalones que tocan. Sin IVA."""
    partes = []
    inicio = 0.0
    for nombre, tam, precio in escalones(fecha):
        fin = float("inf") if tam is None else inicio + tam
        a, b = max(kwh_desde, inicio), min(kwh_hasta, fin)
        if b > a:
            partes.append({"escalon": nombre, "kwh": b - a, "precio": precio, "importe": (b - a) * precio})
        inicio = fin
    return partes


def costo_incremental(kwh_previos_mes: float, kwh_nuevos: float, fecha: date | None = None) -> float:
    """Cuanto cuestan (MXN, con IVA) `kwh_nuevos` si ya se llevan
    `kwh_previos_mes` consumidos en el mes."""
    subtotal = sum(p["importe"] for p in desglose(kwh_previos_mes, kwh_previos_mes + kwh_nuevos, fecha))
    return subtotal * (1 + IVA)


def recibo_mensual(kwh_mes: float, fecha: date | None = None) -> dict:
    """Recibo de luz de un mes con `kwh_mes` consumidos (Tarifa 1C)."""
    partes = desglose(0.0, kwh_mes, fecha)
    subtotal = sum(p["importe"] for p in partes)
    return {
        "kwh": round(kwh_mes, 1),
        "escalones": [
            {"escalon": p["escalon"], "kwh": round(p["kwh"], 1), "precio": p["precio"], "importe": round(p["importe"], 2)}
            for p in partes
        ],
        "subtotal": round(subtotal, 2),
        "iva": round(subtotal * IVA, 2),
        "total": round(subtotal * (1 + IVA), 2),
    }


def recibo_dac(kwh_mes: float) -> float:
    """Lo que costaria el mismo mes si el servicio ya estuviera en DAC (con IVA)."""
    return round((DAC_CARGO_FIJO_MXN + kwh_mes * DAC_PRECIO_KWH) * (1 + IVA), 2)


def escalon_actual(kwh_mes_acumulado: float, fecha: date | None = None) -> tuple[str, float]:
    """Escalon en el que cae el siguiente kWh y su precio marginal (MXN/kWh, con IVA)."""
    inicio = 0.0
    for nombre, tam, precio in escalones(fecha):
        if tam is None or kwh_mes_acumulado < inicio + tam:
            return nombre, round(precio * (1 + IVA), 3)
        inicio += tam
    raise AssertionError("el ultimo escalon no tiene limite")


def limite_subsidiado_kwh(fecha: date | None = None) -> float:
    """kWh del mes antes de entrar al escalon excedente."""
    return sum(tam for _, tam, _ in escalones(fecha) if tam is not None)


# --- Modelo anterior por horario (punta/base) ---
# Se conserva mientras el resto del codigo migra a escalones; se retira despues.
PERIODO_PUNTA = (18, 22)
PRECIOS_MXN_KWH = {"base": 1.20, "punta": 4.50}


def periodo_actual(hora: int | None = None) -> str:
    from datetime import datetime
    h = hora if hora is not None else datetime.now().hour
    inicio, fin = PERIODO_PUNTA
    return "punta" if inicio <= h < fin else "base"


def precio_kwh(hora: int | None = None) -> float:
    return PRECIOS_MXN_KWH[periodo_actual(hora)]
