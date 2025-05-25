from db.connection import get_connection
from db.models import get_all_items, add_item
from  logic.orders import generate_random_order, process_order, clear_shelf
from simulation.admin_panel_gui import run_gui


# conn = get_connection()
# # generate_random_order(conn)
# # process_order(conn, 2)
# clear_shelf(conn, shelf_id=3)
# conn.close()

run_gui()























# ТЕСТУВАННЯ РОБОТИ З'єднання з БД

# if __name__ == '__main__':
#     conn = get_connection()
#     if not conn:
#         print("З'єднання не встановлено. Перевір параметри підключення.")
#         exit()
#     items = get_all_items(conn)
#     for item in items:
#         print(f"{item.id}: {item.name} - {item.description}")

#     conn.close()
    

