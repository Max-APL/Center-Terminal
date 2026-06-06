# Configuración visual y de diseño para la aplicación (Aesthetic Premium Dark Theme)

# Colores principales (Hex)
BG_MAIN = "#09090b"          # Fondo principal ultra oscuro (Zinc 950)
BG_SIDEBAR = "#111115"       # Fondo lateral ligeramente elevado
BG_CARD = "#18181b"          # Fondo de tarjetas (Zinc 900)
BG_CARD_HOVER = "#27272a"    # Hover de tarjetas (Zinc 800)
BORDER_COLOR = "#27272a"     # Bordes sutiles

# Colores de estado
COLOR_PRIMARY = "#10b981"    # Verde esmeralda suave (Color de acento principal)
COLOR_SUCCESS = "#10b981"    # Verde esmeralda (Éxito y activo)
COLOR_DANGER = "#f43f5e"     # Rojo (Eliminaciones / Detener)
COLOR_WARNING = "#f59e0b"    # Ambar
COLOR_MUTED = "#a1a1aa"      # Gris zinc para textos secundarios

# Colores específicos del terminal
TERMINAL_BG = "#050505"      # Fondo de terminal (casi negro absoluto)
TERMINAL_FG = "#e4e4e7"      # Texto de terminal principal (Zinc 200)

# Tipografías (Aumento ligero de tamaños y pesos más definidos)
FONT_TITLE = ("Segoe UI", 24, "bold")
FONT_SUBTITLE = ("Segoe UI", 16, "bold")
FONT_BODY = ("Segoe UI", 13)
FONT_MUTED = ("Segoe UI", 12)
FONT_MONO = ("Consolas", 12)  # Tipografía para el terminal

# Configuración global del tema CustomTkinter
THEME_MODE = "dark"
THEME_COLOR_MAP = {
    "bg_main": BG_MAIN,
    "bg_sidebar": BG_SIDEBAR,
    "bg_card": BG_CARD,
    "bg_card_hover": BG_CARD_HOVER,
    "border": BORDER_COLOR,
    "primary": COLOR_PRIMARY,
    "success": COLOR_SUCCESS,
    "danger": COLOR_DANGER,
    "warning": COLOR_WARNING,
    "muted": COLOR_MUTED,
    "terminal_bg": TERMINAL_BG,
    "terminal_fg": TERMINAL_FG
}
