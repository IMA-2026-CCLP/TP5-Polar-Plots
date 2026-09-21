"""
ui/scale_dialog.py — Editor de escalas: elegir una de la biblioteca (integradas por categoría + propias),
agregar/quitar notas y guardarla en la base propia (core/scales.py). "Usar esta escala" la deja activa.
"""
import json

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PyQt6.QtGui import QFont, QStandardItem

from core import scales


def fill_scale_combo(combo: QComboBox, select: str | None = None):
    """Llena un combo con la biblioteca agrupada por categoría (encabezados no seleccionables).
    itemData = nombre de la escala. Devuelve el nombre seleccionado."""
    combo.blockSignals(True)
    combo.clear()
    model = combo.model()
    sel_idx = -1
    for cat, d in scales.library().items():
        head = QStandardItem(cat)
        head.setEnabled(False)
        f = QFont(); f.setBold(True); head.setFont(f)
        model.appendRow(head)
        for name in d:
            combo.addItem("    " + name, name)
            if name == select:
                sel_idx = combo.count() - 1
    if sel_idx < 0:
        sel_idx = combo.findData(scales.DEFAULT_SCALE)          # si no existe, la escala por defecto
    if sel_idx < 0:
        for i in range(combo.count()):
            if combo.itemData(i):
                sel_idx = i
                break
    combo.setCurrentIndex(sel_idx)
    combo.blockSignals(False)
    return combo.currentData()


