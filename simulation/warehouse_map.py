from db.connection import get_warehouse_size

grid_width, grid_height = get_warehouse_size()
#Координати полиць (40 рядів × 3 рівні)
shelf_coords = {}

for i in range(40):
    base_x = 1  # полиці зліва
    base_y = i + 1  # кожен рядок вниз
    shelf_coords[f"{i + 1}-1"] = (base_x, base_y)
    shelf_coords[f"{i + 1}-2"] = (base_x + 1, base_y)
    shelf_coords[f"{i + 1}-3"] = (base_x + 2, base_y)

#Координати палет (30 штук, 5 стовпців × 6 рядів)
pallet_coords = {}
pallet_number = 1
for row in range(2, 14, 2):  # ряди Y: 2,4,6,8,10,12
    for col in range(6, 16, 2):  # стовпці X: 5,7,9,11,13
        pallet_coords[pallet_number] = (col, row)
        pallet_number += 1

charging_station_coords = []
for y in range(2,17):
    charging_station_coords.append((19, y))

CHARGING_STATIONS = {
    76: (19, 2),   # Робот #76 Зарядка (19, 2)
    77: (19, 3),   # Робот #77 Зарядка (19, 3)
    78: (19, 4),   # Робот #78 Зарядка (19, 4)
    79: (19, 5),   # Робот #79 Зарядка (19, 5)
    80: (19, 6),   # Робот #80 Зарядка (19, 6)
    81: (19, 7),   # Робот #81 Зарядка (19, 7)
    82: (19, 8),   # Робот #82 Зарядка (19, 8)
    83: (19, 9),   # Робот #83 Зарядка (19, 9)
    84: (19, 10),  # Робот #84 Зарядка (19, 10)
    85: (19, 11),  # Робот #85 Зарядка (19, 11)
    86: (19, 12),  # Робот #86 Зарядка (19, 12)
    87: (19, 13),   # Робот #81 Зарядка (19, 13)
    88: (19, 14),   # Робот #82 Зарядка (19, 14)
    89: (19, 15),   # Робот #83 Зарядка (19, 15)
    90: (19, 16),  # Робот #84 Зарядка (19, 16)
}

#Координата зони видачі
delivery_zone = (0, 1)


