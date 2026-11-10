"""Trapster colours and style sheet: lime green, dark green and orange."""

# names kept from earlier versions; values are the Trapster palette
OLIVE = "#4E8A1E"        # main green (buttons, bars)
OLIVE_DARK = "#263A14"   # dark green (titles, logo monkey)
OLIVE_LIGHT = "#E5F1D2"  # light green (selection)
LIME = "#96CD3C"
HEADER = "#36401F"       # dark olive header
OCHRE = "#F7931E"        # orange accent
OCHRE_DARK = "#D97A0B"
SAND = "#F6F6F0"
CARD = "#FFFFFF"
LINE = "#E1E3D6"
TEXT = "#232A1B"
MUTED = "#6F7563"
RED = "#B23A2E"
BLUE = "#3E6E8E"

# for charts
CHART = ["#4E8A1E", "#F7931E", "#3E6E8E", "#96CD3C", "#B23A2E", "#7B5E3B", "#263A14", "#FBC37A", "#6A8FA8", "#9C6B5A"]

GROUP_COLOURS = {
    "animal": OLIVE, "uncertain": OCHRE, "human": BLUE, "team": "#7B5E3B", "empty": "#A3A796", "pending": "#D3D6C8",
}

STYLE = f"""
QWidget {{ font-family: "Segoe UI", Arial; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {SAND}; }}
QStackedWidget > QWidget {{ background: {SAND}; }}

#Header {{ background: {HEADER}; }}
#HeaderSub {{ color: {OCHRE}; font-size: 8.5pt; font-weight: 600; }}
#Header QLabel {{ color: white; }}
#HeaderTitle {{ font-size: 14pt; font-weight: 600; color: white; }}
#Crumb {{ color: #D9DCC8; font-size: 11pt; }}
#HeaderButton {{ background: transparent; color: white; border: 1px solid rgba(255,255,255,0.35);
                 border-radius: 6px; padding: 5px 12px; }}
#HeaderButton:hover {{ background: rgba(255,255,255,0.12); }}

#Sidebar {{ background: {CARD}; border-right: 1px solid {LINE}; }}
#Sidebar QTreeWidget {{ border: none; background: {CARD}; font-size: 10.5pt; }}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: {OLIVE_LIGHT}; color: {TEXT}; border-radius: 4px; }}

#PageTitle {{ font-size: 18pt; font-weight: 600; color: {OLIVE_DARK}; }}
#PageSubtitle {{ color: {MUTED}; font-size: 10pt; }}
#SectionTitle {{ font-size: 11.5pt; font-weight: 600; color: {OLIVE_DARK}; }}

#Card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; }}
#Card:hover[clickable="true"] {{ border: 1px solid {OCHRE}; }}
#Tile {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; }}
#TileValue {{ font-size: 18pt; font-weight: 600; color: {OLIVE_DARK}; }}
#TileLabel {{ color: {MUTED}; font-size: 9pt; }}
#TileNote {{ color: {MUTED}; font-size: 8.5pt; }}

QPushButton {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {OCHRE}; background: #FFFBF2; }}
QPushButton:disabled {{ color: #B4AEA0; }}
QPushButton#Primary {{ background: {OLIVE}; color: white; border: 1px solid {OLIVE}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {OLIVE_DARK}; }}
QPushButton#Accent {{ background: {OCHRE}; color: white; border: 1px solid {OCHRE}; font-weight: 600; }}
QPushButton#Accent:hover {{ background: {OCHRE_DARK}; }}
QPushButton#Danger {{ color: {RED}; }}
QPushButton#Quick {{ background: #F1F3EA; border: 1px solid {LINE}; font-weight: 600; padding: 8px 10px; }}
QPushButton#Quick:hover {{ background: {OLIVE_LIGHT}; border-color: {OLIVE}; }}
#Tile[clickable="true"]:hover {{ border: 1px solid {OCHRE}; background: #FFFBF4; }}
QPushButton#Flat {{ border: none; background: transparent; color: {OLIVE}; text-decoration: underline; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTextEdit {{
    background: white; border: 1px solid {LINE}; border-radius: 5px; padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{ border-color: {OLIVE}; }}
QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit {{ padding-right: 18px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button, QDateTimeEdit::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none;
    border-left: 1px solid {LINE}; border-top-right-radius: 5px; background: #FAF8F3; }}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button, QDateTimeEdit::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none;
    border-left: 1px solid {LINE}; border-bottom-right-radius: 5px; background: #FAF8F3; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {{ background: {OLIVE_LIGHT}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow, QDateTimeEdit::up-arrow {{
    image: url(__ASSETS__/arrow_up.png); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow,
QComboBox::down-arrow {{ image: url(__ASSETS__/arrow_down.png); width: 9px; height: 9px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QDateEdit::drop-down, QDateTimeEdit::drop-down {{ border: none; width: 22px; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
#HomeInner {{ background: {SAND}; }}
QLineEdit#Search {{ padding: 7px 10px; font-size: 11pt; border-radius: 16px; }}

QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; background: {CARD}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; margin-right: 2px; color: {MUTED};
               border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {OLIVE_DARK}; border-bottom: 3px solid {OCHRE}; }}

QTableWidget, QTableView {{ background: white; border: 1px solid {LINE}; border-radius: 6px;
                            gridline-color: #EEE9DE; selection-background-color: {OLIVE_LIGHT};
                            selection-color: {TEXT}; alternate-background-color: #FBF9F4; }}
QHeaderView::section {{ background: {OLIVE_LIGHT}; color: {OLIVE_DARK}; border: none;
                        border-right: 1px solid {LINE}; padding: 5px 6px; font-weight: 600; }}
QListWidget {{ background: white; border: 1px solid {LINE}; border-radius: 6px; }}
QListWidget::item:selected {{ background: {OLIVE_LIGHT}; color: {TEXT}; }}

QProgressBar {{ border: 1px solid {LINE}; border-radius: 6px; background: white; height: 22px; text-align: center; }}
QProgressBar::chunk {{ background: {OLIVE}; border-radius: 5px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 14px; background: {CARD}; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {OLIVE_DARK}; font-weight: 600; }}
QMenuBar {{ background: {HEADER}; color: white; }}
QMenuBar::item:selected {{ background: {OLIVE}; }}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 4px; }}
"""


def style_sheet() -> str:
    """The style sheet with the path to the bundled arrow images filled in."""
    from .assets import asset_path

    return STYLE.replace("__ASSETS__", asset_path("x").parent.as_posix())


def apply_matplotlib_style():
    import matplotlib as mpl

    mpl.rcParams.update({
        "axes.prop_cycle": mpl.cycler(color=CHART),
        "axes.edgecolor": "#BDB6A6",
        "axes.labelcolor": TEXT,
        "axes.titleweight": "bold",
        "axes.titlesize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "font.size": 9,
        "font.family": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.color": "#EEE9DE",
        "grid.linewidth": 0.8,
    })
