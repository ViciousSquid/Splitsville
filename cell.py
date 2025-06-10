import random
import math
import uuid
import numpy as np

class Genome:
    def __init__(self, genes=None, never_consume=False):
        self.genes = genes or {
            'size': random.uniform(5, 20),
            'speed': random.uniform(0.5, 2.0),
            'energy_efficiency': random.uniform(0.5, 1.5),
            'division_threshold': random.uniform(20, 40),
            'color': (random.random(), random.random(), random.random()),
            'has_tail': random.choice([True, False]),
            'can_consume': random.choice([True, False]),
            'consumption_size_ratio': random.uniform(1.2, 2.0),
            'nitrogen_reserve': random.uniform(0.2, 0.5),
            'adhesin': random.choice([True, False]),
            'radiation_sensitivity': random.uniform(0.1, 0.5)
        }
        self.dna = self.encode_genes()
        self.never_consume = never_consume

    def encode_genes(self):
        dna = 0
        dna |= (int(self.genes['size'] * 10) & 0xFF) << 24
        dna |= (int(self.genes['speed'] * 10) & 0xFF) << 16
        dna |= (int(self.genes['energy_efficiency'] * 10) & 0xFF) << 8
        dna |= (int(self.genes['division_threshold'] * 10) & 0xFF)
        dna |= (int(self.genes['consumption_size_ratio'] * 10) & 0xFF) << 32
        dna |= (int(self.genes['color'][0] * 255) & 0xFF) << 40
        dna |= (int(self.genes['color'][1] * 255) & 0xFF) << 48
        dna |= (int(self.genes['color'][2] * 255) & 0xFF) << 56
        dna |= (int(self.genes['has_tail']) & 0x1) << 64
        dna |= (int(self.genes['can_consume']) & 0x1) << 65
        dna |= (int(self.genes['nitrogen_reserve'] * 10) & 0xFF) << 72
        dna |= (int(self.genes['adhesin']) & 0x1) << 80
        dna |= (int(self.genes['radiation_sensitivity'] * 10) & 0xFF) << 88
        return dna

    def decode_genes(self, dna):
        self.genes['size'] = ((dna >> 24) & 0xFF) / 10.0
        self.genes['speed'] = ((dna >> 16) & 0xFF) / 10.0
        self.genes['energy_efficiency'] = ((dna >> 8) & 0xFF) / 10.0
        self.genes['division_threshold'] = (dna & 0xFF) / 10.0
        self.genes['consumption_size_ratio'] = ((dna >> 32) & 0xFF) / 10.0
        self.genes['color'] = (
            ((dna >> 40) & 0xFF) / 255.0,
            ((dna >> 48) & 0xFF) / 255.0,
            ((dna >> 56) & 0xFF) / 255.0
        )
        self.genes['has_tail'] = (dna >> 64) & 0x1
        self.genes['can_consume'] = (dna >> 65) & 0x1
        self.genes['nitrogen_reserve'] = ((dna >> 72) & 0xFF) / 10.0
        self.genes['adhesin'] = (dna >> 80) & 0x1
        self.genes['radiation_sensitivity'] = ((dna >> 88) & 0xFF) / 10.0

    def mutate(self, mutation_rate=0.1):
        for gene in self.genes:
            if random.random() < mutation_rate:
                if isinstance(self.genes[gene], bool):
                    if gene == 'can_consume' and self.never_consume:
                        continue  # Skip mutation if never_consume is enabled
                    self.genes[gene] = not self.genes[gene]
                elif isinstance(self.genes[gene], tuple):
                    self.genes[gene] = tuple(min(1, max(0, x + random.uniform(-0.1, 0.1))) for x in self.genes[gene])
                else:
                    self.genes[gene] *= random.uniform(0.8, 1.2)

    def copy(self):
        return Genome(self.genes.copy(), self.never_consume)

