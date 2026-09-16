"""Modelo local y simplificado de la tarifa CFE DAC (Domestica de Alto Consumo).

No existe una API publica de CFE para consultar la tarifa en tiempo real --
por eso se modela localmente, tal como describe la propuesta del proyecto.
Es una aproximacion ilustrativa (horario pico/base tipico de verano en
tarifas DAC), NO el tarifario oficial vigente -- ajustar PRECIOS_MXN_KWH
con el recibo real de luz cuando se tenga.
"""
from datetime import datetime

# (hora_inicio, hora_fin) en formato 24h, ambas inclusive del lado de inicio.
PERIODO_PUNTA = (18, 22)   # 18:00 - 21:59, el tramo mas caro
PRECIOS_MXN_KWH = {
    "base": 1.20,
    "punta": 4.50,
}


def periodo_actual(hora: int | None = None) -> str:
    """'punta' o 'base' segun la hora del dia (local)."""
    h = hora if hora is not None else datetime.now().hour
    inicio, fin = PERIODO_PUNTA
    return "punta" if inicio <= h < fin else "base"


def precio_kwh(hora: int | None = None) -> float:
    return PRECIOS_MXN_KWH[periodo_actual(hora)]
