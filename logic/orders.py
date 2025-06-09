import random
from datetime import datetime

import random

def generate_random_order(conn):
    cursor = conn.cursor()

    #Створюємо нове замовлення та одразу отримуємо його ID
    status = 'pending'
    cursor.execute("""
        INSERT INTO orders (created_at, status)
        OUTPUT INSERTED.id
        VALUES (GETDATE(), ?)
    """, (status,))
    result = cursor.fetchone()
    order_id = int(result[0]) if result else None

    if not order_id:
        print("Помилка: не вдалося отримати ID створеного замовлення.")
        return

    print(f"Створено замовлення №{order_id}")

    #Отримуємо всі доступні товари
    cursor.execute("SELECT id FROM items")
    items = [row.id for row in cursor.fetchall()]

    if not items:
        print("У таблиці товарів (items) немає записів.")
        return

    #Випадково вибираємо кілька товарів для замовлення
    num_items = random.randint(1, 2)
    selected_items = random.sample(items, num_items)

    for item_id in selected_items:
        quantity = random.randint(1, 4)
        cursor.execute("""
            INSERT INTO order_items (order_id, item_id, quantity)
            VALUES (?, ?, ?)
        """, (order_id, item_id, quantity))

    conn.commit()
    print(f"До замовлення №{order_id} додано {num_items} позицій.")


def process_order(conn, order_id):
    cursor = conn.cursor()

    #Отримати всі товари з замовлення
    cursor.execute("""
        SELECT item_id, quantity FROM order_items
        WHERE order_id = ?
    """, (order_id,))
    items = cursor.fetchall()

    for item in items:
        item_id = item[0]
        qty_needed = item[1]

        #Знайти потрібний товар на палетах
        cursor.execute("""
            SELECT id, location_id, quantity FROM inventory
            WHERE item_id = ? AND location_type = 'pallet'
            ORDER BY quantity DESC
        """, (item_id,))
        sources = cursor.fetchall()

        for source in sources:
            if qty_needed <= 0:
                break

            source_id = source[0]
            location_id = source[1]
            available = source[2]
            take = min(available, qty_needed)

            #Зменшити кількість на палеті
            new_qty = available - take
            if new_qty > 0:
                cursor.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, source_id))
            else:
                cursor.execute("DELETE FROM inventory WHERE id = ?", (source_id,))

            qty_needed -= take

            #Знайти вільну полицю
            cursor.execute("""
                SELECT id FROM shelves
                WHERE status = 'free'
                ORDER BY id
            """)
            shelf = cursor.fetchone()
            if not shelf:
                print("Немає вільних полиць!")
                conn.rollback()
                return

            shelf_id = shelf[0]

            #Покласти товар на полицю
            cursor.execute("""
                INSERT INTO inventory (item_id, location_type, location_id, quantity)
                VALUES (?, 'shelf', ?, ?)
            """, (item_id, shelf_id, take))

            #Оновити полицю
            cursor.execute("""
                UPDATE shelves
                SET status = 'busy', current_order_id = ?
                WHERE id = ?
            """, (order_id, shelf_id))

    #Завершити замовлення
    cursor.execute("UPDATE orders SET status = 'done' WHERE id = ?", (order_id,))
    conn.commit()
    print(f"Замовлення #{order_id} виконано")

def clear_shelf(conn, shelf_id):
    cursor = conn.cursor()

    # Отримуємо замовлення, яке прив'язане до полиці
    cursor.execute("""
        SELECT current_order_id FROM shelves WHERE id = ?
    """, (shelf_id,))
    result = cursor.fetchone()

    if not result or result[0] is None:
        print(f"Полиця #{shelf_id} не пов'язана з жодним замовленням.")
        return

    order_id = result[0]

    # Видаляємо товари з inventory, які на цій полиці
    cursor.execute("""
        DELETE FROM inventory
        WHERE location_type = 'shelf' AND location_id = ?
    """, (shelf_id,))

    # Очищаємо полицю
    cursor.execute("""
        UPDATE shelves
        SET status = 'free', current_order_id = NULL
        WHERE id = ?
    """, (shelf_id,))

    # Перевіряємо, чи ще є полиці з цим замовленням
    cursor.execute("""
        SELECT COUNT(*) FROM shelves
        WHERE current_order_id = ?
    """, (order_id,))
    remaining = cursor.fetchone()[0]

    # Якщо більше немає — оновлюємо статус замовлення
    if remaining == 0:
        cursor.execute("""
            UPDATE orders
            SET status = 'completed'
            WHERE id = ?
        """, (order_id,))
        print(f"Замовлення #{order_id} повністю вивантажено.")

    conn.commit()
    print(f"Полиця #{shelf_id} очищена.")


def clear_all_shelves_for_order(conn, order_id):
    cursor = conn.cursor()

    #Знайти всі полиці, прив'язані до цього замовлення
    cursor.execute("""
        SELECT id FROM shelves
        WHERE current_order_id = ?
    """, (order_id,))
    shelf_ids = [row[0] for row in cursor.fetchall()]

    if not shelf_ids:
        print(f"Немає полиць для замовлення #{order_id}.")
        return

    print(f"Очищення {len(shelf_ids)} полиць для замовлення #{order_id}:")

    for shelf_id in shelf_ids:
        clear_shelf(conn, shelf_id) 

    print(f"Замовлення #{order_id} повністю видане.")




# def process_order(order_id):

#     return