class Cell:
    def __init__(self, genome, position, dna=None):
        self.genome = genome
        self.position = np.array(position, dtype=float) # Use a numpy array for position
        self.energy = 20
        self.age = 0
        self.dna = dna or self.genome.encode_genes()
        self.angle = random.uniform(0, 2 * math.pi)
        self.type = "Cell"
        self.nitrogen_reserve = self.genome.genes['nitrogen_reserve']
        self.adhesin = self.genome.genes['adhesin']
        self.radiation_sensitivity = self.genome.genes['radiation_sensitivity']
        self.last_eaten = 0  # Track the last time the cell ate
        self.adhered_cells = []  # List to store adhered cells
        self.max_size = 32  # Maximum size a cell can reach

    def update(self, environment, dt):
        self.age += dt
        self.energy += self.genome.genes['energy_efficiency'] * dt

        # Energy consumption based on size
        energy_consumption = self.genome.genes['size'] * 0.01 * dt
        self.energy -= energy_consumption

        # Increase energy consumption for larger cells
        energy_consumption_movement = self.genome.genes['size'] * 0.02 * dt  # Larger cells consume more energy to move
        self.energy -= energy_consumption_movement

        # Check if the cell has reached the maximum size and divide if necessary
        if self.genome.genes['size'] >= self.max_size:
            self.divide()

        self.nitrogen_reserve += 0.01 * dt

        self.energy -= self.radiation_sensitivity * dt

        # Movement calculation using numpy
        if self.genome.genes['has_tail']:
            speed = self.genome.genes['speed']
            velocity = np.array([math.cos(self.angle), math.sin(self.angle)]) * speed * dt
        else:
            velocity = np.random.uniform(-1, 1, 2) * self.genome.genes['speed'] * dt

        self.position += velocity

        # Calculate energy loss due to movement
        distance_moved = np.linalg.norm(velocity)
        energy_loss = distance_moved * 0.1  # Adjust the multiplier as needed
        self.energy -= energy_loss

        self.resolve_boundary_collision(environment)

        if self.energy <= 0:
            self.genome.genes['color'] = (0.5, 0.5, 0.5)  # Turn grey
            self.die(environment)

        # Check for starvation
        if environment.current_time - self.last_eaten > environment.starvation_threshold:
            self.die(environment)

        # Scale size based on energy
        self.genome.genes['size'] = max(5, min(128, self.energy * 0.5))

        # Cap energy at 100
        self.energy = min(100, self.energy)

        # Energy sharing with adhered cells
        if self.adhesin and self.adhered_cells:
            total_energy = self.energy + sum(cell.energy for cell in self.adhered_cells)
            avg_energy = total_energy / (len(self.adhered_cells) + 1)
            self.energy = avg_energy
            for cell in self.adhered_cells:
                cell.energy = avg_energy

    def can_divide(self):
        return self.age >= 20 and self.energy > self.genome.genes['division_threshold'] and self.nitrogen_reserve >= 0.2

    def divide(self):
        child_genome = self.genome.copy()
        child_genome.mutate()
        
        # Child position is created using numpy array now
        offset = np.array([random.choice([-8, 8]), random.choice([-8, 8])])
        child_position = self.position + offset
        
        child_dna = (self.dna & 0xFFFF0000) | (random.randint(0, 65535) & 0x0000FFFF)
        child = Cell(child_genome, child_position, child_dna)
        child.type = self.type
        self.energy /= 2
        child.energy = self.energy
        self.nitrogen_reserve /= 2
        child.nitrogen_reserve = self.nitrogen_reserve

        # Ensure the child cells are smaller than the parent
        self.genome.genes['size'] /= 2
        child.genome.genes['size'] = self.genome.genes['size']

        return child

    def can_consume(self, other_cell):
        # Rule 1: Phagocytes can consume Bacteria
        if self.type == "Phagocyte" and other_cell.type == "Bacteria":
            return True
            
        # Rule 2: General size-based consumption (if not disabled)
        if not self.genome.genes['can_consume']:
            return False
        size_ratio = self.genome.genes['size'] / other_cell.genome.genes['size']
        return size_ratio > self.genome.genes['consumption_size_ratio']

    def consume(self, other_cell, environment):
        self.energy += other_cell.energy
        self.nitrogen_reserve += other_cell.nitrogen_reserve
        
        # Increase size by 10% of the consumed cell's size when consuming another cell
        self.genome.genes['size'] += other_cell.genome.genes['size'] * 0.1
        
        # Cap size at 32 to prevent indefinite growth
        self.genome.genes['size'] = min(self.genome.genes['size'], 32)
        
        self.last_eaten = environment.current_time  # Update the last eaten time

        # Cap energy at 100
        self.energy = min(100, self.energy)

    def die(self, environment):
        distance = np.linalg.norm(self.position - environment.center)
        if distance <= environment.radius:
            environment.food.append(tuple(self.position))
        if self in environment.cells:
            environment.remove_cell(self)

    def adhere_to(self, other_cell):
        if self.adhesin and other_cell.adhesin and other_cell not in self.adhered_cells:
            self.adhered_cells.append(other_cell)
            other_cell.adhered_cells.append(self)

    def separate_from(self, other_cell):
        if other_cell in self.adhered_cells:
            self.adhered_cells.remove(other_cell)
            other_cell.adhered_cells.remove(self)

    def check_collision(self, other_cell):
        distance = np.linalg.norm(self.position - other_cell.position)
        return distance < (self.genome.genes['size'] + other_cell.genome.genes['size']) / 2

    def resolve_collision(self, other_cell):
        distance = np.linalg.norm(self.position - other_cell.position)
        overlap = (self.genome.genes['size'] + other_cell.genome.genes['size']) / 2 - distance
        if overlap > 0:
            # Vector from self to other_cell, normalized
            direction = (other_cell.position - self.position) / distance
            self.position -= direction * overlap / 2
            other_cell.position += direction * overlap / 2

    def resolve_boundary_collision(self, environment):
        center_vec = np.array(environment.center)
        distance_vec = self.position - center_vec
        distance = np.linalg.norm(distance_vec)

        if distance > environment.radius - self.genome.genes['size'] / 2:
            if environment.wrap_around:
                # Wrap around using numpy vector operations
                self.position = (self.position - center_vec) % (2 * environment.radius) + center_vec - environment.radius
            else:
                # Bounce back from the boundary
                direction = distance_vec / distance
                self.position = center_vec + direction * (environment.radius - self.genome.genes['size'] / 2)


