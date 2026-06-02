"""
Polar Pattern Analyzer — Entry point with QStackedWidget two-screen architecture
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Polar Pattern Analyzer")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("AcousticTools")

    # Configure application font
    font = QFont()
    if sys.platform == "win32":
        font.setFamily("Segoe UI")
    elif sys.platform == "darwin":
        font.setFamily("SF Pro Display")
    else:
        font.setFamily("Ubuntu")
    font.setPointSize(10)
    app.setFont(font)

    # Create and show main window with two-screen stacked widget
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
