import random
import math
import numpy as np
from cell import Cell, Genome, Phagocyte, Photocyte


class SpatialGrid:
    def __init__(self, cell_size=64):
        self.cell_size = cell_size
        self._grid = {}

    def clear(self):
        self._grid.clear()

    def insert(self, obj, x, y):
        key = (int(x // self.cell_size), int(y // self.cell_size))
        bucket = self._grid.get(key)
        if bucket is None:
            self._grid[key] = [obj]
        else:
            bucket.append(obj)

    def query(self, x, y, radius):
        cs = self.cell_size
        gx0 = int((x - radius) // cs)
        gx1 = int((x + radius) // cs)
        gy0 = int((y - radius) // cs)
        gy1 = int((y + radius) // cs)
        result = []
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                bucket = self._grid.get((gx, gy))
                if bucket:
                    result.extend(bucket)
        return result

    def query_aabb(self, x, y, w, h):
        cs = self.cell_size
        gx0 = int(x // cs)
        gx1 = int((x + w) // cs)
        gy0 = int(y // cs)
        gy1 = int((y + h) // cs)
        result = []
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                bucket = self._grid.get((gx, gy))
                if bucket:
                    result.extend(bucket)
        return result


Quadtree = SpatialGrid


class Environment:
    def __init__(self, radius):
        self.radius = radius
        self.center = (radius, radius)
        self.cells = []
        self.food = []
        self.food_generation_rate = 5
        self.max_food = 600
        self.current_time = 0
        self.starvation_threshold = 1000
        self.wrap_around = False
        self.quadtree_boundary = (0, 0, radius * 2, radius * 2)

        self.light_source = (radius, radius)
        self.light_color = (255, 255, 200)
        self.light_intensity = 1.0
        self.light_enabled = True

        self._spatial_grid = SpatialGrid(cell_size=32)
        self._collision_frame = False

        # Death markers: each is (x, y, cell_size, remaining_time)
        self.death_markers = []

    def add_death_marker(self, x, y, cell_size, duration=1.2):
        """Add a temporary 'DIED' marker scaled to cell size."""
        self.death_markers.append((x, y, cell_size, duration))

    def update_death_markers(self, dt):
        """Update marker lifetimes and remove expired ones."""
        self.death_markers = [(x, y, sz, t - dt) for (x, y, sz, t) in self.death_markers if t - dt > 0]

    def add_cell(self, cell):
        self.cells.append(cell)

    def remove_cell(self, cell):
        if cell in self.cells:
            self.cells.remove(cell)

    def update(self, dt, generate_food=True, allow_merge=False):
        self.current_time += dt

        # Update death markers (they fade over time)
        self.update_death_markers(dt)

        grid = self._spatial_grid
        grid.clear()
        for cell in self.cells:
            grid.insert(cell, float(cell.position[0]), float(cell.position[1]))

        new_children = []
        dead_set = set()

        for cell in self.cells[:]:
            if id(cell) in dead_set:
                continue
            cell.update(self, dt)
            if cell not in self.cells:
                dead_set.add(id(cell))
                continue
            if cell.energy <= 0.72 or cell.age >= cell.MAX_AGE:
                cell.die(self)
                dead_set.add(id(cell))
            elif cell.can_divide():
                new_cell = cell.divide()
                new_children.append(new_cell)

        for child in new_children:
            self.add_cell(child)

        while len(self.cells) > 3000:
            if not self.cells:
                break
            weakest = min(self.cells, key=lambda c: c.energy)
            weakest.die(self)

        grid.clear()
        for cell in self.cells:
            grid.insert(cell, float(cell.position[0]), float(cell.position[1]))

        self._collision_frame = not self._collision_frame
        if self._collision_frame:
            alive_set = set(self.cells)
            cells_snapshot = self.cells[:]
            for cell1 in cells_snapshot:
                if cell1 not in alive_set:
                    continue
                id1 = id(cell1)
                s1 = cell1._cached_size
                px1 = float(cell1.position[0])
                py1 = float(cell1.position[1])
                search_r = s1 + 32
                nearby = grid.query(px1, py1, search_r)
                for cell2 in nearby:
                    id2 = id(cell2)
                    if id2 <= id1 or cell2 not in alive_set:
                        continue
                    dx = px1 - float(cell2.position[0])
                    dy = py1 - float(cell2.position[1])
                    dist = math.hypot(dx, dy)
                    min_dist = (s1 + cell2._cached_size) * 0.5
                    if dist >= min_dist:
                        continue

                    t1 = cell1.type
                    t2 = cell2.type
                    if allow_merge and t1 == t2:
                        self.merge_cells(cell1, cell2)
                        alive_set.discard(cell1)
                        alive_set.discard(cell2)
                        break
                    elif t1 == "Phagocyte" and cell1.can_consume(cell2):
                        cell1.consume(cell2, self)
                        alive_set.discard(cell2)
                        self.remove_cell(cell2)
                    elif t2 == "Phagocyte" and cell2.can_consume(cell1):
                        cell2.consume(cell1, self)
                        alive_set.discard(cell1)
                        self.remove_cell(cell1)
                        break
                    else:
                        overlap = min_dist - dist
                        inv_d = 1.0 / max(dist, 0.001)
                        nx = dx * inv_d
                        ny = dy * inv_d
                        half = overlap * 0.5
                        cell1.position[0] -= nx * half
                        cell1.position[1] -= ny * half
                        cell2.position[0] += nx * half
                        cell2.position[1] += ny * half

        if generate_food:
            food_to_generate = self.food_generation_rate * dt
            cx, cy = self.center
            while food_to_generate > 0 and len(self.food) < self.max_food:
                if random.random() < food_to_generate:
                    angle = random.uniform(0, 2 * math.pi)
                    distance = random.uniform(0, self.radius)
                    self.food.append((cx + math.cos(angle) * distance,
                                      cy + math.sin(angle) * distance))
                food_to_generate -= 1

        if self.food and self.cells:
            self._consume_food_numpy()

    def _consume_food_numpy(self):
        n_food = len(self.food)
        n_cells = len(self.cells)
        if n_food == 0 or n_cells == 0:
            return

        food_arr = np.empty((n_food, 2), dtype=float)
        for i, (fx, fy) in enumerate(self.food):
            food_arr[i, 0] = fx
            food_arr[i, 1] = fy

        cell_x = np.empty(n_cells, dtype=float)
        cell_y = np.empty(n_cells, dtype=float)
        cell_r = np.empty(n_cells, dtype=float)
        for i, c in enumerate(self.cells):
            cell_x[i] = float(c.position[0])
            cell_y[i] = float(c.position[1])
            cell_r[i] = c._cached_size + 1.5

        dx = cell_x[:, None] - food_arr[:, 0]
        dy = cell_y[:, None] - food_arr[:, 1]
        dist_sq = dx * dx + dy * dy
        r_sq = (cell_r ** 2)[:, None]
        eaten_matrix = dist_sq < r_sq
        food_eaten = eaten_matrix.any(axis=0)

        if not food_eaten.any():
            return

        n_eaten_per_cell = eaten_matrix[:, food_eaten].sum(axis=1)
        for i, cell in enumerate(self.cells):
            n = int(n_eaten_per_cell[i])
            if n > 0:
                for _ in range(n):
                    cell.eat_food(self)

        surviving = food_arr[~food_eaten]
        self.food = [tuple(surviving[i]) for i in range(len(surviving))]

    def merge_cells(self, cell1, cell2):
        new_genome = Genome()
        for gene in new_genome.genes:
            if isinstance(new_genome.genes[gene], bool):
                new_genome.genes[gene] = (cell1.genome.genes[gene] or cell2.genome.genes[gene])
            elif isinstance(new_genome.genes[gene], tuple):
                new_genome.genes[gene] = tuple(
                    (a + b) / 2 for a, b in zip(cell1.genome.genes[gene], cell2.genome.genes[gene]))
            else:
                new_genome.genes[gene] = (cell1.genome.genes[gene] + cell2.genome.genes[gene]) / 2
        new_genome.genes['size'] = cell1.genome.genes['size'] + cell2.genome.genes['size']
        new_pos = ((cell1.position[0] + cell2.position[0]) / 2,
                   (cell1.position[1] + cell2.position[1]) / 2)
        new_cell = Cell(new_genome, new_pos)
        new_cell.energy = cell1.energy + cell2.energy
        new_cell.nitrogen_reserve = (cell1.nitrogen_reserve + cell2.nitrogen_reserve) / 2
        new_cell.type = cell1.type
        self.remove_cell(cell1)
        self.remove_cell(cell2)
        self.add_cell(new_cell)

    def get_state(self):
        return {
            'cells': [(cell.position, cell.genome.genes['size'],
                       cell.genome.genes['color'],
                       cell.genome.genes.get('motility_mode', 1), cell.angle)
                      for cell in self.cells],
            'food': self.food
        }