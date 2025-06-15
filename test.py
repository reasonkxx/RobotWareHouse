import time
import sys # Додаємо sys для роботи з аргументами командного рядка
from db.connection import get_connection
from logic.robot import RobotNavigator
from simulation.warehouse_map import shelf_coords, pallet_coords, grid_width, grid_height
from simulation.file_diagnostics import init_simulation_diagnostics, save_simulation_results, add_robot_to_simulation
from threading import Thread


def start_robot(robot_id):
    robot = RobotNavigator(
        robot_id=robot_id,
        grid_width=grid_width,
        grid_height=grid_height,
        shelf_coords=shelf_coords,
        pallet_coords=pallet_coords
    )

    thread = Thread(target=robot.run)
    thread.daemon = True #потік завершиться, коли завершиться основний потік
    thread.start()

    #початкова діагностика та реєстрація
    diagnostic_data = robot.diagnose_current_state()
    add_robot_to_simulation(robot_id, diagnostic_data, robot.navigator.algorithm_stats)

    return robot

if __name__ == "__main__":
    print("Початок тестування роботів...")
    init_simulation_diagnostics()

    robots_to_run = [] #список ID роботів, яких потрібно запустити

    #значення за замовчуванням, якщо аргументи не передано або вони некоректні
    default_robot_ids = [76, 77, 78, 79, 80, 81, 82, 83]

    if len(sys.argv) > 1: 
        try:
            ids_from_panel_str = sys.argv[1]
            parsed_ids = [int(id_str.strip()) for id_str in ids_from_panel_str.split(',') if id_str.strip()]
            
            if parsed_ids: 
                robots_to_run = parsed_ids
                print(f"Роботи для запуску (з адмін-панелі): {robots_to_run}")
            else:
                print("Попередження: Отримано порожній список ID з адмін-панелі. Використовуються ID за замовчуванням.")
                robots_to_run = default_robot_ids
        except ValueError:
            print("Помилка: Не вдалося розпарсити ID роботів з аргументів. Переконайтеся, що це числа, розділені комою.")
            print("Використовуються ID за замовчуванням.")
            robots_to_run = default_robot_ids
        except Exception as e:
            print(f"Неочікувана помилка при обробці аргументів: {e}")
            print("Використовуються ID за замовчуванням.")
            robots_to_run = default_robot_ids
    else:
        #якщо аргументи не передано, використовуємо список за замовчуванням
        print("Аргументи не передано. Використовуються ID роботів за замовчуванням.")
        robots_to_run = default_robot_ids

    # список для відстеження активних об'єктів роботів
    active_robots_objects = []

    if not robots_to_run:
        print("Немає роботів для запуску. Завершення.")
    else:
        print(f"Запуск симуляції з роботами: {robots_to_run}")
        for r_id in robots_to_run:
            try:
                robot_obj = start_robot(r_id)
                active_robots_objects.append(robot_obj)
                time.sleep(0.1) # невелика затримка між запусками потоків
            except Exception as e:
                print(f"Помилка при запуску робота ID {r_id}: {e}")
        
        if active_robots_objects:
            print(f"Всі {len(active_robots_objects)} обрані роботи запущені. Симуляція триває...")
            # чекаємо на введення користувача для завершення
            input("Натисніть Enter для завершення симуляції...")
        else:
            print("Не вдалося запустити жодного робота.")

    #збираємо фінальну статистику перед завершенням
    if active_robots_objects:
        print("Збір фінальної статистики...")
        for robot in active_robots_objects:
            try:
                #оновлюємо фінальні дані робота
                final_diagnostic_data = robot.diagnose_current_state() 
                add_robot_to_simulation(robot.robot_id, final_diagnostic_data, robot.navigator.algorithm_stats)
            except Exception as e:
                print(f"Помилка збору фінальних даних для робота #{robot.robot_id}: {e}")

    #зберігаємо результати симуляції
    test_info = f"""
ПАРАМЕТРИ СИМУЛЯЦІЇ:
- Сітка: {grid_width}x{grid_height}
- Кількість запущених роботів: {len(active_robots_objects)}
- ID запущених роботів: {[r.robot_id for r in active_robots_objects]}
"""

    save_simulation_results(test_info)
    print("Симуляцію завершено! Результати збережено у simulation/results_of_simulation.txt")