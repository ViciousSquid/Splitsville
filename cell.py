"""
cell.py — Biologically grounded cell simulation with Spore-like cartoon realism.

Key design principles:
  - Energy only comes from FOOD (or photosynthesis). No passive generation.
  - Physical size (_body_size) is separate from the heritable target size (genome['size']).
    Body size grows slowly over lifetime; halves on division; does NOT track energy.
  - Hungry cells actively seek food (chemotaxis).
  - Cells flee nearby predators regardless of type.
  - Division requires reaching target size AND having sufficient energy.
  - energy_efficiency controls how much energy is extracted from each food particle.
  - Motility mode: 0 = none, 1 = flagellum (tail), 2 = cilia.
    Cilia give slower speed but very fast turning.
  - Body shape: 0 = round, 1 = oval (elongated along movement direction).
"""

import random
import math
import uuid
import numpy as np


# ---------------------------------------------------------------------------
# Genome — now encodes motility_mode + body_shape, 128‑bit DNA
# ---------------------------------------------------------------------------
class Genome:
    """
    DNA layout (128 bits):
      0-7   : size *10
      8-15  : speed *10
      16-23 : energy_efficiency *10
      24-31 : division_threshold *10
      32-39 : consumption_size_ratio *10
      40-43 : motility_mode (2 bits) 0=none,1=flagellum,2=cilia
      44    : body_shape (1 bit) 0=round,1=oval
      45    : can_consume (1 bit)
      46    : adhesin (1 bit)
      47-54 : nitrogen_reserve *10
      55-62 : radiation_sensitivity *100
      63-70 : color R *255
      71-78 : color G *255
      79-86 : color B *255
      87-127: reserved (future use)
    """

    DNA_BITS = 128

    def __init__(self, genes=None, never_consume=False):
        self.genes = genes or {
            'size':                  random.uniform(8, 22),
            'speed':                 random.uniform(0.8, 2.5),
            'energy_efficiency':     random.uniform(0.6, 1.4),
            'division_threshold':    random.uniform(50, 80),
            'consumption_size_ratio': random.uniform(1.5, 2.5),
            # motility_mode: 0=none, 1=flagellum, 2=cilia
            # drastically lower flagellum chance: now only 5% have tails
            'motility_mode':         random.choices([0,1,2], weights=[65,5,30], k=1)[0],
            'body_shape':            random.choices([0,1], weights=[80,20], k=1)[0],        # round,oval
            'can_consume':           random.choice([True, False]),
            'adhesin':               random.choice([True, False]),
            'nitrogen_reserve':      random.uniform(0.3, 0.8),
            'radiation_sensitivity': random.uniform(0.02, 0.15),
            'color':                 (random.random(), random.random(), random.random()),
        }
        self.never_consume = never_consume
        self.dna = self.encode_genes()

    def encode_genes(self):
        dna = 0
        g = self.genes
        # Helper: pack value, scale, bits, shift
        def pack(val, scale, bits, shift):
            nonlocal dna
            v = int(val * scale) & ((1 << bits) - 1)
            dna |= v << shift

        pack(g['size'], 10, 8, 0)
        pack(g['speed'], 10, 8, 8)
        pack(g['energy_efficiency'], 10, 8, 16)
        pack(g['division_threshold'], 10, 8, 24)
        pack(g['consumption_size_ratio'], 10, 8, 32)

        dna |= (g['motility_mode'] & 0x3) << 40
        dna |= (g['body_shape'] & 0x1) << 44
        dna |= (1 if g['can_consume'] else 0) << 45
        dna |= (1 if g['adhesin'] else 0) << 46

        pack(g['nitrogen_reserve'], 10, 8, 47)
        pack(g['radiation_sensitivity'], 100, 8, 55)

        r, grn, b = g['color']
        pack(r, 255, 8, 63)
        pack(grn, 255, 8, 71)
        pack(b, 255, 8, 79)

        # bits 87-127 reserved
        return dna

    def decode_genes(self, dna):
        g = self.genes
        def unpack(shift, bits, scale):
            return ((dna >> shift) & ((1 << bits) - 1)) / scale

        g['size'] = unpack(0, 8, 10)
        g['speed'] = unpack(8, 8, 10)
        g['energy_efficiency'] = unpack(16, 8, 10)
        g['division_threshold'] = unpack(24, 8, 10)
        g['consumption_size_ratio'] = unpack(32, 8, 10)

        g['motility_mode'] = (dna >> 40) & 0x3
        g['body_shape'] = (dna >> 44) & 0x1
        g['can_consume'] = bool((dna >> 45) & 1)
        g['adhesin'] = bool((dna >> 46) & 1)

        g['nitrogen_reserve'] = unpack(47, 8, 10)
        g['radiation_sensitivity'] = unpack(55, 8, 100)

        g['color'] = (
            unpack(63, 8, 255),
            unpack(71, 8, 255),
            unpack(79, 8, 255),
        )

    def mutate(self, mutation_rate=0.08):
        for gene in self.genes:
            if random.random() < mutation_rate:
                val = self.genes[gene]
                if isinstance(val, bool):
                    if gene == 'can_consume' and self.never_consume:
                        continue
                    self.genes[gene] = not val
                elif isinstance(val, tuple):
                    self.genes[gene] = tuple(
                        min(1.0, max(0.0, x + random.gauss(0, 0.06)))
                        for x in val)
                elif isinstance(val, int):
                    if gene == 'motility_mode':
                        self.genes[gene] = random.choice([0,1,2])
                    elif gene == 'body_shape':
                        self.genes[gene] = random.choice([0,1])
                else:
                    self.genes[gene] *= random.uniform(0.85, 1.18)

        self.dna = self.encode_genes()

    def copy(self):
        return Genome(self.genes.copy(), self.never_consume)


