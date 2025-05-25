
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

#Координата зарядної станції
charging_station = (18, 1)



#Координата зони видачі (курʼєр забирає)
delivery_zone = (0, 1)

#Загальна сітка (можна використовувати для малювання)
grid_width = 20
grid_height = 41
