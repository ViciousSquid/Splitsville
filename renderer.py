from PyQt5.QtWidgets import QOpenGLWidget, QToolButton
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QRadialGradient,
                          QPainterPath, QLinearGradient, QTransform, QFont)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
import math
import time


class Renderer(QOpenGLWidget):
    cell_selected = pyqtSignal(object)

    def __init__(self, environment, parent=None):
        super().__init__(parent)
        self.environment = environment
        self.selected_cell = None
        self.draw_food_mode = False
        self.erase_food_mode = False
        self.move_light_mode = False

        self._zoom = 1.0
        self._pan_offset = QPointF(0, 0)
        self._last_mouse = None
        self._panning = False

        self._anim_time = 0.0
        self._last_frame_time = time.monotonic()

        self.frame_times = []
        self.cell_items = {}

        self.draw_food_button = QToolButton()
        self.draw_food_button.setText("Draw Food")
        self.draw_food_button.setCheckable(True)
        self.draw_food_button.clicked.connect(self.toggle_draw_food_mode)

        self.erase_food_button = QToolButton()
        self.erase_food_button.setText("Erase Food")
        self.erase_food_button.setCheckable(True)
        self.erase_food_button.clicked.connect(self.toggle_erase_food_mode)

        self.setMinimumSize(500, 500)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ helpers
    def get_visible_bounds(self):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        ex, ey = self.environment.center
        margin = 80.0
        left   = (0 - cx - self._pan_offset.x()) / self._zoom + ex - margin
        top    = (0 - cy - self._pan_offset.y()) / self._zoom + ey - margin
        right  = (w - cx - self._pan_offset.x()) / self._zoom + ex + margin
        bottom = (h - cy - self._pan_offset.y()) / self._zoom + ey + margin
        return left, top, right, bottom

    def _screen_to_world(self, sx, sy):
        cx, cy = self.width() / 2, self.height() / 2
        ex, ey = self.environment.center
        wx = (sx - cx - self._pan_offset.x()) / self._zoom + ex
        wy = (sy - cy - self._pan_offset.y()) / self._zoom + ey
        return wx, wy

    def _apply_transform(self, painter):
        cx, cy = self.width() / 2, self.height() / 2
        ex, ey = self.environment.center
        painter.translate(cx + self._pan_offset.x(), cy + self._pan_offset.y())
        painter.scale(self._zoom, self._zoom)
        painter.translate(-ex, -ey)

    # ------------------------------------------------------------------ paint
    def paintGL(self):
        now = time.monotonic()
        self.frame_times.append(now)
        while self.frame_times and self.frame_times[0] < now - 1.0:
            self.frame_times.pop(0)
        fps = len(self.frame_times)

        self._anim_time += now - self._last_frame_time
        self._last_frame_time = now
        t = self._anim_time

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        painter.fillRect(self.rect(), QColor(12, 14, 18))

        painter.save()
        self._apply_transform(painter)

        self._draw_petri_dish(painter, t)
        self._draw_food_batch(painter, t)
        self._draw_cells(painter, t)
        # Only draw light source if enabled
        if getattr(self.environment, 'light_enabled', True):
            self._draw_light_source(painter, t)

        # Draw death markers (DIED text)
        self._draw_death_markers(painter)

        # Draw floating score popups
        self._draw_score_popups(painter)

        painter.restore()

        # ---- HUD overlay (drawn in screen space, not transformed) ----
        painter.setPen(QColor(255, 255, 220, 240))
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(15, 24, f"FPS: {fps}")
        painter.drawText(15, 42, f"Cells: {len(self.environment.cells)}")
        painter.drawText(15, 60, f"Food:  {len(self.environment.food)}")
        painter.drawText(15, 78, f"Zoom:  {self._zoom:.1f}x")

        # Score and combo in bottom right of viewport
        self._draw_score_hud(painter)

        painter.end()

    # -------------------------------------------------------- score HUD
    def _draw_score_hud(self, painter):
        """Draw score and combo in the bottom-right corner of the viewport."""
        env = self.environment
        w = self.width()
        h = self.height()

        # Score text
        score_text = f"Score: {env.score}"
        score_font = QFont("Arial", 14)
        score_font.setBold(True)
        painter.setFont(score_font)

        fm = painter.fontMetrics()
        score_width = fm.horizontalAdvance(score_text)
        score_height = fm.height()

        # Combo text
        combo_text = ""
        if env.combo_count > 1:
            mult = 1.0 + (env.combo_count - 1) * 0.5
            combo_text = f"COMBO x{mult:.1f}!"

        combo_font = QFont("Arial", 11)
        combo_font.setBold(True)
        painter.setFont(combo_font)
        fm_combo = painter.fontMetrics()
        combo_width = fm_combo.horizontalAdvance(combo_text) if combo_text else 0
        combo_height = fm_combo.height()

        # Right-align with padding
        padding = 15
        right_x = w - padding

        # Draw score
        score_y = h - padding - combo_height - 4
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(right_x - score_width + 1, score_y + 1, score_text)
        painter.setPen(QColor(255, 215, 0))  # Gold
        painter.drawText(right_x - score_width, score_y, score_text)

        # Draw combo below score
        if combo_text:
            combo_y = h - padding
            painter.setFont(combo_font)
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(right_x - combo_width + 1, combo_y + 1, combo_text)
            painter.setPen(QColor(255, 102, 0))  # Orange
            painter.drawText(right_x - combo_width, combo_y, combo_text)

    # -------------------------------------------------------- petri dish
    def _draw_petri_dish(self, painter, t):
        env = self.environment
        r = env.radius
        cx, cy = env.center
        lx, ly = env.light_source
        intensity = getattr(env, 'light_intensity', 1.0)
        light_color = getattr(env, 'light_color', (255, 255, 200))

        base_grad = QRadialGradient(cx, cy, r)
        base_grad.setColorAt(0.0, QColor(22, 42, 28))
        base_grad.setColorAt(1.0, QColor(10, 20, 14))
        painter.setBrush(QBrush(base_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        spread_r = r * 0.85
        light_alpha = int(70 * intensity)
        lc = QColor(*light_color, light_alpha)
        lc_fade = QColor(*light_color, 0)
        light_grad = QRadialGradient(lx, ly, spread_r)
        light_grad.setColorAt(0.0, lc)
        light_grad.setColorAt(0.45, QColor(*light_color, int(25 * intensity)))
        light_grad.setColorAt(1.0, lc_fade)
        painter.setBrush(QBrush(light_grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        rim_grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        rim_grad.setColorAt(0.0, QColor(200, 210, 220, 160))
        rim_grad.setColorAt(0.5, QColor(120, 140, 160, 80))
        rim_grad.setColorAt(1.0, QColor(180, 190, 200, 140))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(rim_grad), 4))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.setPen(QPen(QColor(255, 255, 255, 30), 2))
        painter.drawArc(QRectF(cx - r + 10, cy - r + 10, r * 2 - 20, r * 2 - 20),
                        30 * 16, 80 * 16)

    # -------------------------------------------------------- food
    def _draw_food_batch(self, painter, t):
        if not self.environment.food:
            return
        vis_l, vis_t, vis_r, vis_b = self.get_visible_bounds()
        animate = len(self.environment.food) < 300

        path = QPainterPath()
        glow_path = QPainterPath()
        for fx, fy in self.environment.food:
            if not (vis_l < fx < vis_r and vis_t < fy < vis_b):
                continue
            s = 2.0 * (0.8 + 0.2 * math.sin(t * 2.5 + fx * 0.1 + fy * 0.07)) if animate else 2.0
            path.addEllipse(QRectF(fx - s, fy - s, s * 2, s * 2))
            glow_path.addEllipse(QRectF(fx - s * 2, fy - s * 2, s * 4, s * 4))

        painter.setBrush(QColor(60, 230, 100, 25))
        painter.setPen(Qt.NoPen)
        painter.drawPath(glow_path)
        painter.setBrush(QColor(70, 240, 110, 220))
        painter.drawPath(path)

    # -------------------------------------------------------- cells — 4‑tier LOD
    def _draw_cells(self, painter, t):
        env = self.environment
        lx, ly = env.light_source
        intensity = getattr(env, 'light_intensity', 1.0)
        vis_l, vis_t, vis_r, vis_b = self.get_visible_bounds()
        zoom = self._zoom

        tier1_paths = {}
        tier2_cells = []
        tier3_cells = []

        for cell in env.cells:
            px = float(cell.position[0])
            py = float(cell.position[1])
            size = max(float(cell._body_size), 4.0)

            if not (vis_l - size < px < vis_r + size and vis_t - size < py < vis_b + size):
                continue

            pulse_phase = cell.pulse_phase
            pulse_rate = 1.8 / max(size / 10, 0.5)
            energy_frac = cell.energy / 100.0
            pulse_amp = 0.04 + 0.08 * (1.0 - energy_frac)
            pulse = 1.0 + pulse_amp * math.sin(t * pulse_rate + pulse_phase)
            draw_size = size * pulse
            screen_size = draw_size * zoom

            if screen_size < 1.5:
                continue

            r_f, g_f, b_f = cell.genome.genes['color']
            if energy_frac < 0.35:
                grey = 0.5
                blend = (0.35 - energy_frac) / 0.35
                r_f = r_f + (grey - r_f) * blend
                g_f = g_f + (grey - g_f) * blend
                b_f = b_f + (grey - b_f) * blend

            base_color = QColor.fromRgbF(min(1, r_f), min(1, g_f), min(1, b_f))

            if screen_size < 6.0:
                ck = (int(r_f * 8), int(g_f * 8), int(b_f * 8))
                if ck not in tier1_paths:
                    avg_col = QColor.fromRgbF(round(r_f * 8) / 8,
                                              round(g_f * 8) / 8,
                                              round(b_f * 8) / 8)
                    tier1_paths[ck] = (QPainterPath(), avg_col)
                path, _ = tier1_paths[ck]
                half = max(screen_size / zoom, 1.5)
                path.addRect(QRectF(px - half, py - half, half * 2, half * 2))
            elif screen_size < 18.0:
                tier2_cells.append((px, py, draw_size, base_color, cell))
            else:
                tier3_cells.append((px, py, draw_size, base_color, cell))

        # Tier 1 batch
        painter.setPen(Qt.NoPen)
        for path, col in tier1_paths.values():
            painter.setBrush(col)
            painter.drawPath(path)

        # Tier 2 fast
        for px, py, draw_size, base_color, cell in tier2_cells:
            highlight = QColor(base_color).lighter(160)
            highlight.setAlpha(200)
            shadow = QColor(base_color).darker(150)
            body_grad = QRadialGradient(
                px - draw_size * 0.25, py - draw_size * 0.25, draw_size * 0.9)
            body_grad.setColorAt(0.0, highlight)
            body_grad.setColorAt(1.0, shadow)
            painter.setBrush(QBrush(body_grad))
            painter.setPen(QPen(QColor(255, 60, 60), 2.5, Qt.DashLine)
                           if cell is self.selected_cell
                           else QPen(QColor(90, 100, 95), 1.0))
            half = draw_size / 2
            painter.drawEllipse(QRectF(px - half, py - half, draw_size, draw_size))

        # Tier 3 full detail
        for px, py, draw_size, base_color, cell in tier3_cells:
            self._draw_cell_full(painter, cell, px, py, draw_size, base_color, t,
                                  lx, ly, intensity, env)

    # -------------------------------------------------------- full‑detail cell
    def _draw_cell_full(self, painter, cell, px, py, draw_size, base_color, t,
                         lx, ly, intensity, env):
        pulse_phase = cell.pulse_phase
        motility = cell.genome.genes.get('motility_mode', 1)
        body_shape = cell.genome.genes.get('body_shape', 0)
        angle = cell.angle

        # Photocyte glow
        if cell.type == "Photocyte":
            glow_brightness = getattr(cell, 'glow_intensity', 0.0)
            if glow_brightness > 0.05:
                glow_r = draw_size * (1.5 + glow_brightness)
                grad = QRadialGradient(px, py, glow_r)
                grad.setColorAt(0.0, QColor(160, 255, 160, int(120 * glow_brightness)))
                grad.setColorAt(0.6, QColor(80, 255, 120, int(90 * glow_brightness)))
                grad.setColorAt(1.0, QColor(0, 200, 80, 0))
                painter.setBrush(QBrush(grad))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QRectF(px - glow_r, py - glow_r, glow_r * 2, glow_r * 2))

        # Phagocyte danger aura
        if cell.type == "Phagocyte":
            hunt_intensity = max(0.2, 1.0 - cell.energy / 100.0)
            aura_pulse = 0.5 + 0.5 * abs(math.sin(t * 1.2 + pulse_phase))
            aura_r = draw_size * 1.4
            painter.setBrush(QColor(220, 80, 30, int(50 * aura_pulse * hunt_intensity)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(px - aura_r, py - aura_r, aura_r * 2, aura_r * 2))

        # Adhesin ring
        if getattr(cell, 'adhesin', False):
            adhesin_r = draw_size * 1.2 + 8
            adhesin_col = QColor(base_color)
            adhesin_col.setAlpha(35)
            painter.setBrush(adhesin_col)
            painter.setPen(QPen(QColor(base_color.red(), base_color.green(),
                                       base_color.blue(), 60), 1.5, Qt.DotLine))
            painter.drawEllipse(QRectF(px - adhesin_r, py - adhesin_r,
                                       adhesin_r * 2, adhesin_r * 2))

        # ── Motility rendering ────────────────────────────────────────────
        # Flagellum or cilia

        # Clip to petri dish
        r = env.radius
        cx, cy = env.center
        clip_path = QPainterPath()
        clip_path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.save()
        painter.setClipPath(clip_path, Qt.IntersectClip)

        if motility == 1:               # Flagellum (tail)
            self._draw_flagellum(painter, cell, px, py, draw_size, base_color, t)

        elif motility == 2:             # Cilia hairs
            self._draw_cilia(painter, cell, px, py, draw_size, base_color, t)

        painter.restore()

        # ── Cell body (oval or round) ─────────────────────────────────────
        # Outline pen
        if cell is self.selected_cell:
            pen = QPen(QColor(255, 60, 60), 2.8, Qt.DashLine)
        elif cell.type == "Phagocyte":
            pen = QPen(QColor(230, 110, 40), 2.2)
        elif cell.type == "Bacteria":
            pen = QPen(QColor(100, 210, 160), 1.2)
        elif cell.type == "Photocyte":
            pen = QPen(QColor(60, 250, 100), 1.6)
        else:
            pen = QPen(QColor(90, 100, 95), 1.0)

        # Gradient body
        highlight = QColor(base_color).lighter(180)
        highlight.setAlpha(220)
        shadow = QColor(base_color).darker(170)

        if body_shape == 1:   # Oval – elongate along movement angle
            a = draw_size * 0.7        # semi‑major
            b = draw_size * 0.4        # semi‑minor
            # Build an ellipse path and rotate it
            body_rect = QRectF(-a, -b, a * 2, b * 2)
            body_path = QPainterPath()
            body_path.addEllipse(body_rect)

            # Create a gradient in local coords (aligned before rotation)
            body_grad = QRadialGradient(0, 0, a * 0.9)
            body_grad.setColorAt(0.0, highlight)
            body_grad.setColorAt(0.4, base_color)
            body_grad.setColorAt(1.0, shadow)

            painter.save()
            painter.translate(px, py)
            painter.rotate(math.degrees(angle))
            painter.setBrush(QBrush(body_grad))
            painter.setPen(pen)
            painter.drawPath(body_path)
            painter.restore()
        else:                 # Round
            body_grad = QRadialGradient(
                px - draw_size * 0.25, py - draw_size * 0.25, draw_size * 0.9)
            body_grad.setColorAt(0.0, highlight)
            body_grad.setColorAt(0.4, base_color)
            body_grad.setColorAt(1.0, shadow)
            painter.setBrush(QBrush(body_grad))
            painter.setPen(pen)
            half = draw_size / 2
            painter.drawEllipse(QRectF(px - half, py - half, draw_size, draw_size))

        # ── Nucleus (eukaryotes) ──────────────────────────────────────────
        if cell.type != "Bacteria":
            ns = draw_size * 0.28
            nuc_col = QColor(base_color).darker(200)
            nuc_col.setAlpha(170)
            nx = px + math.sin(t * 0.7 + pulse_phase) * draw_size * 0.08
            ny = py + math.cos(t * 0.5 + pulse_phase) * draw_size * 0.08
            painter.setBrush(nuc_col)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(nx - ns / 2, ny - ns / 2, ns, ns))
            nn = ns * 0.4
            painter.setBrush(QColor(base_color).lighter(140))
            painter.drawEllipse(QRectF(nx - nn / 2, ny - nn / 2, nn, nn))

        # Membrane shimmer
        shimmer_alpha = int(60 + 40 * math.sin(t * 4 + pulse_phase))
        painter.setBrush(QColor(255, 255, 255, shimmer_alpha))
        painter.setPen(Qt.NoPen)
        sh = draw_size * 0.22
        painter.drawEllipse(QRectF(
            px - draw_size * 0.28, py - draw_size * 0.32, sh, sh * 0.6))

    # ── Flagellum drawing ──────────────────────────────────────────────
    def _draw_flagellum(self, painter, cell, px, py, draw_size, base_color, t):
        angle = cell.angle
        pulse_phase = cell.pulse_phase
        tail_len = draw_size * 2.2
        segments = 10
        seg_len = tail_len / segments

        attach_angle = angle + math.pi
        ax = px + math.cos(attach_angle) * draw_size * 0.4
        ay = py + math.sin(attach_angle) * draw_size * 0.4

        path = QPainterPath()
        path.moveTo(ax, ay)
        cx_prev, cy_prev = ax, ay
        cos_a = math.cos(attach_angle)
        sin_a = math.sin(attach_angle)
        perp_x = -sin_a
        perp_y  =  cos_a

        for i in range(1, segments + 1):
            wave = math.sin(t * 9 + pulse_phase + i * 0.7) * (draw_size * 0.08 * i / segments)
            cx_n = cx_prev + cos_a * seg_len + perp_x * wave
            cy_n = cy_prev + sin_a * seg_len + perp_y * wave
            path.lineTo(cx_n, cy_n)
            cx_prev, cy_prev = cx_n, cy_n

        tail_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 180)
        pen = QPen(tail_color, max(1.5, draw_size * 0.12), Qt.SolidLine,
                   Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    # ── Cilia drawing ───────────────────────────────────────────────────
    def _draw_cilia(self, painter, cell, px, py, draw_size, base_color, t):
        """
        Draw many short, wavy hairs around the cell perimeter, like Spore cilia.
        """
        num_hairs = 16
        angle = cell.angle
        cilia_len = draw_size * 0.55
        cilia_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 140)
        pen = QPen(cilia_color, max(1.0, draw_size * 0.08), Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        pulse_phase = cell.pulse_phase

        for i in range(num_hairs):
            a = i * (2 * math.pi / num_hairs)
            # base point on the body surface
            bx = px + math.cos(a) * (draw_size * 0.45)
            by = py + math.sin(a) * (draw_size * 0.45)
            # tip with wave
            wave = math.sin(t * 13 + i * 1.1 + pulse_phase) * 0.3
            tip_a = a + wave * 0.3
            tx = bx + math.cos(tip_a) * cilia_len
            ty = by + math.sin(tip_a) * cilia_len
            painter.drawLine(QPointF(bx, by), QPointF(tx, ty))

    # -------------------------------------------------------- death markers
    def _draw_death_markers(self, painter):
        """Draw 'DIED' text above each active death marker, scaled by cell size."""
        for x, y, cell_size, remaining in self.environment.death_markers:
            alpha = min(255, int(200 * (remaining / 1.2)))
            if alpha <= 5:
                continue
            # Smaller range: 5–10 pt instead of 6–14 pt
            font_size = max(5, min(10, 5 + int(cell_size / 4.0)))
            painter.setPen(QColor(255, 80, 80, alpha))
            font = painter.font()
            font.setPointSize(font_size)
            font.setBold(True)
            painter.setFont(font)
            # Draw text slightly above the death position
            painter.drawText(QPointF(x - 12, y - 12 - (font_size / 6)), "DIED")

    # -------------------------------------------------------- score popups
    def _draw_score_popups(self, painter):
        """Draw floating score popups that drift upward and fade out."""
        for popup in self.environment.score_popups:
            x, y, text, r, g, b, remaining, font_size = popup
            alpha = min(255, int(255 * (remaining / self.environment.popup_lifetime)))
            if alpha <= 5:
                continue
            age = self.environment.popup_lifetime - remaining
            drift_y = age * 30
            draw_y = y - 15 - drift_y

            font = painter.font()
            # Scale down dynamically but keep a readable floor
            font.setPointSize(max(6, int(font_size * 0.7)))
            font.setBold(True)
            painter.setFont(font)

            # Shadow for readability
            painter.setPen(QColor(0, 0, 0, alpha))
            painter.drawText(QPointF(x - 19, draw_y + 1), text)

            # Main text
            painter.setPen(QColor(r, g, b, alpha))
            painter.drawText(QPointF(x - 20, draw_y), text)

    # -------------------------------------------------------- light source
    def _draw_light_source(self, painter, t):
        """Only called if light_enabled is True."""
        lx, ly = self.environment.light_source
        intensity = getattr(self.environment, 'light_intensity', 1.0)
        light_color = getattr(self.environment, 'light_color', (255, 255, 200))
        lc = QColor(*light_color)

        corona_r = 18 + 5 * math.sin(t * 2.5)
        corona_grad = QRadialGradient(lx, ly, corona_r)
        corona_grad.setColorAt(0.0, QColor(lc.red(), lc.green(), lc.blue(), int(120 * intensity)))
        corona_grad.setColorAt(1.0, QColor(lc.red(), lc.green(), lc.blue(), 0))
        painter.setBrush(QBrush(corona_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(lx - corona_r, ly - corona_r, corona_r * 2, corona_r * 2))

        ray_color = QColor(lc.red(), lc.green(), lc.blue(), int(140 * intensity))
        painter.setPen(QPen(ray_color, 1.2))
        for i in range(8):
            ra = i * (math.pi * 2 / 8) + t * 0.6
            inner = 6.0
            outer = 13.0 + 3 * math.sin(t * 3 + i)
            painter.drawLine(
                QPointF(lx + math.cos(ra) * inner, ly + math.sin(ra) * inner),
                QPointF(lx + math.cos(ra) * outer, ly + math.sin(ra) * outer))

        core_r = 5.0 + 1.5 * math.sin(t * 4)
        core_grad = QRadialGradient(lx - 1.5, ly - 1.5, core_r)
        core_grad.setColorAt(0.0, Qt.white)
        core_grad.setColorAt(0.5, lc)
        core_grad.setColorAt(1.0, QColor(lc.red(), lc.green(), lc.blue(), 0))
        painter.setBrush(QBrush(core_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(lx - core_r, ly - core_r, core_r * 2, core_r * 2))

    # ---------------------------------------------------------------- public API
    def update_scene(self):
        self.cell_items = {cell.id: True for cell in self.environment.cells}
        self.update()

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, event):
        wx, wy = self._screen_to_world(event.x(), event.y())

        if self.move_light_mode and event.button() == Qt.LeftButton:
            ex, ey = self.environment.center
            if math.hypot(wx - ex, wy - ey) <= self.environment.radius:
                self.environment.light_source = (wx, wy)
                self.update()
            return

        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._last_mouse = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.LeftButton:
            if self.draw_food_mode:
                self.environment.food.append((wx, wy))
                self.update_scene()
                return
            if self.erase_food_mode:
                for food in self.environment.food[:]:
                    if math.hypot(wx - food[0], wy - food[1]) < 6:
                        self.environment.food.remove(food)
                        self.update_scene()
                        break
                return

            best, best_dist = None, float('inf')
            for cell in self.environment.cells:
                dist = math.hypot(wx - cell.position[0], wy - cell.position[1])
                cell_r = max(cell._body_size / 2, 4)
                if dist < cell_r and dist < best_dist:
                    best_dist = dist
                    best = cell
            self.selected_cell = best
            self.cell_selected.emit(best)
            self.update()

    def mouseMoveEvent(self, event):
        if self._panning and self._last_mouse is not None:
            delta = event.pos() - self._last_mouse
            self._pan_offset += QPointF(delta.x(), delta.y())
            self._last_mouse = event.pos()
            self.update()
            return
        if self.move_light_mode and event.buttons() & Qt.LeftButton:
            wx, wy = self._screen_to_world(event.x(), event.y())
            ex, ey = self.environment.center
            if math.hypot(wx - ex, wy - ey) <= self.environment.radius:
                self.environment.light_source = (wx, wy)
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom = max(0.15, min(12.0, self._zoom * factor))
        self.update()

    def toggle_draw_food_mode(self):
        self.draw_food_mode = self.draw_food_button.isChecked()
        if self.draw_food_mode:
            self.erase_food_button.setChecked(False)
            self.erase_food_mode = False

    def toggle_erase_food_mode(self):
        self.erase_food_mode = self.erase_food_button.isChecked()
        if self.erase_food_mode:
            self.draw_food_button.setChecked(False)
            self.draw_food_mode = False

    def zoom_in(self):
        self._zoom = min(12.0, self._zoom * 1.2)
        self.update()

    def zoom_out(self):
        self._zoom = max(0.15, self._zoom / 1.2)
        self.update()

    def scroll(self, dx, dy):
        self._pan_offset += QPointF(dx, dy)
        self.update()