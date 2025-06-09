import time
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
    thread.daemon = True
    thread.start()
    
    
    diagnostic_data = robot.diagnose_current_state()
    # robot.print_statistics()
    
    #реєстрація робота в симуляції
    add_robot_to_simulation(robot_id, diagnostic_data, robot.navigator.algorithm_stats)
    
    return robot


print("Початок тестування роботів...")
init_simulation_diagnostics()

#список роботів для відстеження
robots = []

for r_id in [76, 77, 78, 79, 80, 81, 82, 83,]:
    robot = start_robot(r_id)
    robots.append(robot)
    time.sleep(0.5)  

print("Всі роботи запущені. Тест триває...")


input("Натисніть Enter, для завершення тесту...")

#збираємо фінальну статистику перед завершенням
print("Збір фінальної статистики...")
for robot in robots:
    try:
        #оновлюємо фінальні дані робота
        final_diagnostic = robot.diagnose_current_state()
        add_robot_to_simulation(robot.robot_id, final_diagnostic, robot.navigator.algorithm_stats)
    except Exception as e:
        print(f"Помилка збору фінальних даних робота #{robot.robot_id}: {e}")

# ДОДАЄМО: Зберігаємо результати симуляції
test_info = f"""
ПАРАМЕТРИ ТЕСТУ:
- Сітка: {grid_width}x{grid_height}
- Кількість роботів: {len(robots)}
- ID роботів: {[r.robot_id for r in robots]}
- Алгоритм за замовчуванням: A*
"""

save_simulation_results(test_info)
print("Тест завершено! Результати збережено у simulation/results_of_simulation.txt")