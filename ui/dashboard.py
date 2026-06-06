import customtkinter as ctk
import psutil
from ui.theme import *
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import matplotlib as mpl
import textwrap

# Configurar el tema de Matplotlib para que coincida con la UI
mpl.rcParams.update({
    "text.color": "white",
    "axes.labelcolor": "white",
    "axes.edgecolor": BORDER_COLOR,
    "xtick.color": COLOR_MUTED,
    "ytick.color": COLOR_MUTED,
    "figure.facecolor": BG_MAIN,
    "axes.facecolor": BG_MAIN,
    "font.family": "sans-serif",
})

CHART_PALETTE = [
    COLOR_PRIMARY, "#8b5cf6", "#f59e0b", "#ec4899", 
    "#06b6d4", "#84cc16", "#ef4444", "#3b82f6"
]

class DashboardView(ctk.CTkFrame):
    def __init__(self, parent, on_action=None, on_select_service=None):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        
        self.on_action = on_action
        self.on_select_service = on_select_service
        self.cards = {}  # Cache de componentes visuales de cada servicio
        self.ws_rows_cache = {} # Cache de los items del resumen
        self.last_filter = None
        
        self.create_widgets()

    def create_widgets(self):
        # Contenedor con scroll para todo el panel
        self.scroll_container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_container.pack(fill="both", expand=True, padx=15, pady=15)
        
        # 1. Cabecera con Filtro
        header_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(5, 15))
        
        title_lbl = ctk.CTkLabel(
            header_frame, text="Panel de Control", 
            font=FONT_TITLE, text_color="white"
        )
        title_lbl.pack(side="left")

        self.filter_var = ctk.StringVar(value="Todos los Espacios")
        self.filter_dropdown = ctk.CTkOptionMenu(
            header_frame, 
            values=["Todos los Espacios"],
            variable=self.filter_var,
            fg_color=BG_CARD,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER
        )
        self.filter_dropdown.pack(side="right")

        # 2. Grid de Métricas Globales (4 Tarjetas)
        self.metrics_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.metrics_frame.pack(fill="x", pady=(0, 20))
        self.metrics_frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="equal")

        self.card_total = self.create_metric_card(self.metrics_frame, "Servicios Registrados", "0", 0)
        self.card_active = self.create_metric_card(self.metrics_frame, "En Ejecución", "0", 1, color=COLOR_SUCCESS, has_progress=True, progress_color=COLOR_SUCCESS)
        self.card_cpu = self.create_metric_card(self.metrics_frame, "Consumo CPU", "0.0%", 2, has_progress=True, progress_color=COLOR_PRIMARY)
        self.card_mem = self.create_metric_card(self.metrics_frame, "Consumo Memoria", "0 MB", 3, has_progress=True, progress_color="white")

        # 3. Gráficos y Resumen
        self.charts_frame = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.charts_frame.pack(fill="x", pady=(0, 20))
        self.charts_frame.grid_columnconfigure(0, weight=5) # Gráficos más grandes
        self.charts_frame.grid_columnconfigure(1, weight=2) # Resumen más compacto

        # 3.1 Contenedor de gráficos (Matplotlib)
        self.chart_container = ctk.CTkFrame(self.charts_frame, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12, height=250)
        self.chart_container.grid(row=0, column=0, padx=(5, 10), sticky="nsew")
        self.chart_container.pack_propagate(False)

        # Inicializar 2 gráficos (Memoria en Barras, CPU en Anillo)
        self.fig, (self.ax1, self.ax2) = plt.subplots(1, 2, figsize=(9, 2.5), dpi=100)
        self.fig.subplots_adjust(left=0.22, right=0.95, top=0.8, bottom=0.15, wspace=0.3)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_container)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)

        # 3.2 Contenedor del resumen
        self.ws_summary_container = ctk.CTkFrame(self.charts_frame, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12, height=250)
        self.ws_summary_container.grid(row=0, column=1, padx=(10, 5), sticky="nsew")
        self.ws_summary_container.pack_propagate(False)
        
        self.ws_summary_lbl = ctk.CTkLabel(self.ws_summary_container, text="Resumen General", font=ctk.CTkFont(size=14, weight="bold"), text_color="white")
        self.ws_summary_lbl.pack(anchor="w", padx=15, pady=(15, 5))
        
        self.ws_rows_frame = ctk.CTkScrollableFrame(self.ws_summary_container, fg_color="transparent")
        self.ws_rows_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 4. Encabezado de la lista de servicios
        self.list_title_lbl = ctk.CTkLabel(
            self.scroll_container, text="Servicios en Ejecución", 
            font=FONT_SUBTITLE, text_color="white"
        )
        self.list_title_lbl.pack(anchor="w", pady=(10, 10))

        # Contenedor para las filas de servicios
        self.services_container = ctk.CTkFrame(self.scroll_container, fg_color="transparent")
        self.services_container.pack(fill="x")

    def create_metric_card(self, parent, title, value, column, color="white", has_progress=False, progress_color=COLOR_PRIMARY):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, height=120, corner_radius=12)
        card.grid(row=0, column=column, padx=5, sticky="nsew")
        card.pack_propagate(False)

        title_lbl = ctk.CTkLabel(card, text=title, font=FONT_MUTED, text_color=COLOR_MUTED)
        title_lbl.pack(anchor="w", padx=15, pady=(12, 2))

        val_lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"), text_color=color)
        val_lbl.pack(anchor="w", padx=15)

        progress_bar = None
        if has_progress:
            progress_bar = ctk.CTkProgressBar(card, height=4, fg_color=BORDER_COLOR, progress_color=progress_color)
            progress_bar.pack(fill="x", padx=15, pady=(10, 0))
            progress_bar.set(0.0)

        return {"card": card, "value_label": val_lbl, "progress_bar": progress_bar}

    def rebuild_grid(self, services, selected_ws_id=None):
        for card_id, widgets in list(self.cards.items()):
            widgets["frame"].destroy()
        self.cards.clear()

        filtered_services = {k: v for k, v in services.items() if selected_ws_id is None or v.workspace_id == selected_ws_id}

        if not filtered_services:
            no_services_frame = ctk.CTkFrame(self.services_container, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, height=110, corner_radius=12)
            no_services_frame.pack(fill="x", pady=5)
            no_services_frame.pack_propagate(False)
            lbl = ctk.CTkLabel(no_services_frame, text="No hay servicios para mostrar en esta vista.", font=FONT_BODY, text_color=COLOR_MUTED)
            lbl.pack(expand=True)
            self.cards["_empty"] = {"frame": no_services_frame}
            return

        for service_id, service in filtered_services.items():
            row_frame = ctk.CTkFrame(
                self.services_container, fg_color=BG_CARD, border_width=1, 
                border_color=BORDER_COLOR, height=75, corner_radius=12
            )
            row_frame.pack(fill="x", pady=5)
            row_frame.pack_propagate(False)

            row_frame.bind("<Enter>", lambda e, rf=row_frame: rf.configure(fg_color=BG_CARD_HOVER))
            row_frame.bind("<Leave>", lambda e, rf=row_frame: rf.configure(fg_color=BG_CARD))

            # Info
            info_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            info_frame.pack(side="left", fill="both", padx=15, expand=True)
            
            lbl_name = ctk.CTkLabel(info_frame, text=service.name, font=ctk.CTkFont(size=14, weight="bold"), text_color="white")
            lbl_name.pack(anchor="w", pady=(10, 0))
            
            cmd_preview = service.command
            if len(cmd_preview) > 35:
                cmd_preview = cmd_preview[:32] + "..."
            lbl_cmd = ctk.CTkLabel(info_frame, text=cmd_preview, font=FONT_MUTED, text_color=COLOR_MUTED)
            lbl_cmd.pack(anchor="w", pady=(0, 5))

            # Status
            status_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=100)
            status_frame.pack(side="left", fill="y", padx=10)
            status_frame.pack_propagate(False)
            
            badge_container = ctk.CTkFrame(status_frame, fg_color="transparent")
            badge_container.pack(expand=True)
            status_badge = ctk.CTkFrame(badge_container, width=10, height=10, corner_radius=5, fg_color=COLOR_MUTED)
            status_badge.pack(side="left", padx=(0, 6), pady=6)
            lbl_status = ctk.CTkLabel(badge_container, text="Detenido", font=FONT_BODY, text_color="white")
            lbl_status.pack(side="left")

            # CPU
            cpu_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=120)
            cpu_frame.pack(side="left", fill="y", padx=10)
            cpu_frame.pack_propagate(False)
            cpu_container = ctk.CTkFrame(cpu_frame, fg_color="transparent")
            cpu_container.pack(expand=True, fill="x", padx=5)
            lbl_cpu = ctk.CTkLabel(cpu_container, text="CPU: 0.0%", font=FONT_MUTED, text_color=COLOR_MUTED)
            lbl_cpu.pack(anchor="w")
            bar_cpu = ctk.CTkProgressBar(cpu_container, height=6, fg_color=BORDER_COLOR, progress_color=COLOR_PRIMARY)
            bar_cpu.pack(fill="x", pady=(2, 0))
            bar_cpu.set(0.0)

            # Mem
            mem_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=120)
            mem_frame.pack(side="left", fill="y", padx=10)
            mem_frame.pack_propagate(False)
            mem_container = ctk.CTkFrame(mem_frame, fg_color="transparent")
            mem_container.pack(expand=True, fill="x", padx=5)
            lbl_mem = ctk.CTkLabel(mem_container, text="Mem: 0 MB", font=FONT_MUTED, text_color=COLOR_MUTED)
            lbl_mem.pack(anchor="w")
            bar_mem = ctk.CTkProgressBar(mem_container, height=6, fg_color=BORDER_COLOR, progress_color="white")
            bar_mem.pack(fill="x", pady=(2, 0))
            bar_mem.set(0.0)

            # Actions
            actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent", width=150)
            actions_frame.pack(side="right", fill="y", padx=10)
            actions_frame.pack_propagate(False)

            btn_play = ctk.CTkButton(
                actions_frame, text="Iniciar", width=65, height=28,
                fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="white",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda sid=service_id: self.toggle_service_state(sid)
            )
            btn_play.pack(side="left", padx=3, expand=True)

            btn_terminal = ctk.CTkButton(
                actions_frame, text="Logs", width=55, height=28,
                fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
                text_color="white", hover_color=BG_CARD_HOVER,
                font=ctk.CTkFont(size=11),
                command=lambda sid=service_id: self.select_service(sid)
            )
            btn_terminal.pack(side="left", padx=3, expand=True)

            self.cards[service_id] = {
                "frame": row_frame, "lbl_status": lbl_status, "badge": status_badge,
                "lbl_cpu": lbl_cpu, "bar_cpu": bar_cpu, "lbl_mem": lbl_mem,
                "bar_mem": bar_mem, "btn_play": btn_play
            }

    def update_stats(self, services, global_stats, ws_stats=None, ws_names=None):
        if not ws_names:
            ws_names = {}

        # 1. Actualizar Filtro
        current_options = ["Todos los Espacios"] + list(ws_names.values())
        if current_options != self.filter_dropdown.cget("values"):
            self.filter_dropdown.configure(values=current_options)
            
        selected_name = self.filter_var.get()
        selected_ws_id = None
        if selected_name != "Todos los Espacios":
            for wid, wname in ws_names.items():
                if wname == selected_name:
                    selected_ws_id = wid
                    break

        if self.last_filter != selected_ws_id:
            self.last_filter = selected_ws_id
            self.rebuild_grid(services, selected_ws_id)
            
            # Cambiar titulo resumen
            if selected_ws_id:
                self.ws_summary_lbl.configure(text=f"Servicios en {selected_name}")
            else:
                self.ws_summary_lbl.configure(text="Resumen por Espacios")

        # 2. Métricas Superiores
        target_stats = global_stats
        if selected_ws_id and ws_stats and selected_ws_id in ws_stats:
            target_stats = ws_stats[selected_ws_id]

        total = target_stats.get("total_count", 0)
        running = target_stats.get("running_count", 0)
        
        self.card_total["value_label"].configure(text=str(total))
        self.card_active["value_label"].configure(text=str(running))
        if self.card_active["progress_bar"]:
            self.card_active["progress_bar"].set((running / total) if total > 0 else 0.0)
            
        cpu_val = target_stats.get('total_cpu', 0.0)
        self.card_cpu["value_label"].configure(text=f"{cpu_val:.1f}%")
        if self.card_cpu["progress_bar"]:
            self.card_cpu["progress_bar"].set(cpu_val / 100.0)
        
        total_mem_mb = target_stats.get("total_mem", 0) / (1024 * 1024)
        mem_str = f"{total_mem_mb:.1f} MB" if total_mem_mb < 1024 else f"{total_mem_mb/1024:.2f} GB"
        self.card_mem["value_label"].configure(text=mem_str)
        
        total_system_mem_mb = psutil.virtual_memory().total / (1024 * 1024)
        if self.card_mem["progress_bar"]:
            self.card_mem["progress_bar"].set((total_mem_mb / total_system_mem_mb) if total_system_mem_mb > 0 else 0.0)

        # 3. Datos de Listas y Gráficos
        list_items = [] # (id, name, text1, text2, color)
        names_for_chart = []
        mem_for_chart = []
        cpu_for_chart = []
        
        if selected_ws_id is None:
            # Vista General
            for wid, stats in ws_stats.items():
                wname = ws_names.get(wid, "Desconocido")
                list_items.append((
                    wid, wname, 
                    f"{stats.get('running_count', 0)}/{stats.get('total_count', 0)} act",
                    f"{stats.get('total_cpu', 0):.1f}% CPU",
                    COLOR_SUCCESS if stats.get("running_count", 0) > 0 else COLOR_MUTED
                ))
                names_for_chart.append(wname)
                mem_for_chart.append(stats.get("total_mem", 0) / (1024*1024))
                cpu_for_chart.append(stats.get("total_cpu", 0))
        else:
            # Vista Especifica de Espacio
            filtered_services = {k: v for k, v in services.items() if v.workspace_id == selected_ws_id}
            for sid, srv in filtered_services.items():
                list_items.append((
                    sid, srv.name,
                    srv.status.capitalize(),
                    f"{srv.cpu_usage:.1f}% CPU",
                    COLOR_SUCCESS if srv.status == "running" else COLOR_MUTED
                ))
                names_for_chart.append(srv.name)
                mem_for_chart.append(srv.mem_usage / (1024*1024))
                cpu_for_chart.append(srv.cpu_usage)

        # 3.1 Actualizar Resumen List Cacheado
        current_ids = set([item[0] for item in list_items])
        for cid in list(self.ws_rows_cache.keys()):
            if cid not in current_ids:
                self.ws_rows_cache[cid]["frame"].destroy()
                del self.ws_rows_cache[cid]

        for idx, item in enumerate(list_items):
            cid, name, t1, t2, color = item
            if cid not in self.ws_rows_cache:
                row = ctk.CTkFrame(self.ws_rows_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                # Ancho incrementado a 150 para que quepa el nombre
                lbl_name = ctk.CTkLabel(row, text="", width=150, anchor="w", text_color="white", font=ctk.CTkFont(weight="bold", size=11))
                lbl_name.pack(side="left", padx=5)
                lbl_t1 = ctk.CTkLabel(row, text="", width=70, anchor="w", font=ctk.CTkFont(size=11))
                lbl_t1.pack(side="left")
                lbl_t2 = ctk.CTkLabel(row, text="", width=70, anchor="e", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11))
                lbl_t2.pack(side="right", padx=5)
                self.ws_rows_cache[cid] = {"frame": row, "lbl_name": lbl_name, "lbl_t1": lbl_t1, "lbl_t2": lbl_t2}
            
            cache = self.ws_rows_cache[cid]
            # Truncar con elipsoide si es muy largo, ajustando a 25 caracteres para mejor lectura
            display_name = name[:25] + "..." if len(name) > 25 else name
            cache["lbl_name"].configure(text=display_name)
            cache["lbl_t1"].configure(text=t1, text_color=color)
            cache["lbl_t2"].configure(text=t2)

        # 3.2 Dibujar Gráficos
        self.ax1.clear()
        self.ax2.clear()

        if names_for_chart:
            colors = [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(names_for_chart))]
            
            # Envolver textos largos en dos líneas (máximo 12 caracteres por línea aprox)
            short_names = [textwrap.fill(n, width=12) for n in names_for_chart]

            # Gráfico de Barras: Memoria vs Límite Físico del Sistema
            bars = self.ax1.barh(short_names, mem_for_chart, color=colors, alpha=0.9)
            
            # Limitar el eje X a la RAM total del sistema para ver la escala real
            self.ax1.set_xlim(0, total_system_mem_mb)
            self.ax1.set_title("Memoria en uso frente al Total (MB)", color="white", fontsize=10, fontweight="bold", pad=8)
            
            # Añadir las etiquetas del número encima de las barras
            self.ax1.bar_label(bars, fmt='%.1f', padding=4, color="white", fontsize=8)

            self.ax1.tick_params(axis='x', colors=COLOR_MUTED, labelsize=8)
            self.ax1.tick_params(axis='y', colors="white", labelsize=9)
            self.ax1.spines['top'].set_visible(False)
            self.ax1.spines['right'].set_visible(False)
            self.ax1.spines['left'].set_color(BORDER_COLOR)
            self.ax1.spines['bottom'].set_color(BORDER_COLOR)

            # Gráfico de Anillo: CPU usada vs CPU Libre (100%)
            total_cpu = sum(cpu_for_chart)
            if total_cpu > 0:
                # Calculamos cuanto sobra hasta 100%
                free_cpu = max(0, 100 - total_cpu)
                pie_data = cpu_for_chart + [free_cpu]
                pie_colors = colors + [BG_MAIN]
                
                # Explotar la porcion para que resalte y ocultar porcentaje interno para evitar solapamiento
                wedges, texts = self.ax2.pie(
                    pie_data, 
                    wedgeprops=dict(width=0.4, edgecolor=BORDER_COLOR), 
                    colors=pie_colors
                )

                # Si el último valor es "Libre", lo ocultamos o le cambiamos el color de borde para que no resalte
                if len(wedges) > len(cpu_for_chart):
                    wedges[-1].set_edgecolor(BORDER_COLOR)
                    wedges[-1].set_facecolor("none")

                self.ax2.set_title("Uso de CPU (Escala real 100%)", color="white", fontsize=10, fontweight="bold", pad=8)
                
                # Central text
                self.ax2.text(0, 0, f"{total_cpu:.1f}%", ha='center', va='center', fontsize=12, fontweight='bold', color="white")
            else:
                self.ax2.pie([1], wedgeprops=dict(width=0.4), colors=[BORDER_COLOR])
                self.ax2.set_title("CPU Inactiva", color=COLOR_MUTED, fontsize=10, fontweight="bold", pad=8)
                self.ax2.text(0, 0, "0.0%", ha='center', va='center', fontsize=12, fontweight='bold', color=COLOR_MUTED)
        
        self.canvas.draw()

        # 4. Filas individuales de servicios
        for service_id, service in services.items():
            if service_id not in self.cards:
                continue

            card = self.cards[service_id]

            status = service.status
            if status == "running":
                card["badge"].configure(fg_color=COLOR_SUCCESS)
                card["lbl_status"].configure(text="Corriendo", text_color="white")
                card["btn_play"].configure(text="Detener", fg_color=COLOR_DANGER, hover_color="#dc2626")
            elif status == "starting":
                card["badge"].configure(fg_color=COLOR_WARNING)
                card["lbl_status"].configure(text="Iniciando...", text_color=COLOR_WARNING)
                card["btn_play"].configure(text="Detener", fg_color=COLOR_DANGER, hover_color="#dc2626")
            elif status == "error":
                card["badge"].configure(fg_color=COLOR_DANGER)
                card["lbl_status"].configure(text="Error", text_color=COLOR_DANGER)
                card["btn_play"].configure(text="Iniciar", fg_color=COLOR_SUCCESS, hover_color="#059669")
            else: # stopped
                card["badge"].configure(fg_color=COLOR_MUTED)
                card["lbl_status"].configure(text="Detenido", text_color=COLOR_MUTED)
                card["btn_play"].configure(text="Iniciar", fg_color=COLOR_SUCCESS, hover_color="#059669")

            cpu_val = service.cpu_usage
            card["lbl_cpu"].configure(text=f"CPU: {cpu_val:.1f}%")
            card["bar_cpu"].set(cpu_val / 100.0)

            mem_bytes = service.mem_usage
            mem_mb = mem_bytes / (1024 * 1024)
            card["lbl_mem"].configure(text=f"Mem: {mem_mb:.1f} MB")
            card["bar_mem"].set(min(1.0, mem_mb / 500.0))

    def toggle_service_state(self, service_id):
        if not self.on_action: return
        card = self.cards.get(service_id)
        if not card: return
        self.on_action(service_id, "start" if card["btn_play"].cget("text") == "Iniciar" else "stop")

    def select_service(self, service_id):
        if self.on_select_service:
            self.on_select_service(service_id)
