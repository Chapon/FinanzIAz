# Validez de los veredictos publicados — sobre qué muestra se validó cada uno

**Tarea 189.** Esta tabla existe porque la respuesta a *«¿sobre qué muestra se validó por
última vez este veredicto?»* **no era buscable**. El 2026-09-10 se re-corrieron nueve runners
sobre el cohorte refrescado y la evidencia quedó repartida así: dos en un doc propio, **cinco
en una sola línea** de la entrada 164 del backlog, y **uno en una fila de tabla** de un doc que
se llama por otra tarea.

**El costo está demostrado, y el caso fue una auditoría de este repo.** La corrida de `muestra`
del 2026-09-11 midió la cobertura con `ls docs/*2026-09-09* docs/*2026-09-10*` —o sea **por
nombre de archivo**— y publicó tres veredictos como *«nadie los re-chequeó»* cuando **dos de
los tres sí lo habían sido**. Lo destapó el `verificador`, no la auditoría.

---

## Cómo leer esta tabla

**La fecha manda.** Cuando dos fuentes dicen cosas distintas sobre el mismo runner, la
**posterior** es la buena, y acá se anota la discrepancia en vez de esconderla. Pasó con el
T37 y el T47: la entrada 164 del backlog los da por **INVÁLIDOS** —que era el estado durante
su diagnóstico, por el sanity no anclado— y las corridas **completas** posteriores (167 y el
§4 de la 164) los dan por **VÁLIDOS**. La última palabra es de las corridas completas.

**«Validez» y «veredicto» son ejes distintos.** Una corrida puede ser VÁLIDA y dar NO-SHIP
(el instrumento funcionó y la respuesta es que no), o INVÁLIDA (el instrumento no se validó,
así que **no hay respuesta**). Un NO-SHIP no es lo mismo que un «sin veredicto».

---

## La tabla

| runner | tarea | veredicto publicado | última validación | sobre qué muestra | evidencia |
|---|---|---|---|---|---|
| `run_stop_value_t37.py` | T37 | **NO-SHIP** (era SHIP por los nueve) | **2026-09-10 · VÁLIDA** | refresh 2026-09-09 | `docs/stop_value_rerun_t167_2026-09-10.md` |
| `run_stop_price_redecide_t47.py` | T47 | NO-SHIP por C3 y C7 | **2026-09-10 · VÁLIDA** (reproduce exacto) | refresh 2026-09-09 | `docs/control_resorteado_t164_2026-09-10.md` §4 |
| `run_stop_loosen_t34.py` | T34 | NO-SHIP por C6 | **2026-09-10 · VÁLIDA** | refresh 2026-09-09 | `docs/control_resorteado_t164_2026-09-10.md` §4 |
| `run_stop_price_replay_t26b.py` | T26b | NO-SHIP por C5 | **2026-09-10 · INVÁLIDA** (sanity falla) | refresh 2026-09-09 | `docs/t26b_sanity_t168_2026-09-10.md` |
| `run_rank_neutral_t39.py` | T39 | NO-SHIP por C2, C4 y C6 | **2026-09-10 · VÁLIDA** | refresh 2026-09-09 | `docs/BACKLOG.md`, entrada **164** |
| `run_anom_profile_t45.py` | T45 | NO-SHIP por C4 y C8 | **2026-09-10 · VÁLIDA** | refresh 2026-09-09 | `docs/BACKLOG.md`, entrada **164** |
| `run_prio_event_t49.py` | T49 | NO-SHIP por C1, C2, C4, C5 y C7 | **2026-09-10 · VÁLIDA** | refresh 2026-09-09 | `docs/BACKLOG.md`, entrada **164** |
| `run_exit_policy_t170.py` | T170 | **NO MOVER** · rejilla CERRADA | **2026-09-10 · VÁLIDA** (corrida nueva) | refresh 2026-09-09 | `docs/exit_policy_t170_2026-09-10.md` |
| `run_event_timestop_t51.py` | T51 | **sin veredicto** | 2026-08-28 · **INVÁLIDA** (ya publicada así) | pre-refresh | `docs/event_timestop_t51_2026-08-28.md` |
| `run_trail_arm_t54.py` | T54 | **sin veredicto** | 2026-08-28 · **INVÁLIDA** (ya publicada así) | pre-refresh | `docs/trail_arm_t54_2026-08-28.md` |
| `run_anom_regime_t38.py` | T38 | **sin veredicto** | 2026-08-19 · **INVÁLIDA** (sanity §5.4) | pre-refresh | `docs/anom_regime_t38_2026-08-19.md` |
| `run_stop_cal_replay_t26.py` | T26 | NO-SHIP | 2026-08-13 · **INVÁLIDA** (sanity) | pre-refresh | `docs/stop_cal_t26_2026-08-13.md` |
| `run_ranking_t21.py` | T21 | NO-SHIP · opción (a) | **NO RE-CORRIDO desde el refresh** | pre-refresh (2026-08-12) | tarea **183** |

**El único que queda sin re-validar es el T21**, y la tarea **183** lo declara con su severidad
(BAJA: margen de 94× sobre el umbral, el mecanismo que rompió al T37/T47 no le aplica, y nada
está cableado sobre él).

---

## Qué NO dice esta tabla

- **No dice que un veredicto «pre-refresh» sea falso.** Desde la **T48** este repo declara que
  *«ningún veredicto publicado vuelve a reproducir»* tras un refresh: cada uno se midió sobre
  su propia muestra y ahí queda. La tabla dice **sobre cuál**, no si sigue valiendo.
- **No reemplaza al doc de cada tarea.** Es un índice: la evidencia está en la última columna.

## El guard

`tests/test_validez_veredictos_t189.py` mantiene la tabla **completa** contra una población que
se **descubre**, no se enumera: todo runner que ancle su sanity de reproducción
(`measured_on=WINDOW_*`) **o** que tenga un umbral de sanity de clase `magnitud` en el
inventario de la tarea 164. Son los dos mecanismos por los que un refresh puede invalidar un
veredicto, así que un runner nuevo con cualquiera de los dos **no puede nacer sin fila**.
