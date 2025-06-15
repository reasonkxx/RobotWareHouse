import time
import math
import heapq
import random
from collections import defaultdict, deque
from threading import Thread, Lock
from simulation.file_diagnostics import add_robot_to_simulation
from logic.navigator import Navigator

from db.connection import get_connection


DIRECTIONS = [
    (0, -1),  
    (1, -1),  
    (1, 0),   
    (1, 1),   
    (0, 1),   
    (-1, 1),  
    (-1, 0),  
    (-1, -1) 
]


DIRECTIONS_4 = [
    (0, -1),  
    (1, 0),   
    (0, 1),  
    (-1, 0),  
]

#глобальне блокування для уникнення конфліктів при резервуванні клітинок
grid_lock = Lock()
reserved_cells = {}  #координати (x, y): robot_id
#глобальний словник для відстеження цілей роботів
robot_destinations = {}  #robot_id: (x, y)
robots_cannot_retreat = set() #глобальна змінна для відстеження роботів, які не можуть відступити

class RobotNavigator:
    def __init__(self, robot_id, grid_width, grid_height, shelf_coords, pallet_coords):
        self.robot_id = robot_id
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.shelf_coords = shelf_coords
        self.pallet_coords = pallet_coords
        self.path = []
        self.current_task = None
        self.destination = None
        self.carrying_items = []  #список товарів, які робот несе
        self.max_capacity = 6  #максимальна ємність робота
        self.current_position = self.get_current_position()
        self.battery_threshold = 20 #мінімальний рівень заряду   
        self.critical_battery_threshold = 10  #крітичний рівень
        self.battery_level = self.get_battery_level()
        self.is_charging = False
        self.status_lock = Lock()  #блокування для оновлення статуса
        self.planned_path_lock = Lock()  #блокування для оновлення запланованого шляху
        self.planned_path = []  #запланований шлях для інших роботів
        self.pathfinding_algorithm = "a_star"
        #доступні опції: "a_star", "dijkstra", "auto"
        self.navigator = Navigator()  
        self.max_retry_attempts = 5  #максимальна кількість спроб
        self.retry_delay = 2  #затримка між спробами (секунди)
        self.max_wait_time = 30  #максимальний час очікування (секунди)
        self.fallback_positions = []  #резервні позиції для очікування
          #налаштування для автоматичного вибору алгоритму
        self.auto_switch_threshold = 20  #кількість викликів для прийняття рішення
        self.performance_weight = 0.7   #вага продуктивності проти якості шляху
        self.default_shelf_coords = (4, 21)
        self.charging_power_W = 1000.0    #потужність зарядного пристрою, Вт 
        self.battery_capacity_Wh = 1500.0 #номінальна ємність акумулятора робота, Вт.год
        self.charging_efficiency = 0.9   #90% ефективність перетворення енергії в акумулятор
        self.min_resume_charge_percent = 30.0  #після досягнення 30% може виїхати обробляти замовлення
        self.full_charge_percent = 100.0       #до 100% заряд
    
    @property
    def algorithm_stats(self):
        """Отримати актуальну статистику алгоритмів від навігатора"""
        return self.navigator.get_statistics()
        
    def get_current_position(self):
        """Отримати поточні координати робота з БД"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT x, y FROM robots WHERE id = ?", (self.robot_id,))
        position = cursor.fetchone()
        conn.close()
        return (position[0], position[1]) if position else (0, 0)
    
    def get_battery_level(self):
        """Отримати поточний рівень заряду батареї"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT battery FROM robots WHERE id = ?", (self.robot_id,))
        battery = cursor.fetchone()
        conn.close()
        return battery[0] if battery else 100
    
    def update_position(self, x, y):
        """Оновити позицію робота в БД"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE robots SET x = ?, y = ?, updated_at = GETDATE() WHERE id = ?", 
                       (x, y, self.robot_id))
        conn.commit()
        conn.close()
        self.current_position = (x, y)
    
    def update_status(self, status):
        """Оновити статус робота в БД"""
        with self.status_lock:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE robots SET status = ?, updated_at = GETDATE() WHERE id = ?", 
                          (status, self.robot_id))
            conn.commit()
            conn.close()

    def has_pending_orders(self):
        """Проста перевірка замовлень, що знаходяться в стані очікування"""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except:
            return False
    
    def update_battery(self, new_level):
        """Оновлює рівень заряду в БД і локально."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE robots SET battery = ?, updated_at = GETDATE() WHERE id = ?",
                       (new_level, self.robot_id))
        conn.commit()
        conn.close()
        self.battery_level = new_level
    
    def calculate_energy_consumption_percent(self,
                                          distance_m,
                                          m0,
                                          m_payload,
                                          k1,
                                          k2=0.01,
                                          g=9.81,
                                          eta_t=0.9):
        """
        Обчислює відсоток заряду, який споживається при русі з вантажем.
        """
        # 1) Сумарна маса робота + вантаж
        M = m0 + m_payload  # [кг]
        # 2) Сила тертя (Н)
        F_tertya = k1 * M * g
        # 3) Енергія для коліс у Вт·год (1 Вт·год = 3600 Дж)
        E_kolesa_Wh = (F_tertya * distance_m) / 3600.0
        # 4) З урахуванням ефективності трансмісії
        E_spozhyto_Wh = E_kolesa_Wh / eta_t
        # 5) Базовий % від ємності батареї
        base_percent = 100.0 * E_spozhyto_Wh / self.battery_capacity_Wh
        # 6) Додаткові втрати (наприклад, електроніка, прискорення/гальмування)
        extra_loss = k2 * distance_m
        # 7) Сумарний відсоток витрат
        total_percent = base_percent + extra_loss
        # print(f"Вирохований процент {total_percent}")
        return total_percent

    def decrease_battery(self, percent):
        """Зменшити заряд батареї при русі"""
        new_level = max(0, self.battery_level - percent)
        self.update_battery(new_level)
        return new_level
    
    def charge_battery(self, amount=10):
        """Зарядити батарею"""
        new_level = min(100, self.battery_level + amount)
        self.update_battery(new_level)
        return new_level
    
    def go_to_charging_station(self):
        """Надсилає робота до зарядної станції:"""
        charging_pos = self.get_charging_station()
        print(f"Робот #{self.robot_id}: Недостатній заряд ({self.battery_level:.1f}%), прямуємо на зарядку до {charging_pos}.")
        self.update_status("going_to_charge")
        got_here = self.safe_move_to(charging_pos)
        if not got_here:
            print(f"Робот #{self.robot_id}: Не вдалося дістатися зарядки!")
            return False

        #починаємо заряджання в окремому потоці
        self.is_charging = True
        self.update_status("charging")
        charging_thread = Thread(target=self.charging_process)
        charging_thread.daemon = True
        charging_thread.start()
        return True

    def charging_process(self):
        """Процес зарядки акумулятора робота """
        print(f"Робот #{self.robot_id}: Розпочали зарядку з {self.battery_level:.1f}%")
        #отримуємо координати зарядної станції
        station_pos = self.get_charging_station()

        #продовжуємо заряджатися, доки не досягнемо 100% або доки не виїдемо з платформи заряджання
        while self.is_charging and self.battery_level < self.full_charge_percent:
            # Перевіряємо, чи робот досі на станції
            if self.current_position != station_pos:
                print(f"Робот #{self.robot_id}: Вийшов із зони зарядки, процес перервано.")
                self.is_charging = False
                break
            #обчислюємо, скільки відсотків заряджаємо за один інтервал (1 секунда)
            energy_added_Wh = (self.charging_power_W * 1.0) / 3600.0
            energy_to_battery_Wh = energy_added_Wh * self.charging_efficiency
            #відсоток від ємності акумулятора, який отримано за 1 с:
            percent_added = 100.0 * energy_to_battery_Wh / self.battery_capacity_Wh
            #оновлення заряду
            new_level = min(self.full_charge_percent, self.battery_level + percent_added)
            self.update_battery(new_level)
            print(f"Робот #{self.robot_id}: Зарядка... {self.battery_level:.1f}%")
            #затримка 5 секунд ітерації
            time.sleep(1.0)

        #після досягнення 100% або коли заряджання перерване
        if self.battery_level >= self.full_charge_percent:
            print(f"Робот #{self.robot_id}: Зарядка завершена – {self.battery_level:.1f}%")
        self.is_charging = False
        self.update_status("idle")
        self.current_task = None

        #повернення на стандартну позицію після завершення
        standard_pos = self.get_standard_position()
        print(f"Робот #{self.robot_id}: Повертаюся на стандартну позицію {standard_pos}")
        self.safe_move_to(standard_pos)
        print(f"Робот #{self.robot_id}: Готовий до роботи на позиції {standard_pos}")
    
    def get_charging_station(self):
        """Отримати позицію зарядної станції робота"""
        charging_y = 2 + (self.robot_id - 76)
        return (19, charging_y)
            
    def calculate_path_battery_cost(self, destination, battery_cost_per_cell=0.2):
        """Розрахувати вартість батареї для маршруту"""
        path = self.find_path(self.current_position, destination)
        if not path:
            return float('inf')  #якщо маршрут неможливий
        
        #кількість = довжини шляху 
        cells_count = len(path)
        battery_cost = cells_count * battery_cost_per_cell
        
        print(f"Робот #{self.robot_id}: Маршрут до {destination} = {cells_count} клітинок, ціна замовлення {battery_cost}% заряда")
        return battery_cost

    def can_complete_order_with_battery(self, pallet_pos, estimated_payload_kg):
        """
        Перевіряє, чи вистачить батареї для:
        1) проїзду від поточної позиції до палети (без вантажу),
        2) проїзду від палети до полиці (з вантажем),
        3) повернення від полиці до стандартної позиції (без вантажу).
        Повертає True, якщо після такого циклу заряд залишиться вище порогового запасу (15%).
        """
        current_batt = self.battery_level

        #маршрут до палети
        path_to_pallet = self.find_path(self.current_position, pallet_pos)
        if not path_to_pallet:
            print(f"Робот #{self.robot_id}: Неможливо побудувати маршрут до палети {pallet_pos}.")
            return False
        distance_to_pallet = len(path_to_pallet) * 1.0  

        percent_to_pallet = self.calculate_energy_consumption_percent(
            distance_m=distance_to_pallet,
            m0=50.0,
            m_payload=0.0,
            k1=0.02,
            k2=0.01,
            g=9.81,
            eta_t=0.9,
        )
        

        #маршрут від палети до полиці
        shelf_pos = self.default_shelf_coords  # наприклад, (4, 21)
        path_from_pallet_to_shelf = self.find_path(pallet_pos, shelf_pos)
        if not path_from_pallet_to_shelf:
            return False
        distance_pallet_to_shelf = len(path_from_pallet_to_shelf) * 1.0

        percent_pallet_to_shelf = self.calculate_energy_consumption_percent(
            distance_m=distance_pallet_to_shelf,
            m0=50.0,
            m_payload=estimated_payload_kg,
            k1=0.02,
            k2=0.01,
            g=9.81,
            eta_t=0.9,
        )

        #маршрут від полиці до стандартної позиції
        standard_pos = self.get_standard_position()
        path_shelf_to_standard = self.find_path(shelf_pos, standard_pos)
        if not path_shelf_to_standard:
            return False
        distance_shelf_to_standard = len(path_shelf_to_standard) * 1.0

        percent_shelf_to_standard = self.calculate_energy_consumption_percent(
            distance_m=distance_shelf_to_standard,
            m0=50.0,
            m_payload=0.0,
            k1=0.02,
            k2=0.01,
            g=9.81,
            eta_t=0.9,
        )
        total_percent_needed = (
            percent_to_pallet
            + percent_pallet_to_shelf
            + percent_shelf_to_standard
        )
        print(f"Робот #{self.robot_id}: Загальна витрата енергії ≈ {total_percent_needed:.2f}%. Поточний заряд = {current_batt:.2f}%.")

        if current_batt - total_percent_needed < 15.0:
            print(f"Робот #{self.robot_id}: Не вистачає батареї (потрібно {total_percent_needed:.2f}%, лишиться {current_batt - total_percent_needed:.2f}%).")
            return False

        print(f"Робот #{self.robot_id}: Батареї достатньо (після циклу лишиться {current_batt - total_percent_needed:.2f}%).")
        return True

            

    def get_standard_position(self):
        """Отримати стандартну позицію очікування"""
        standard_y = 2 + (self.robot_id - 76) 
        return (18, standard_y)

    def check_battery_before_order(self, pallet_pos):
        """Перевірити батарею перед прийняттям замовлення"""
        if not self.can_complete_order_with_battery(pallet_pos, estimated_payload_kg=20.0):
            print(f"Робот #{self.robot_id}: Недостатньо заряду для виконання замовлення. Їду на зарядку.")
            return False
        return True

    
    def is_cell_pallet(self, x, y):
        """Перевірити, чи є клітинка палетою"""
        for pallet_id, coords in self.pallet_coords.items():
            if coords == (x, y):
                return True
        return False
    
    def is_cell_occupied(self, x, y):
        """Перевірити, чи зайнята клітинка"""
        #перевірка на вихід за межі сітки
        if x < 0 or x >= self.grid_width or y < 0 or y >= self.grid_height:
            return True
    
        #перевірка на зайнятість іншими роботами
        with grid_lock:
            if (x, y) in reserved_cells and reserved_cells[(x, y)] != self.robot_id:
                return True
                
            #перевіряємо, чи не планує інший робот пройти через цю клітинку
            for robot_id, dest in robot_destinations.items():
                if robot_id != self.robot_id and dest == (x, y):
                    return True

        #перевірка на палети,завжди вважаємо, що палети зайняті
        if self.is_cell_pallet(x, y):
            return True

        #якщо це координати полиці і це не наша ціль то вважається зайнятою
        for shelf_code, coords in self.shelf_coords.items():
            if coords == (x, y):
                if self.destination != (x, y):
                    return True

        return False
    
    def reserve_cell(self, x, y):
        """Зарезервувати клітинку для робота"""
        with grid_lock:
            if (x, y) not in reserved_cells or reserved_cells[(x, y)] == self.robot_id:
                reserved_cells[(x, y)] = self.robot_id
                robot_destinations[self.robot_id] = (x, y)
                return True
            return False
    
    def release_cell(self, x, y):
        """Звільнити клітинку"""
        with grid_lock:
            if (x, y) in reserved_cells and reserved_cells[(x, y)] == self.robot_id:
                del reserved_cells[(x, y)]
    
    def heuristic(self, a, b):
        """Евристична функція відстані для A*"""
        #евклідова відстань
        return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
    
    
    def choose_best_algorithm(self):
        """Автоматичний вибір найкращого алгоритму на основі статистики"""
        a_star_stats = self.algorithm_stats["a_star"]
        dijkstra_stats = self.algorithm_stats["dijkstra"]
        
        #якщо мало даних то використовуємо поточний алгоритм
        if (a_star_stats["calls"] < self.auto_switch_threshold and 
            dijkstra_stats["calls"] < self.auto_switch_threshold):
            return self.pathfinding_algorithm
        
        #обчислюємо оцінку продуктивності
        def calculate_score(stats):
            if stats["calls"] == 0:
                return float('inf')
            
            #враховуємо час виконання та якість шляху
            time_score = stats["avg_time"]
            path_score = stats["avg_path_length"] if stats["successful_paths"] > 0 else float('inf')
            success_rate = stats["successful_paths"] / stats["calls"]
            
            #комбінована оцінка (чим менше, тим краще)
            combined_score = (self.performance_weight * time_score + 
                            (1 - self.performance_weight) * path_score) / success_rate
            
            return combined_score
        
        a_star_score = calculate_score(a_star_stats)
        dijkstra_score = calculate_score(dijkstra_stats)
        
        return "a_star" if a_star_score < dijkstra_score else "dijkstra"
    
    def find_path(self, start, goal):
        """Використовує Navigator для пошуку шляху"""
        #створюємо функцію перевірки зайнятості для навігатора
        def check_occupied(x, y):
            return self.is_cell_occupied(x, y)
        
        return self.navigator.find_path(start, goal, check_occupied, self.pathfinding_algorithm)

    def get_algorithm_statistics(self):
        """Отримати статистику від навігатора"""
        return self.navigator.get_statistics()
    
    def wait_for_free_position(self, target_positions, max_wait_time=None):
        """Очікувати звільнення однієї з позицій"""
        if max_wait_time is None:
            max_wait_time = self.max_wait_time
            
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            for pos in target_positions:
                if not self.is_cell_occupied(*pos):
                    return pos
            
            print(f"Робот #{self.robot_id}: Очікую звільнення позицій {target_positions}")
            time.sleep(self.retry_delay)
            
        return None
    
    def find_alternative_approach_positions(self, target_pos, radius=3):
        """Знайти альтернативні позиції для підходу в радіусі"""
        x, y = target_pos
        positions = []
        
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) == r or abs(dy) == r:  #тільки на межі радіуса
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < self.grid_width and 
                            0 <= ny < self.grid_height and 
                            not self.is_cell_occupied(nx, ny)):
                            positions.append((nx, ny))
        
        #сортуємо за відстанню від поточної позиції
        positions.sort(key=lambda pos: self.heuristic(self.current_position, pos))
        return positions
    
    def safe_move_to(self, destination, max_attempts=None):
        """Безпечне переміщення з обробкою помилок"""
        if max_attempts is None:
            max_attempts = self.max_retry_attempts
            
        for attempt in range(max_attempts):
            try:
                result = self.move_to_basic(destination)
                if result:
                    return True
                    
                print(f"Робот #{self.robot_id}: Спроба {attempt + 1}/{max_attempts} не вдалася")
                
                #якщо не остання спроба, чекаємо та пробуємо знову
                if attempt < max_attempts - 1:
                    time.sleep(self.retry_delay)
                    
            except Exception as e:
                print(f"Робот #{self.robot_id}: Помилка при русі до {destination}: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(self.retry_delay)
                    
        return False

    def find_approach_position_for_pallet_improved(self, pallet_pos):
        """пошук позиції підходу до палети"""
        #спочатку пробуємо стандартні сусідні клітинки
        x, y = pallet_pos
        primary_positions = []
        
        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            if (0 <= nx < self.grid_width and 
                0 <= ny < self.grid_height):
                primary_positions.append((nx, ny))
        
        #перевіряємо доступність основних позицій
        for pos in primary_positions:
            if not self.is_cell_occupied(*pos):
                return pos
        
        #якщо основні позиції зайняті, чекаємо їх звільнення
        print(f"Робот #{self.robot_id}: Основні позиції біля палети {pallet_pos} зайняті, очікую...")
        free_pos = self.wait_for_free_position(primary_positions, max_wait_time=30)
        if free_pos:
            return free_pos
        
        #якщо не дочекалися, шукаємо альтернативні позиції
        alternative_positions = self.find_alternative_approach_positions(pallet_pos)
        if alternative_positions:
            return alternative_positions[0]
        
        return None
    
    def get_approach_position_improved(self, shelf_coords):
        """функція отримання позиції підходу до полиці"""
        _, y = shelf_coords
        
        #основна позиція підходу
        primary_target = (4, y)
        
        if not self.is_cell_occupied(*primary_target):
            return primary_target
        
        #альтернативні позиції в тому ж ряду
        alternative_targets = []
        for dx in [-1, 1, -2, 2]:
            new_target = (4, y + dx)
            if (0 <= new_target[1] < self.grid_height):
                alternative_targets.append(new_target)
        
        #перевіряємо альтернативи
        for target in alternative_targets:
            if not self.is_cell_occupied(*target):
                return target
        
        #чекаємо звільнення позицій
        all_targets = [primary_target] + alternative_targets
        free_pos = self.wait_for_free_position(all_targets, max_wait_time=30)
        if free_pos:
            return free_pos
        
        #в крайньому випадку шукаємо будь-яку доступну позицію поряд
        alternative_positions = self.find_alternative_approach_positions(shelf_coords)
        if alternative_positions:
            return alternative_positions[0]
            
        return None

    def find_closest_accessible_cell(self, target):
        """Знайти найближчу доступну клітинку поруч із ціллю"""
        x, y = target
        #перевіряємо всі клітинки навколо цілі
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
        """Оновити запланований шлях"""
        with self.planned_path_lock:
            self.planned_path = path
            
    def is_path_clear(self, path):
        """Перевірити, чи вільний шлях від інших роботів"""
        with grid_lock:
            for pos in path:
                if self.is_cell_occupied(*pos):
                    return False
            return True
        
    def detect_deadlock_chain(self, target_pos):
        """Виявити ланцюг deadlock"""
        visited = set()
        current_pos = self.current_position
        chain = [self.robot_id]
        
        while True:
            visited.add(current_pos)
            
            #хто займає нашу цільову клітинку?
            with grid_lock:
                if target_pos in reserved_cells:
                    blocking_robot = reserved_cells[target_pos]
                    if blocking_robot == self.robot_id:
                        return None  
                        
                    chain.append(blocking_robot)
                    
                    #куди хоче піти блокуючий робот?
                    if blocking_robot in robot_destinations:
                        next_target = robot_destinations[blocking_robot]
                        
                        #якщо він хоче на вже відвідану позицію - є цикл
                        if next_target in visited:
                            return chain
                        
                        #продовжуємо пошук
                        current_pos = target_pos
                        target_pos = next_target
                    else:
                        return None
                else:
                    return None
        

    def find_nearest_free_cells(self, count=3):
        """Знайти найближчі вільні клітинки для відступу"""
        current_x, current_y = self.current_position
        free_cells = []
        
        #шуккаємо в радіусі
        for radius in range(1, 5):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if abs(dx) == radius or abs(dy) == radius:
                        nx, ny = current_x + dx, current_y + dy
                        
                        if (0 <= nx < self.grid_width and 
                            0 <= ny < self.grid_height and
                            not self.is_cell_occupied(nx, ny)):
                            free_cells.append((nx, ny))
            
            if len(free_cells) >= count:
                break
        
        #сортуємо за відстанню
        free_cells.sort(key=lambda pos: self.heuristic(self.current_position, pos))
        return free_cells[:count]
    
    def can_robot_retreat(self, robot_id):
        """Перевірити чи може робот відступити"""
        #знаходимо позицію робота
        robot_pos = None
        with grid_lock:
            for pos, rid in reserved_cells.items():
                if rid == robot_id:
                    robot_pos = pos
                    break
        
        if not robot_pos:
            return False
        
        #перевіряємо чи є вільні клітинки навколо
        x, y = robot_pos
        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            if (0 <= nx < self.grid_width and 
                0 <= ny < self.grid_height and
                not self.is_cell_occupied(nx, ny)):
                return True
        
        return False

    def _execute_retreat_maneuver(self, original_destination):
        """Виконати маневр відступу - просто звільнити клітинку і відійти"""
        print(f"Робот #{self.robot_id}: Виконую маневр відступу")
        
        #звільняємо поточну клітинку
        current_x, current_y = self.current_position
        self.release_cell(current_x, current_y)
        
        #видаляємо себе з destinations тимчасово
        with grid_lock:
            if self.robot_id in robot_destinations:
                del robot_destinations[self.robot_id]
        
        #знаходимо найближчі вільні клітинки
        free_cells = self.find_nearest_free_cells(count=5)
        
        if not free_cells:
            print(f"Робот #{self.robot_id}: УВАГА! Немає вільних клітинок для відступу! Залишаюся на місці.")
            #повертаємо False щоб сигналізувати про неможливість відступу
            time.sleep(2)
            return False
        
        #вибираємо випадкову з топ-3 найближчих
        retreat_pos = random.choice(free_cells[:3])
        
        #рухаємося на один крок до вільної клітинки
        if self.reserve_cell(*retreat_pos):
            print(f"Робот #{self.robot_id}: Відступаю на {retreat_pos}")
            percent = self.calculate_energy_consumption_percent(
                distance_m=1,
                m0=50.0,         
                m_payload=20.0,  
                k1=0.02,         
                k2=0.01,          
                g=9.81,
                eta_t=0.9,
            )
            self.decrease_battery(percent)
            self.update_position(*retreat_pos)
            
            #чекаємо поки інші роботи пройдуть
            wait_time = random.uniform(2, 4)
            print(f"Робот #{self.robot_id}: Чекаю {wait_time:.1f} секунд")
            time.sleep(wait_time)
            
            #звільняємо тимчасову позицію
            self.release_cell(*retreat_pos)
            
            #невелика затримка перед поверненням
            time.sleep(random.uniform(0.5, 1.5))
            
            #повертаємося до початкового завдання
            print(f"Робот #{self.robot_id}: Повертаюся до завдання")
            return self.move_to_basic(original_destination)
        else:
            #якщо не вдалося зарезервувати - повертаємо False
            print(f"Робот #{self.robot_id}: Не вдалося зарезервувати позицію для відступу")
            return False

    def move_to_basic(self, destination):
        """Базове переміщення з детектором deadlock"""
        self.current_position = self.get_current_position()
        self.destination = destination
        
        if self.current_position == destination:
            return True
        
        path = self.find_path(self.current_position, destination)
        if not path:
            print(f"Робот #{self.robot_id}: Не вдалося знайти шлях до {destination}")
            return False
        
        self.update_planned_path(path)
        self.path = path
        self.update_status("moving")
        
        consecutive_wait_time = 0
        last_blocked_pos = None
        deadlock_resolution_attempts = 0
        
        for next_pos in path:
            retry_attempts = 20
            while self.is_cell_occupied(*next_pos) and retry_attempts > 0:
                #якщо чекаємо в тому ж місці
                if next_pos == last_blocked_pos:
                    consecutive_wait_time += 0.8
                else:
                    consecutive_wait_time = 0.8
                    last_blocked_pos = next_pos
                
                #швидка перевірка deadlock
                if consecutive_wait_time > 2:
                    deadlock_chain = self.detect_deadlock_chain(next_pos)
                    
                    if deadlock_chain and len(deadlock_chain) >= 2:
                        print(f"Робот #{self.robot_id}: Виявлено deadlock: {deadlock_chain}")
                        deadlock_resolution_attempts += 1
                        
                        #проста стратегія для двох роботів
                        if len(deadlock_chain) == 2:
                            other_robot = deadlock_chain[1] if deadlock_chain[0] == self.robot_id else deadlock_chain[0]
                            
                            #спочатку стандартне правило: більший ID відступає
                            if self.robot_id > other_robot:
                                print(f"Робот #{self.robot_id}: Мій ID більший, спробую відступити")
                                retreat_success = self._execute_retreat_maneuver(destination)
                                if retreat_success:
                                    return retreat_success
                                else:
                                    print(f"Робот #{self.robot_id}: Не можу відступити! Робот #{other_robot} має відступити")
                                    #даємо сигнал іншому роботу через глобальну змінну
                                    with grid_lock:
                                        robots_cannot_retreat.add(self.robot_id)
                            else:
                                #перевіряємо чи може інший робот відступити
                                can_other_retreat = self.can_robot_retreat(other_robot)
                                
                                #також перевіряємо глобальний сигнал
                                other_cannot_retreat = False
                                with grid_lock:
                                    if other_robot in robots_cannot_retreat:
                                        other_cannot_retreat = True
                                
                                if not can_other_retreat or other_cannot_retreat or deadlock_resolution_attempts > 3:
                                    print(f"Робот #{self.robot_id}: Робот #{other_robot} не може відступити, відступаю я")
                                    retreat_success = self._execute_retreat_maneuver(destination)
                                    if retreat_success:
                                        return retreat_success
                                    else:
                                        #критична ситуація, обидва не можуть відступити
                                        print(f"Робот #{self.robot_id}: КРИТИЧНО! Жоден робот не може відступити!")
                                        #чекаємо довше і пробуємо перерахувати маршрут
                                        time.sleep(5)
                                        return self.move_to_basic(destination)
                                else:
                                    #даємо більше часу роботу з більшим ID
                                    print(f"Робот #{self.robot_id}: Чекаю, поки робот #{other_robot} відступить")
                                    retry_attempts += 15
                        
                        else:
                            #для складних deadlock: адаптивна стратегія
                            my_index = deadlock_chain.index(self.robot_id)
                            
                            #перевіряємо, чи можемо ми відступити
                            free_cells = self.find_nearest_free_cells(count=1)
                            
                            if free_cells:
                                #якщо можемо відступити і маємо парний індекс або пройшло багато спроб
                                if my_index % 2 == 0 or deadlock_resolution_attempts > 2:
                                    print(f"Робот #{self.robot_id}: Відступаю для вирішення складного deadlock")
                                    return self._execute_retreat_maneuver(destination)
                            else:
                                print(f"Робот #{self.robot_id}: Не можу відступити, чекаю інших")
                                retry_attempts += 10
                        
                        consecutive_wait_time = 0  #скидаємо лічильник
                
                time.sleep(0.8)
                retry_attempts -= 1

            #якщо так і не вдалося пройти
            if self.is_cell_occupied(*next_pos):
                print(f"Робот #{self.robot_id}: Не можу пройти через {next_pos}, шукаю альтернативний маршрут")
                
                #спробуємо альтернативний маршрут
                alt_path = self._try_alternative_route(destination)
                if alt_path:
                    #продовжуємо з новим шляхом
                    self.path = alt_path
                    continue  #продовжуємо цикл з новим шляхом
                
                #якщо нічого не допомагає - чекаємо і перераховуємо
                time.sleep(random.uniform(2, 4))
                return self.move_to_basic(destination)

            #очищаємо лічильник спроб вирішення deadlock при успішному русі
            deadlock_resolution_attempts = 0
            
            #резервуємо клітинку
            x, y = next_pos
            if not self.reserve_cell(x, y):
                print(f"Робот #{self.robot_id}: Не вдалося зарезервувати {next_pos}")
                time.sleep(0.5)
                return self.move_to_basic(destination)
            
            #звільняємо попередню клітинку
            old_x, old_y = self.current_position
            self.release_cell(old_x, old_y)

            percent = self.calculate_energy_consumption_percent(
                distance_m=1,
                m0=50.0,         # маса порожнього робота
                m_payload=20.0,  # середня маса вантажу
                k1=0.02,         # коефіцієнт опору руху
                k2=0.01,          # додаткові втрати 0.01 %/м
                g=9.81,
                eta_t=0.9,
            )

            #Розхід батареї
            self.decrease_battery(percent)
            #рухаємося
            self.update_position(x, y)
            
            
            #невелика пауза між кроками
            time.sleep(0.5)
        
        #видаляємо себе з destinations коли досягли цілі
        with grid_lock:
            if self.robot_id in robot_destinations:
                del robot_destinations[self.robot_id]
        
        self.update_status("idle")
        return True


    def move_to(self, destination):
        """Переміщення робота (використовує безпечну версію)"""
        return self.safe_move_to(destination)
    
    def _try_alternative_route(self, destination):
        """Спробувати знайти альтернативний маршрут обходячи зайняті клітинки"""
        print(f"Робот #{self.robot_id}: Шукаю альтернативний маршрут")
        
        #тимчасово збільшуємо "вартість" зайнятих клітинок
        current_pos = self.current_position
        
        #модифікований A* що уникає зайнятих клітинок
        frontier = []
        frontier.append((0, current_pos))
        came_from = {current_pos: None}
        cost_so_far = {current_pos: 0}
        
        while frontier:
            frontier.sort()
            current_cost, current = frontier.pop(0)
            
            if current == destination:
                break
            
            for next_pos in self.navigator.get_neighbors(current, destination):
                #додаємо штраф за клітинки поруч із зайнятими
                penalty = 0
                x, y = next_pos
                for dx, dy in DIRECTIONS_4:
                    check_x, check_y = x + dx, y + dy
                    if self.is_cell_occupied(check_x, check_y):
                        penalty += 5  #штраф за сусідство з зайнятою клітинкою
                
                new_cost = cost_so_far[current] + 1 + penalty
                
                if next_pos not in cost_so_far or new_cost < cost_so_far[next_pos]:
                    cost_so_far[next_pos] = new_cost
                    priority = new_cost + self.heuristic(next_pos, destination)
                    frontier.append((priority, next_pos))
                    came_from[next_pos] = current
        
        #відновлюємо альтернативний шлях
        if destination not in came_from:
            return None
        
        path = []
        current = destination
        while current != current_pos:
            path.append(current)
            current = came_from[current]
        path.reverse()
        
        if path:
            print(f"Робот #{self.robot_id}: Знайдено альтернативний шлях довжиною {len(path)}")
            self.path = path
            self.update_planned_path(path)
            return path
        
        return None
    
    def find_nearest_pallet_with_item_excluding(self, item_id, quantity_needed, excluded_pallets):
        """Знайти найближчу палету, виключаючи вказані"""
        conn = get_connection()
        cursor = conn.cursor()
        
        exclude_condition = ""
        params = [item_id, quantity_needed]
        
        if excluded_pallets:
            placeholders = ",".join("?" * len(excluded_pallets))
            exclude_condition = f"AND i.location_id NOT IN ({placeholders})"
            params.extend(excluded_pallets)
        
        cursor.execute(f"""
            SELECT i.location_id, i.quantity, p.x, p.y 
            FROM inventory i
            JOIN pallets p ON i.location_id = p.id
            WHERE i.item_id = ? AND i.location_type = 'pallet' AND i.quantity >= ?
            {exclude_condition}
            ORDER BY i.quantity DESC
        """, params)
        
        pallets = cursor.fetchall()
        conn.close()
        
        if not pallets:
            return None
        
        #знаходимо найближчу палету
        min_distance = float('inf')
        nearest_pallet = None
        for pallet in pallets:
            pallet_location = (pallet[2], pallet[3])
            distance = self.heuristic(self.current_position, pallet_location)
            if distance < min_distance:
                min_distance = distance
                nearest_pallet = pallet
        
        return nearest_pallet
    
    def find_nearest_pallet_with_item(self, item_id, quantity_needed):
        """для суміності"""
        return self.find_nearest_pallet_with_item_excluding(item_id, quantity_needed, set())
    
    def find_free_shelf(self):
        """Знайти та атомарно зарезервувати вільну полицю """
        shelf_data = self.find_and_reserve_free_shelf()
        if shelf_data:
            shelf_code, shelf_x, shelf_y = shelf_data
            return (shelf_code, shelf_code, shelf_x, shelf_y)
        return None
        
    
    def find_approach_position_for_pallet(self, pallet_pos):
        """для суміності"""
        return self.find_approach_position_for_pallet_improved(pallet_pos)
    
    def get_approach_position(self, shelf_coords):
        """для суміності"""
        return self.get_approach_position_improved(shelf_coords)
    
    def pick_item_from_pallet(self, pallet_id, item_id, quantity):
        """Взяти товар з палети"""
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
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return 0
            
        available = result[0]
        take = min(available, quantity)
        
        #оновлюємо інвентар палети
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
        
        #додаємо товари до переносних
        for _ in range(take):
            self.carrying_items.append(item_id)
        
        return take
    
    
    def find_and_reserve_free_shelf(self, order_id=None):
        """Знайти полицю спеціально для потрібного замовлення"""
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            #шукаємо полиці з товарами цього замовлення (використовуємо shelf.id)
            if order_id:
                cursor.execute("""
                    SELECT DISTINCT s.shelf_code, s.x, s.y, s.id
                    FROM shelves s
                    JOIN inventory i ON i.location_id = s.id AND i.location_type = 'shelf'
                    WHERE i.order_id = ? AND s.status = 'busy'
                    ORDER BY s.shelf_code
                """, (order_id,))
                
                existing_order_shelves = cursor.fetchall()
                
                if existing_order_shelves:
                    for shelf in existing_order_shelves:
                        shelf_code, shelf_x, shelf_y, shelf_id = shelf
                        print(f"Робот #{self.robot_id}: Використовую існуючу полицю {shelf_code} для замовлення {order_id}")
                        return (shelf_code, shelf_x, shelf_y, shelf_id) 
            
            #шукаємо повністю вільні полиці
            cursor.execute("""
                SELECT s.shelf_code, s.x, s.y, s.id
                FROM shelves s
                LEFT JOIN inventory i ON i.location_id = s.id AND i.location_type = 'shelf'
                WHERE s.status = 'free' AND i.location_id IS NULL
                ORDER BY s.shelf_code
            """)
            
            completely_free_shelves = cursor.fetchall()
            
            if not completely_free_shelves:
                conn.close()
                return None
            
            #знаходимо найближчу полицю і резервуємо
            min_distance = float('inf')
            best_shelf = None
            
            for shelf in completely_free_shelves:
                shelf_code, shelf_x, shelf_y, shelf_id = shelf
                distance = self.heuristic(self.current_position, (shelf_x, shelf_y))
                
                if distance < min_distance:
                    min_distance = distance
                    best_shelf = shelf
            
            if best_shelf:
                shelf_code, shelf_x, shelf_y, shelf_id = best_shelf
                
                #резервуємо використовуючи shelf_code
                cursor.execute("""
                    UPDATE shelves 
                    SET status = 'reserved', robot_id = ?, order_id = ?, updated_at = GETDATE()
                    WHERE shelf_code = ? AND status = 'free'
                """, (self.robot_id, order_id, shelf_code))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    print(f"Робот #{self.robot_id}: Зарезервував полицю {shelf_code} для замовлення {order_id}")
                    conn.close()
                    return (shelf_code, shelf_x, shelf_y, shelf_id)
            
            conn.close()
            return None
            
        except Exception as e:
            print(f"Робот #{self.robot_id}: Помилка при резервуванні полиці: {e}")
            conn.close()
            return None

    def release_shelf(self, shelf_code):
        """Звільнити зарезервовану полицю"""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shelves 
                SET status = 'free', robot_id = NULL, updated_at = GETDATE()
                WHERE shelf_code = ? AND robot_id = ?
            """, (shelf_code, self.robot_id))
            
            if cursor.rowcount > 0:
                conn.commit()
                print(f"Робот #{self.robot_id}: Звільнив полицю {shelf_code}")
            else:
                print(f"Робот #{self.robot_id}: Не вдалося звільнити полицю {shelf_code}")
            
            conn.close()
            
        except Exception as e:
            print(f"Робот #{self.robot_id}: Помилка при звільненні полиці {shelf_code}: {e}")

    def mark_shelf_as_busy(self, shelf_code):
        """Позначити полицю як зайняту товарами"""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            #сбрасуємо robot_id при переведенні в busy
            cursor.execute("""
                UPDATE shelves 
                SET status = 'busy', robot_id = NULL, updated_at = GETDATE()
                WHERE shelf_code = ? AND robot_id = ?
            """, (shelf_code, self.robot_id))
            
            if cursor.rowcount > 0:
                conn.commit()
                print(f"Робот #{self.robot_id}: Полиця {shelf_code} тепер зайнята товарами")
            
            conn.close()
            
        except Exception as e:
            print(f"Робот #{self.robot_id}: Помилка при позначенні полиці як зайнятої: {e}")
    
    def deliver_items_to_shelf(self, order_id, item_id, quantity):
        """Доставити товари на полицю"""
        max_shelf_attempts = 5
        
        for attempt in range(max_shelf_attempts):
            print(f"Робот #{self.robot_id}: Спроба {attempt + 1} знайти полицю для замовлення {order_id}")
            
            shelf_data = self.find_and_reserve_free_shelf(order_id)
            
            if not shelf_data:
                print(f"Робот #{self.robot_id}: Не знайдено полиць для замовлення {order_id}, спроба {attempt + 1}")
                if attempt < max_shelf_attempts - 1:
                    wait_time = random.uniform(2, 5)
                    time.sleep(wait_time)
                continue
            
            shelf_code, shelf_x, shelf_y, shelf_id = shelf_data
            shelf_pos = (shelf_x, shelf_y)
            
            try:
                approach_pos = self.get_approach_position_improved(shelf_pos)
                if not approach_pos:
                    print(f"Робот #{self.robot_id}: Не вдалося знайти позицію підходу до полиці {shelf_code}")
                    self.release_shelf(shelf_code)
                    continue
                
                print(f"Робот #{self.robot_id}: Прямую до полиці {shelf_code} через {approach_pos}")
                
                move_result = self.safe_move_to(approach_pos)
                if not move_result:
                    print(f"Робот #{self.robot_id}: Не вдалося дійти до полиці {shelf_code}")
                    self.release_shelf(shelf_code)
                    continue
                
                #передаємо shelf_id в place_items_on_shelf
                success = self.place_items_on_shelf(shelf_code, order_id, item_id, quantity, shelf_id)
                
                if success:
                    self.mark_shelf_as_busy(shelf_code)
                    print(f"Робот #{self.robot_id}: Поклав {quantity} одиниць товару {item_id} на полицю {shelf_code}")
                    return True
                else:
                    print(f"Робот #{self.robot_id}: Не вдалося покласти товари на полицю {shelf_code}")
                    self.release_shelf(shelf_code)
                    
            except Exception as e:
                print(f"Робот #{self.robot_id}: Помилка при доставці на полицю {shelf_code}: {e}")
                self.release_shelf(shelf_code)
        
        return False

    def place_items_on_shelf(self, shelf_code, order_id, item_id, quantity, shelf_id=None):
        """Розмістити товари з використанням shelf_id"""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            if shelf_id is None:
                cursor.execute("SELECT id FROM shelves WHERE shelf_code = ?", (shelf_code,))
                result = cursor.fetchone()
                if not result:
                    print(f"Робот #{self.robot_id}: Не знайдено полицю з кодом {shelf_code}")
                    conn.close()
                    return False
                shelf_id = result[0]
            #перевірка суміності
            cursor.execute("""
                SELECT DISTINCT order_id FROM inventory 
                WHERE location_type = 'shelf' AND location_id = ?
            """, (shelf_id,))
            
            existing_orders = cursor.fetchall()
            
            if existing_orders:
                existing_order_ids = [row[0] for row in existing_orders if row[0] is not None]
                if existing_order_ids and order_id not in existing_order_ids:
                    print(f"Робот #{self.robot_id}: КРИТИЧНА ПОМИЛКА! На полиці {shelf_code} вже є товари з замовлення {existing_order_ids}")
                    conn.close()
                    return False
            
            #додаємо товари (використовуємо shelf_id)
            cursor.execute("""
                INSERT INTO inventory (location_type, location_id, item_id, quantity, order_id)
                VALUES ('shelf', ?, ?, ?, ?)
            """, (shelf_id, item_id, quantity, order_id))
            
            conn.commit()
            conn.close()
            
            #виддаляємо товари з переносимих
            items_to_remove = min(quantity, self.carrying_items.count(item_id))
            for _ in range(items_to_remove):
                if item_id in self.carrying_items:
                    self.carrying_items.remove(item_id)
            
            print(f"Робот #{self.robot_id}: Розмістив {items_to_remove} одиниць товару {item_id} на полиці {shelf_code}")
            return True
            
        except Exception as e:
            print(f"Робот #{self.robot_id}: Помилка при розміщенні товарів на полиці: {e}")
            return False
    
    def process_order_item_improved(self, order_id, item_id, quantity_needed):
        """Покращена обробка позиції замовлення з обробкою помилок"""
        try:
            self.update_status(f"processing_order_{order_id}")
            remaining = quantity_needed
            failed_pallets = set()  #відстежуємо невдалі палети
            retry_count = 0
            max_retries = 10

            while remaining > 0 and len(self.carrying_items) < self.max_capacity and retry_count < max_retries:
                #знаходимо найближчу палету з потрібним товаром (виключаючи невдалі)
                pallet = self.find_nearest_pallet_with_item_excluding(item_id, remaining, failed_pallets)
                
                if not pallet:
                    print(f"Робот #{self.robot_id}: Немає доступних палет з товаром {item_id}")
                    
                    # Якщо є невдалі палети, очищуємо список і пробуємо знову
                    if failed_pallets:
                        print(f"Робот #{self.robot_id}: Очищую список невдалих палет і пробую знову")
                        failed_pallets.clear()
                        time.sleep(5)  # Чекаємо, можливо ситуація зміниться
                        retry_count += 1
                        continue
                    else:
                        # Дійсно немає товару
                        print(f"Робот #{self.robot_id}: товар {item_id} недоступний. Замовлення не може бути виконано повністю.")
                        return False  # Повертаємо False для позначення невдачі

                pallet_id, available_qty, pallet_x, pallet_y = pallet
                pallet_pos = (pallet_x, pallet_y)

                # Знаходимо позицію для підходу до палети з покращеною логікою
                approach_pos = self.find_approach_position_for_pallet_improved(pallet_pos)
                if not approach_pos:
                    print(f"Робот #{self.robot_id}: Не вдається підійти до палети {pallet_id}")
                    failed_pallets.add(pallet_id)
                    retry_count += 1
                    continue
                
                # Безпечно рухаємося до позиції перед палетою
                print(f"Робот #{self.robot_id}: Прямую до позиції перед палетою {pallet_id} ({approach_pos})")
                move_result = self.safe_move_to(approach_pos)
                if not move_result:
                    print(f"Робот #{self.robot_id}: Не вдалося дістатися до палети {pallet_id}")
                    failed_pallets.add(pallet_id)
                    retry_count += 1
                    continue

                # Забираємо товар
                try:
                    take = self.pick_item_from_pallet(pallet_id, item_id, remaining)
                    print(f"Робот #{self.robot_id}: Взяв {take} одиниць товару {item_id}")
                    remaining -= take
                    
                    if take == 0:
                        failed_pallets.add(pallet_id)
                        retry_count += 1
                        continue
                        
                except Exception as e:
                    print(f"Робот #{self.robot_id}: Помилка при взятті товару з палети {pallet_id}: {e}")
                    failed_pallets.add(pallet_id)
                    retry_count += 1
                    continue

                # Якщо потрібно відвезти товар на полицю
                if len(self.carrying_items) >= self.max_capacity or remaining <= 0:
                    # ✅ Используем новый метод с атомарным резервированием
                    success = self.deliver_items_to_shelf(order_id, item_id, quantity_needed - remaining)
                    
                    if not success:
                        print(f"Робот #{self.robot_id}: Критична помилка - не вдалося доставити товари на полицю")
                        # Возвращаем товары на палету или обрабатываем ошибку
                        return False
            
            # Перевіряємо, чи вдалося зібрати весь товар
            if remaining > 0:
                print(f"Робот #{self.robot_id}: Не вдалося зібрати {remaining} одиниць товару {item_id}")
                return False
                
            return True
        
        except Exception as e:
            print(f"Робот #{self.robot_id}: Помилка при обробці товару {item_id}: {e}")
            return False
    
    def process_order_item(self, order_id, item_id, quantity_needed):
        """Обробити позицію замовлення (сумісність зі старим кодом)"""
        return self.process_order_item_improved(order_id, item_id, quantity_needed)
    
    def find_and_process_new_order_improved(self):
        """Покращена обробка замовлень з перевіркою батареї та пропуском недоступних товарів"""
        conn = get_connection()
        cursor = conn.cursor()

        #шукаємо замовлення
        cursor.execute("""
            SELECT TOP 1 o.id FROM orders o
            WHERE o.status = 'pending'
            ORDER BY o.id
        """)
        order_result = cursor.fetchone()
        if not order_result:
            conn.close()
            return False

        order_id = order_result[0]

        #отримуємо всі товари з замовлення
        cursor.execute("""
            SELECT item_id, quantity FROM order_items
            WHERE order_id = ?
            ORDER BY item_id
        """, (order_id,))
        all_order_items = cursor.fetchall()
        
        if not all_order_items:
            conn.close()
            return False

        #перевіряємо доступність та рівень батареї
        available_items = []
        battery_check_done = False
        
        for item_id, quantity in all_order_items:
            #перевіряємо, чи є товар на палетах
            cursor.execute("""
                SELECT TOP 1 p.id, p.x, p.y FROM inventory i
                JOIN pallets p ON i.location_id = p.id
                WHERE i.item_id = ? AND i.location_type = 'pallet' AND i.quantity > 0
                ORDER BY i.quantity DESC
            """, (item_id,))
            
            pallet_data = cursor.fetchone()
            if pallet_data:
                available_items.append((item_id, quantity, pallet_data))
                
                #перевірка батареї
                if not battery_check_done:
                    pallet_id, pallet_x, pallet_y = pallet_data
                    pallet_pos = (pallet_x, pallet_y)
                    
                    if not self.check_battery_before_order(pallet_pos):
                        conn.close()
                        self.go_to_charging_station()
                        return False
                    
                    battery_check_done = True
            else:
                print(f"Робот #{self.robot_id}: товар {item_id} (кількість: {quantity}) недоступний на палетах - пропускаю")

        #перевіряємо, чи є хоч 1 доступний товар 
        if not available_items:
            print(f"Робот #{self.robot_id}: Жоден товар з замовлення {order_id} недоступний - позначаю failed")
            cursor.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order_id,))
            conn.commit()
            conn.close()
            return False

        #пробуємо забронювати замовлення
        cursor.execute("""
            UPDATE orders
            SET status = 'processing'
            WHERE id = ? AND status = 'pending'
        """, (order_id,))
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return False

        print(f"Робот #{self.robot_id}: Взяв замовлення #{order_id}")
        print(f"Робот #{self.robot_id}: Доступно {len(available_items)} з {len(all_order_items)} товарів")
        conn.close()

        #обробляємо тільки доступні товари
        successful_items = 0
        total_available = len(available_items)
        
        for item_id, quantity, pallet_data in available_items:
            print(f"Робот #{self.robot_id}: Обробляю товар {item_id} (кількість: {quantity})")
            
            success = self.process_order_item_improved(order_id, item_id, quantity)
            if success:
                successful_items += 1
                print(f"Робот #{self.robot_id}: ✅ товар {item_id} успішно оброблено")
            else:
                print(f"Робот #{self.robot_id}: ❌ Не вдалося обробити товар {item_id}")

        conn = get_connection()
        cursor = conn.cursor()
        
        if successful_items == 0:
            #якщо ні 1 товар не оброблен
            cursor.execute("UPDATE orders SET status = 'failed' WHERE id = ?", (order_id,))
            print(f"Робот #{self.robot_id}: ❌ Замовлення #{order_id} повністю не виконано (0/{total_available})")
            final_status = "failed"
        elif successful_items == total_available:
            #якщо всі  товари оброблені
            cursor.execute("UPDATE orders SET status = 'done' WHERE id = ?", (order_id,))
            print(f"Робот #{self.robot_id}: ✅ Замовлення #{order_id} повністю виконано ({successful_items}/{total_available})")
            final_status = "done"
        else:
            #частково
            cursor.execute("UPDATE orders SET status = 'partial' WHERE id = ?", (order_id,))
            print(f"Робот #{self.robot_id}: ⚠️ Замовлення #{order_id} частково виконано ({successful_items}/{total_available})")
            final_status = "partial"
        
        conn.commit()
        conn.close()

        self.update_status("idle")
        self.current_task = None

        #перевірка батареї
        if self.battery_level <= 15.0:
            print(f"Робот #{self.robot_id}: Після завершення замовлення заряд {self.battery_level}% - їду на зарядку")
            self.go_to_charging_station()
            return final_status == "done"
        
        return final_status == "done"
    
    def find_and_process_new_order(self):
        """для суміності"""
        return self.find_and_process_new_order_improved()
    
    def set_pathfinding_algorithm(self, algorithm):
        """Встановити алгоритм пошуку шляху"""
        if algorithm in ["a_star", "dijkstra", "auto"]:
            self.pathfinding_algorithm = algorithm
            print(f"Робот #{self.robot_id}: Алгоритм пошуку шляху змінено на {algorithm}")
        else:
            print(f"Робот #{self.robot_id}: Невідомий алгоритм {algorithm}")
    
    def get_error_statistics(self):
        """Отримати статистику помилок та відмов"""
        conn = get_connection()
        cursor = conn.cursor()
        
        #статистика замовлень
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM orders 
            GROUP BY status
        """)
        order_stats = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            "orders": order_stats,
            "algorithm_stats": self.get_algorithm_statistics()
        }
    
    # def diagnose_current_state(self):
    #     """Діагностика поточного стану робота"""
    #     # print(f"\n=== Діагностика робота #{self.robot_id} ===")
    #     # print(f"Поточна позиція: {self.current_position}")
    #     # print(f"Заряд батареї: {self.battery_level}%")
    #     # print(f"Поточне завдання: {self.current_task}")
    #     # print(f"товарів у переносці: {len(self.carrying_items)}/{self.max_capacity}")
    #     # print(f"Алгоритм пошуку: {self.pathfinding_algorithm}")
    #     # print(f"Зарядка: {'Так' if self.is_charging else 'Ні'}")
        
    #     # Перевірка доступності навколишніх клітинок
    #     x, y = self.current_position
    #     available_neighbors = []
    #     for dx, dy in DIRECTIONS_4:
    #         nx, ny = x + dx, y + dy
    #         if not self.is_cell_occupied(nx, ny):
    #             available_neighbors.append((nx, ny))
        
    #     # print(f"Доступні сусідні клітинки: {available_neighbors}")
        
        
    #     diagnostic_data = {
    #         "position": self.current_position,
    #         "battery_level": self.battery_level,  
    #         "is_charging": self.is_charging,  
    #         "carrying_items": len(self.carrying_items),
    #         "max_capacity": self.max_capacity,
    #         "current_algorithm": self.pathfinding_algorithm,
    #         "available_neighbors": available_neighbors,
    #         "current_task": str(self.current_task) if self.current_task else "None"
    #     }
        
    #     return diagnostic_data

    def diagnose_current_state(self):
        """Діагностика поточного стану робота"""
        # print(f"\n=== Діагностика робота #{self.robot_id} ===")
        # print(f"Поточна позиція: {self.current_position}")
        # print(f"Заряд батареї: {self.battery_level}%")
        # print(f"Поточне завдання: {self.current_task}")
        # print(f"Товарів у переносці: {len(self.carrying_items)}/{self.max_capacity}")
        # print(f"Алгоритм пошуку: {self.pathfinding_algorithm}")
        # print(f"Зарядка: {'Так' if self.is_charging else 'Ні'}")
        
        # Перевірка доступності навколишніх клітинок
        x, y = self.current_position
        available_neighbors = []
        for dx, dy in DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            if not self.is_cell_occupied(nx, ny):
                available_neighbors.append((nx, ny))
        
        # print(f"Доступні сусідні клітинки: {available_neighbors}")
        
        
        diagnostic_data = {
            "position": self.current_position,
            "battery": self.battery_level,
            "carrying_items": len(self.carrying_items),
            "max_capacity": self.max_capacity,
            "current_algorithm": self.pathfinding_algorithm,
            "available_neighbors": available_neighbors,
            "is_charging": self.is_charging,
            "current_task": str(self.current_task) if self.current_task else "None"
        }
        
        return diagnostic_data

    
    def update_simulation_data(self):
        """Оновити дані робота в симуляції"""
        try:
            diagnostic_data = self.diagnose_current_state()
            add_robot_to_simulation(self.robot_id, diagnostic_data, self.navigator.algorithm_stats)
        except Exception as e:
            print(f"Помилка оновлення даних симуляції для робота #{self.robot_id}: {e}")
    
    def run(self):
        """Основний цикл роботи робота"""
        print(f"Робот #{self.robot_id}: Починаю роботу")
        self.update_status("idle")

        last_simulation_update = time.time()

        while True:
            current_time = time.time()

            #критичний рівень батареї 
            if self.battery_level <= self.critical_battery_threshold and not self.is_charging:
                print(f"Робот #{self.robot_id}: Критично низький заряд ({self.battery_level}%)! Їду на зарядку!")
                self.go_to_charging_station()
                time.sleep(1.0)
                continue

            #якщо зараз заряджаємося, перевіряємо умови для припинення зарядки
            if self.is_charging:
                #якщо досяг рівня, достатнього для обробки нових замовлень
                if self.battery_level >= self.min_resume_charge_percent and self.has_pending_orders():
                    print(f"Робот #{self.robot_id}: Заряд {self.battery_level:.1f}% – зупиняю зарядку та беру замовлення.")
                    self.is_charging = False
                    self.update_status("idle")
                #якщо зарядився до 100%, повертаємось на стандартну позицію
                elif self.battery_level >= 100.0:
                    print(f"Робот #{self.robot_id}: Зарядився до 100%! Повертаюся на стандартну позицію")
                    self.is_charging = False
                    self.update_status("idle")
                    self.safe_move_to(self.get_standard_position())
                #або продовжуємо чекати на зарядці
                time.sleep(5)
                continue

            if current_time - last_simulation_update >= 30:
                self.update_simulation_data()
                last_simulation_update = current_time

            #основна логіка: якщо зараз не виконуємо замовлення, пробуємо взяти нове
            if self.current_task is None:
                if self.has_pending_orders():
                    #якщо є pending-замовлення тоді обробляємо його
                    success = self.find_and_process_new_order_improved()
                    continue
                else:
                    #немає замовлень
                    if self.battery_level < 90.0:
                        #якщо заряд < 90% і нема чого робити то їдемо на зарядку
                        # print(f"Робот #{self.robot_id}: Немає замовлень і заряд {self.battery_level}% < 90% → їду на зарядку")
                        self.go_to_charging_station()
                    else:
                        #заряд достатній, але нема замовлень то повертаємося на стандартну позицію
                        standard_pos = self.get_standard_position()
                        # print(f"Робот #{self.robot_id}: Немає замовлень і заряд {self.battery_level}% ≥ 90% → повертаюся на стандартну позицію {standard_pos}")
                        self.safe_move_to(standard_pos)

            #коротка пауза щоб уникнути «гарячого» циклу
            time.sleep(1)

#функція для запуску робота в окремому потоці
def run_robot(robot_id, grid_width, grid_height, shelf_coords, pallet_coords):
    """Запустити робота в окремому потоці"""
    robot = RobotNavigator(
        robot_id=robot_id,
        grid_width=grid_width,
        grid_height=grid_height,
        shelf_coords=shelf_coords,
        pallet_coords=pallet_coords,
        
    )
    
    robot_thread = Thread(target=robot.run)
    robot_thread.daemon = True
    robot_thread.start()
    
    return robot