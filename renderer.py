from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsEllipseItem, QGraphicsPolygonItem, QToolButton, QVBoxLayout, QWidget, QLabel
from PyQt5.QtGui import QColor, QPen, QPainter, QPolygonF
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
import math

class CellItem(QGraphicsEllipseItem):
    def __init__(self, cell, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cell = cell
        self.setFlag(QGraphicsEllipseItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsEllipseItem.ItemIsMovable, True)

class Renderer(QGraphicsView):
    cell_selected = pyqtSignal(object)

    def __init__(self, environment, parent=None):
        super().__init__(parent)
        self.environment = environment
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.selected_cell = None
        self.draw_food_mode = False
        self.erase_food_mode = False

        self.draw_food_button = QToolButton()
        self.draw_food_button.setText("Draw Food")
        self.draw_food_button.setCheckable(True)
        self.draw_food_button.clicked.connect(self.toggle_draw_food_mode)

        self.erase_food_button = QToolButton()
        self.erase_food_button.setText("Erase Food")
        self.erase_food_button.setCheckable(True)
        self.erase_food_button.clicked.connect(self.toggle_erase_food_mode)

        self.tool_layout = QVBoxLayout()
        self.tool_layout.addWidget(self.draw_food_button)
        self.tool_layout.addWidget(self.erase_food_button)

        self.tool_widget = QWidget()
        self.tool_widget.setLayout(self.tool_layout)
        self.tool_widget.setFixedWidth(100)

        self.energy_label = QLabel()
        self.tool_layout.addWidget(self.energy_label)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def render(self):
        # Store the current transformation
        current_transform = self.transform()

        self.scene.clear()

        boundary = QGraphicsEllipseItem(0, 0, self.environment.radius * 2, self.environment.radius * 2)
        boundary.setPen(QPen(Qt.black, 2))
        self.scene.addItem(boundary)

        for cell in self.environment.cells:
            x, y = cell.position
            size = max(cell.genome.genes['size'], 15)
            color = QColor.fromRgbF(*cell.genome.genes['color'])

            if cell.adhesin:
                adhesin_size = size + 20
                adhesin_color = QColor(color)
                adhesin_color.setAlpha(100)
                adhesin_item = QGraphicsEllipseItem(x - adhesin_size / 2, y - adhesin_size / 2, adhesin_size, adhesin_size)
                adhesin_item.setBrush(adhesin_color)
                adhesin_item.setPen(QPen(Qt.NoPen))
                self.scene.addItem(adhesin_item)

            cell_item = CellItem(cell, x - size / 2, y - size / 2, size, size)
            cell_item.setBrush(color)
            cell_item.setPen(QPen(Qt.black, 0.5))
            self.scene.addItem(cell_item)

            if cell.genome.genes['has_tail']:
                tail_length = size * 1.5
                tail_end_x = x + math.cos(cell.angle) * tail_length
                tail_end_y = y + math.sin(cell.angle) * tail_length
                tail = QGraphicsPolygonItem(QPolygonF([
                    QPointF(x, y),
                    QPointF(x - size / 4, y - size / 4),
                    QPointF(tail_end_x, tail_end_y),
                    QPointF(x + size / 4, y - size / 4)
                ]))
                tail.setBrush(color)
                self.scene.addItem(tail)

        for food in self.environment.food:
            x, y = food
            food_item = QGraphicsEllipseItem(x - 1, y - 1, 2, 2)
            food_item.setBrush(Qt.green)
            self.scene.addItem(food_item)

        if self.selected_cell:
            self.highlight_cell(self.selected_cell)
            self.energy_label.setText(f"Energy: {self.selected_cell.energy:.2f}")

        # The collision resolution logic has been moved to environment.py for efficiency.

        # Restore the transformation
        self.setTransform(current_transform)

    def highlight_cell(self, cell):
        for item in self.scene.items():
            if isinstance(item, CellItem) and item.cell == cell:
                pen = QPen(Qt.red, 3) # Changed the thickness to 3
                pen.setStyle(Qt.DashLine) # Added a dash line style for more visibility
                item.setPen(pen)
                break

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, CellItem):
                self.selected_cell = item.cell
                self.cell_selected.emit(item.cell)
                self.render()
            else:
                self.selected_cell = None
                self.cell_selected.emit(None)
                self.render()

            if self.draw_food_mode:
                pos = self.mapToScene(event.pos())
                self.environment.food.append((pos.x(), pos.y()))
                self.render()
            elif self.erase_food_mode:
                pos = self.mapToScene(event.pos())
                for food in self.environment.food[:]:
                    x, y = food
                    if math.sqrt((pos.x() - x) ** 2 + (pos.y() - y) ** 2) < 5:
                        self.environment.food.remove(food)
                        self.render()
                        break
        super().mousePressEvent(event)

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

    def itemMoved(self, item):
        pos = item.scenePos()
        distance = math.sqrt((pos.x() - self.environment.center[0]) ** 2 + (pos.y() - self.environment.center[1]) ** 2)
        if distance > self.environment.radius:
            angle = math.atan2(self.environment.center[1] - pos.y(), self.environment.center[0] - pos.x())
            new_x = self.environment.center[0] + math.cos(angle) * self.environment.radius
            new_y = self.environment.center[1] + math.sin(angle) * self.environment.radius
            item.setPos(new_x - item.cell.genome.genes['size'] / 2, new_y - item.cell.genome.genes['size'] / 2)
            item.cell.position = (new_x, new_y)
        else:
            item.cell.position = (pos.x(), pos.y())
        self.render()

    def mouseMoveEvent(self, event):
        if self.selected_cell:
            pos = self.mapToScene(event.pos())
            self.selected_cell.position = (pos.x(), pos.y())
            self.render()
        super().mouseMoveEvent(event)

    def zoom_in(self):
        self.scale(1.2, 1.2)

    def zoom_out(self):
        self.scale(1 / 1.2, 1 / 1.2)

    def scroll(self, dx, dy):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)