class ScaleEditorDialog(QDialog):
    """
    get_scale()      → escala activa (la de la tabla) al aceptar con "Usar esta escala"
    selected_name    → nombre de la escala elegida/guardada (None si se editó sin guardar)
    db_changed       → True si se guardó/eliminó/importó algo en la base propia
    """

    def __init__(self, scale: dict, current_name: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Escalas")
        self.setMinimumWidth(460)
        self.selected_name = current_name
        self.db_changed = False

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self._combo = QComboBox()
        self._combo.setToolTip("Escalas integradas (por categoría) y las de tu base propia")
        self._combo.currentIndexChanged.connect(self._on_pick)
        form = QFormLayout()
        form.addRow("Escala:", self._combo)
        self._name = QLineEdit()
        self._name.setToolTip("Nombre con el que se guarda en tu base (tiene que ser único)")
        form.addRow("Nombre:", self._name)
        self._cat = QComboBox()
        self._cat.setEditable(True)
        self._cat.setToolTip("Categoría de tu base; escribí una nueva para crearla")
        form.addRow("Categoría:", self._cat)
        lay.addLayout(form)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Nota", "Freq (Hz)"])
        for c in (0, 1):
            self._table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(220)
        lay.addWidget(self._table)

        row = QHBoxLayout()
        b_add = QPushButton("+ Nota")
        b_add.clicked.connect(lambda: self._add_row())
        b_del = QPushButton("− Nota")
        b_del.clicked.connect(self._del_row)
        self._b_save = QPushButton("Guardar en mi base")
        self._b_save.setToolTip("Guarda esta escala (con este nombre y categoría) en tu base propia")
        self._b_save.clicked.connect(self._save)
        self._b_delete = QPushButton("Eliminar de mi base")
        self._b_delete.clicked.connect(self._delete)
        for b in (b_add, b_del, self._b_save, self._b_delete):
            b.setAutoDefault(False)
            row.addWidget(b)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        b_imp = QPushButton("Importar…")
        b_imp.clicked.connect(self._import)
        b_exp = QPushButton("Exportar mi base…")
        b_exp.clicked.connect(self._export)
        for b in (b_imp, b_exp):
            b.setAutoDefault(False)
            row2.addWidget(b)
        row2.addStretch(1)
        lay.addLayout(row2)

        self._hint = QLabel("")
        self._hint.setObjectName("rb_status")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Usar esta escala")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        fill_scale_combo(self._combo, current_name)
        self._refill_categories()
        if scale:                                    # la escala activa manda (puede tener ediciones sin guardar)
            self._load_table(scale)
            self._name.setText(current_name or "")
        else:
            self._on_pick()
        self._update_state()

    # ── tabla ─────────────────────────────────────────────────────────────
    def _load_table(self, scale: dict):
        self._table.setRowCount(0)
        for n, hz in scale.items():
            self._add_row(n, hz)

    def _add_row(self, nota: str = "", hz: float = 440.0):
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(str(nota)))
        self._table.setItem(r, 1, QTableWidgetItem(f"{hz:g}"))

    def _del_row(self):
        r = self._table.currentRow()
        if r >= 0:
            self._table.removeRow(r)

    def get_scale(self) -> dict:
        out = {}
        for i in range(self._table.rowCount()):
            n, f = self._table.item(i, 0), self._table.item(i, 1)
            if n and f and n.text().strip():
                try:
                    hz = float(f.text().replace(',', '.'))
                except ValueError:
                    continue
                if hz > 0:
                    out[n.text().strip()] = hz
        return out

    # ── biblioteca ────────────────────────────────────────────────────────
    def _refill_categories(self):
        cats = list(scales.load_user().keys())
        if scales.USER_CATEGORY not in cats:
            cats.insert(0, scales.USER_CATEGORY)
        self._cat.clear()
        self._cat.addItems(cats)

    def _on_pick(self, _=None):
        name = self._combo.currentData()
        if not name:
            return
        cat, sc = scales.find(name)
        self.selected_name = name
        self._load_table(sc)
        self._name.setText(name)
        if not scales.is_builtin(name):
            self._cat.setCurrentText(cat)
        else:
            self._name.setText(f"{name} (mía)")     # sugerencia: las integradas no se pisan, se guarda una copia
            self._cat.setCurrentText(scales.USER_CATEGORY)
        self._update_state()

    def _update_state(self):
        name = self._combo.currentData()
        user_scale = bool(name) and not scales.is_builtin(name)
        self._b_delete.setEnabled(user_scale)
        self._hint.setText(
            "Escala integrada: podés editar las notas y guardarla como copia propia (con otro nombre)."
            if name and scales.is_builtin(name) else
            "Escala propia: al guardar con el mismo nombre se actualiza.")

    def _save(self):
        name = self._name.text().strip()
        sc = self.get_scale()
        cat = self._cat.currentText().strip() or scales.USER_CATEGORY
        if not name or not sc:
            QMessageBox.warning(self, "Escalas", "Poné un nombre y al menos una nota con su frecuencia.")
            return
        if scales.is_builtin(name):
            QMessageBox.warning(self, "Escalas", f"'{name}' es una escala integrada. Elegí otro nombre para tu copia.")
            return
        user = scales.load_user()
        for c in list(user):                       # el nombre es único: si cambió de categoría, se mueve
            user[c].pop(name, None)
            if not user[c]:
                del user[c]
        user.setdefault(cat, {})[name] = sc
        scales.save_user(user)
        self.db_changed = True
        self.selected_name = name
        fill_scale_combo(self._combo, name)
        self._refill_categories()
        self._cat.setCurrentText(cat)
        self._update_state()
        self._hint.setText(f"Guardada '{name}' en «{cat}».")

    def _delete(self):
        name = self._combo.currentData()
        if not name or scales.is_builtin(name):
            return
        if QMessageBox.question(self, "Escalas", f"¿Eliminar '{name}' de tu base?") != QMessageBox.StandardButton.Yes:
            return
        user = scales.load_user()
        for c in list(user):
            user[c].pop(name, None)
            if not user[c]:
                del user[c]
        scales.save_user(user)
        self.db_changed = True
        self.selected_name = None
        fill_scale_combo(self._combo, scales.DEFAULT_SCALE)
        self._refill_categories()
        self._on_pick()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar escalas", "", "Escalas (*.json)")
        if not path:
            return
        try:
            data = json.loads(open(path, encoding='utf-8').read())
            n = scales.merge_into_user(data.get("categories", data))
        except Exception as e:
            QMessageBox.warning(self, "Escalas", f"No se pudo importar: {e}")
            return
        self.db_changed = True
        fill_scale_combo(self._combo, self._combo.currentData())
        self._refill_categories()
        self._hint.setText(f"Importadas {n} escala(s).")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar mi base de escalas", "mis_escalas.json", "Escalas (*.json)")
        if path:
            scales.save_user(scales.load_user(), __import__('pathlib').Path(path))
            self._hint.setText(f"Exportada a {path}")
