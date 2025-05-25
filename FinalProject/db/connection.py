import pyodbc

def get_connection():
    conn_str = (
        "DRIVER={SQL Server};"
        "SERVER=localhost\\MSSQLSERVER1;"  
        "DATABASE=robotic_warehouse;"
        "Trusted_Connection=yes;"
    )

    try:
        # Встановлюємо з'єднання
        conn = pyodbc.connect(conn_str)
        return conn
    
    except Exception as e:
        print("Помилка підключення до БД", e)
        return None