# ---------------------------------------------------------------------------
# Cell — base class
# ---------------------------------------------------------------------------
class Cell:
    BASE_FOOD_ENERGY    = 30.0
    MAINTENANCE_RATE    = 0.018
    MOVE_COST           = 0.04
    GROWTH_COST         = 0.8
    GROWTH_RATE         = 1.2
    MIN_GROWTH_ENERGY   = 25.0
    FOOD_SEEK_RANGE     = 120.0
    FLEE_RANGE          = 90.0
    FOOD_SEARCH_PERIOD  = 0.4
    MAX_AGE             = 1400
    STARTING_ENERGY     = 40.0

    def __init__(self, genome, position, dna=None):
        self.id            = uuid.uuid4()
        self.genome        = genome
        self.position      = np.array(position, dtype=float)
        self.energy        = self.STARTING_ENERGY
        self.age           = 0.0
        self.dna           = dna or genome.encode_genes()
        self.angle         = random.uniform(0, 2 * math.pi)
        self.type          = "Cell"

        target             = genome.genes['size']
        self._body_size    = target * 0.4
        self._cached_size  = self._body_size

        self.nitrogen_reserve   = genome.genes['nitrogen_reserve']
        self.adhesin            = genome.genes['adhesin']
        self.radiation_sensitivity = genome.genes['radiation_sensitivity']
        self.last_eaten         = 0.0
        self.adhered_cells      = []
        self.max_size           = 40

        self.pulse_phase   = random.uniform(0, 2 * math.pi)
        self._turn_speed   = random.uniform(1.8, 3.5)

                # motion helpers – always initialise cilia phase, it only gets used by cilia cells
        self._cilia_phase = random.uniform(0, 2 * math.pi)

        motility = genome.genes.get('motility_mode', 1)
        if motility == 2:   # cilia
            self._turn_speed = random.uniform(4.0, 7.0)   # very nimble
        elif motility == 1: # flagellum
            self._turn_speed = random.uniform(1.8, 3.5)

        self._food_target      = None
        self._threat_pos       = None
        self._scan_timer       = random.uniform(0, self.FOOD_SEARCH_PERIOD)

    # ── Steering ─────────────────────────────────────────────────────────────

    def _steer_toward(self, target_pos, dt):
        dx = target_pos[0] - self.position[0]
        dy = target_pos[1] - self.position[1]
        if math.hypot(dx, dy) < 1.0:
            return
        desired = math.atan2(dy, dx)
        diff = (desired - self.angle + math.pi) % (2 * math.pi) - math.pi
        self.angle += max(-self._turn_speed * dt, min(self._turn_speed * dt, diff))

    def _steer_away(self, pos, dt):
        dx = self.position[0] - pos[0]
        dy = self.position[1] - pos[1]
        if math.hypot(dx, dy) < 1.0:
            return
        desired = math.atan2(dy, dx)
        diff = (desired - self.angle + math.pi) % (2 * math.pi) - math.pi
        self.angle += max(-self._turn_speed * 2 * dt, min(self._turn_speed * 2 * dt, diff))

    def _update_scan(self, environment):
        px, py = float(self.position[0]), float(self.position[1])
        genes = self.genome.genes

        self._threat_pos = None
        grid = getattr(environment, '_spatial_grid', None)
        if grid is not None:
            nearby_cells = grid.query(px, py, self.FLEE_RANGE)
            for c in nearby_cells:
                if c is self:
                    continue
                if c.type == "Phagocyte" and c._body_size > self._body_size * 0.8:
                    self._threat_pos = (float(c.position[0]), float(c.position[1]))
                    break

        self._food_target = None
        if self.energy < 55.0 and genes.get('motility_mode', 1) > 0:  # only if can move
            best_dist_sq = self.FOOD_SEEK_RANGE ** 2
            for (fx, fy) in environment.food:
                d2 = (fx - px) ** 2 + (fy - py) ** 2
                if d2 < best_dist_sq:
                    best_dist_sq = d2
                    self._food_target = (fx, fy)

    # ── Main update ──────────────────────────────────────────────────────────

    def update(self, environment, dt):
        self.age += dt
        genes   = self.genome.genes
        px, py  = float(self.position[0]), float(self.position[1])
        size    = self._body_size
        motility = genes.get('motility_mode', 1)

        # ── Maintenance cost ──────────────────────────────────────────────────
        self.energy -= size * self.MAINTENANCE_RATE * dt
        self.energy -= self.radiation_sensitivity * dt

        # ── Growth ────────────────────────────────────────────────────────────
        target_size = min(genes['size'], self.max_size)
        if self._body_size < target_size and self.energy > self.MIN_GROWTH_ENERGY:
            growth = min(self.GROWTH_RATE * dt, target_size - self._body_size)
            self._body_size    += growth
            self._cached_size   = self._body_size
            self.energy        -= growth * self.GROWTH_COST

        # ── Periodic scan ────────────────────────────────────────────────────
        self._scan_timer -= dt
        if self._scan_timer <= 0:
            self._scan_timer = self.FOOD_SEARCH_PERIOD + random.uniform(-0.1, 0.1)
            self._update_scan(environment)

        # ── Movement ─────────────────────────────────────────────────────────
        speed = genes['speed']
        
        # Energy‑based speed reduction (realism)
        if self.energy < 25.0:
            energy_factor = max(0.15, self.energy / 25.0)
            speed *= energy_factor

        if motility == 1:           # Flagellum
            if self._threat_pos is not None:
                self._steer_away(self._threat_pos, dt)
                speed *= 1.5
            elif self._food_target is not None:
                self._steer_toward(self._food_target, dt)
                dx = self._food_target[0] - px
                dy = self._food_target[1] - py
                if math.hypot(dx, dy) < size + 2:
                    self._food_target = None
            else:
                self.angle += random.gauss(0, 0.06)

            vx = math.cos(self.angle) * speed * dt
            vy = math.sin(self.angle) * speed * dt

        elif motility == 2:         # Cilia
            speed *= 0.7            # Slower overall
            if self._threat_pos is not None:
                self._steer_away(self._threat_pos, dt)
                speed *= 1.2
            elif self._food_target is not None:
                self._steer_toward(self._food_target, dt)
            else:
                self.angle += random.gauss(0, 0.12)

            # Cilia wiggle – small lateral oscillation
            side_angle = self.angle + math.pi/2
            cilia_wave = math.sin(self.age * 12 + self._cilia_phase) * 0.3
            vx = math.cos(self.angle) * speed * dt + math.cos(side_angle) * cilia_wave * speed * dt
            vy = math.sin(self.angle) * speed * dt + math.sin(side_angle) * cilia_wave * speed * dt

        else:                       # None – Brownian drift only
            if self._threat_pos is not None:
                self._steer_away(self._threat_pos, dt)
                vx = math.cos(self.angle) * speed * 0.5 * dt
                vy = math.sin(self.angle) * speed * 0.5 * dt
            else:
                vx = (random.random() * 2.0 - 1.0) * speed * 0.4 * dt
                vy = (random.random() * 2.0 - 1.0) * speed * 0.4 * dt

        self.position[0] += vx
        self.position[1] += vy
        self.energy -= math.hypot(vx, vy) * self.MOVE_COST

        # ── Boundary ─────────────────────────────────────────────────────────
        self.resolve_boundary_collision(environment)

        # ── Death checks ─────────────────────────────────────────────────────
        if self.energy <= 0:
            genes['color'] = (0.45, 0.45, 0.45)
            self.die(environment)
            return

        self.energy = min(100.0, self.energy)
        self.nitrogen_reserve = min(1.0, self.nitrogen_reserve + 0.003 * dt)

        # Adhesin sharing
        if self.adhesin and self.adhered_cells:
            total = self.energy + sum(c.energy for c in self.adhered_cells)
            avg   = total / (len(self.adhered_cells) + 1)
            self.energy = avg
            for c in self.adhered_cells:
                c.energy = avg

    # ── Division ──────────────────────────────────────────────────────────────

    def can_divide(self):
        genes = self.genome.genes
        return (
            self.age >= 15.0
            and self._body_size >= genes['size'] * 0.92
            and self.energy >= genes['division_threshold']
            and self.nitrogen_reserve >= 0.4
        )

    def divide(self):
        child_genome = self.genome.copy()
        child_genome.mutate()

        offset_x = random.choice([-1, 1]) * (self._body_size * 0.8 + 2)
        offset_y = random.choice([-1, 1]) * (self._body_size * 0.8 + 2)
        child_pos = (self.position[0] + offset_x, self.position[1] + offset_y)

        child_dna = (self.dna & 0xFFFF0000) | (random.randint(0, 65535) & 0x0000FFFF)
        child = type(self)(child_genome, child_pos, child_dna)
        child.type = self.type

        self._body_size     /= 2
        self._cached_size    = self._body_size
        self.energy          = self.energy * 0.5
        self.age             = 0.0

        child._body_size     = self._body_size
        child._cached_size   = child._body_size
        child.energy         = self.energy
        child.nitrogen_reserve = self.nitrogen_reserve * 0.5
        self.nitrogen_reserve *= 0.5

        return child

    # ── Consumption ──────────────────────────────────────────────────────────

    def can_consume(self, other):
        if self.genome.genes.get('never_consume', False):
            return False
        if not self.genome.genes.get('can_consume', False):
            return False
        return self._body_size / max(other._body_size, 0.5) > self.genome.genes['consumption_size_ratio']

    def consume(self, other, environment):
        gained = other.energy * 0.7 + 8.0
        self.energy = min(100.0, self.energy + gained * self.genome.genes['energy_efficiency'])
        self.nitrogen_reserve = min(1.0, self.nitrogen_reserve + other.nitrogen_reserve * 0.5)
        growth = other._body_size * 0.06
        self._body_size   = min(self._body_size + growth, self.max_size)
        self._cached_size = self._body_size
        self.last_eaten   = environment.current_time

    def eat_food(self, environment):
        gained = self.BASE_FOOD_ENERGY * self.genome.genes['energy_efficiency']
        self.energy     = min(100.0, self.energy + gained)
        self.last_eaten = environment.current_time
        self.nitrogen_reserve = min(1.0, self.nitrogen_reserve + 0.06)
        self._food_target = None

    def die(self, environment):
        cx, cy = environment.center
        if math.hypot(self.position[0] - cx, self.position[1] - cy) <= environment.radius:
            environment.food.append((float(self.position[0]), float(self.position[1])))
        environment.remove_cell(self)
        # Add death marker with cell size for scaling
        environment.add_death_marker(self.position[0], self.position[1], self._body_size)

    def adhere_to(self, other):
        if self.adhesin and other.adhesin and other not in self.adhered_cells:
            self.adhered_cells.append(other)
            other.adhered_cells.append(self)

    def separate_from(self, other):
        if other in self.adhered_cells:
            self.adhered_cells.remove(other)
            other.adhered_cells.remove(self)

    def check_collision(self, other):
        dx = self.position[0] - other.position[0]
        dy = self.position[1] - other.position[1]
        return math.hypot(dx, dy) < (self._cached_size + other._cached_size) * 0.5

    def resolve_collision(self, other):
        dx = self.position[0] - other.position[0]
        dy = self.position[1] - other.position[1]
        dist = math.hypot(dx, dy) or 0.001
        overlap = (self._cached_size + other._cached_size) * 0.5 - dist
        if overlap > 0:
            inv_d  = 1.0 / dist
            nx, ny = dx * inv_d, dy * inv_d
            half   = overlap * 0.5
            self.position[0]  -= nx * half
            self.position[1]  -= ny * half
            other.position[0] += nx * half
            other.position[1] += ny * half

    def resolve_boundary_collision(self, environment):
        cx, cy = environment.center
        dx = self.position[0] - cx
        dy = self.position[1] - cy
        dist = math.hypot(dx, dy) or 0.001
        limit = environment.radius - self._cached_size * 0.5
        if dist > limit:
            inv_d  = 1.0 / dist
            ndx, ndy = dx * inv_d, dy * inv_d
            self.position[0] = cx + ndx * limit
            self.position[1] = cy + ndy * limit
            if not environment.wrap_around:
                normal_x, normal_y = -ndx, -ndy
                dot = math.cos(self.angle) * normal_x + math.sin(self.angle) * normal_y
                self.angle = math.atan2(
                    math.sin(self.angle) - 2 * dot * normal_y,
                    math.cos(self.angle) - 2 * dot * normal_x)