class Bacteria(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Bacteria"
        self.genome.genes['size'] *= 0.5
        self.genome.genes['speed'] *= 1.5
        self.genome.genes['energy_efficiency'] *= 0.8

    def update(self, environment, dt):
        super().update(environment, dt)
        if random.random() < 0.001:
            self.energy = self.genome.genes['division_threshold']

        # Cap energy at 100
        self.energy = min(100, self.energy)

class Phagocyte(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Phagocyte"

    def update(self, environment, dt):
        super().update(environment, dt)

class Photocyte(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Photocyte"

    def update(self, environment, dt):
        super().update(environment, dt)

class PredatorCell(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Predator"
        self.genome.genes['speed'] *= 1.5  # Predators are faster
        self.genome.genes['can_consume'] = True  # Predators can consume other cells
        self.hunting_efficiency = random.uniform(0.5, 1.5)  # Efficiency in hunting

    def update(self, environment, dt):
        super().update(environment, dt)
        self.hunt(environment)

    def hunt(self, environment):
        for cell in environment.cells:
            if cell != self and self.can_consume(cell):
                distance = np.linalg.norm(self.position - cell.position)
                if distance < self.genome.genes['size']:
                    self.consume(cell, environment)
                    break

class PhotosyntheticCell(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Photosynthetic"
        self.light_sensitivity = random.uniform(0.5, 1.5)  # Sensitivity to light

    def update(self, environment, dt):
        super().update(environment, dt)
        self.photosynthesize(environment, dt)

    def photosynthesize(self, environment, dt):
        # Simulate photosynthesis by converting light into energy
        light_energy = self.light_sensitivity * dt
        self.energy += light_energy
        self.energy = min(100, self.energy)  # Cap energy at 100

class DefensiveCell(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Defensive"
        self.defense_strength = random.uniform(0.5, 1.5)  # Strength of defense

    def update(self, environment, dt):
        super().update(environment, dt)
        self.defend(environment)

    def defend(self, environment):
        # Simulate defense by protecting nearby cells
        for cell in environment.cells:
            if cell != self and self.check_collision(cell):
                cell.energy += self.defense_strength * dt
                cell.energy = min(100, cell.energy)  # Cap energy at 100

class ReproductiveCell(Cell):
    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Reproductive"
        self.reproduction_rate = random.uniform(0.5, 1.5)  # Rate of reproduction

    def update(self, environment, dt):
        super().update(environment, dt)
        self.reproduce(environment)

    def reproduce(self, environment):
        # Simulate reproduction by dividing more frequently
        if self.can_divide():
            for _ in range(int(self.reproduction_rate)):
                new_cell = self.divide()
                if new_cell:
                    environment.add_cell(new_cell)