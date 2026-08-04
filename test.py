from pathlib import Path
from tkinter import *
from tkinter import filedialog, messagebox
import re

FILE=Path.home() / r"Documents\My Games\WarThunder\Saves\53423873\production\UserSights\all_tanks\Ozen_Small_Right.blk"
print(FILE)




"""def extract_section(text, name):
    start = text.find(name)

    if start == -1:
        return None

    brace_start = text.find("{", start)

    if brace_start == -1:
        return None

    depth = 0

    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1

            if depth == 0:
                return text[brace_start + 1:i]

    return None


def parse_draw_lines(filename):
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    block = extract_section(text, "drawLines")

    if block is None:
        return []

    pattern = re.compile(
        r"line:p4\s*=\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)"
    )

    return [
        list(map(float, m.groups()))
        for m in pattern.finditer(block)
    ]

"""






def extract_section(text, name):
    start = text.find(name)

    if start == -1:
        return None

    brace_start = text.find("{", start)

    if brace_start == -1:
        return None

    depth = 0

    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1

            if depth == 0:
                return text[brace_start + 1:i]

    return None


def parse_draw_lines(filename):
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    block = extract_section(text, "drawLines")

    if block is None:
        return []

    pattern = re.compile(
        r"line:p4\s*=\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
        r"([-+]?\d+(?:\.\d+)?)"
        r"(?P<props>[^}]*)"
    )

    result = []

    for m in pattern.finditer(block):
        values = list(map(float, m.groups()[:4]))

        props = m.group("props")

        if re.search(r"thousandth:b\s*=\s*true", props):
            values = [v / 1000 for v in values]

        result.append(values)

    return result




lines = parse_draw_lines(FILE)









#print(lines)




import re


def extract_section(text, name):
    start = text.find(name)

    if start == -1:
        return None

    brace_start = text.find("{", start)

    depth = 0

    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1

            if depth == 0:
                return text[brace_start + 1:i]

    return None


def parse_draw_quads(filename):
    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    block = extract_section(text, "drawQuads")

    if block is None:
        return []

    result = []

    quads = re.findall(
        r"quad\s*\{(.*?)\}",
        block,
        re.DOTALL
    )

    for quad in quads:

        points = re.findall(
            r"[a-z]{2}:p2\s*=\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)",
            quad
        )

        if len(points) == 4:
            arr = []

            for x, y in points:
                arr.extend([
                    float(x),
                    float(y)
                ])

            result.append(arr)

    return result


quads = parse_draw_quads(FILE)

#print(quads)

rectan = lines + quads
rectan1000 = [[x * 1000 for x in sublist] for sublist in rectan]





"""for i in rectan1000:
    print(i)"""
mul = 3
j = (0,0,0,0)
for i in rectan1000:
    j = mul*j
    if  i[0]>j[0] or i[1]>j[1] or i[2]>j[2] or i[3]>j[3]:
        print(f"{i}\n{j[0]/mul,j[1]/mul,j[2]/mul,j[3]/mul}\nx")


    j = i


for i in rectan1000:
    print(i , "")








points = rectan1000
WIDTH = 600
HEIGHT = 600


def convert_coordinates(data, width, height, padding=0.05, flip_y=False):
    """
    Переводит реальные координаты в координаты Canvas, масштабируя набор точек
    под заданный размер (width x height).

    padding: доля от минимального размера (0..0.5) используемая как отступ с краев.
    flip_y: если True — инвертирует ось Y чтобы нулевой Y был внизу (обычная
    математическая система координат). Для tkinter можно установить False, если
    исходные координаты уже соответствуют экранной системе.
    """
    if not data:
        return []

    # собираем все X и Y
    xs = []
    ys = []

    for poly in data:
        for i in range(0, len(poly), 2):
            xs.append(poly[i])
            ys.append(poly[i+1])

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    range_x = max_x - min_x
    range_y = max_y - min_y

    # защитимся от вырождений
    if range_x == 0:
        range_x = 1.0
    if range_y == 0:
        range_y = 1.0

    pad = max(0, min(padding, 0.4)) * min(width, height)
    usable_w = max(1.0, width - 2 * pad)
    usable_h = max(1.0, height - 2 * pad)

    scale = min(usable_w / range_x, usable_h / range_y)

    result = []

    for poly in data:
        converted = []

        for i in range(0, len(poly), 2):
            x = poly[i]
            y = poly[i+1]

            cx = (x - min_x) * scale + pad

            if flip_y:
                # инвертируем Y так, чтобы минимальный Y оказался внизу
                cy = height - ((y - min_y) * scale + pad)
            else:
                cy = (y - min_y) * scale + pad

            converted.extend([cx, cy])

        result.append(converted)

    return result


