import pyodbc

def get_connection():
    conn_str = (
        "DRIVER={SQL Server};"
        "SERVER=localhost\\MSSQLSERVER1;"  
        "DATABASE=robotic_warehouse;"
        "Trusted_Connection=yes;"
    )

    try:
        #встановлюємо з'єднання
        conn = pyodbc.connect(conn_str)
        return conn
    
    except Exception as e:
        print("Помилка підключення до БД", e)
        return None
    
def get_warehouse_size():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT width, height FROM warehouse_config WHERE id = 1")
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0], result[1]  # width, height
    else:
        return 20, 41




