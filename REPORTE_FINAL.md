# Auditoría de Seguridad DevSecOps — `devsecops-demo`

**Repositorio auditado:** [`devsecops-demo`](https://github.com/AngelSantana05/devsecops-demo)
**Estudiante:** Angel Vicente Santana Loera
**Materia:** Herramientas de tecnologías de la información
**Institución:** Tecmilenio
**Plan original:** 28 de agosto de 2026 · **Ejecución y hallazgos reales:** 15-16 de septiembre de 2026

> Este informe extiende el plan de auditoría original (Secciones 1-5, ya
> evaluadas) con la ejecución real de las tres herramientas seleccionadas
> sobre el repositorio (Secciones 6-11): hallazgos consolidados,
> clasificación, análisis de falso positivo, plan de remediación, evidencia
> del pipeline de CI/CD, y guía de empaquetado/adaptación para otros
> usuarios.

---

## 1. Propósito de la auditoría y fundamento de DevSecOps

### 1.1 Introducción y propósito de la auditoría

Este documento plantea el plan y los resultados de una auditoría de
seguridad sobre el repositorio `devsecops-demo`, un proyecto en Python que
simula la gestión de un bucket de almacenamiento compatible con S3 mediante
LocalStack. Incluye un flujo de trabajo con ramas `dev` y `production`, un
conjunto de scripts que validan políticas de acceso y detectan secretos
expuestos, y una bitácora de auditoría de pipeline (`pipeline_audit.log`).

El propósito de auditar un repositorio no es solo encontrar errores
puntuales, sino verificar sistemáticamente tres dimensiones que suelen pasar
inadvertidas durante el desarrollo cotidiano:

1. La calidad de seguridad del código que el equipo escribe.
2. La exposición a vulnerabilidades heredadas de dependencias de terceros.
3. La presencia de credenciales o secretos expuestos — incluso
   temporalmente — en el historial de control de versiones.

En `devsecops-demo` estas tres dimensiones están presentes de forma
concreta: código Python propio en `app-ejemplo/`, dependencias gestionadas
con `pip`, y un antecedente ya documentado de una clave de AWS embebida en
`config_malo.py` durante la simulación del flujo de la rama `dev`.

### 1.2 Fundamento de DevSecOps y shift-left

DevSecOps extiende la cultura de CI/CD de DevOps para incorporar la
seguridad como responsabilidad compartida y continua a lo largo de todo el
ciclo de vida del software, en lugar de una revisión aislada justo antes del
lanzamiento. El principio central es **shift-left**: mover las
verificaciones de seguridad a las etapas más tempranas del desarrollo —
idealmente al commit o al pull request — en vez de esperar a una auditoría
manual final.

El propio repositorio ya materializa este principio parcialmente:
`gatekeeper.py` ejecuta un escaneo de secretos y una validación de política
de infraestructura antes de autorizar que un cambio pase de `dev` a
`production`, bloqueando el flujo si algún control falla (ver la bitácora
real en `pipeline_audit.log`, Sección 9). El propósito de esta auditoría es
**formalizar y ampliar** esa lógica: en lugar de un único chequeo de
secretos por expresiones regulares, se incorporan herramientas
especializadas de SAST, SCA y escaneo de secretos sobre el historial
completo, como puertas de control automatizadas y repetibles en CI (ver
Sección 9).

### 1.3 Diferencia con las revisiones de seguridad al final del ciclo

Una revisión tradicional al final del ciclo evalúa el sistema una sola vez,
cuando el código ya está casi terminado. El enfoque DevSecOps evalúa cada
cambio de forma incremental. Esta auditoría no reemplaza la lógica continua
que ya existía (`gatekeeper.py`): la robustece con cobertura que el
escáner de secretos artesanal no ofrecía — y la Sección 6 muestra
exactamente qué encontró cada herramienta que `scan_secrets.py` por sí solo
no hubiera podido encontrar.

---

## 2. Revisión preliminar del repositorio y riesgo esperado

| Elemento observado | Riesgo esperado | Justificación técnica | ¿Confirmado en la ejecución real? |
|---|---|---|---|
| `app-ejemplo/config_malo.py` | Secreto expuesto en el código fuente | Contiene credenciales de AWS como literales de texto | **Sí** — ver Sección 6, hallazgo #1 |
| Historial de Git (rama `dev`) | Secreto persistente en commits anteriores | El secreto se removió en un commit posterior, pero el commit original permanece en el historial | **Sí** — Gitleaks lo encontró en el commit `1b8bad6`, ver Sección 6 |
| `requirements.txt` (pip) | Dependencias de terceros con CVEs conocidos | `requests`/`python-dotenv` gestionados vía pip sin control de SCA | **Sí** — 3 CVEs en `requests`, 1 en `python-dotenv`, ver Sección 6 |
| `infra/bucket_policy_publico.json` | Configuración de infraestructura excesivamente permisiva | Política simulada con `Principal: "*"` y `Action: "s3:*"` | **Sí** — confirmada por inspección manual y por `gatekeeper.py`, ver Sección 6 |
| `scripts/scan_secrets.py` | Cobertura limitada del control de secretos existente | Regex propio, no revisa historial de git | **Sí** — demostrado en vivo: pasa limpio en el árbol de trabajo actual mientras Gitleaks sí encuentra el secreto en el historial |
| Flujo `dev` → `production` | Sin puerta de control a nivel de plataforma | El gatekeeper corría solo en local | **Corregido** — ahora es un paso obligatorio del pipeline de CI, ver Sección 9 |

---

## 3. Selección y justificación de herramientas SAST, SCA y secret scanning

| Categoría | Herramienta | Versión usada | Compatibilidad técnica | Hallazgos esperados |
|---|---|---|---|---|
| **SAST** | [Bandit](https://bandit.readthedocs.io/) | `1.9.4` | Analizador AST 100% Python, corre directo sobre `app-ejemplo/` y `scripts/` | Credenciales embebidas, `subprocess` inseguro, rutas temporales predecibles |
| **SCA** | [pip-audit](https://pypi.org/project/pip-audit/) | `2.9.0` (CLI) | Lee `requirements.txt` sin instalar el proyecto; base de datos PyPA/OSV | CVEs conocidos en dependencias declaradas |
| **Secret scanning** | [Gitleaks](https://github.com/gitleaks/gitleaks) | `8.21.2` (binario) | Escanea todo el historial de commits, no solo el árbol de trabajo | Secretos ya removidos del código pero presentes en commits anteriores |

*(Nota: `bandit==1.7.9` y `pip-audit==2.7.3`, las versiones propuestas en el
plan original, resultaron incompatibles con intérpretes Python recientes —
ver Sección 10, nota de portabilidad. Se repinearon a las versiones
estables más nuevas verificadas contra Python 3.12/3.13/3.14.)*

### 3.1 Complementariedad de las tres herramientas (confirmada en la ejecución real)

La ejecución real reveló un caso concreto y no anticipado de
complementariedad: al correr Bandit sobre `config_malo.py` en su versión
original (con el secreto hardcodeado), la regla `B105` (hardcoded password
string) **sí detectó parcialmente el problema, pero lo clasificó como
severidad BAJA / confianza MEDIA** — porque Bandit evalúa el *patrón del
nombre de variable y la entropía del string*, no si el valor coincide con
el formato real de una credencial de un proveedor cloud específico.
Gitleaks, en cambio, usa una regla dedicada (`aws-access-token`) que
reconoce el formato exacto `AKIA[0-9A-Z]{16}` de AWS — el mismo hallazgo,
pero clasificado correctamente como lo que realmente es: una credencial de
nube expuesta, no un "posible password" genérico. Esto ilustra exactamente
la tesis de la Sección 1.2: **una sola herramienta no basta**, y la
severidad que reporta cada una no siempre refleja el riesgo real sin
cruzarla con el contexto de las otras.

---

## 4. Plan de ejecución de la auditoría

Ejecutado en un LXC dedicado (Debian 13, aislado del resto del homelab
donde vive este proyecto) con Docker para LocalStack y un entorno virtual
Python separado para las herramientas de auditoría (ver Sección 10, nota
sobre por qué separado del entorno de la aplicación).

1. Preparación del entorno — `requirements-audit.txt` con versiones fijas.
2. Revisión del repositorio — Sección 2, confirmada.
3. Ejecución de Bandit sobre `app-ejemplo/` y `scripts/` — Sección 6.
4. Ejecución de pip-audit sobre `requirements.txt` — Sección 6.
5. Ejecución de Gitleaks sobre el historial completo — Sección 6.
6. Documentación de hallazgos — Sección 6 (tabla consolidada).
7. Clasificación por tipo y severidad — Sección 7.
8. Análisis de falso positivo + propuesta de remediación — Sección 8.
9. Integración a CI/CD como quality gate — Sección 9.

---

## 5. Conclusión del plan original

*(Sección conservada del documento original — ver Sección 11 para la
conclusión final con los resultados reales.)*

Planear una auditoría antes de ejecutar cualquier herramienta obliga a
razonar explícitamente sobre qué se está protegiendo y por qué. El valor de
esta auditoría está en **ampliar** `gatekeeper.py`, no en sustituirlo, con
cobertura especializada de código, dependencias y secretos históricos que
el chequeo artesanal no alcanzaba a cubrir.

---

## 6. Hallazgos consolidados (evidencia real)

Comandos exactos ejecutados (reproducibles, ver también `README.md`):

```bash
bandit -r app-ejemplo scripts -f json -o reports/bandit-report.json
bandit -r app-ejemplo scripts -lll                                      # gate
pip-audit -r requirements.txt -f json -o reports/pip-audit-report.json
gitleaks detect --source . -v --report-format json --report-path reports/gitleaks-report.json
```

Reportes crudos (JSON) en [`reports/`](reports/): `bandit-report.json`,
`pip-audit-report.json`, `gitleaks-report.json` — corresponden al estado
del repositorio en el commit `7083f27` (después de aplicar las
remediaciones de secreto y dependencias, antes de la remediación de
`B602`, ver Sección 8).

| # | Herramienta | Tipo | Descripción | Archivo / componente | Severidad | Evidencia |
|---|---|---|---|---|---|---|
| 1 | Gitleaks | Secreto expuesto (histórico) | Credencial de AWS (`AKIAXAJI0Y6DPBHSAHXT`) hardcodeada en el commit inicial `1b8bad6`, removida del árbol de trabajo en `b374e23` pero presente para siempre en el historial mientras no se reescriba | `app-ejemplo/config_malo.py:3`, commit `1b8bad6` | **Crítica** | `reports/gitleaks-report.json`, regla `aws-access-token` |
| 2 | Bandit | Código inseguro (B602) | `subprocess.run(..., shell=True)` con el nombre del bucket interpolado directo en el comando — riesgo de inyección de comandos (CWE-78) si `bucket`/`destino` llegan a alimentarse de entrada no confiable | `app-ejemplo/s3_bucket_manager.py:43` | **Alta** | `reports/bandit-report.json`, regla `B602` |
| 3 | Bandit | Código inseguro (B108) | Ruta de archivo temporal predecible (`/tmp/backup`) hardcodeada como valor por defecto | `app-ejemplo/s3_bucket_manager.py:39` | Media | `reports/bandit-report.json`, regla `B108` |
| 4 | Bandit | Informativo (B404) | Import de `subprocess` — no accionable por sí solo, señala dónde revisar B602 | `app-ejemplo/s3_bucket_manager.py:2` | Baja | `reports/bandit-report.json`, regla `B404` |
| 5 | Bandit | Cobertura parcial (B105) | Mismo secreto del hallazgo #1, detectado por heurística genérica de "password hardcodeado" — solo la línea del secret key, no la del access key id, y mal clasificado como severidad baja | `app-ejemplo/config_malo.py:4` (versión ya remediada en HEAD) | Baja (real: crítica, ver 3.1) | corrida local contra el commit `1b8bad6` |
| 6 | pip-audit | Dependencia vulnerable (SCA) | `requests==2.30.0` — múltiples CVEs conocidos, incluye `PYSEC-2023-74` (CVE-2023-32681, fuga del header `Proxy-Authorization` en redirects) | `requirements.txt` | **Alta** | corrida local contra el commit previo a `05e99b6` |
| 7 | pip-audit | Dependencia vulnerable (SCA) | `python-dotenv==1.0.1` — `PYSEC-2026-2270` | `requirements.txt` | Media | corrida local contra el commit previo a `05e99b6` |
| 8 | Revisión manual + `gatekeeper.py` | Configuración de infraestructura (IaC) | Política de bucket con `Principal: "*"` y `Action: "s3:*"` — acceso público total si se usara | `infra/bucket_policy_publico.json` | Alta (si se usara en producción) | `scripts/gatekeeper.py::check_politica_bucket()` la rechaza explícitamente; no es la política canónica (`bucket_policy_privado.json` sí lo es) |

**Hallazgo más crítico: #1 (secreto de AWS en el historial de git).**
Explicación en términos de equipo de desarrollo/seguridad: aunque el
desarrollador "arregló" el problema quitando la credencial del archivo
(commit `b374e23`), **cualquiera que clone el repositorio y corra
`git log -p` o `git show 1b8bad6` sigue viendo la credencial completa** —
el fix visual en el código no revierte la exposición ya ocurrida. Si la
credencial hubiera sido real, la única remediación completa habría sido
**rotarla en AWS de inmediato**, independientemente de si se "arregla" el
código; el código arreglado solo previene que se exponga *de nuevo*, no
deshace la exposición ya sucedida. Es exactamente el tipo de riesgo que un
escáner de secretos en CI (Sección 9) existe para atrapar antes de que la
credencial real llegue a un repositorio público.

---

## 7. Clasificación y priorización

| Prioridad | Hallazgo | Categoría | Justificación de por qué va primero |
|---|---|---|---|
| 1 | #1 — Secreto AWS en historial | Secreto expuesto | Impacto potencial máximo (acceso a cuenta cloud completa) si la credencial fuera real; irreversible sin rotación |
| 2 | #6/#7 — Dependencias vulnerables | Dependencia vulnerable | CVEs con explotación documentada públicamente, afectan cualquier despliegue que use la versión pineada |
| 3 | #2 — `subprocess shell=True` (B602) | Código inseguro | Alta severidad/confianza de Bandit, pero explotabilidad actual limitada (ver análisis de falso positivo, Sección 8) |
| 4 | #8 — Política de bucket pública | Configuración IaC | Ya mitigado por diseño (no es la política canónica), pero debe quedar claramente fuera de uso |
| 5 | #3 — Ruta temporal predecible (B108) | Código inseguro | Severidad media, impacto bajo en el flujo actual |
| 6 | #4/#5 — Hallazgos informativos/parciales | Informativo | No accionables por sí solos, dan contexto a los demás |

---

## 8. Análisis de falso positivo y plan de remediación

### 8.1 Análisis de falso positivo — hallazgo #2 (`B602`, subprocess shell=True)

**¿Es un falso positivo?** Se evaluó con contexto de código, flujo de datos
y explotabilidad práctica. **Conclusión: no es un falso positivo — es un
hallazgo real, pero de explotabilidad *actualmente* limitada.**

- **Código:** `respaldo_local(bucket=None, destino="/tmp/backup")` en
  `app-ejemplo/s3_bucket_manager.py:36-44` construye
  `f"tar -czf {destino}.tar.gz -C /tmp/{bucket} ."` y lo ejecuta con
  `shell=True`.
- **Flujo de datos actual:** revisando todos los call sites del
  repositorio (`grep -rn respaldo_local`), la función nunca se invoca desde
  ningún punto de entrada expuesto a un usuario externo — solo existiría
  una llamada interna con el `bucket` por defecto de `config_malo.py`. Hoy,
  ni `bucket` ni `destino` se originan de una fuente no confiable.
  **Por eso la explotabilidad práctica hoy es baja.**
  Justo por esto es un caso real de "leer el hallazgo con contexto, no solo
  la regla" — pero la conclusión NO es descartarlo, sino tratarlo como
  deuda de seguridad activa (ver 8.2 #3): el patrón es inseguro por diseño,
  y el día que cualquier código nuevo conecte `bucket` o `destino` a un
  parámetro de API, un archivo de configuración editable por el usuario, o
  cualquier entrada externa, se vuelve una inyección de comandos real
  (CWE-78) sin que nadie tenga que volver a auditar esa línea para
  notarlo.

### 8.2 Plan de remediación — las 3 vulnerabilidades principales

| # | Vulnerabilidad | Prioridad | Riesgo | Acción inmediata (contención) | Acción preventiva (mejora) | Responsable sugerido | Resultado esperado |
|---|---|---|---|---|---|---|---|
| 1 | Secreto AWS en historial (Gitleaks) | Crítica | Exposición total de una cuenta cloud si fuera real | **Ejecutada:** remover el literal del código (commit `b374e23`), usar variables de entorno | Rotar la credencial en el proveedor real (N/A aquí, es sintética) + evaluar reescritura de historial (`git filter-repo`/BFG) **solo si el repo aún no se compartió** — deliberadamente NO ejecutada en este repo académico para preservar la evidencia que Gitleaks debe encontrar (ver nota en `README.md`) | Dev que introdujo el cambio + revisor de PR | Gitleaks en CI bloquea cualquier commit *nuevo* con este patrón (confirmado, Sección 9); el hallazgo histórico queda documentado y aceptado conscientemente, no ignorado por accidente |
| 2 | Dependencias vulnerables (`requests`, `python-dotenv`) | Alta | CVEs con explotación pública documentada | **Ejecutada:** bump a `requests==2.34.2` / `python-dotenv==1.2.3` (commit `05e99b6`) | Agregar `pip-audit` como paso obligatorio de CI (ya hecho, Sección 9) + revisar dependencias mensualmente aunque no haya cambios de código | Mantenedor del repo | pip-audit pasa limpio (confirmado, `reports/pip-audit-report.json` tras el fix) |
| 3 | `subprocess shell=True` (`B602`) | Media-Alta | Inyección de comandos si `bucket`/`destino` reciben alguna vez entrada no confiable | Code review obligatorio en cualquier PR que modifique `respaldo_local()` o agregue un caller nuevo; restringir el gate de Bandit en CI a que bloquee explícitamente esta severidad (ya configurado, Sección 9) | Reemplazar `subprocess.run(..., shell=True)` por `subprocess.run(["tar","-czf",f"{destino}.tar.gz","-C",f"/tmp/{bucket}","."], shell=False)` o por el módulo `tarfile` de la librería estándar (elimina el riesgo por completo, sin depender de un binario externo) | Dev asignado al backlog de `app-ejemplo/` | El pipeline de CI deja de bloquear en el paso "Bandit (alta severidad)" una vez aplicado el refactor |

---

## 9. Integración a CI/CD y evidencia del quality gate

Pipeline: [`.github/workflows/security-audit.yml`](.github/workflows/security-audit.yml)
(GitHub Actions), dispara en `push` a `dev`/`production` y en `pull_request`
hacia `production`.

**Diseño del gate:** cada herramienta corre de forma independiente
(`continue-on-error: true` por paso) y un paso final ("Evaluar quality gate
consolidado") revisa el resultado de las 4 verificaciones
(Bandit-alta-severidad, pip-audit, Gitleaks, `gatekeeper.py`) y falla el
job completo si **cualquiera** de ellas falló — esto garantiza que las
otras herramientas siempre terminen de correr y generen su reporte como
evidencia, en vez de que un solo hallazgo detenga el job antes de que las
demás lleguen a ejecutarse.

### Corrida real (evidencia)

**Run:** [`#35055765307`](https://github.com/AngelSantana05/devsecops-demo/actions/runs/35055765307)
— push a `dev`, commit `2093b32`.

```
Bandit (alta severidad): failure
pip-audit:               success
Gitleaks (historial):    success
gatekeeper.py:            success

::error::Quality gate FALLIDO -- ver el detalle de cada paso arriba. Se bloquea el merge/deploy.
Process completed with exit code 1.
```

**Resultado:** el job terminó en **failure**, bloqueando el merge —
exactamente el comportamiento esperado, ya que `B602` (Sección 8) sigue sin
remediar por diseño. Los pasos individuales de Bandit, pip-audit y Gitleaks
en el log de Actions muestran ✓ verde porque `continue-on-error` evita que
un fallo individual detenga el job antes de tiempo, **pero el paso final
"Evaluar quality gate consolidado" muestra ✗ y es el que realmente decide
el resultado del pipeline** — el detalle impreso en ese paso (arriba)
confirma cuál de las 4 verificaciones causó el bloqueo.

**Nota sobre Gitleaks en CI vs. local:** `gitleaks-action` en un evento
`push` escanea únicamente los *commits nuevos incluidos en ese push*, no
todo el historial en cada corrida — por eso este run específico (que solo
tocaba `README.md`) pasó limpio en el paso de Gitleaks, mientras que la
corrida manual `gitleaks detect --source .` (Sección 6, hallazgo #1), que
sí escanea el historial completo, encontró el secreto. Esto es un hallazgo
real de la auditoría, no un error de configuración: **el gate de CI por
push protege contra secretos *nuevos* hacia adelante, pero un repositorio
que adopta Gitleaks después de tener historial previo necesita además una
corrida manual (o un job programado) de historial completo al menos una
vez, para atrapar lo que ya estaba ahí antes de que existiera el gate.**
Queda anotado como mejora futura: agregar un job semanal
(`schedule:`) que corra `gitleaks detect` sobre el historial completo.

`pipeline_audit.log` (bitácora del gate local `gatekeeper.py`, corrida
antes de cada merge real) documenta 3 intentos reales sobre este mismo
repositorio: 1 bloqueado (secreto presente) y 2 permitidos (después de cada
fix) — ver el archivo completo en la raíz del repo.

---

## 10. Cómo generar/adaptar esto para otros usuarios (complejidad de uso)

*(Ver también la sección correspondiente en `README.md` — aquí se agrega
el detalle técnico encontrado durante la ejecución real, no solo lo
planeado.)*

**Cambios de entorno que aparecieron ejecutando esto, no anticipados en el
plan original:**

- `bandit==1.7.9` y `pip-audit==2.7.3` (versiones propuestas originalmente)
  **fallan silenciosamente con Python 3.14** (excepción interna en cada
  archivo, sin ningún hallazgo reportado — un falso "todo limpio" muy
  peligroso para quien no se dé cuenta). Se repineó a `bandit==1.9.4` /
  `pip-audit==2.9.0`, verificadas contra 3.12/3.13/3.14. **Lección para
  adaptar esto a otro proyecto:** siempre validar que la versión pineada de
  la herramienta de auditoría soporte la versión de Python del entorno
  donde corre — un mensaje "0 issues" no siempre significa que sí escaneó.
- Instalar `requirements-audit.txt` en el **mismo** entorno virtual que
  `requirements.txt` del proyecto puede fallar por conflictos de
  dependencias (en este caso, `pip-audit` requiere una versión de
  `requests` más nueva que la que el propio proyecto audita a propósito).
  **Usar un entorno virtual separado solo para las herramientas de
  auditoría** — además es más realista: en CI, Bandit/pip-audit tampoco
  necesitan que el proyecto esté instalado, `pip-audit -r requirements.txt`
  lee el archivo, no instala los paquetes.
- El clave AWS sintética usada para la demo (Sección "Nota sobre las
  credenciales de ejemplo" en `README.md`) tuvo que generarse
  aleatoriamente — la credencial de ejemplo oficial de AWS
  (`AKIAIOSFODNN7EXAMPLE`, la que aparece en toda la documentación pública
  de AWS) está en la lista de excepciones (*allowlist*) por defecto de
  Gitleaks precisamente por ser tan usada en ejemplos, así que **no
  sirve para demostrar la detección**. Quien adapte este demo con su propio
  secreto de prueba debe evitar credenciales de ejemplo publicadas
  oficialmente por la misma razón.

**Complejidad de adopción para un proyecto Python real** (resumen, detalle
completo en `README.md`): **baja** si el proyecto ya usa
`pip`/`requirements.txt` estándar — copiar
`.github/workflows/security-audit.yml` + `requirements-audit.txt` y
ajustar las rutas de `bandit -r <dirs>`. **Media** si usa Poetry/Pipenv
(requiere exportar a `requirements.txt` antes de `pip-audit`, o correr
`pip-audit` sin `-r` contra el entorno ya instalado). El componente que
**no es genérico y sí requeriría reescribirse** es `scripts/gatekeeper.py`
en la parte de `check_politica_bucket()` — está acoplado al formato de
política de bucket S3 de este demo específico; el resto (`scan_secrets.py`,
la estructura del pipeline, el patrón de quality gate consolidado) es
reutilizable tal cual.

---

## 11. Conclusión final

La ejecución real confirmó los tres riesgos anticipados en la Sección 2 y
agregó un hallazgo no anticipado: **la complementariedad entre Bandit y
Gitleaks no es solo teórica** (Sección 3.1) — se observó en vivo cómo la
misma credencial fue detectada por ambas herramientas con clasificaciones
de severidad distintas, confirmando que ninguna herramienta por sí sola
cubre el riesgo completo.

El pipeline de CI (Sección 9) demuestra el principio central de
shift-left/DevSecOps de forma verificable, no solo declarada: existe una
corrida real de GitHub Actions donde el quality gate bloqueó
automáticamente un merge por una vulnerabilidad de código real (`B602`)
que sigue abierta a propósito, con un plan de remediación explícito
(Sección 8) que distingue qué ya se corrigió (secreto, dependencias) de qué
queda pendiente y por qué (contención vs. mejora preventiva). Formalizar
Bandit, pip-audit y Gitleaks como controles automáticos previos al merge —
sobre la misma lógica que ya bloqueaba el flujo `dev` → `production` con
`gatekeeper.py` — convirtió un principio en una práctica repetible y
demostrable para `devsecops-demo`.

### Referencias

1. OWASP Foundation. (s.f.). *DevSecOps Guideline*. https://owasp.org/www-project-devsecops-guideline/
2. Red Hat. (s.f.). *What is shift-left security?* https://www.redhat.com/en/topics/devops/shift-left-security
3. OWASP Foundation. (s.f.). *Source Code Analysis Tools (SAST)*. https://owasp.org/www-community/Source_Code_Analysis_Tools
4. OWASP Foundation. (s.f.). *Software Component Analysis (SCA)*. https://owasp.org/www-community/Component_Analysis
5. GitHub Docs. (s.f.). *About secret scanning*. https://docs.github.com/code-security/secret-scanning
6. PyCQA. (s.f.). *Bandit — a security linter for Python code*. https://bandit.readthedocs.io/
7. Python Packaging Authority. (s.f.). *pip-audit*. https://pypi.org/project/pip-audit/
8. Gitleaks. (s.f.). *Gitleaks*. https://github.com/gitleaks/gitleaks
9. MITRE. (s.f.). *CWE-78: OS Command Injection*. https://cwe.mitre.org/data/definitions/78.html
10. Python Software Foundation. (s.f.). *PyPI Advisory Database / PYSEC*. https://github.com/pypa/advisory-database
