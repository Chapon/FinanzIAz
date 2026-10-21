"""
Tarjeta de valuación de la pestaña Analysis — tarea 383, display-only.

Muestra lo que calcula ``analysis.valuation.valuar`` con los fundamentals de EDGAR: el número de
Graham y su margen de seguridad, el retorno anual esperado a 10 años y el precio máximo para un
15% anual (*Buffettology*), y el PEG y la categoría de Lynch. Se oculta si no hay valuación (sin
fundamentals, EPS no positivo en todo, o empresa extranjera), como ``RecommendationsCard``.

No entra en ninguna decisión: es para leer.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui.styles import PALETTE


def _pesos(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1%}"


def lineas_de(v) -> list[str]:
    """El texto de la tarjeta, una línea por mirada. Pura, para testearla sin Qt."""
    out = []
    if v.numero_graham is not None:
        estado = "debajo" if v.margen_graham and v.margen_graham > 0 else "encima"
        out.append(
            f"Graham: valor {_pesos(v.numero_graham)} (EPS {_pesos(v.eps)} y valor libro "
            f"{_pesos(v.valor_libro_x_accion)} por acción). El precio está {estado}: "
            f"margen de seguridad {_pct(v.margen_graham)}. Castiga a las empresas con poco valor libro "
            f"(marcas, software): es la regla del inversor defensivo, no un veredicto."
        )
    else:
        out.append("Graham: sin valor (hace falta EPS y valor libro positivos).")
    if v.retorno_anual is not None:
        out.append(
            f"Buffettology: con el EPS creciendo {_pct(v.crecimiento)} anual "
            f"({v.anios_crecimiento} años{', topeado en 15%' if v.crecimiento and v.crecimiento > 0.15 else ''}) "
            f"y su PE mediano de {v.pe_historico:.1f} ({v.anios_pe} años), en 10 años valdría "
            f"{_pesos(v.precio_en_10)}: {_pct(v.retorno_anual)} anual comprando hoy, sin dividendos. "
            f"Para esperar 15% anual, el precio máximo es {_pesos(v.precio_max_objetivo)}."
        )
    else:
        out.append("Buffettology: sin proyección (hace falta crecimiento del EPS y 3 años de PE).")
    peg = f"PEG {v.peg:.2f}" if v.peg is not None else "PEG —"
    cat = f"{v.categoria} ({v.motivo_categoria})" if v.categoria else f"sin categoría ({v.motivo_categoria})"
    out.append(f"Lynch: {peg} (menos de 1 es barato para su crecimiento) · {cat}.")
    if v.calidad:
        nombres = {
            "roe": "ROE estable",
            "rentab_bruta": "ganancia bruta / activos",
            "deuda": "deuda baja",
            "regularidad": "ganancia que crece parejo",
        }
        patas = ", ".join(f"{nombres[p]} p{pct:.0f}" for p, pct in v.calidad["percentiles"].items())
        out.append(
            f"Calidad del negocio: {v.calidad['puntaje']:.0f}/100 entre {v.calidad['n']} empresas ({patas}). "
            f"Describe el negocio; medido contra el retorno que vino después (tarea 384), no lo anticipó."
        )
    return out


class ValuationCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        titulo = QLabel("Valuación (fundamentals de EDGAR)")
        titulo.setStyleSheet(f"font-weight: 600; color: {PALETTE['text1']};")
        lay.addWidget(titulo)
        self.cuerpo = QLabel("")
        self.cuerpo.setWordWrap(True)
        lay.addWidget(self.cuerpo)
        self.pie = QLabel("")
        self.pie.setWordWrap(True)
        self.pie.setStyleSheet(f"color: {PALETTE['text3']}; font-size: 11px;")
        lay.addWidget(self.pie)
        self.setVisible(False)

    def set_data(self, v) -> None:
        if v is None:
            self.setVisible(False)
            return
        self.cuerpo.setText("\n\n".join(lineas_de(v)))
        avisos = f" Avisos: {'; '.join(v.avisos)}." if v.avisos else ""
        self.pie.setText(
            f"Último año fiscal: {v.fin_ultimo_anio}. Sólo para leer: no entra en ninguna decisión de la app.{avisos}"
        )
        self.setVisible(True)