# ---------------------------------------------------------------------------
# Bacteria — run‑and‑tumble, always flagellum
# ---------------------------------------------------------------------------
class Bacteria(Cell):
    BASE_FOOD_ENERGY  = 35.0
    MAINTENANCE_RATE  = 0.012
    GROWTH_RATE       = 2.0
    FOOD_SEEK_RANGE   = 80.0

    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Bacteria"
        genome.genes['size']             = min(genome.genes['size'], 10.0)
        genome.genes['speed']            = max(genome.genes['speed'] * 1.4, 1.5)
        genome.genes['energy_efficiency'] = max(genome.genes['energy_efficiency'], 1.0)
        genome.genes['motility_mode']    = 1   # flagellum
        genome.genes['division_threshold'] = min(genome.genes['division_threshold'], 60.0)

        self._body_size  = genome.genes['size'] * 0.4
        self._cached_size = self._body_size

        self._tumble_timer = random.uniform(0.3, 1.2)
        self._run_mode     = True

    def update(self, environment, dt):
        self._tumble_timer -= dt
        if self._tumble_timer <= 0:
            if self._run_mode:
                self.angle += random.uniform(-math.pi, math.pi)
                self._tumble_timer = random.uniform(0.05, 0.25)
                self._run_mode = False
            else:
                self._tumble_timer = random.uniform(0.4, 1.8)
                self._run_mode = True
        super().update(environment, dt)