if __name__ == "__main__":
    root = Tk()
    root.title("Polygon map")
    # Верхняя панель управления: выбор папки и масштаб сетки
    topbar = Frame(root)
    topbar.pack(fill="x", padx=4, pady=4)

    folder_var = StringVar(value=str(FILE))
    grid_scale_var = IntVar(value=10)
    show_grid_var = BooleanVar(value=True)

    def on_select_folder():
        folder = filedialog.askdirectory()
        if not folder:
            return

        folder_var.set(folder)

        # Попробуем найти первый .blk файл в папке и загрузить его
        p = Path(folder)
        blk = None
        for f in p.rglob('*.blk'):
            blk = f
            break

        if blk is None:
            messagebox.showinfo("Info", "Не найден .blk файл в выбранной папке")
            return

        try:
            lines_new = parse_draw_lines(str(blk))
            quads_new = parse_draw_quads(str(blk))

            rectan_new = lines_new + quads_new
            rectan1000_new = [[x * 1000 for x in sublist] for sublist in rectan_new]

            # Обновляем глобальные точки
            global points
            points = rectan1000_new
            on_render()
        except Exception as e:
            messagebox.showerror("Error", f"Ошибка при загрузке файла: {e}")

    Button(topbar, text="Выбрать папку...", command=on_select_folder).pack(side="left")

    Entry(topbar, textvariable=folder_var, width=60).pack(side="left", padx=6)

    Label(topbar, text="Масштаб сетки (px):").pack(side="left", padx=(10,2))
    grid_scale = Scale(topbar, from_=2, to=200, orient=HORIZONTAL, variable=grid_scale_var)
    grid_scale.pack(side="left")

    Checkbutton(topbar, text="Показать сетку", variable=show_grid_var, command=lambda: on_render()).pack(side="left", padx=6)

    # Canvas
    canvas = Canvas(
        root,
        width=WIDTH,
        height=HEIGHT,
        bg="white"
    )
    canvas.pack(fill="both", expand=True)

    def draw_grid(w, h, step):
        if step <= 0:
            return
        # вертикальные линии
        for x in range(0, int(w), step):
            canvas.create_line(x, 0, x, h, fill="#e0e0e0")
        # горизонтальные линии
        for y in range(0, int(h), step):
            canvas.create_line(0, y, w, y, fill="#e0e0e0")

    def on_render(event=None):
        # Получаем текущие размеры canvas (учтём, что до отрисовки они могут быть 1)
        w = canvas.winfo_width() or WIDTH
        h = canvas.winfo_height() or HEIGHT

        canvas.delete("all")

        # Рисуем сетку при включённой опции
        if show_grid_var.get():
            step = max(1, grid_scale_var.get())
            draw_grid(w, h, step)

        converted = convert_coordinates(points, w, h, padding=0.05, flip_y=False)

        for polygon in converted:
            canvas.create_polygon(
                polygon,
                fill="lightblue",
                outline="black",
                width=2
            )


    # Перерисовываем при изменении размера
    canvas.bind("<Configure>", on_render)

    # Инициалная отрисовка
    root.after(50, on_render)

    root.mainloop()




#####################



""""
root = Tk()

root.geometry("600x600")

canvas = Canvas(bg="white", width=500, height=500)
canvas.pack(anchor=CENTER, expand=1)

root.mainloop()
"""


