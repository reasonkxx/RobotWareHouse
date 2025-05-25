import time
from db.connection import get_connection
from logic.robot import RobotNavigator
from simulation.warehouse_map import shelf_coords, pallet_coords, charging_station, grid_width, grid_height
from threading import Thread



def start_robot(robot_id):
    robot = RobotNavigator(
        robot_id=robot_id,
        grid_width=grid_width,
        grid_height=grid_height,
        shelf_coords=shelf_coords,
        pallet_coords=pallet_coords,
        charging_station=charging_station
    )
    thread = Thread(target=robot.run)
    thread.daemon = True
    thread.start()


for r_id in [76, 77, 78, 79, 80, 81, 82, 83, 84, 85]:
    start_robot(r_id)

input("Натисніть Enter, для завершення тесту...")