# ---------------------------------------------------------------------------
# Phagocyte — predator with flagellum
# ---------------------------------------------------------------------------
class Phagocyte(Cell):
    MAINTENANCE_RATE  = 0.025
    MOVE_COST         = 0.03
    FLEE_RANGE        = 0.0
    FOOD_SEEK_RANGE   = 150.0
    HUNT_RANGE        = 160.0

    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Phagocyte"
        genome.genes['size']    = max(genome.genes['size'] * 1.4, 16.0)
        genome.genes['speed']   = genome.genes['speed'] * 0.75
        genome.genes['motility_mode'] = 1   # flagellum
        genome.genes['can_consume'] = True
        genome.genes['consumption_size_ratio'] = 1.4

        self._body_size   = genome.genes['size'] * 0.4
        self._cached_size = self._body_size
        self._hunt_target     = None
        self._hunt_timer      = 0.0
        self.HUNT_SEARCH_PERIOD = 0.4

    def update(self, environment, dt):
        self._hunt_timer -= dt
        if self._hunt_timer <= 0:
            self._hunt_timer  = self.HUNT_SEARCH_PERIOD + random.uniform(-0.1, 0.1)
            self._hunt_target = self._find_nearest_prey(environment)

        if self._hunt_target is not None and self._hunt_target in environment.cells:
            self._steer_toward(self._hunt_target.position, dt)
        else:
            self._hunt_target = None

        super().update(environment, dt)

    def _find_nearest_prey(self, environment):
        grid = getattr(environment, '_spatial_grid', None)
        px, py = float(self.position[0]), float(self.position[1])
        candidates = grid.query(px, py, self.HUNT_RANGE) if grid else environment.cells
        best, best_dist = None, float('inf')
        for cell in candidates:
            if cell is self or cell.type == "Phagocyte":
                continue
            if cell._body_size >= self._body_size * 0.75:
                continue
            dist = math.hypot(px - float(cell.position[0]),
                              py - float(cell.position[1]))
            if dist < best_dist:
                best_dist = dist
                best = cell
        return best

    def can_consume(self, other):
        if other.type == "Phagocyte":
            return False
        return self._body_size > other._body_size * 1.3


