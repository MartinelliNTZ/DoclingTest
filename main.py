"""
Conversor simples: arquivo local (PDF, imagem, Office, etc.) -> Markdown via Docling.
Requer Python 3.10+ (Docling >= 2.70).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


FILTERS = (
    "Documentos suportados (*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.webp "
    "*.docx *.pptx *.xlsx *.html *.htm *.txt *.md);;"
    "PDF (*.pdf);;"
    "Imagens (*.png *.jpg *.jpeg *.tiff *.tif *.webp);;"
    "Office (*.docx *.pptx *.xlsx);;"
    "Todos os arquivos (*.*)"
)


class ConvertThread(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, file_path: Path) -> None:
        super().__init__()
        self._file_path = file_path

    def run(self) -> None:
        try:
            from docling.document_converter import DocumentConverter

            self.status.emit("Inicializando Docling (modelos podem baixar na 1ª vez)...")
            converter = DocumentConverter()
            self.status.emit("Convertendo…")
            result = converter.convert(str(self._file_path))
            md = result.document.export_to_markdown()
            self.finished_ok.emit(md)
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

        self._worker = ConvertThread(self._current_file)
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
