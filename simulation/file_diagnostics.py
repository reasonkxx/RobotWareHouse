import json
import os
from datetime import datetime
from threading import Lock

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

class SimulationDiagnostics:
    """Система збереження звітів симуляції у results_of_simulation.txt"""
    
    def __init__(self, results_file="simulation/results_of_simulation.txt"):
        self.results_file = results_file
        self.file_lock = Lock()  #для безпечного запису з різних потоків
        self.current_simulation = {
            "start_time": datetime.now(),
            "robots": {},
            "simulation_id": None,
            "orders_stats": {}  #додаємо статистику заказів
        }
        
        #створюємо директорію якщо її немає
        os.makedirs(os.path.dirname(self.results_file), exist_ok=True)
        
        #генеруємо унікальний ID симуляції
        self.current_simulation["simulation_id"] = self.generate_simulation_id()
        
        #збираємо початкову статистику заказів
        self._collect_initial_orders_stats()
    
    def generate_simulation_id(self):
        """Генерувати унікальний ID симуляції"""
        return f"SIM_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def add_robot_diagnostics(self, robot_id, diagnostic_data, algorithm_stats):
        """Додати діагностику робота до поточної симуляції"""
        self.current_simulation["robots"][robot_id] = {
            "diagnostic_data": diagnostic_data,
            "algorithm_stats": algorithm_stats,
            "recorded_at": datetime.now().isoformat()
        }
    
    def _collect_initial_orders_stats(self):
        """Зібрати початкову статистику заказів"""
        try:
            conn = get_connection()
            if not conn:
                print("Не вдалося підключитися до БД для збору статистики заказів")
                return
                
            cursor = conn.cursor()
            
            #збираємо статистику по статусам заказів
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM orders
                GROUP BY status
            """)
            
            stats = {}
            for row in cursor.fetchall():
                status = row[0] if row[0] else 'unknown'
                count = row[1]
                stats[status] = count
            
            self.current_simulation["orders_stats"]["initial"] = stats
            conn.close()
            
        except Exception as e:
            print(f"Помилка при зборі початкової статистики заказів: {e}")
            self.current_simulation["orders_stats"]["initial"] = {}
    
    def _collect_current_orders_stats(self):
        """Зібрати поточну статистику заказів"""
        try:
            conn = get_connection()
            if not conn:
                return {}
                
            cursor = conn.cursor()
            
            #збираємо детальну статистику заказів
            cursor.execute("""
                SELECT 
                    status,
                    COUNT(*) as count,
                    MIN(created_at) as earliest_order,
                    MAX(created_at) as latest_order
                FROM orders
                GROUP BY status
            """)
            
            stats = {}
            total_orders = 0
            
            for row in cursor.fetchall():
                status = row[0] if row[0] else 'unknown'
                count = row[1]
                earliest = row[2]
                latest = row[3]
                
                stats[status] = {
                    'count': count,
                    'earliest_order': earliest.isoformat() if earliest else None,
                    'latest_order': latest.isoformat() if latest else None
                }
                total_orders += count
            
            #додаємо загальну статистику
            stats['_totals'] = {
                'total_orders': total_orders,
                'successful_orders': stats.get('done', {}).get('count', 0) + stats.get('completed', {}).get('count', 0),
                'failed_orders': stats.get('failed', {}).get('count', 0),
                'pending_orders': stats.get('pending', {}).get('count', 0),
                'processing_orders': stats.get('processing', {}).get('count', 0)
            }
            
            #обчислюємо коефіцієнт успішності
            if total_orders > 0:
                success_rate = ((stats['_totals']['successful_orders']) / total_orders) * 100
                stats['_totals']['success_rate'] = round(success_rate, 2)
            else:
                stats['_totals']['success_rate'] = 0
            
            conn.close()
            return stats
            
        except Exception as e:
            print(f"Помилка при зборі поточної статистики заказів: {e}")
            return {}
    
    def get_orders_statistics_report(self):
        """Генерувати звіт по статистиці заказів"""
        current_stats = self._collect_current_orders_stats()
        initial_stats = self.current_simulation["orders_stats"].get("initial", {})
        
        if not current_stats:
            return "Не вдалося отримати статистику заказів"
        
        totals = current_stats.get('_totals', {})
        report = f"""
        --- СТАТИСТИКА ЗАКАЗІВ ---
        
        ЗАГАЛЬНА ІНФОРМАЦІЯ:
        • Всього заказів: {totals.get('total_orders', 0)}
        • Успішних заказів: {totals.get('successful_orders', 0)}
        • Невдалих заказів: {totals.get('failed_orders', 0)}
        • В очікуванні: {totals.get('pending_orders', 0)}
        • В обробці: {totals.get('processing_orders', 0)}
        • Коефіцієнт успішності: {totals.get('success_rate', 0)}%
        
        ДЕТАЛЬНА ІНФОРМАЦІЯ ПО СТАТУСАМ:"""
        
        #додаємо детальну інформацію по кожному статусу
        status_names = {
            'pending': 'Очікування',
            'processing': 'В обробці', 
            'done': 'Виконано',
            'completed': 'Завершено',
            'failed': 'Невдалі'
        }
        
        for status, name in status_names.items():
            if status in current_stats:
                data = current_stats[status]
                report += f"\n        • {name}: {data['count']} заказів"
                
        
        #порівняння з початковою статистикою
        if initial_stats:
            report += f"\n\n        ЗМІНИ ЗА ЧАС СИМУЛЯЦІЇ:"
            for status in status_names.keys():
                initial_count = initial_stats.get(status, 0)
                current_count = current_stats.get(status, {}).get('count', 0)
                change = current_count - initial_count
                if change != 0:
                    sign = "+" if change > 0 else ""
                    report += f"\n        • {status_names[status]}: {sign}{change}"
        
        return report
    
    def save_simulation_report(self, additional_info=None):
        """Зберегти звіт симуляції у файл results_of_simulation.txt"""
        try:
            with self.file_lock:
                #підготовка звіту
                report = self._generate_simulation_report(additional_info)
                
                #додаємо до файлу
                with open(self.results_file, 'a', encoding='utf-8') as f:
                    f.write(report)
                    f.write("\n" + "="*100 + "\n\n")
                
                print(f"Звіт симуляції збережено у {self.results_file}")
                return True
                
        except Exception as e:
            print(f"Помилка збереження звіту симуляції: {e}")
            return False
    
    def _generate_simulation_report(self, additional_info=None):
        """Генерувати текст звіту симуляції"""
        end_time = datetime.now()
        duration = end_time - self.current_simulation["start_time"]
        
        #заголовок звіту
        report = f"""
                ЗВІТ СИМУЛЯЦІЇ РОБОТІВ
                Simulation ID: {self.current_simulation["simulation_id"]}
                Дата і час: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
                Тривалість тесту: {self._format_duration(duration)}
                Кількість роботів: {len(self.current_simulation["robots"])}

                --- ЗАГАЛЬНА СТАТИСТИКА ---
                """
        
        #аналіз по всіх роботах
        total_calls = {"a_star": 0, "dijkstra": 0}        
        total_success = {"a_star": 0, "dijkstra": 0}
        total_time = {"a_star": 0, "dijkstra": 0}
        active_robots = []
        
        for robot_id, robot_data in self.current_simulation["robots"].items():
            diagnostic = robot_data["diagnostic_data"]
            stats = robot_data["algorithm_stats"]
            
            #збираємо статистику алгоритмів
            for algorithm in ["a_star", "dijkstra"]:
                if algorithm in stats:
                    alg_stats = stats[algorithm]
                    total_calls[algorithm] += alg_stats.get("calls", 0)
                    total_success[algorithm] += alg_stats.get("successful_paths", 0)
                    total_time[algorithm] += alg_stats.get("total_time", 0)
            
            #збираємо дані про роботів
            active_robots.append(robot_id)
        #статистика алгоритмів
        for algorithm in ["a_star", "dijkstra"]:
            if total_calls[algorithm] > 0:
                success_rate = (total_success[algorithm] / total_calls[algorithm]) * 100
                avg_time = (total_time[algorithm] / total_calls[algorithm]) * 1000
                
                report += f"""
                    {algorithm.upper()}:
                    • Всього викликів: {total_calls[algorithm]}
                    • Успішних: {total_success[algorithm]} ({success_rate:.1f}%)
                    • Середній час: {avg_time:.2f} мс                    """
          #загальна статистика роботів
        report += f"""
                    СТАН РОБОТІВ:
                    • Активних роботів: {len(active_robots)}
                    """
        
        #додаємо статистику заказів
        orders_report = self.get_orders_statistics_report()
        report += orders_report
        
        #детальна інформація по кожному роботу
        report += "\n--- ДЕТАЛЬНА ІНФОРМАЦІЯ ПО РОБОТАХ ---\n"
        
        for robot_id in sorted(self.current_simulation["robots"].keys()):
            robot_data = self.current_simulation["robots"][robot_id]
            diagnostic = robot_data["diagnostic_data"]
            stats = robot_data["algorithm_stats"]
            report += f"""
                    РОБОТ #{robot_id}:
                    • Позиція: {diagnostic.get("position", [0, 0])}
                    • Товарів у переносці: {diagnostic.get("carrying_items", 0)}/6
                    • Доступних сусідів: {len(diagnostic.get("available_neighbors", []))}
                    """
            
            #статистика алгоритмів для робота
            for algorithm in ["a_star", "dijkstra"]:
                if algorithm in stats and stats[algorithm].get("calls", 0) > 0:
                    alg_stats = stats[algorithm]
                    success_rate = (alg_stats["successful_paths"] / alg_stats["calls"]) * 100
                    avg_time = alg_stats["avg_time"] * 1000
                    
                    report += f"""  • {algorithm.upper()}: {alg_stats["calls"]} викликів, {success_rate:.1f}% успіх, {avg_time:.2f} мс"""
        
        #додаткова інформація якщо є
        if additional_info:
            report += f"\n--- ДОДАТКОВА ІНФОРМАЦІЯ ---\n{additional_info}\n"
        
        return report
    
    def _format_duration(self, duration):
        """Форматувати тривалість у читабельний вигляд"""
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}г {minutes}хв {seconds}с"
        elif minutes > 0:
            return f"{minutes}хв {seconds}с"
        else:
            return f"{seconds}с"
    
    def get_last_simulation_summary(self):
        """Отримати зведення останньої симуляції"""
        if not self.current_simulation["robots"]:
            return "Немає даних симуляції"
        
        robot_count = len(self.current_simulation["robots"])
        duration = datetime.now() - self.current_simulation["start_time"]
        
        return f"Симуляція {self.current_simulation['simulation_id']}: {robot_count} роботів, {self._format_duration(duration)}"


#глобальна змінна для діагностики симуляції
_simulation_diagnostics = None

def init_simulation_diagnostics():
    """Ініціалізувати діагностику симуляції"""
    global _simulation_diagnostics
    _simulation_diagnostics = SimulationDiagnostics()
    print(f"Початок симуляції: {_simulation_diagnostics.current_simulation['simulation_id']}")

def add_robot_to_simulation(robot_id, diagnostic_data, algorithm_stats):
    """Додати робота до поточної симуляції"""
    global _simulation_diagnostics
    if _simulation_diagnostics:
        _simulation_diagnostics.add_robot_diagnostics(robot_id, diagnostic_data, algorithm_stats)

def save_simulation_results(additional_info=None):
    """Зберегти результати симуляції"""
    global _simulation_diagnostics
    if _simulation_diagnostics:
        success = _simulation_diagnostics.save_simulation_report(additional_info)
        if success:
            summary = _simulation_diagnostics.get_last_simulation_summary()
            print(f"Симуляція завершена: {summary}")
        return success
    return False

def get_simulation_summary():
    """Отримати зведення поточної симуляції"""
    global _simulation_diagnostics
    if _simulation_diagnostics:
        return _simulation_diagnostics.get_last_simulation_summary()
    return "Симуляція не ініціалізована"


def get_orders_statistics():
    """Отримати статистику заказів з поточної симуляції"""
    global _simulation_diagnostics
    if _simulation_diagnostics:
        return _simulation_diagnostics.get_orders_statistics_report()
    return "Симуляція не ініціалізована"

def get_orders_success_rate():
    """Отримати коефіцієнт успішності заказів"""
    global _simulation_diagnostics
    if _simulation_diagnostics:
        current_stats = _simulation_diagnostics._collect_current_orders_stats()
        return current_stats.get('_totals', {}).get('success_rate', 0)
    return 0

def save_orders_statistics_to_file(filename=None):
    """Зберегти статистику заказів в окремий файл"""
    global _simulation_diagnostics
    if not _simulation_diagnostics:
        return False
    
    if filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"simulation/orders_statistics_{timestamp}.txt"
    
    try:
        #створюємо директорію якщо її немає
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        stats_report = get_orders_statistics()
        current_stats = _simulation_diagnostics._collect_current_orders_stats()
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("ДЕТАЛЬНА СТАТИСТИКА ЗАКАЗІВ\n")
            f.write("=" * 50 + "\n")
            f.write(f"Згенеровано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Симуляція: {_simulation_diagnostics.current_simulation['simulation_id']}\n\n")
            
            f.write(stats_report)
            
            #додаємо JSON дані для машинного читання
            f.write("\n\n" + "=" * 50)
            f.write("\nДАНІ В ФОРМАТІ JSON:\n")
            f.write(json.dumps(current_stats, indent=2, ensure_ascii=False, default=str))
        
        print(f"Статистика заказів збережена в {filename}")
        return True
        
    except Exception as e:
        print(f"Помилка збереження статистики заказів: {e}")
        return False