# ---------------------------------------------------------------------------
# Photocyte — photosynthetic, tends toward cilia
# ---------------------------------------------------------------------------
class Photocyte(Cell):
    BASE_FOOD_ENERGY  = 18.0
    MAINTENANCE_RATE  = 0.010
    _BASE_COLOR = (0.12, 0.78, 0.22)

    def __init__(self, genome, position, dna=None):
        super().__init__(genome, position, dna)
        self.type = "Photocyte"
        r, g, b = self._BASE_COLOR
        genome.genes['color'] = (
            max(0.0, min(1.0, r + random.uniform(-0.08, 0.08))),
            max(0.0, min(1.0, g + random.uniform(-0.12, 0.12))),
            max(0.0, min(1.0, b + random.uniform(-0.08, 0.08))),
        )
        genome.genes['speed']   *= 0.65
        genome.genes['motility_mode'] = 2   # cilia, gentle movement
        genome.genes['can_consume'] = False
        self._body_size   = genome.genes['size'] * 0.4
        self._cached_size = self._body_size
        self.glow_intensity = 0.0

    def update(self, environment, dt):
        lx, ly = environment.light_source
        intensity = getattr(environment, 'light_intensity', 1.0)
        self._steer_toward((lx, ly), dt)

        px, py = float(self.position[0]), float(self.position[1])
        dist_to_light = math.hypot(px - lx, py - ly)
        light_factor = max(0.0, 1.0 - dist_to_light / environment.radius)
        self.glow_intensity = light_factor * intensity

        # Only gain energy if light is enabled
        if getattr(environment, 'light_enabled', True):
            photo_gain = light_factor * intensity * 4.0 * dt
            self.energy += photo_gain
            if photo_gain > 0.01:
                self.last_eaten = environment.current_time

        if light_factor > 0.35:
            r, g, b = self.genome.genes['color']
            self.genome.genes['color'] = (
                max(0.05, r - 0.002 * dt),
                min(0.92, g + 0.004 * dt),
                max(0.05, b - 0.002 * dt),
            )
        elif light_factor < 0.08:
            r, g, b = self.genome.genes['color']
            self.genome.genes['color'] = (
                min(0.8, r + 0.002 * dt),
                max(0.25, g - 0.003 * dt),
                min(0.6, b + 0.002 * dt),
            )

        super().update(environment, dt)