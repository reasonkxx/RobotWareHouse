
import time
import heapq
import math
from simulation.warehouse_map import grid_width, grid_height 

class Navigator:
    """Клас для пошуку шляху"""
    
    def __init__(self):
        """
        Створюємо навігатор
        Беремо розміри карти з warehouse_map.py
        """
        self.grid_width = grid_width    
        self.grid_height = grid_height  
        
        self.DIRECTIONS_4 = [
            (0, -1),  
            (1, 0),  
            (0, 1),   
            (-1, 0),  
        ]
        
        #налаштування для автоматичного вибору алгоритму
        self.auto_switch_threshold = 10  #кількість викликів для прийняття рішення
        self.performance_weight = 0.7    #вага продуктивності проти якості шляху

        
        self.algorithm_stats = {
            "a_star": {
                "calls": 0, 
                "total_time": 0, 
                "total_path_length": 0,
                "successful_paths": 0,
                "failed_paths": 0,
                "avg_time": 0,
                "avg_path_length": 0,
                "min_time": float('inf'),
                "max_time": 0,
                "min_path_length": float('inf'),
                "max_path_length": 0
            },
            "dijkstra": {
                "calls": 0, 
                "total_time": 0, 
                "total_path_length": 0,
                "successful_paths": 0,
                "failed_paths": 0,
                "avg_time": 0,
                "avg_path_length": 0,
                "min_time": float('inf'),
                "max_time": 0,
                "min_path_length": float('inf'),
                "max_path_length": 0
            }
        }
    
    def heuristic(self, a, b):
        """
        Евристична функція - обчислює відстань між точками.
        Використовується в A* для оцінки відстані до цілі.
        """
        return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
    
    def get_neighbors(self, position, goal, is_cell_occupied_func):
        """
        Отримати сусідні клітинки, куди можна піти
        position - поточна позиція (x, y)
        goal - цільова позиція (x, y)
        is_cell_occupied_func - функція перевірки зайнятості клітинки
        """
        x, y = position
        neighbors = []

        for dx, dy in self.DIRECTIONS_4:
            nx, ny = x + dx, y + dy
            
            #межи карти
            if nx < 0 or nx >= self.grid_width or ny < 0 or ny >= self.grid_height:
                continue
            
            #якщо це мета - можна йти туди
            if (nx, ny) == goal:
                neighbors.append((nx, ny))
            #інакше перевіряємо, чи вільна клітка
            elif not is_cell_occupied_func(nx, ny):
                neighbors.append((nx, ny))

        return neighbors
    
    def update_algorithm_stats(self, algorithm, execution_time, path_length, success):
        """Оновити статистику алгоритму"""
        stats = self.algorithm_stats[algorithm]
        stats["calls"] += 1
        stats["total_time"] += execution_time
        
        if success:
            stats["successful_paths"] += 1
            stats["total_path_length"] += path_length
            
            stats["min_time"] = min(stats["min_time"], execution_time)
            stats["max_time"] = max(stats["max_time"], execution_time)
            stats["min_path_length"] = min(stats["min_path_length"], path_length)
            stats["max_path_length"] = max(stats["max_path_length"], path_length)
            
            #обчислюємо середні значення
            stats["avg_path_length"] = stats["total_path_length"] / stats["successful_paths"]
        else:
            stats["failed_paths"] += 1
        
        #загальний середній час виконання
        stats["avg_time"] = stats["total_time"] / stats["calls"]
    
    def a_star_search(self, start, goal, is_cell_occupied_func):
        """
        Алгоритм A* для пошуку шляху
        start - початкова точка (x, y)
        goal - кінцева точка (x, y)
        is_cell_occupied_func - функція перевірки, чи зайнята клітинка
        """
        start_time = time.perf_counter()
        
        # черга з пріорітетом
        frontier = []
        frontier.append((0, start))
        
        #звідки ми прийшли в кожну точку
        came_from = {start: None}
        #вартість шляху до кожної точки
        cost_so_far = {start: 0}
        
        while frontier:
            frontier.sort()  #сортируємо по пріорітету
            current_cost, current = frontier.pop(0)
            
            #досягли цілі
            if current == goal:
                break
            
            #перевіряємо сусідей
            neighbors = self.get_neighbors(current, goal, is_cell_occupied_func)
            
            for next_pos in neighbors:
                new_cost = cost_so_far[current] + 1
                
                #якщо знайшли більш короткий шлях до сусіда
                if next_pos not in cost_so_far or new_cost < cost_so_far[next_pos]:
                    cost_so_far[next_pos] = new_cost
                    priority = new_cost + self.heuristic(next_pos, goal)
                    frontier.append((priority, next_pos))
                    came_from[next_pos] = current
        
        #відновлюємл шлях
        path = []
        current = goal
        
        while current != start:
            path.append(current)
            if current not in came_from:
                #путь не знайден
                execution_time = time.perf_counter() - start_time
                self.update_algorithm_stats("a_star", execution_time, 0, False)
                return []
            current = came_from[current]
        
        path.reverse()
        
        #оновлюємо статистику 
        execution_time = time.perf_counter() - start_time
        self.update_algorithm_stats("a_star", execution_time, len(path), True)
        
        return path
    
    def dijkstra_search(self, start, goal, is_cell_occupied_func):
        """
        Алгоритм Дейкстри для пошуку шляху
        start - початкова точка (x, y)
        goal - кінцева точка (x, y)
        is_cell_occupied_func - функція перевірки, чи зайнята клітинка
        """
        start_time = time.perf_counter()
        
        #відстань від початкової точки
        distances = {start: 0}
        #звідки прийшли
        came_from = {start: None}
        #відвідані вузли
        visited = set()
        
        #пріоритетна черга: (відстань, позиція)
        priority_queue = [(0, start)]
        
        while priority_queue:
            current_distance, current_position = heapq.heappop(priority_queue)
            
            #якщо вже були - то пропускаємо
            if current_position in visited:
                continue
            
            #помічаєм як вже відвідану
            visited.add(current_position)
            
            #якщо досягли цілі-то виходио
            if current_position == goal:
                break
            
            #перевіряємо усіх сусідей
            neighbors = self.get_neighbors(current_position, goal, is_cell_occupied_func)
            
            for neighbor in neighbors:
                if neighbor in visited:
                    continue
                
                #рахуємо як нову відстань
                new_distance = current_distance + 1
                
                #якщо знайшли більш короткий шлях?
                if neighbor not in distances or new_distance < distances[neighbor]:
                    distances[neighbor] = new_distance
                    came_from[neighbor] = current_position
                    heapq.heappush(priority_queue, (new_distance, neighbor))
        
        #оновлюємо шлях
        if goal not in came_from:
            execution_time = time.perf_counter() - start_time
            self.update_algorithm_stats("dijkstra", execution_time, 0, False)
            return []
        
        path = []
        current = goal
        
        while current != start:
            path.append(current)
            current = came_from[current]
            if current is None:
                execution_time = time.perf_counter() - start_time
                self.update_algorithm_stats("dijkstra", execution_time, 0, False)
                return []
        
        path.reverse()
        
        #оновлюємо статистику
        execution_time = time.perf_counter() - start_time
        self.update_algorithm_stats("dijkstra", execution_time, len(path), True)
        
        return path
    
    def choose_best_algorithm(self):
        """Автоматичний вибір найкращого алгоритму на основі статистики"""
        a_star_stats = self.algorithm_stats["a_star"]
        dijkstra_stats = self.algorithm_stats["dijkstra"]
        
        #якщо даних недостатньо, використовуємо A**
        if (a_star_stats["calls"] < self.auto_switch_threshold and 
            dijkstra_stats["calls"] < self.auto_switch_threshold):
            return "a_star"  #за заомвч А*
        
        #обчислюємо оцінки продуктивності
        def calculate_score(stats):
            if stats["calls"] == 0:
                return float('inf')
            
            #враховуємо час виконання та якість шляху
            time_score = stats["avg_time"]
            path_score = stats["avg_path_length"] if stats["successful_paths"] > 0 else float('inf')
            success_rate = stats["successful_paths"] / stats["calls"]
            
            #комбінована оцінка
            combined_score = (self.performance_weight * time_score + 
                            (1 - self.performance_weight) * path_score) / success_rate
            
            return combined_score
        
        a_star_score = calculate_score(a_star_stats)
        dijkstra_score = calculate_score(dijkstra_stats)
        
        return "a_star" if a_star_score < dijkstra_score else "dijkstra"
    
    def find_path(self, start, goal, is_cell_occupied_func, algorithm="a_star"):
        """
        Головна функція пошуку шляху
        start - звідки йдемо
        goal - куди йдемо
        is_cell_occupied_func - функція перевірки зайнятості клітинки
        algorithm - який алгоритм використовувати («a_star», “dijkstra” або «auto»)
        """
        #якщо обран авто, то обирається найкращий алгоритм 
        if algorithm == "auto":
            algorithm = self.choose_best_algorithm()
            # print(f"Navigator: автоматично обран алгоритм {algorithm}")
        
        #використовуємо обраний алгор
        if algorithm == "dijkstra":
            return self.dijkstra_search(start, goal, is_cell_occupied_func)
        else:
            return self.a_star_search(start, goal, is_cell_occupied_func)
    
    def get_statistics(self):
        """Отримати статистику роботи алгоритмів"""
        stats = {}
        for alg_name, alg_stats in self.algorithm_stats.items():
            if alg_stats["calls"] > 0:
                stats[alg_name] = {
                    "calls": alg_stats["calls"],
                    "success_rate": alg_stats["successful_paths"] / alg_stats["calls"] * 100,
                    "avg_time_ms": alg_stats["avg_time"] * 1000,
                    "avg_path_length": alg_stats["avg_path_length"],
                }
            else:
                stats[alg_name] = {"calls": 0, "message": "Алгоритм ще не використовувався"}
        
        return stats