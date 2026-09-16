"""Motor de decision: ¿que apagar primero si se acerca el limite de presupuesto?

Algoritmo: ordena dispositivos por peso de prioridad ascendente (1 = se
sacrifica primero) y va acumulando el ahorro estimado hasta cubrir el
excedente sobre el presupuesto.
"""


def priorizar_apagado(
    dispositivos: list[dict],   # [{'id', 'nombre', 'peso_prioridad', 'consumo_w'}]
    gasto_actual_mxn: float,
    presupuesto_mxn: float,
    precio_kwh: float,
) -> list[dict]:
    """Regresa la lista de dispositivos a apagar, en orden, hasta cubrir el excedente."""
    excedente_mxn = gasto_actual_mxn - presupuesto_mxn
    if excedente_mxn <= 0:
        return []

    candidatos = sorted(dispositivos, key=lambda d: d["peso_prioridad"])

    plan = []
    ahorro_acumulado_mxn = 0.0
    for d in candidatos:
        if ahorro_acumulado_mxn >= excedente_mxn:
            break
        ahorro_estimado_mxn = round((d["consumo_w"] / 1000) * precio_kwh, 4)
        ahorro_acumulado_mxn += ahorro_estimado_mxn
        plan.append({
            "device_id": d["id"],
            "nombre": d["nombre"],
            "razon": (
                f"Presupuesto excedido por ${excedente_mxn:.2f} MXN. "
                f"Prioridad {d['peso_prioridad']} (menor = se sacrifica antes). "
                f"Ahorro estimado al apagar: ${ahorro_estimado_mxn:.4f} MXN/hora."
            ),
        })

    return plan
