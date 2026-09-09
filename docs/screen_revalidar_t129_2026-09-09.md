# T129 — SCREEN-REVALIDAR: el screen E1b sobre el universo que filtra hoy

**Fecha:** 2026-09-09 · **Tarea:** 129 (ref `docs/auditoria_desvios_2026-09-08.md` §3 [D-3])
**Instrumento:** `scripts/run_universe_screen_validation.py --account-id 2` (arreglado por la tarea 128)
**Datos:** EDGAR XBRL vivo + watchlist real de la cuenta 2 · **Read-only**, no se modificó ninguna perilla.

---

## 0. Veredicto

**El kill-criteria PASA: el screen no excluye ningún nombre de los 128 del universo vivo.**
`other_exclusions: []`, `kill_pass: True`, exit 0.

No hay ninguna decisión forzada para Chapa. Lo que sigue son las dos preguntas que la
tarea pedía separar, y **tres cosas que la medición contradice del enunciado**.

## 1. La corrida

| | |
|---|---|
| Cuenta resuelta | **2** (contra `is_active`, sin flag hacía falta pasar `--account-id`) |
| Nombres evaluados | **128** |
| Excluidos | **0** |
| `fragile_not_in_universe` | `["MLTX"]` |
| `true_positive_exercised` | **False** |

**Los umbrales de la corrida coinciden exactamente con los vivos** —se verificó clave por
clave contra `settings`, no se asumió—: `min_adv_dollars=0.0`, `fundamentals_enabled=True`,
`min_negative_years=2`, `revenue_floor=$10M`. O sea que esto mide la política que corre,
no los defaults del script.

**Lo que esta corrida NO ejercita, y va dicho:** MLTX no está en el universo vivo, así que
el lado *verdadero-positivo* del kill-criteria (agarrar a los tipo MLTX) **no se probó acá**.
Se probó en julio, sobre otra población. Lo que se midió hoy es el lado *falso-positivo*:
que no recorte nombres buenos. Es el que estaba sin medir y el que la tarea perseguía.

## 2. Las dos preguntas de la tarea, separadas

> *«de los 79, (a) cuáles no resuelven revenue con los cinco conceptos actuales, y
> (b) cuáles tienen dos net income anuales negativos seguidos. El riesgo vive en la
> intersección.»*

| pregunta | resultado sobre los 128 |
|---|---|
| **(a)** revenue no resuelve | **5**: ASML, AVB, GS, TSM, XOM — de esos, **3 nunca validados** (AVB, GS, XOM) |
| **(b)** 2 años seguidos de NI negativo | **1**: INTC (rev $52.9B ≫ piso ⇒ conservado, igual que en julio) |
| **(a ∩ b) — el riesgo** | **vacío** |

**La intersección está vacía, así que hoy no hay ningún nombre en riesgo.**

## 3. Tres cosas que la medición contradice del enunciado

### 3.1 La hipótesis sectorial es FALSA para la enorme mayoría

El enunciado decía que los 79 son bancos, utilities, REITs y energía, y que *«ninguno de los
cinco conceptos es el tag primario de un banco, una utility regulada ni una aseguradora»*, con
la implicación de que por eso no resolverían. **Medido: 76 de los 79 resuelven revenue sin
problema.** Los nombres que el propio enunciado citaba como el mecanismo:

| ticker | resuelve con | revenue |
|---|---|---|
| C (banco) | `Revenues` | $85.2B |
| BAC (banco) | `Revenues` | $113.1B |
| DUK (utility) | `Revenues` + otros **tres** | $19.6B |
| WELL / O / PSA (REITs) | `Revenues` | $10.8B / $5.7B / $4.8B |

La preocupación era razonable a priori y **el barrido de conceptos la desmiente**: `Revenues`
es un tag genérico que estos emisores sí usan.

### 3.2 Queda UN caso real del mecanismo predicho, y es GS

**Goldman Sachs es el único nombre del universo donde pasa exactamente lo que el enunciado
describía.** Sus facts us-gaap **no tienen** ninguno de los cinco conceptos; tienen
`RevenuesNetOfInterestExpense`, que es el tag que el enunciado nombró.

Hoy **está conservado**, y no por casualidad: su `NetIncomeLoss` sí resuelve y es fuertemente
positivo (**+$17.2B, +$14.3B, +$8.5B**), así que la pata de fragilidad nunca llega a mirar el
revenue. La regla exige *evidencia positiva* de pérdidas sostenidas antes de leer la ausencia
de revenue como pre-revenue.

**Pero la exposición es real y latente:** el día que GS reporte **dos años seguidos** de
pérdida GAAP, `revenue_latest = None` se leerá como *debajo del piso* y el screen lo va a
sacar de los candidatos a BUY **sin decir nada**. Para un banco, dos años de pérdida no es
exótico. Queda como tarea **150**.

### 3.3 Cuatro nombres son INVISIBLES para la pata fundamental, por tres causas distintas

Éste no estaba en el enunciado y es el hallazgo más grande de la corrida. Cuatro de los 128
llegan al screen **sin ningún fact de EDGAR** (`net_income_recent: []` y `revenue_latest: None`):

| ticker | causa | detalle |
|---|---|---|
| **AVB** | **no hay CIK** | `cik_for_ticker("AVB")` devuelve `None`. Es el **único** del universo al que le pasa: los otros ocho REITs resuelven. Y **no es que AVB no esté en EDGAR**: `CIK0000915912` responde 200 con *AVALONBAY COMMUNITIES, INC.* El defecto está en el mapa, no en la fuente. |
| **XOM** | **CIK nuevo, sin historia** | El mapa resuelve XOM → **CIK 2115436**, cuyo `entityName` **sí es** *Exxon Mobil Corporation* — o sea que no es un mapeo equivocado. Pero ese CIK tiene **94 conceptos us-gaap** y, tanto en `Revenues` como en `NetIncomeLoss`, **4 entradas totales, todas de un 10-Q y ninguna anual**. La historia larga de Exxon vive en el CIK legacy. |
| **ASML, TSM** | foreign filers | Ya documentado en julio (`docs/universe_screen_e1b_2026-07-02.md`): presentan 20-F, no 10-K. Conservados por fail-open, **aceptado**. |

**El fail-open es correcto** —un nombre sin datos no puede excluirse— y por eso ninguno de los
cuatro corre riesgo. **Lo que no está bien es el silencio:** nada en el proyecto mide cuántos
nombres del universo vivo llegan al screen sin datos, así que la pata fundamental puede quedar
inerte para una porción creciente del universo sin que nadie se entere. Y el mecanismo de XOM
**generaliza**: cualquier emisor que se re-registre pierde su historia anual de un día para el
otro y se vuelve invisible. Queda como tarea **149**.

## 4. Lo que esta corrida NO afirma

- **No afirma que el screen sea inocuo para siempre.** Afirma que hoy, sobre los 128 y con los
  umbrales vivos, no excluye a nadie. Los dos caminos por los que eso puede cambiar están
  identificados y anotados (149 y 150).
- **No re-valida el lado verdadero-positivo.** MLTX no está en el universo; ver §1.
- **No mide el piso de ADV$**, porque está en 0 en vivo (la pata de liquidez está apagada, igual
  que en julio).

## 5. Trazas

- JSON completo de la corrida: `--account-id 2 --json`, 128 filas con ADV$, revenue, NI y veredicto.
- La corrida es reproducible con EDGAR vivo; `_FACTS_CACHE` es por proceso, así que no hay
  artefacto congelado que envejezca (y por eso tampoco hay ancla de reproducción que re-anclar).
