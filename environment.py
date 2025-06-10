import random
import math
from cell import Cell, Genome, PredatorCell, PhotosyntheticCell, DefensiveCell, ReproductiveCell

# A Quadtree implementation for efficient collision detection
class Quadtree:
    def __init__(self, boundary, capacity):
        self.boundary = boundary  # A tuple: (x, y, width, height)
        self.capacity = capacity  # Max number of points in a node
        self.cells = []
        self.divided = False

    def subdivide(self):
        x, y, w, h = self.boundary
        half_w, half_h = w / 2, h / 2
        
        # Create four sub-quadrants
        self.ne = Quadtree((x + half_w, y, half_w, half_h), self.capacity)
        self.nw = Quadtree((x, y, half_w, half_h), self.capacity)
        self.se = Quadtree((x + half_w, y + half_h, half_w, half_h), self.capacity)
        self.sw = Quadtree((x, y + half_h, half_w, half_h), self.capacity)
        
        self.divided = True

    def insert(self, cell):
        # If cell is not in the boundary of this quadtree, do not insert it
        if not self.contains(cell.position):
            return False

        if len(self.cells) < self.capacity:
            self.cells.append(cell)
            return True
        else:
            if not self.divided:
                self.subdivide()

            # Insert into the correct quadrant
            if self.ne.insert(cell): return True
            if self.nw.insert(cell): return True
            if self.se.insert(cell): return True
            if self.sw.insert(cell): return True
        return False

    def query(self, aabb, found_cells=None):
        if found_cells is None:
            found_cells = []

        if not self.intersects(aabb):
            return found_cells

        for cell in self.cells:
            if self.aabb_contains(aabb, cell.position):
                found_cells.append(cell)

        if self.divided:
            self.nw.query(aabb, found_cells)
            self.ne.query(aabb, found_cells)
            self.sw.query(aabb, found_cells)
            self.se.query(aabb, found_cells)
            
        return found_cells

    def contains(self, pos):
        x, y, w, h = self.boundary
        return (pos[0] >= x and pos[0] < x + w and
                pos[1] >= y and pos[1] < y + h)

    def aabb_contains(self, aabb, pos):
        x, y, w, h = aabb
        return (pos[0] >= x and pos[0] < x + w and
                pos[1] >= y and pos[1] < y + h)

    def intersects(self, aabb):
        b_x, b_y, b_w, b_h = self.boundary
        a_x, a_y, a_w, a_h = aabb
        return not (a_x > b_x + b_w or
                    a_x + a_w < b_x or
                    a_y > b_y + b_h or
                    a_y + a_h < b_y)

