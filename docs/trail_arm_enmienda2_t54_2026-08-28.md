# Enmienda 2 al pre-registro de TRAIL-ARM (Tarea 54) — el oráculo elegía sobre un pool que el brazo **no puede tocar**

**Fecha:** 2026-08-28 · **Pre-registro:** `docs/trail_arm_prereg_t54_2026-08-28.md` (`9040c0f`) ·
**Enmienda 1:** `docs/trail_arm_enmienda_t54_2026-08-28.md`
**Escrita después del SMOKE de cañería y ANTES de la corrida completa.** El §9.3 del pre-registro
dice que del smoke **no se leen umbrales**; de acá no se leyó ninguno. Lo que el smoke mostró es que
**un brazo de sanity no hacía nada**, que es exactamente para lo que existe.

---

## 1. El defecto, con la huella del smoke

El sanity §5.4 (con la enmienda 1) construye los dos oráculos con `oracle_cap_keys`, heredado de la
51: elige, entre **todos los candidatos del día**, los que peor (o mejor) terminan, en la misma
cantidad que la población diferencial. En el smoke eso dio:

| brazo | CAGR | tomadas | tenencia |
|---|--:|--:|--:|
| `base_k1.00` | 10.26% | 2542 | 7.7d |
| `ORACULO_arm` | 10.46% | 2542 | 7.7d |
| `ANTI_ORACULO_arm` | **10.26%** | **2542** | **7.7d** |

**El anti-oráculo es el baseline, dígito por dígito.** No es ruido: es que **no cambió nada**.

La razón es estructural y estaba a la vista en el §0.2 del pre-registro. El brazo sólo puede
modificar a los trades cuyo excedente cae en el intervalo `(k*, 1.0]` (o `(1.0, k*]`): los de
excedente alto arman el trailing con cualquiera de los dos umbrales y son **inmunes**. Y el
excedente está **fuertemente correlacionado con el retorno** —es su techo—, así que "los que mejor
terminan" son casi exactamente "los inmunes". El anti-oráculo elegía, con información perfecta, un
conjunto de posiciones sobre las que el mecanismo **no tiene efecto posible**.

Un oráculo que no puede moverse no acota nada, y su comparación con el candidato no significa nada.

---

## 2. Qué cambia

Los dos brazos de sanity se construyen **dentro de la población que el brazo puede tocar**:

- Sea `D` la **población diferencial** del `k*` — los trades del baseline con excedente en el
  intervalo que el umbral mueve (§5.3).
- **`ORACULO_arm`** aplica `k*` a la **mitad peor** de `D`, ordenada por el retorno realizado en el
  baseline.
- **`ANTI_ORACULO_arm`** aplica `k*` a la **mitad mejor** de `D`.
- **Igualados en tasa por construcción**: los dos tocan `⌊|D|/2⌋` posiciones.

El umbral del §5.4 no cambia: **`CAGR(ORACULO_arm) − CAGR(ANTI_ORACULO_arm) ≥ +1.00 pp`**, y el
candidato tiene que quedar **dentro** del intervalo que los dos definen.

**Y el criterio conserva su filo, con una lectura declarada de antemano:** si aun eligiendo con
información perfecta *dentro de la población afectable* los dos oráculos no se separan **1,00 pp**,
la corrida es **INVÁLIDA** y no hay veredicto — pero el hallazgo que hay que publicar en ese caso es
que **el umbral de armado no es un knob explotable ni con presciencia perfecta**, que es la misma
forma del titular de la 37 (*"casi todo el valor del stop duro está en las veces que se equivoca"*) y
del corolario de la 51. Eso se dice **acá**, antes de correr, para que no parezca una racionalización
después.

### Efecto colateral, declarado

La construcción nueva usa el **retorno realizado del baseline**, que ya está en `PortfolioResult`, y
por lo tanto **elimina la llamada a `precompute_realized`** (que evaluaba las ~143.000 entradas
candidatas). La corrida completa pasa a ser sensiblemente más barata. No cambia ningún criterio.

---

## 3. Lo que esta enmienda no toca

- La grilla, su población medida, el baseline y la config (§2 y §3) — **congelados**.
- Los criterios C1, C3, C4, C6, C7, C8 y C9 del §6, con sus umbrales.
- Los sanity §5.1 (contabilidad), §5.2 (reproducción), §5.3 (población diferencial ≥5%) y §5.5 (el
  umbral muerde).
- La regla de selección de `k*` por walk-forward sobre la grilla con población.
- El §7: no se cabla nada en esta tarea.
