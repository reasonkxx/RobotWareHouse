import subprocess
import os
import tkinter as tk
from tkinter import ttk, messagebox
from db.connection import get_connection 
from logic.orders import ( 
    generate_random_order,
    process_order,
    clear_all_shelves_for_order
)
from simulation.warehouse_map import shelf_coords, pallet_coords, grid_width, grid_height, charging_station_coords

#cловник для зберігання стану "включеності" роботів (айді: BooleanVar)
robot_selection_states = {}

def run_gui():
    root = tk.Tk()
    root.title("Адмін-панель складу")
    root.geometry("1200x1024")

    # === Вкладки ===
    tabs = ttk.Notebook(root)
    tabs.pack(fill='both', expand=True)

    # === Фрейм "Замовлення" ===
    orders_frame = ttk.Frame(tabs)
    tabs.add(orders_frame, text="Замовлення")

    orders_list = tk.Listbox(orders_frame, width=50, height=20)
    orders_list.pack(pady=10)

    def refresh_orders():
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, status FROM orders ORDER BY id DESC")
            orders = cursor.fetchall()
            conn.close()
            orders_list.delete(0, tk.END)
            for order in orders:
                orders_list.insert(tk.END, f"#{order[0]} — {order[1]}")
        except Exception as e:
            messagebox.showerror("Помилка БД", f"Не вдалося оновити замовлення: {e}")


    def on_create_order():
        try:
            conn = get_connection()
            generate_random_order(conn)
            conn.close()
            refresh_orders()
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося створити замовлення: {e}")


    def delete_order(order_id):
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
            conn.commit()
            print(f"Замовлення #{order_id} успішно видалено.")
        except Exception as e:
            print(f"Помилка при видаленні замовлення #{order_id}: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    def on_delete_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для видалення.")
            return
        try:
            order_id_str = orders_list.get(selected[0]).split('—')[0].strip()[1:]
            order_id = int(order_id_str)
            if messagebox.askyesno("Підтвердження", f"Ви впевнені, що хочете видалити замовлення #{order_id}?"):
                delete_order(order_id)
                refresh_orders()
        except ValueError:
             messagebox.showerror("Помилка", "Некоректний ID замовлення.")
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося видалити замовлення: {e}")


    def on_process_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для обробки.")
            return
        try:
            order_id_str = orders_list.get(selected[0]).split('—')[0].strip()[1:]
            order_id = int(order_id_str)
            conn = get_connection()
            process_order(conn, order_id) 
            conn.close()
            refresh_orders()
            refresh_shelves() 
        except ValueError:
             messagebox.showerror("Помилка", "Некоректний ID замовлення.")
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося обробити замовлення: {e}")


    def on_clear_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для очищення полиць.")
            return
        try:
            order_id_str = orders_list.get(selected[0]).split('—')[0].strip()[1:]
            order_id = int(order_id_str)
            conn = get_connection()
            clear_all_shelves_for_order(conn, order_id) 
            conn.close()
            refresh_orders()
            refresh_shelves()
        except ValueError:
             messagebox.showerror("Помилка", "Некоректний ID замовлення.")
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося очистити полиці: {e}")


    tk.Button(orders_frame, text="Створити замовлення", command=on_create_order).pack(pady=5)
    tk.Button(orders_frame, text="Обробити замовлення", command=on_process_order).pack(pady=5)
    tk.Button(orders_frame, text="Очистити полиці (для замовлення)", command=on_clear_order).pack(pady=5)
    tk.Button(orders_frame, text="Видалити замовлення", command=on_delete_order).pack(pady=5)

    # === Фрейм "Полиці" ===
    shelves_frame = ttk.Frame(tabs)
    tabs.add(shelves_frame, text="Полиці")

    shelves_list = tk.Listbox(shelves_frame, width=60, height=25)
    shelves_list.pack(pady=10)

    def refresh_shelves():
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT shelf_code, status, capacity, order_id
                FROM shelves
                ORDER BY id
            """)
            shelves = cursor.fetchall()
            conn.close()
            shelves_list.delete(0, tk.END)
            for s in shelves:
                code, status, cap, order_id = s
                order_text = f"#{order_id}" if order_id else "—"
                shelves_list.insert(tk.END, f"{code} | Статус: {status} | Місткість: {cap} | Замовлення: {order_text}")
        except Exception as e:
            messagebox.showerror("Помилка БД", f"Не вдалося оновити полиці: {e}")

    tk.Button(shelves_frame, text="🔄 Оновити полиці", command=refresh_shelves).pack(pady=5)


    # === Фрейм "Роботи"===
    robots_setup_frame = ttk.Frame(tabs)
    tabs.add(robots_setup_frame, text="Роботи")

    tk.Label(robots_setup_frame, text="Управління активними роботами:", font=("Arial", 14)).pack(pady=10)

    robot_list_frame = tk.Frame(robots_setup_frame)
    robot_list_frame.pack(pady=10, fill="x", padx=20)

    robot_checkbuttons = {} # {robot_id: (IntVar_variable, Checkbutton_widget)}

    def populate_robot_list():
        for widget in robot_list_frame.winfo_children():
            widget.destroy()
        robot_checkbuttons.clear()
        global robot_selection_states

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM robots ORDER BY id")
            all_robots_from_db = cursor.fetchall()
            conn.close()

            if not all_robots_from_db:
                tk.Label(robot_list_frame, text="У базі даних немає роботів. Додайте їх спочатку.").pack()
                return

            tk.Label(robot_list_frame, text="Оберіть роботів для запуску в симуляції:", font=("Arial", 11, "bold")).pack(anchor="w")

            for robot_id, robot_name in all_robots_from_db:
                if robot_id not in robot_selection_states:
                    robot_selection_states[robot_id] = tk.BooleanVar(value=True) # За замовчуванням всі включені

                var = robot_selection_states[robot_id]
                cb = tk.Checkbutton(robot_list_frame, text=f"{robot_name} (ID: {robot_id})", variable=var,
                                    onvalue=True, offvalue=False)
                cb.pack(anchor="w", padx=10)
                robot_checkbuttons[robot_id] = (var, cb) 
        except Exception as e:
            messagebox.showerror("Помилка БД", f"Не вдалося завантажити список роботів: {e}")


    tk.Button(robots_setup_frame, text="🔄 Оновити список роботів з БД", command=populate_robot_list).pack(pady=5)


    # === Фрейм "Склад" ===
    warehouse_frame = ttk.Frame(tabs)
    tabs.add(warehouse_frame, text="Склад")

    buttons_frame_warehouse = tk.Frame(warehouse_frame) 
    buttons_frame_warehouse.pack(side='top', fill='x', pady=5)

    canvas = tk.Canvas(warehouse_frame, width=1000, height=700, bg='white')
    canvas.pack(side='left', fill='both', expand=True)

    scrollbar = tk.Scrollbar(warehouse_frame, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')
    canvas.configure(yscrollcommand=scrollbar.set)
    auto_update_id = None # 

    def draw_warehouse():
        canvas.delete("all")
        cell_size = 65 
        
        # === Сітка з координатами ===
        for x_coord in range(grid_width):
            for y_coord in range(grid_height):
                x1, y1 = x_coord * cell_size, y_coord * cell_size
                x2, y2 = x1 + cell_size, y1 + cell_size
                canvas.create_rectangle(x1, y1, x2, y2, outline="#cccccc")
                canvas.create_text(x1 + 5, y1 + 5, text=f"({x_coord},{y_coord})", anchor="nw", font=("Arial", 5), fill="#999999")


        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Полиці
            cursor.execute("SELECT shelf_code, status FROM shelves")
            shelf_statuses = {row[0]: row[1] for row in cursor.fetchall()}
            for code, (x, y) in shelf_coords.items():
                x1, y1 = x * cell_size, y * cell_size
                x2, y2 = x1 + cell_size, y1 + cell_size
                status = shelf_statuses.get(code, 'free')
                color = "#ff9999" if status == 'busy' else "#add8e6"
                canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="black")
                canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=code, font=("Arial", 6), width=cell_size - 10)

            # Палети
            cursor.execute("""
                SELECT p.id, p.label, i.item_id, i.quantity, it.name
                FROM pallets p
                LEFT JOIN inventory i ON i.location_type = 'pallet' AND i.location_id = p.id
                LEFT JOIN items it ON i.item_id = it.id
            """)
            pallets_data = cursor.fetchall()
            for pallet_id_db, label, _, quantity, item_name in pallets_data:
                x, y = pallet_coords.get(pallet_id_db, (-1, -1)) 
                if x == -1: continue #Пропускаємо, якщо координати не знайдено
                x1, y1 = x * cell_size, y * cell_size
                x2, y2 = x1 + cell_size, y1 + cell_size
                color = "#90ee90" if item_name and quantity else "#d3d3d3"
                text_content = f"{item_name}\n{quantity}" if item_name and quantity else "порожньо"
                canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="black")
                canvas.create_text((x1 + x2) / 2, y1 + 12, text=label or f"P{pallet_id_db}", font=("Arial", 7, "bold"), width=cell_size - 10)
                canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 10, text=text_content, font=("Arial", 7), width=cell_size - 10)

            #зарядні станції
            for i, (x, y) in enumerate(charging_station_coords, 1):
                x1, y1 = x * cell_size, y * cell_size
                x2, y2 = x1 + cell_size, y1 + cell_size
                canvas.create_rectangle(x1, y1, x2, y2, fill="#0044ff", outline="black", width=2)
                canvas.create_text((x1 + x2) / 2, y2 - 8, text=f"C{i}", font=("Arial", 8, "bold"), fill="white")

            #роботи
            cursor.execute("SELECT id, name, x, y FROM robots")
            robots_db_data = cursor.fetchall()
            r_oval = 10 #радіус овалу

            for robot_id_db, name, x_db, y_db in robots_db_data:
                x_center = x_db * cell_size + cell_size // 2
                y_center = y_db * cell_size + cell_size // 2
                
                x1_oval = x_center - r_oval
                y1_oval = y_center - r_oval
                x2_oval = x_center + r_oval
                y2_oval = y_center + r_oval

                #визначаємо колір залежно від того, чи обраний робот для симуляції
                is_active = robot_id_db in robot_selection_states and robot_selection_states[robot_id_db].get()
                robot_fill_color = "orange" if is_active else "gray" # Активні - помаранчеві, неактивні - сірі
                robot_outline_color = "black"
                text_color = "black"
                #малюємо робота
                canvas.create_oval(x1_oval, y1_oval, x2_oval, y2_oval, fill=robot_fill_color, outline=robot_outline_color)
                #малюємо айді робота всередині овалу
                canvas.create_text(x_center, y_center, text=str(robot_id_db), font=("Arial", 8, "bold"), fill=text_color)
                canvas.create_text(x_center, y1_oval - 10, text=name, font=("Arial", 9), fill=text_color)

        except Exception as e:
            print(f"Помилка при малюванні складу (роботи): {e}") 
        finally:
            if conn: 
                conn.close()
        canvas.configure(scrollregion=canvas.bbox("all"))


    def auto_update_warehouse():
        global auto_update_id
        draw_warehouse()
        auto_update_id = canvas.after(500, auto_update_warehouse) #500 мс

    def run_test_simulation():
        global robot_selection_states
        selected_robot_ids = [robot_id for robot_id, var_obj in robot_selection_states.items() if var_obj.get()]

        if not selected_robot_ids:
            messagebox.showwarning("Увага", "Жоден робот не обраний для запуску симуляції!")
            return
        try:
            test_script_path = r"E:\Work\FinalProject\test.py"

            if not os.path.exists(test_script_path):
                messagebox.showerror("Помилка", f"Файл test.py не знайдено за шляхом: {test_script_path}\nПеревірте шлях у коді.")
                return

            robot_ids_arg = ",".join(map(str, selected_robot_ids))
                
            creation_flags = subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            subprocess.Popen(['python', test_script_path, robot_ids_arg], creationflags=creation_flags)
                
            messagebox.showinfo("Успіх", f"Симуляція запущена в новому вікні з роботами: {robot_ids_arg}!")
        except Exception as e:
            messagebox.showerror("Помилка запуску", f"Не вдалося запустити симуляцію: {str(e)}")

    tk.Button(buttons_frame_warehouse, text="Запуск симуляції", command=run_test_simulation, bg='#90EE90').pack(side='left', padx=5)

    #початкове завантаження даних
    refresh_orders()
    refresh_shelves()
    populate_robot_list()
    auto_update_warehouse() #запускаємо автоматичне оновлення візуалізації

    root.mainloop()

if __name__ == '__main__':
    run_gui()