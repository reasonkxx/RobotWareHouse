import time
import math
import heapq
import random
from collections import deque
from threading import Thread, Lock

from db.connection import get_connection

# Пути для обхода (8 направлений)
DIRECTIONS = [
    (0, -1),  # вверх
    (1, -1),  # вверх-вправо
    (1, 0),   # вправо
    (1, 1),   # вниз-вправо
    (0, 1),   # вниз
    (-1, 1),  # вниз-влево
    (-1, 0),  # влево
    (-1, -1)  # вверх-влево
]

# Пути для обхода (4 направления - для большей точности движения)
DIRECTIONS_4 = [
    (0, -1),  # вверх
    (1, 0),   # вправо
    (0, 1),   # вниз
    (-1, 0),  # влево
]

# Глобальная блокировка для избежания конфликтов при резервировании клеток
grid_lock = Lock()
reserved_cells = {}  # координаты (x, y): robot_id
# Новое: глобальный словарь для отслеживания целей роботов
robot_destinations = {}  # robot_id: (x, y)

class RobotNavigator:
    def __init__(self, robot_id, grid_width, grid_height, shelf_coords, pallet_coords, charging_station):
        self.robot_id = robot_id
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.shelf_coords = shelf_coords
        self.pallet_coords = pallet_coords
        self.charging_station = charging_station
        self.path = []
        self.current_task = None
        self.destination = None
        self.carrying_items = []  # список товарів, які робот несе
        self.max_capacity = 6  # максимальна емність робота
        self.current_position = self.get_current_position()
        self.battery_threshold = 10  # критичний рівень заряду батареї (%)
        self.battery_level = self.get_battery_level()
        self.is_charging = False
        self.status_lock = Lock()  # блокіровка для оновлення статуса
        self.planned_path_lock = Lock()  # блокіровка для оновлення запланованого путі
        self.planned_path = []  # запланований путь для у інших роботів
        self.pathfinding_algorithm = "a_star"  # По умолчанию A*
        # Доступные опции: "a_star", "dijkstra", "auto"
        
        # Дополнительные настройки
        self.algorithm_stats = {
            "a_star": {"calls": 0, "total_time": 0, "avg_path_length": 0},
            "dijkstra": {"calls": 0, "total_time": 0, "avg_path_length": 0}
        }
        
    def get_current_position(self):
        """Получить текущие координаты робота из БД"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT x, y FROM robots WHERE id = ?", (self.robot_id,))
        position = cursor.fetchone()
        conn.close()
        return (position[0], position[1]) if position else (0, 0)
    
    def get_battery_level(self):
        """Получить текущий уровень заряда батареи"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT battery FROM robots WHERE id = ?", (self.robot_id,))
        battery = cursor.fetchone()
        conn.close()
        return battery[0] if battery else 100
    
    def update_position(self, x, y):
        """Обновить позицию робота в БД"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE robots SET x = ?, y = ?, updated_at = GETDATE() WHERE id = ?", 
                       (x, y, self.robot_id))
        conn.commit()
        conn.close()
        self.current_position = (x, y)
    
    def update_status(self, status):
        """Обновить статус робота в БД"""
        with self.status_lock:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE robots SET status = ?, updated_at = GETDATE() WHERE id = ?", 
                          (status, self.robot_id))
            conn.commit()
            conn.close()
    
    def update_battery(self, level):
        """Обновить уровень заряда батареи"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE robots SET battery = ?, updated_at = GETDATE() WHERE id = ?", 
                      (level, self.robot_id))
        conn.commit()
        conn.close()
        self.battery_level = level
    
    def decrease_battery(self, amount=0.2):
        """Уменьшить заряд батареи при движении"""
        new_level = max(0, self.battery_level - amount)
        self.update_battery(new_level)
        return new_level
    
    def charge_battery(self, amount=5):
        """Зарядить батарею"""
        new_level = min(100, self.battery_level + amount)
        self.update_battery(new_level)
        return new_level
    
    def is_cell_pallet(self, x, y):
        """Проверить, является ли клетка паллетой"""
        for pallet_id, coords in self.pallet_coords.items():
            if coords == (x, y):
                return True
        return False
    
    def is_cell_occupied(self, x, y):
        """Перевірити, чи зайнята клітинка"""
        # Перевірка на вихід за межі сітки
        if x < 0 or x >= self.grid_width or y < 0 or y >= self.grid_height:
            return True

        # Перевірка на зайнятість іншими роботами
        with grid_lock:
            if (x, y) in reserved_cells and reserved_cells[(x, y)] != self.robot_id:
                return True
                
            # Нове: перевіряємо, чи не планує інший робот пройти через цю клітинку
            for robot_id, dest in robot_destinations.items():
                if robot_id != self.robot_id and dest == (x, y):
                    return True

        # Перевірка на палети — НОВЕ: завжди вважаємо, що палети зайняті
        if self.is_cell_pallet(x, y):
            return True

        # Якщо це координати полиці і це не наша ціль — вважається зайнятою
        for shelf_code, coords in self.shelf_coords.items():
            if coords == (x, y):
                if self.destination != (x, y):
                    return True

        return False
    
    def reserve_cell(self, x, y):
        """Резервировать клетку для робота"""
        with grid_lock:
            if (x, y) not in reserved_cells or reserved_cells[(x, y)] == self.robot_id:
                reserved_cells[(x, y)] = self.robot_id
                # Обновляем целевую клетку
                robot_destinations[self.robot_id] = (x, y)
                return True
            return False
    
    def release_cell(self, x, y):
        """Освободить клетку"""
        with grid_lock:
            if (x, y) in reserved_cells and reserved_cells[(x, y)] == self.robot_id:
                del reserved_cells[(x, y)]
    
    def heuristic(self, a, b):
        """Евристична функція відстані для A*"""
        # Евклідова відстань
        return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
    
    def get_neighbors(self, position, goal=None):
        """Отримати сусідні клітинки для A*. Якщо goal передана — вона не вважається зайнятою."""
        x, y = position
        neighbors = []

        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy

            if goal and (nx, ny) == goal:
                neighbors.append((nx, ny))
            elif not self.is_cell_occupied(nx, ny):
                neighbors.append((nx, ny))

        return neighbors

    
    def a_star_search(self, start, goal):
        """Реалізація алгоритму A* без перевірки зайнятості цілі"""
        frontier = []
        frontier.append((0, start))

        came_from = {start: None}
        cost_so_far = {start: 0}

        while frontier:
            frontier.sort()  # по пріоритету
            current_cost, current = frontier.pop(0)

            if current == goal:
                break

            neighbors = self.get_neighbors(current, goal)

            for next_pos in neighbors:
                new_cost = cost_so_far[current] + 1
                if next_pos not in cost_so_far or new_cost < cost_so_far[next_pos]:
                    cost_so_far[next_pos] = new_cost
                    priority = new_cost + self.heuristic(next_pos, goal)
                    frontier.append((priority, next_pos))
                    came_from[next_pos] = current

        # Відновлення шляху
        path = []
        current = goal
        while current != start:
            path.append(current)
            if current not in came_from:
                return []  # шляху немає
            current = came_from[current]
        path.reverse()
        return path

    def dijkstra_search(self, start, goal):
        """
        Реализация алгоритма Дейкстры для поиска кратчайшего пути
        
        Args:
            start (tuple): Начальная позиция (x, y)
            goal (tuple): Целевая позиция (x, y)
        
        Returns:
            list: Список координат пути от start до goal (без start)
        """
        # Инициализация структур данных
        distances = {start: 0}  # Расстояния от начальной точки
        came_from = {start: None}  # Для восстановления пути
        visited = set()  # Посещенные узлы
        
        # Приоритетная очередь: (расстояние, позиция)
        priority_queue = [(0, start)]
        
        while priority_queue:
            current_distance, current_position = heapq.heappop(priority_queue)
            
            # Если уже посетили эту позицию, пропускаем
            if current_position in visited:
                continue
                
            # Отмечаем как посещенную
            visited.add(current_position)
            
            # Если достигли цели, прекращаем поиск
            if current_position == goal:
                break
            
            # Проверяем всех соседей
            neighbors = self.get_neighbors(current_position, goal)
            
            for neighbor in neighbors:
                if neighbor in visited:
                    continue
                    
                # Вычисляем новое расстояние до соседа
                # В данном случае все переходы имеют вес 1
                new_distance = current_distance + 1
                
                # Если нашли более короткий путь или впервые посещаем этого соседа
                if neighbor not in distances or new_distance < distances[neighbor]:
                    distances[neighbor] = new_distance
                    came_from[neighbor] = current_position
                    heapq.heappush(priority_queue, (new_distance, neighbor))
        
        # Восстановление пути
        if goal not in came_from:
            return []  # Путь не найден
        
        path = []
        current = goal
        
        while current != start:
            path.append(current)
            current = came_from[current]
            if current is None:  # Защита от бесконечного цикла
                return []
    
        path.reverse()
        return path
    
    def find_path(self, start, goal):
        """Выбирает и выполняет нужный алгоритм"""
        if self.pathfinding_algorithm == "dijkstra":
            return self.dijkstra_search(start, goal)
        else:  # По умолчанию A*
            return self.a_star_search(start, goal)

    def find_closest_accessible_cell(self, target):
        """Знайти найближчу доступну клітинку поруч із ціллю"""
        x, y = target
        # Перевіряємо всі клітинки навколо цілі
        min_distance = float('inf')
        best_cell = None
        
        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            if not self.is_cell_occupied(nx, ny):
                dist = self.heuristic(self.current_position, (nx, ny))
                if dist < min_distance:
                    min_distance = dist
                    best_cell = (nx, ny)
                    
        return best_cell

    
    def update_planned_path(self, path):
        """Обновить запланированный путь"""
        with self.planned_path_lock:
            self.planned_path = path
            
    def is_path_clear(self, path):
        """Проверить, свободен ли путь от других роботов"""
        with grid_lock:
            for pos in path:
                if self.is_cell_occupied(*pos):
                    return False
            return True
    
    def move_to(self, destination):
        """Переместить робота к указанной позиции"""
        self.current_position = self.get_current_position()
        self.destination = destination
        
        #якщо ми вже в точці
        if self.current_position == destination:
            return True
        
        #пошук шляху
        path = self.find_path(self.current_position, destination)
        if not path:
            print(f"Робот #{self.robot_id}: Не вдалось зайти шлях до {destination}")
            return False
        
        # Обновляем запланированный путь
        self.update_planned_path(path)
        self.path = path
        self.update_status("moving")
        
        # Передвижение по пути
        for next_pos in path:
            # Проверка критического уровня заряда
            if self.battery_level <= self.battery_threshold and destination != self.charging_station:
                print(f"Робот #{self.robot_id}: Низький заряд батареї! Направляюсь на зарядку.")
                self.go_to_charging_station()
                return False
            
            # Перепроверяем, что путь все еще свободен (динамическая проверка)
            retry_attempts = 10
            while self.is_cell_occupied(*next_pos) and retry_attempts > 0:
                print(f"Робот #{self.robot_id}: Клітинка {next_pos} тимчасово зайнята. Очікую...")
                time.sleep(0.5)
                retry_attempts -= 1

            if self.is_cell_occupied(*next_pos):
                print(f"Робот #{self.robot_id}: Клітинка {next_pos} не звільнилась. Перераховую маршрут.")
                return self.move_to(destination)

            
            x, y = next_pos
            # Пытаемся зарезервировать следующую клетку
            if not self.reserve_cell(x, y):
                # Если клетка занята, пересчитываем путь
                print(f"Робот #{self.robot_id}: Не можу зарезервувати клітинку {next_pos}, перераховую путь.")
                time.sleep(0.2)
                return self.move_to(destination)
            
            # Обновляем позицию робота
            self.update_position(x, y)
            # Освобождаем предыдущую клетку
            self.release_cell(self.current_position[0], self.current_position[1])
            
            # Уменьшаем заряд при движении
            self.decrease_battery()
            
            # Задержка для анимации движения
            time.sleep(0.7)
        
        self.update_status("idle")
        return True
    
    def go_to_charging_station(self):
        """Отправить робота на зарядную станцию"""
        self.update_status("going_to_charge")
        result = self.move_to(self.charging_station)
        if result:
            self.is_charging = True
            self.update_status("charging")
            # Запускаем процесс зарядки в отдельном потоке
            charging_thread = Thread(target=self.charging_process)
            charging_thread.daemon = True
            charging_thread.start()
        return result
    
    def charging_process(self):
        """Процесс зарядки батареи"""
        while self.is_charging and self.battery_level < 100:
            self.charge_battery()
            time.sleep(2)  # Зарядка идет постепенно
            
            # Если батарея зарядилась полностью
            if self.battery_level >= 100:
                self.is_charging = False
                self.update_status("idle")
                print(f"Робот #{self.robot_id}: Батарея полностью заряжена.")
    
    def find_nearest_pallet_with_item(self, item_id, quantity_needed):
        """Найти ближайшую паллету с нужным товаром"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT i.location_id, i.quantity, p.x, p.y 
            FROM inventory i
            JOIN pallets p ON i.location_id = p.id
            WHERE i.item_id = ? AND i.location_type = 'pallet' AND i.quantity >= ?
            ORDER BY i.quantity DESC
        """, (item_id, quantity_needed))
        pallets = cursor.fetchall()
        conn.close()
        
        if not pallets:
            return None
        
        # Находим ближайшую паллету
        min_distance = float('inf')
        nearest_pallet = None
        for pallet in pallets:
            pallet_location = (pallet[2], pallet[3])
            distance = self.heuristic(self.current_position, pallet_location)
            if distance < min_distance:
                min_distance = distance
                nearest_pallet = pallet
        
        return nearest_pallet
    
    def find_free_shelf(self):
        """Найти ближайшую свободную полку"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, shelf_code, x, y 
            FROM shelves
            WHERE status = 'free'
            ORDER BY id
        """)
        shelves = cursor.fetchall()
        conn.close()
        
        if not shelves:
            return None
        
        # Находим ближайшую полку
        min_distance = float('inf')
        nearest_shelf = None
        for shelf in shelves:
            shelf_location = (shelf[2], shelf[3])
            distance = self.heuristic(self.current_position, shelf_location)
            if distance < min_distance:
                min_distance = distance
                nearest_shelf = shelf
        
        return nearest_shelf
    
    def find_approach_position_for_pallet(self, pallet_pos):
        """Найти позицию подхода к паллете"""
        x, y = pallet_pos
        # Проверяем все соседние клетки
        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            # Если клетка доступна и не занята
            if not self.is_cell_occupied(nx, ny):
                return (nx, ny)
        return None
    
    def pick_item_from_pallet(self, pallet_id, item_id, quantity):
        """Взять товар с паллеты"""
        if len(self.carrying_items) + quantity > self.max_capacity:
            quantity = self.max_capacity - len(self.carrying_items)
            if quantity <= 0:
                return 0
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT quantity FROM inventory
            WHERE location_type = 'pallet' AND location_id = ? AND item_id = ?
        """, (pallet_id, item_id))
        available = cursor.fetchone()[0]
        
        take = min(available, quantity)
        
        # Уменьшаем количество на паллете
        new_qty = available - take
        if new_qty > 0:
            cursor.execute("""
                UPDATE inventory 
                SET quantity = ? 
                WHERE location_type = 'pallet' AND location_id = ? AND item_id = ?
            """, (new_qty, pallet_id, item_id))
        else:
            cursor.execute("""
                DELETE FROM inventory
                WHERE location_type = 'pallet' AND location_id = ? AND item_id = ?
            """, (pallet_id, item_id))
        
        conn.commit()
        conn.close()
        
        # Добавляем товары к переносимым
        self.carrying_items.extend([item_id] * take)
        
        return take
    
    def place_item_to_shelf(self, shelf_id, item_id, quantity, order_id):
        """Кладем товар на полку"""
        if not self.carrying_items or len(self.carrying_items) < quantity:
            return 0
        
        # Удаляем товар из переносимых
        for _ in range(quantity):
            if item_id in self.carrying_items:
                self.carrying_items.remove(item_id)
        
        conn = get_connection()
        cursor = conn.cursor()
        
        # Находим координаты полки
        cursor.execute("SELECT x, y FROM shelves WHERE id = ?", (shelf_id,))
        shelf_coords = cursor.fetchone()
        shelf_x, shelf_y = shelf_coords
        
        # Кладем товар на полку
        cursor.execute("""
            INSERT INTO inventory (item_id, location_type, location_id, quantity, x, y)
            VALUES (?, 'shelf', ?, ?, ?, ?)
        """, (item_id, shelf_id, quantity, shelf_x, shelf_y))
        
        # Обновляем статус полки
        cursor.execute("""
            UPDATE shelves
            SET status = 'busy', current_order_id = ?
            WHERE id = ?
        """, (order_id, shelf_id))
        
        conn.commit()
        conn.close()
        
        return quantity
    
    def process_order_item(self, order_id, item_id, quantity_needed):
        """Обрабатываем одну позицию товара"""
        self.update_status(f"processing_order_{order_id}")
        remaining = quantity_needed

        while remaining > 0 and len(self.carrying_items) < self.max_capacity:
            # Находим ближайшую паллету с нужным товаром
            pallet = self.find_nearest_pallet_with_item(item_id, remaining)
            if not pallet:
                print(f"Робот #{self.robot_id}: Немає доступних паллетів з товаром {item_id}. Пропускаю позицію.")
                return True

            pallet_id, available_qty, pallet_x, pallet_y = pallet
            pallet_pos = (pallet_x, pallet_y)

            # НОВОЕ: Находим позицию для подхода к паллете
            approach_pos = self.find_approach_position_for_pallet(pallet_pos)
            if not approach_pos:
                print(f"Робот #{self.robot_id}: Не можу підійти до паллети {pallet_id}. Всі клітинки зайнятті")
                time.sleep(1)
                continue
            
            # Двигаемся к позиции перед паллетой
            print(f"Робот #{self.robot_id}: Направляюсь к позиции перед паллетой {pallet_id} ({approach_pos})")
            move_result = self.move_to(approach_pos)
            if not move_result:
                return False

            # Забираем товар (находясь возле паллеты)
            take = self.pick_item_from_pallet(pallet_id, item_id, remaining)
            print(f"Робот #{self.robot_id}: Взяв {take} одиниць товару {item_id}")
            remaining -= take

            # Если все собрано или достигнута ёмкость
            if len(self.carrying_items) >= self.max_capacity or remaining <= 0:
                shelf = self.find_free_shelf()
                if not shelf:
                    print(f"Робот #{self.robot_id}: Немає вільних полиць")
                    break

                shelf_id, shelf_code, shelf_x, shelf_y = shelf
                shelf_pos = (shelf_x, shelf_y)

                # Получаем подход к полке
                approach_pos = self.get_approach_position(shelf_pos)
                if approach_pos:
                    print(f"Робот #{self.robot_id}: Подходжу до полиці {shelf_code} через {approach_pos}")
                    move_result = self.move_to(approach_pos)
                    if not move_result:
                        return False
                else:
                    print(f"Робот #{self.robot_id}: Не зміг підійти до полиці {shelf_code}")
                    return False

                # Кладем товар
                place_qty = min(quantity_needed - remaining, len(self.carrying_items))
                self.place_item_to_shelf(shelf_id, item_id, place_qty, order_id)
                print(f"Робот #{self.robot_id}: Поклав {place_qty} одиниць товару {item_id} на полку {shelf_code}")

        return remaining <= 0

    def get_approach_position(self, shelf_coords):
        """Возвращает сервисную клетку перед полкой — всегда ряд 4"""
        _, y = shelf_coords  # y – координата столбца полки
        target = (4, y)      # подходим всегда из ряда 4

        if not self.is_cell_occupied(*target):
            return target
        else:
            print(f"Клітинка підходу {target} занята")
            # Пробуем найти соседнюю свободную клетку
            for dx in [-1, 1]:
                new_target = (4, y + dx)
                if not self.is_cell_occupied(*new_target):
                    return new_target
            return None
    
    def run(self):
        """Основной цикл работы робота"""
        print(f"Робот #{self.robot_id}: Починаю роботу")
        self.update_status("idle")
        
        while True:
            # Проверка уровня батареи
            if self.battery_level <= self.battery_threshold and not self.is_charging:
                print(f"Робот #{self.robot_id}: Низький заряд батареї. Їду на зарядку.")
                self.go_to_charging_station()
                continue
            
            # Если робот не занят заказом, ищем новые задания
            if self.current_task is None and self.battery_level > self.battery_threshold:
                self.find_and_process_new_order()
            
            time.sleep(1)
    
    def find_and_process_new_order(self):
        """Найти и обработать новый заказ"""
        conn = get_connection()
        cursor = conn.cursor()

        # Ищем 1 pending-заказ
        cursor.execute("""
            SELECT TOP 1 id FROM orders
            WHERE status = 'pending'
            ORDER BY id
        """)
        order = cursor.fetchone()
        if not order:
            conn.close()
            return False

        order_id = order[0]

        # Пробуем забронировать это замовлення (и обновляем статус)
        cursor.execute("""
            UPDATE orders
            SET status = 'processing'
            WHERE id = ? AND status = 'pending'
        """, (order_id,))
        conn.commit()

        # Если замовлення уже взял другой робот — выходим
        if cursor.rowcount == 0:
            conn.close()
            return False

        print(f"Робот #{self.robot_id}: Взяв замовлення #{order_id}")

        # Получаем все товары из замовлення
        cursor.execute("""
            SELECT item_id, quantity FROM order_items
            WHERE order_id = ?
        """, (order_id,))
        order_items = cursor.fetchall()
        conn.close()

        # Обрабатываем каждый товар
        for item in order_items:
            item_id, quantity = item
            success = self.process_order_item(order_id, item_id, quantity)
            if not success:
                print(f"Робот #{self.robot_id}: Не вдалося завершити замовлення #{order_id}")
                return False

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET status = 'done' WHERE id = ?", (order_id,))
        conn.commit()
        # Перевіряємо — чи залишились ще pending замовлення
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
        pending_count = cursor.fetchone()[0]

        conn.close()
        print(f"Робот #{self.robot_id}: Замовлення #{order_id} виконано")
        self.update_status("idle")
        self.current_task = None

        if pending_count == 0:
            # Якщо немає замовлень — повертаємось на базу
            standard_return_x = 18
            standard_return_y = 2 + (self.robot_id - 76)
            print(f"Робот #{self.robot_id}: Повертаюсь на стандартну позицію ({standard_return_x}, {standard_return_y})")
            self.move_to((standard_return_x, standard_return_y))

        return True


# Функция для запуска робота в отдельном потоке
def run_robot(robot_id, grid_width, grid_height, shelf_coords, pallet_coords, charging_station):
    """Запустить робота в отдельном потоке"""
    robot = RobotNavigator(
        robot_id=robot_id,
        grid_width=grid_width,
        grid_height=grid_height,
        shelf_coords=shelf_coords,
        pallet_coords=pallet_coords,
        charging_station=charging_station
    )
    
    # Запускаем основной цикл робота
    robot_thread = Thread(target=robot.run)
    robot_thread.daemon = True
    robot_thread.start()
    
    return robot

def compare_pathfinding_algorithms(self, start, goal):
    """
    Сравнение производительности и результатов алгоритмов A* и Дейкстры
    
    Args:
        start (tuple): Начальная позиция
        goal (tuple): Целевая позиция
    
    Returns:
        dict: Результаты сравнения алгоритмов
    """
    results = {}
    
    # Тестируем A*
    start_time = time.time()
    a_star_path = self.a_star_search(start, goal)
    a_star_time = time.time() - start_time
    
    results['a_star'] = {
        'path': a_star_path,
        'length': len(a_star_path),
        'time': a_star_time,
        'found': len(a_star_path) > 0
    }
    
    # Тестируем Дейкстру
    start_time = time.time()
    dijkstra_path = self.dijkstra_search(start, goal)
    dijkstra_time = time.time() - start_time
    
    results['dijkstra'] = {
        'path': dijkstra_path,
        'length': len(dijkstra_path),
        'time': dijkstra_time,
        'found': len(dijkstra_path) > 0
    }
    
    # Тестируем Дейкстру с весами
    start_time = time.time()
    dijkstra_weighted_path = self.dijkstra_search_with_weights(start, goal)
    dijkstra_weighted_time = time.time() - start_time
    
    results['dijkstra_weighted'] = {
        'path': dijkstra_weighted_path,
        'length': len(dijkstra_weighted_path),
        'time': dijkstra_weighted_time,
        'found': len(dijkstra_weighted_path) > 0
    }
    
    # Анализ результатов
    results['analysis'] = {
        'fastest_algorithm': min(results.keys(), key=lambda x: results[x]['time'] if x != 'analysis' else float('inf')),
        'shortest_path': min([alg for alg in results.keys() if alg != 'analysis'], 
                           key=lambda x: results[x]['length'] if results[x]['found'] else float('inf')),
        'all_found_same_path': len(set(str(results[alg]['path']) for alg in results.keys() if alg != 'analysis' and results[alg]['found'])) <= 1
    }
    
    return results