"""
Conversor simples: arquivo local (PDF, imagem, Office, etc.) -> Markdown via Docling.
Requer Python 3.10+ (Docling >= 2.70).

Modo colunas: agrupa texto por posição horizontal (útil em capturas de IDE com vários painéis).
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from docling_core.types.doc import (
    CodeItem,
    DocItem,
    DocItemLabel,
    DoclingDocument,
    ListItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)
from docling_core.types.doc.document import FormulaItem


FILTERS = (
    "Documentos suportados (*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.webp "
    "*.docx *.pptx *.xlsx *.html *.htm *.txt *.md);;"
    "PDF (*.pdf);;"
    "Imagens (*.png *.jpg *.jpeg *.tiff *.tif *.webp);;"
    "Office (*.docx *.pptx *.xlsx);;"
    "Todos os arquivos (*.*)"
)


def _norm_center_top(
    doc: DoclingDocument, item: DocItem
) -> tuple[float, float, int] | None:
    """Centro horizontal e topo normalizados (0..1) e número da página."""
    if not item.prov:
        return None
    prov = item.prov[0]
    page = doc.pages.get(prov.page_no)
    if not page:
        return None
    b = prov.bbox.normalized(page.size)
    cx = (b.l + b.r) / 2.0
    top = min(b.t, b.b)
    return cx, top, prov.page_no


def _snippet_for_item(doc: DoclingDocument, item: DocItem) -> str | None:
    """Trecho Markdown aproximado para um item isolado."""
    if isinstance(item, TableItem):
        try:
            return item.export_to_markdown(doc).strip()
        except Exception:
            return None
    if isinstance(item, CodeItem) and item.text.strip():
        lang = getattr(item.code_language, "value", str(item.code_language))
        if lang in ("unknown", "UNKNOWN", "Unknown"):
            lang = ""
        fence = f"```{lang}\n{item.text.strip()}\n```" if lang else f"```\n{item.text.strip()}\n```"
        return fence
    if isinstance(item, FormulaItem) and getattr(item, "text", "") and item.text.strip():
        return f"$${item.text.strip()}$$"
    if not isinstance(item, TextItem) or not item.text.strip():
        return None
    if item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
        return None
    t = item.text.strip()
    if isinstance(item, TitleItem):
        return f"# {t}"
    if isinstance(item, SectionHeaderItem):
        return f"## {t}"
    if isinstance(item, ListItem):
        return f"- {t}"
    return t


def _infer_column_count(cx_values: list[float]) -> int:
    if len(cx_values) < 6:
        return 1
    xs = sorted(cx_values)
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    if not gaps:
        return 1
    med = statistics.median(gaps)
    mg = max(gaps)
    if mg < 0.06 and med < 0.025:
        return 1
    threshold = max(0.08, 2.2 * med)
    splits = sum(1 for g in gaps if g >= threshold)
    k = splits + 1
    return max(1, min(6, k))


def _kmeans1d_assign(xs: list[float], k: int) -> tuple[list[int], list[float]]:
    """Atribui cada x a um cluster 0..k-1; retorna labels na mesma ordem de xs e centróides."""
    if k <= 1 or not xs:
        return [0] * len(xs), [0.5]
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-6:
        return [0] * len(xs), [(lo + hi) / 2]
    centroids = [lo + (hi - lo) * (i + 0.5) / k for i in range(k)]
    labels: list[int] = []
    for _ in range(18):
        clusters: list[list[float]] = [[] for _ in range(k)]
        for x in xs:
            j = min(range(k), key=lambda i: abs(x - centroids[i]))
            clusters[j].append(x)
        for i in range(k):
            if clusters[i]:
                centroids[i] = sum(clusters[i]) / len(clusters[i])
        labels = [min(range(k), key=lambda i: abs(x - centroids[i])) for x in xs]
    return labels, centroids


def export_markdown_by_columns(
    doc: DoclingDocument,
    *,
    manual_columns: int = 0,
    page_no: int = 0,
) -> str | None:
    """
    Monta Markdown com seções por coluna (da esquerda para a direita), usando caixas normalizadas.
    Retorna None se não houver dados suficientes para um layout multi-coluna.
    """
    blocks: list[tuple[float, float, str]] = []
    for item, _level in doc.iterate_items(traverse_pictures=True):
        if not isinstance(item, DocItem):
            continue
        geo = _norm_center_top(doc, item)
        if geo is None:
            continue
        cx, top, pno = geo
        if pno != page_no:
            continue
        snip = _snippet_for_item(doc, item)
        if not snip:
            continue
        blocks.append((cx, top, snip))

    if len(blocks) < 4:
        return None

    cx_list = [b[0] for b in blocks]
    k = manual_columns if manual_columns >= 2 else _infer_column_count(cx_list)
    if k < 2:
        return None

    labels, centroids = _kmeans1d_assign(cx_list, k)
    order = sorted(range(k), key=lambda i: centroids[i])

    by_col: list[list[tuple[float, str]]] = [[] for _ in range(k)]
    for lab, (cx, top, snip) in zip(labels, blocks, strict=True):
        by_col[lab].append((top, snip))

    parts: list[str] = []
    names = ("Esquerda", "Centro", "Direita", "Coluna 4", "Coluna 5", "Coluna 6")
    for r, old_idx in enumerate(order):
        title = names[r] if r < len(names) else f"Coluna {r + 1}"
        parts.append(f"### Painel {r + 1} — {title}\n")
        col_blocks = sorted(by_col[old_idx], key=lambda x: x[0])
        texts = [t for _, t in col_blocks]
        parts.append("\n\n".join(texts))

    return "\n\n".join(parts)


def _build_converter(*, columnar_layout: bool):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_EGRET_LARGE
    from docling.datamodel.pipeline_options import LayoutOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    if not columnar_layout:
        return DocumentConverter()

    pipe = PdfPipelineOptions(
        layout_options=LayoutOptions(model_spec=DOCLING_LAYOUT_EGRET_LARGE),
        images_scale=1.5,
    )
    return DocumentConverter(
        format_options={
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipe),
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipe),
        }
    )


class ConvertThread(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)
    status = Signal(str)

    def __init__(
        self,
        file_path: Path,
        *,
        columnar: bool,
        manual_columns: int,
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._columnar = columnar
        self._manual_columns = manual_columns

    def run(self) -> None:
        try:
            from docling.document_converter import DocumentConverter

            self.status.emit("Inicializando Docling (modelos podem baixar na 1ª vez)...")
            converter: DocumentConverter = _build_converter(columnar_layout=self._columnar)
            self.status.emit("Convertendo…")
            result = converter.convert(str(self._file_path))
            doc = result.document
            base = doc.export_to_markdown(traverse_pictures=True)
            if self._columnar:
                col = export_markdown_by_columns(
                    doc,
                    manual_columns=self._manual_columns,
                    page_no=0,
                )
                if col:
                    self.finished_ok.emit(col)
                    return
            self.finished_ok.emit(base)
        except Exception as exc:  # noqa: BLE001 — feedback na UI
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Docling → Markdown")
        self.resize(900, 640)

        self._current_file: Path | None = None
        self._worker: ConvertThread | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        path_row = QHBoxLayout()
        self.path_label = QLabel("Nenhum arquivo selecionado.")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_row.addWidget(self.path_label, stretch=1)

        btn_open = QPushButton("Abrir arquivo…")
        btn_open.clicked.connect(self._pick_file)
        path_row.addWidget(btn_open)

        btn_convert = QPushButton("Gerar Markdown")
        btn_convert.clicked.connect(self._start_convert)
        path_row.addWidget(btn_convert)

        btn_save = QPushButton("Salvar .md…")
        btn_save.clicked.connect(self._save_md)
        path_row.addWidget(btn_save)

        layout.addLayout(path_row)

        opts = QHBoxLayout()
        self.chk_columns = QCheckBox("Separar por colunas (telas / IDE com vários painéis)")
        self.chk_columns.setToolTip(
            "Usa posição horizontal dos blocos de texto na página 1. "
            "Ativa também um modelo de layout mais pesado (Egret) em PDF/imagem."
        )
        opts.addWidget(self.chk_columns)
        opts.addWidget(QLabel("Nº colunas (0 = automático):"))
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(0, 6)
        self.spin_cols.setValue(0)
        self.spin_cols.setToolTip(
            "0 tenta detectar colunas pelos espaços horizontais. "
            "Valores 2–6 forçam esse número (útil para 3 colunas tipo Cursor)."
        )
        opts.addWidget(self.spin_cols)
        opts.addStretch()
        layout.addLayout(opts)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("O Markdown gerado aparece aqui.")
        layout.addWidget(self.output, stretch=1)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher documento",
            str(Path.home()),
            FILTERS,
        )
        if not path:
            return
        self._current_file = Path(path)
        self.path_label.setText(str(self._current_file.resolve()))
        self.status_label.setText("Arquivo selecionado. Clique em «Gerar Markdown».")

    def _start_convert(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Aguarde", "Já existe uma conversão em andamento.")
            return
        if not self._current_file or not self._current_file.is_file():
            QMessageBox.warning(self, "Arquivo", "Selecione um arquivo válido primeiro.")
            return

        self.output.clear()
        self.progress.setVisible(True)
        self.status_label.setText("")

        self._worker = ConvertThread(
            self._current_file,
            columnar=self.chk_columns.isChecked(),
            manual_columns=self.spin_cols.value(),
        )
        self._worker.status.connect(self._on_status)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.failed.connect(self._on_error)
        self._worker.start()

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _on_done(self, markdown: str) -> None:
        self.output.setPlainText(markdown)
        self.status_label.setText("Concluído.")

    def _on_error(self, message: str) -> None:
        self.status_label.setText("Erro.")
        QMessageBox.critical(self, "Erro na conversão", message)

    def _on_thread_finished(self) -> None:
        self.progress.setVisible(False)
        self._worker = None

    def _save_md(self) -> None:
        text = self.output.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Salvar", "Não há Markdown para salvar.")
            return
        default = ""
        if self._current_file:
            default = self._current_file.with_suffix(".md").name
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Markdown",
            str(Path.home() / default) if default else str(Path.home()),
            "Markdown (*.md);;Todos (*.*)",
        )
        if not path:
            return
        out = Path(path)
        out.write_text(self.output.toPlainText(), encoding="utf-8")
        self.status_label.setText(f"Salvo: {out}")


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
