from simulation.warehouse_map import shelf_coords, pallet_coords, charging_station, grid_width, grid_height
import tkinter as tk
from tkinter import ttk, messagebox
from db.connection import get_connection
from logic.orders import (
    generate_random_order,
    process_order,
    clear_all_shelves_for_order
)

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
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM orders ORDER BY id DESC")
        orders = cursor.fetchall()
        conn.close()
        orders_list.delete(0, tk.END)
        for order in orders:
            orders_list.insert(tk.END, f"#{order[0]} — {order[1]}")

    def on_create_order():
        conn = get_connection()
        generate_random_order(conn)
        conn.close()
        refresh_orders()
    

    def delete_order(order_id):
        """Видалити замовлення та всі пов'язані з ним позиції"""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Спочатку видаляємо товари з замовлення
            cursor.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            
            # Потім видаляємо саме замовлення
            cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
            
            conn.commit()
            print(f"Замовлення #{order_id} успішно видалено.")
        except Exception as e:
            print(f"Помилка при видаленні замовлення #{order_id}: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def on_delete_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для видалення.")
            return
        order_id = int(orders_list.get(selected[0]).split('—')[0].strip()[1:])
        delete_order(order_id)
        refresh_orders()

    def on_process_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для обробки.")
            return
        order_id = int(orders_list.get(selected[0]).split('—')[0].strip()[1:])
        conn = get_connection()
        process_order(conn, order_id)
        conn.close()
        refresh_orders()
        refresh_shelves()

    def on_clear_order():
        selected = orders_list.curselection()
        if not selected:
            messagebox.showinfo("Увага", "Оберіть замовлення для очищення.")
            return
        order_id = int(orders_list.get(selected[0]).split('—')[0].strip()[1:])
        conn = get_connection()
        clear_all_shelves_for_order(conn, order_id)
        conn.close()
        refresh_orders()
        refresh_shelves()

    tk.Button(orders_frame, text="➕ Створити замовлення", command=on_create_order).pack(pady=5)
    tk.Button(orders_frame, text="⚙️ Обробити замовлення", command=on_process_order).pack(pady=5)
    tk.Button(orders_frame, text="🧹 Очистити полиці", command=on_clear_order).pack(pady=5)
    tk.Button(orders_frame, text="🗑️ Видалити замовлення", command=on_delete_order).pack(pady=5)

    # === Фрейм "Полиці" ===
    shelves_frame = ttk.Frame(tabs)
    tabs.add(shelves_frame, text="Полиці")

    shelves_list = tk.Listbox(shelves_frame, width=60, height=25)
    shelves_list.pack(pady=10)

    def refresh_shelves():
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT shelf_code, status, capacity, current_order_id
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

    tk.Button(shelves_frame, text="🔄 Оновити полиці", command=refresh_shelves).pack(pady=5)

    
    # === Фрейм "Склад" ===
    warehouse_frame = ttk.Frame(tabs)
    tabs.add(warehouse_frame, text="Склад")

    canvas = tk.Canvas(warehouse_frame, width=1000, height=700, bg='white')
    canvas.pack(side='left', fill='both', expand=True)

    scrollbar = tk.Scrollbar(warehouse_frame, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')

    canvas.configure(yscrollcommand=scrollbar.set)
    

    def draw_warehouse():
        canvas.delete("all")

        cell_size = 65  # Єдиний розмір усіх елементів
        padding = 0     # Без проміжків між клітинками

        # === Сітка з координатами ===
        for x in range(grid_width):
            for y in range(grid_height):
                x1 = x * cell_size
                y1 = y * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                canvas.create_rectangle(x1, y1, x2, y2, outline="#cccccc")
                canvas.create_text(x1 + 5, y1 + 5, text=f"({x},{y})", anchor="nw", font=("Arial", 5), fill="#999999")

        # === Полиці ===
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT shelf_code, status FROM shelves")
        shelf_statuses = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        for code, (x, y) in shelf_coords.items():
            x1 = x * cell_size
            y1 = y * cell_size
            x2 = x1 + cell_size
            y2 = y1 + cell_size

            # Определяем цвет по статусу
            status = shelf_statuses.get(code, 'free')
            if status == 'busy':
                color = "#ff9999"  # Красный для занятых
            else:
                color = "#add8e6"  # Голубой для свободных

            canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="black")
            canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=code, font=("Arial", 6), width=cell_size - 10)


        # === Палети ===
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.label, i.item_id, i.quantity, it.name
            FROM pallets p
            LEFT JOIN inventory i ON i.location_type = 'pallet' AND i.location_id = p.id
            LEFT JOIN items it ON i.item_id = it.id
        """)
        pallets = cursor.fetchall()
        conn.close()

        for pallet in pallets:
            pallet_id = pallet[0]
            x, y = pallet_coords.get(pallet_id, (0, 0))
            x1 = x * cell_size
            y1 = y * cell_size
            x2 = x1 + cell_size
            y2 = y1 + cell_size

            item_name = pallet[4]
            quantity = pallet[3]
            label = pallet[1] or f"P{pallet_id}"

            color = "#90ee90" if item_name and quantity else "#d3d3d3"
            text = f"{item_name}\n{quantity}" if item_name and quantity else "порожньо"

            canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="black")
            canvas.create_text((x1 + x2) / 2, y1 + 12, text=label, font=("Arial", 7, "bold"), width=cell_size - 10)
            canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 10, text=text, font=("Arial", 7), width=cell_size - 10)

        # === Станція зарядки ===
        x, y = charging_station
        x1 = x * cell_size
        y1 = y * cell_size
        x2 = x1 + cell_size
        y2 = y1 + cell_size
        canvas.create_oval(x1, y1, x2, y2, fill="#ffb6c1", outline="black")
        canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="Зарядка", font=("Arial", 8), width=cell_size - 10)

        canvas.configure(scrollregion=canvas.bbox("all"))

        # === Роботи ===
        update_robots_on_canvas()

    tk.Button(warehouse_frame, text="Оновити карту", command=draw_warehouse).pack(pady=5)

    robot_shapes = {}

    def update_robots_on_canvas():
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, x, y FROM robots")
        robots = cursor.fetchall()
        conn.close()

        cell_size = 65
        r = 10  # радиус кружка

        # Удаляем старые кружки и надписи
        for shape_id, text_id in robot_shapes.values():
            canvas.delete(shape_id)
            canvas.delete(text_id)
        robot_shapes.clear()

        for robot in robots:
            robot_id = robot[0]
            name = robot[1]
            x = robot[2]
            y = robot[3]

            x_center = x * cell_size + cell_size // 2
            y_center = y * cell_size + cell_size // 2

            x1 = x_center - r
            y1 = y_center - r
            x2 = x_center + r
            y2 = y_center + r

            # Рисуем кружок
            shape_id = canvas.create_oval(x1, y1, x2, y2, fill="orange")
            # Рисуем имя робота над ним
            text_id = canvas.create_text(x_center, y1 - 10, text=name, font=("Arial", 10))

            # Сохраняем оба ID
            robot_shapes[robot_id] = (shape_id, text_id)

        # Перезапуск через 1 секунду
        canvas.after(1000, update_robots_on_canvas)



    
    draw_warehouse()
    
    refresh_orders()
    refresh_shelves()
    root.mainloop()
