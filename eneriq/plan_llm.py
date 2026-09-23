"""Genera una explicacion en lenguaje natural del plan de manana, usando el
LLM local del homelab (Ollama directo, LXC `ai`, ver services/ai-stack.md
del skill homelab-implement).

No le pide al modelo que DECIDA nada -- el motor de reglas
(decision_engine.scheduler) ya genero el plan hora por hora con datos duros
(clima, escalon de la tarifa CFE, umbral de confort). El LLM solo lo explica en espanol
llano, siguiendo la misma filosofia del resto del homelab: el LLM local es
para contexto/explicaciones, no para tomar decisiones.

**Por que Ollama directo y no el gateway de IA (10.10.10.12:8090):**
probado en vivo 2026-09-22 -- el gateway (`/v1/chat/completions`, con su
loop de tool-calling de HA) se cuelga indefinidamente con este prompt
(200s+ sin respuesta, 0 bytes, ni un log de `[tool]`), mientras que pegarle
directo a Ollama con el mismo prompt responde en ~6s. No hace falta nada
de tool-calling para esta tarea (solo narrar datos que ya vienen dados),
asi que se evita el gateway por completo en vez de debuggear su loop de
herramientas -- pendiente investigar esa causa raiz por separado, ver
memoria `project-homelab-llm-ollama`.

Se corre bajo demanda (boton en el dashboard -> POST /plan/llm/generar en
main.py), no por timer.
"""
import sys
from datetime import date, timedelta

import analytics
import config
import db
import publish_ha
import requests
import tariff

OLLAMA_URL = "http://10.10.10.12:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:3b-instruct"


def plan_de_manana(cur) -> list[dict]:
    manana = date.today() + timedelta(days=1)
    cur.execute(
        """SELECT hora, accion_sugerida, razon FROM schedules
           WHERE device_id = 'ac' AND fecha = %s ORDER BY hora""",
        (manana,),
    )
    filas = cur.fetchall()
    return [{"hora": h, "accion_sugerida": a, "razon": r} for h, a, r in filas]


def contexto_tarifa(cur) -> dict:
    """Consumo del mes y escalon de la tarifa CFE en el que cae."""
    c = analytics.consumo_mes(cur)
    hoy = date.today()
    escalon, precio = tariff.escalon_actual(c["kwh_mes"], hoy)
    return {
        "kwh_mes": round(c["kwh_mes"], 1),
        "kwh_mes_proyectado": round(c["kwh_mes_proyectado"], 1),
        "limite_subsidiado": tariff.limite_subsidiado_kwh(hoy),
        "escalon": escalon,
        "precio": precio,
        "gasto_hoy": round(tariff.costo_incremental(c["kwh_previo"], c["kwh_hoy"], hoy), 2),
        "temporada": tariff.temporada(hoy),
    }


def construir_prompt(plan: list[dict], t: dict) -> str:
    horas_encender = [p["hora"] for p in plan if p["accion_sugerida"] == "encender"]
    resumen_plan = "\n".join(
        f"- {p['hora']:02d}:00 -> {p['accion_sugerida']} ({p['razon']})"
        for p in plan
    ) or "(el plan de manana todavia no se genero -- avisa que falta correr el scheduling)"
    faltan = max(t["limite_subsidiado"] - t["kwh_mes"], 0)

    return f"""Eres el asistente de EnerIQ, un orquestador de energia domestica en Monterrey.
Ya existe un plan calculado por reglas para manana, hora por hora (no lo
inventes, no cambies los numeros, solo explicalo):

{resumen_plan}

Datos de contexto:
- Tarifa CFE 1C (Monterrey), temporada {t['temporada']}. CFE cobra por escalones de
  consumo del mes, NO por hora: la hora del dia no cambia el precio.
- Consumo del mes hasta hoy: {t['kwh_mes']} kWh; a este ritmo cierra el mes en {t['kwh_mes_proyectado']} kWh.
- Los primeros {t['limite_subsidiado']:.0f} kWh del mes estan subsidiados; despues todo es escalon excedente.
- Escalon actual: {t['escalon']}, cada kWh extra cuesta ${t['precio']} con IVA
  (faltan {faltan:.0f} kWh para llegar al excedente).
- Umbral de confort configurado: {config.TEMP_CONFORT_MAX_C}C
- Horas en las que el plan sugiere encender el aire: {horas_encender if horas_encender else 'ninguna'}

Escribe en espanol, en 4-6 lineas, un plan practico y breve para manana
explicando como mantenerse cerca del umbral de confort gastando la menor
cantidad de kWh posible. No hables de horario punta ni de mover aparatos de
hora (en esta tarifa no ahorra). Tono directo, como si le hablaras al dueno
de la casa. No uses markdown, no repitas la tabla completa, resume lo importante."""


def main():
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            plan = plan_de_manana(cur)
            t = contexto_tarifa(cur)

        prompt = construir_prompt(plan, t)
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        plan_texto = data["message"]["content"].strip()

        publish_ha.publicar_plan_llm(plan_texto, OLLAMA_MODEL, t["gasto_hoy"])
        print(f"plan_llm: generado via {OLLAMA_MODEL} ({len(plan_texto)} caracteres)")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