class Environment:
    def __init__(self, radius):
        self.radius = radius
        self.center = (radius, radius)
        self.cells = []
        self.food = []
        self.food_generation_rate = 5
        self.max_food = 1000
        self.current_time = 0  # Track the current time
        self.starvation_threshold = 1000  # Default value 1000
        self.wrap_around = False  # New attribute to control wrapping behavior
        self.light_source = (radius, radius)  # Center of the environment as a light source
        self.quadtree_boundary = (0, 0, radius * 2, radius * 2)

    def add_cell(self, cell):
        self.cells.append(cell)

    def remove_cell(self, cell):
        if cell in self.cells:
            self.cells.remove(cell)

    def update(self, dt, generate_food=True, allow_merge=False):
        self.current_time += dt
        
        # Update cells and handle division/death
        for cell in self.cells[:]:
            cell.update(self, dt)
            if cell.energy <= 0.72 or cell.nitrogen_reserve <= 0.1 or cell.age >= 240:
                cell.die(self)
            elif cell.can_divide():
                new_cell = cell.divide()
                self.add_cell(new_cell)
            elif cell.genome.genes['size'] >= cell.max_size:
                new_cell = cell.divide()
                self.add_cell(new_cell)

        # Build a new quadtree for the current frame
        qtree = Quadtree(self.quadtree_boundary, 4)
        for cell in self.cells:
            qtree.insert(cell)
        
        # Efficient collision and interaction handling using the quadtree
        for cell1 in self.cells:
            # Define an Area of Interest (AoI) around cell1 to query the quadtree
            size1 = cell1.genome.genes['size']
            aoi = (cell1.position[0] - size1, cell1.position[1] - size1, size1 * 2, size1 * 2)
            
            # Get only the cells that are potentially colliding
            potential_colliders = qtree.query(aoi)

            for cell2 in potential_colliders:
                # Ensure we are not checking a cell against itself
                if cell1 is cell2:
                    continue

                if cell1.check_collision(cell2):
                    # Handle different types of interactions
                    if allow_merge and cell1.type == cell2.type and cell1 in self.cells and cell2 in self.cells:
                        self.merge_cells(cell1, cell2)
                    elif isinstance(cell1, PredatorCell) and cell1.can_consume(cell2):
                        cell1.consume(cell2, self)
                        if cell2 in self.cells: self.remove_cell(cell2)
                    elif isinstance(cell2, PredatorCell) and cell2.can_consume(cell1):
                        cell2.consume(cell1, self)
                        if cell1 in self.cells: self.remove_cell(cell1)
                    else: # Default collision response
                        cell1.resolve_collision(cell2)

        if generate_food:
            food_to_generate = self.food_generation_rate * dt
            while food_to_generate > 0 and len(self.food) < self.max_food:
                if random.random() < food_to_generate:
                    angle = random.uniform(0, 2 * math.pi)
                    distance = random.uniform(0, self.radius)
                    x = self.center[0] + math.cos(angle) * distance
                    y = self.center[1] + math.sin(angle) * distance
                    self.food.append((x, y))
                food_to_generate -= 1

        for cell in self.cells:
            for food in self.food[:]:
                distance = math.sqrt((cell.position[0] - food[0]) ** 2 + (cell.position[1] - food[1]) ** 2)
                if distance < cell.genome.genes['size']:
                    cell.energy += 5
                    cell.last_eaten = self.current_time  # Update the last eaten time
                    self.food.remove(food)

        # Update specific behaviors for different cell types
        for cell in self.cells:
            if isinstance(cell, PhotosyntheticCell):
                cell.photosynthesize(self, dt)
            elif isinstance(cell, PredatorCell):
                cell.hunt(self)
            elif isinstance(cell, DefensiveCell):
                cell.defend(self)
            elif isinstance(cell, ReproductiveCell):
                cell.reproduce(self)

    def merge_cells(self, cell1, cell2):
        # Create a new cell with combined properties
        new_genome = Genome()
        for gene in new_genome.genes:
            if isinstance(new_genome.genes[gene], bool):
                new_genome.genes[gene] = cell1.genome.genes[gene] or cell2.genome.genes[gene]
            elif isinstance(new_genome.genes[gene], tuple):
                new_genome.genes[gene] = tuple((a + b) / 2 for a, b in zip(cell1.genome.genes[gene], cell2.genome.genes[gene]))
            else:
                new_genome.genes[gene] = (cell1.genome.genes[gene] + cell2.genome.genes[gene]) / 2

        new_genome.genes['size'] = cell1.genome.genes['size'] + cell2.genome.genes['size']
        
        new_position = ((cell1.position[0] + cell2.position[0]) / 2,
                        (cell1.position[1] + cell2.position[1]) / 2)
        new_cell = Cell(new_genome, new_position)
        new_cell.energy = cell1.energy + cell2.energy
        new_cell.nitrogen_reserve = (cell1.nitrogen_reserve + cell2.nitrogen_reserve) / 2
        new_cell.type = cell1.type
        
        self.remove_cell(cell1)
        self.remove_cell(cell2)
        self.add_cell(new_cell)

    def get_state(self):
        return {
            'cells': [(cell.position, cell.genome.genes['size'], cell.genome.genes['color'],
                       cell.genome.genes['has_tail'], cell.angle) for cell in self.cells],
            'food': self.food
        }