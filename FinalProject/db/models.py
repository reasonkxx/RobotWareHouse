import pyodbc

def get_all_items(conn):
    """Отримати всі товари з таблиці items."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description FROM items")
    return cursor.fetchall()


def get_item_by_id(conn, item_id):
    """Отримати товар по ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description FROM items WHERE id = ?", (item_id,))
    return cursor.fetchone()


def add_item(conn, name, description):
    """Додати новий товар."""
    cursor = conn.cursor()
    cursor.execute("INSERT INTO items (name, description) VALUES (?, ?)", (name, description))
    conn.commit()


def update_item(conn, item_id, name, description):
    """Оновити дані товара по ID."""
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE items SET name = ?, description = ? WHERE id = ?",
        (name, description, item_id)
    )
    conn.commit()


def delete_item(conn, item_id):
    """Видалити товар по ID."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()


#Orders
def create_order(conn, status):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (created_at, status) VALUES (GETDATE(), ?)", (status,))
    conn.commit()


def get_all_orders(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, created_at, status FROM orders")
    return cursor.fetchall()


def get_order_by_id(conn, order_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, created_at, status FROM orders WHERE id = ?", (order_id,))
    return cursor.fetchone()


def update_order_status(conn, order_id, status):
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()


def delete_order(conn, order_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()


#Order_Items
def add_order_item(conn, order_id, item_id, quantity):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO order_items (order_id, item_id, quantity) VALUES (?, ?, ?)",
                   (order_id, item_id, quantity))
    conn.commit()

def get_order_items(conn, order_id):
    cursor = conn.cursor()
    cursor.execute("SELECT id, item_id, quantity FROM order_items WHERE order_id = ?", (order_id,))
    return cursor.fetchall()

def update_order_item_quantity(conn, order_item_id, quantity):
    cursor = conn.cursor()
    cursor.execute("UPDATE order_items SET quantity = ? WHERE id = ?", (quantity, order_item_id))
    conn.commit()

def delete_order_item(conn, order_item_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM order_items WHERE id = ?", (order_item_id,))
    conn.commit()

#shelves
def create_shelf(conn, shelf_code, capacity):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO shelves (shelf_code, capacity) VALUES (?, ?)", (shelf_code, capacity))
    conn.commit()

def get_all_shelves(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, shelf_code, capacity FROM shelves")
    return cursor.fetchall()

def update_shelf_capacity(conn, shelf_id, capacity):
    cursor = conn.cursor()
    cursor.execute("UPDATE shelves SET capacity = ? WHERE id = ?", (capacity, shelf_id))
    conn.commit()

def delete_shelf(conn, shelf_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM shelves WHERE id = ?", (shelf_id,))
    conn.commit()

#robots
def create_robot(conn, name):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO robots (name) VALUES (?)", (name,))
    conn.commit()

def get_all_robots(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status, x, y, battery, updated_at FROM robots")
    return cursor.fetchall()

def update_robot_status(conn, robot_id, status):
    cursor = conn.cursor()
    cursor.execute("UPDATE robots SET status = ?, updated_at = GETDATE() WHERE id = ?", (status, robot_id))
    conn.commit()

def update_robot_position(conn, robot_id, x, y):
    cursor = conn.cursor()
    cursor.execute("UPDATE robots SET x = ?, y = ?, updated_at = GETDATE() WHERE id = ?", (x, y, robot_id))
    conn.commit()

def delete_robot(conn, robot_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM robots WHERE id = ?", (robot_id,))
    conn.commit()

#Inventory

#Додати товар до обліку (робот поклав товар)
def add_inventory_item(conn, item_id, location_type, location_id, quantity):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO inventory (item_id, location_type, location_id, quantity)
        VALUES (?, ?, ?, ?)
    """, (item_id, location_type, location_id, quantity))
    conn.commit()

#Отримати всю таблицю інвентаризації
def get_inventory(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, item_id, location_type, location_id, quantity FROM inventory")
    return cursor.fetchall()

#Отримати всі товари, що зберігаються на конкретному типі (наприклад, 'shelf')
def get_inventory_by_type(conn, location_type):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inventory WHERE location_type = ?", (location_type,))
    return cursor.fetchall()

#Оновити кількість товару
def update_inventory_quantity(conn, inventory_id, new_quantity):
    cursor = conn.cursor()
    cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_quantity, inventory_id))
    conn.commit()

#Ви  далити запис (наприклад, якщо кур'єр забрав товар з полиці)
def delete_inventory_item(conn, inventory_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
    conn.commit()
