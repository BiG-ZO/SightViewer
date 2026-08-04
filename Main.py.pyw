"""
SightViewer - Viewer for War Thunder sight files (.blk)

A tkinter-based GUI application for browsing, previewing, and managing
sight files. Features include thumbnail rendering, fullscreen preview,
batch operations, and drag-and-drop file management.
"""

from tkinter import *
from tkinter import filedialog
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageTk
import send2trash
import threading
import queue
import os
from concurrent.futures import ThreadPoolExecutor

# ============================================================================
# INITIALIZATION
# ============================================================================

root = Tk()
root.title("SightViewer - 0 files")
root.geometry("1000x800")

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# UI dimensions and layout
GRIDSCALE = 100
CELLS_PER_ROW = 4
CELL_GUTTER = 4
DEFAULT_WINDOW_WIDTH = 1000
DEFAULT_WINDOW_HEIGHT = 800

# Rendering configuration
FULLSCREEN_MIN_SIZE = 800
PADDING_RATIO = 0.05
RENDER_QUEUE_CHECK_INTERVAL = 100  # milliseconds

# UI update frequency
UI_UPDATE_INTERVAL = 10  # Update after every N files loaded

# ============================================================================
# GLOBAL STATE
# ============================================================================

SIGHTFOLDER = ""
SIGHT_FILES = []
CELL_WIDGETS = {}
DELETED_FILES = set()
CURRENT_COLS = CELLS_PER_ROW

# ============================================================================
# CACHES AND THREADING
# ============================================================================

PARSE_CACHE = {}          # file_path -> list of polygons (points)
RENDER_CACHE = {}         # (file_path, size) -> PhotoImage
PIL_CACHE = {}            # (file_path, size) -> PIL.Image
RENDER_QUEUE = queue.Queue()

# Background rendering thread pool
WORKER_COUNT = max(1, (os.cpu_count() or 1))
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=WORKER_COUNT)
RENDER_IN_PROGRESS = set()
RENDER_LOCK = threading.Lock()
FULLSCREEN_WINDOWS = {}

# ============================================================================
# FILE PARSING FUNCTIONS
# ============================================================================

def extract_section(text, name):
    """
    Extract a named section from .blk file content.

    Finds and extracts text between matching braces for a given section name.

    Args:
        text: File content as string
        name: Section name to extract (e.g., 'drawLines', 'drawQuads')

    Returns:
        str: Content between braces, or None if section not found
    """
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
    """
    Parse draw lines from a .blk sight file.

    Extracts line coordinates in format: p4 = x1, y1, x2, y2.
    If thousandth:b = true is present in the line block,
    coordinates are divided by 1000.

    Args:
        filename: Path to .blk file

    Returns:
        list: List of [x1, y1, x2, y2] line coordinates
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            text = f.read()

        block = extract_section(text, "drawLines")
        if block is None:
            return []

        # Every line { ... }
        line_blocks = re.findall(r"line\s*\{(.*?)\}", block, re.DOTALL)

        result = []

        p4_pattern = re.compile(
            r"line:p4\s*=\s*"
            r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
            r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
            r"([-+]?\d+(?:\.\d+)?)\s*,\s*"
            r"([-+]?\d+(?:\.\d+)?)"
        )

        for line_block in line_blocks:
            match = p4_pattern.search(line_block)
            if not match:
                continue

            coords = list(map(float, match.groups()))

            # Checking thousandth
            thousandth = re.search(
                r"thousandth:b\s*=\s*true",
                line_block,
                re.IGNORECASE
            )

            if thousandth:
                coords = [v / 1000 for v in coords]

            result.append(coords)

        return result

    except Exception:
        return []


def parse_draw_quads(filename):
    """
    Parse draw quads (polygons) from a .blk sight file.

    Extracts quadrilateral vertices in format: quad { xx:p2 = x, y; ... }

    If thousandth:b = true is present in the quad block,
    all coordinates are divided by 1000.

    Args:
        filename: Path to .blk file

    Returns:
        list: List of polygons [x1, y1, x2, y2, x3, y3, x4, y4],
              or empty list on error
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            text = f.read()

        block = extract_section(text, "drawQuads")
        if block is None:
            return []

        result = []
        quads = re.findall(r"quad\s*\{(.*?)\}", block, re.DOTALL)

        for quad in quads:
            points = re.findall(
                r"[a-z]{2}:p2\s*=\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)",
                quad
            )

            if len(points) == 4:
                arr = []

                # Checking thousandth
                thousandth = re.search(
                    r"thousandth:b\s*=\s*true",
                    quad,
                    re.IGNORECASE
                )

                divisor = 1000 if thousandth else 1

                for x, y in points:
                    arr.extend([
                        float(x) / divisor,
                        float(y) / divisor
                    ])

                result.append(arr)

        return result

    except Exception:
        return []


def convert_coordinates(data, width, height, padding=0.05, flip_y=False):
    """
    Convert real-world coordinates to canvas pixel coordinates.

    Normalizes and scales polygon coordinates to fit within a canvas area,
    with optional padding and Y-axis flipping.

    Args:
        data: List of polygons, each as flat list [x1, y1, x2, y2, ...]
        width: Canvas width in pixels
        height: Canvas height in pixels
        padding: Proportion of minimum dimension to use as padding (0-0.4)
        flip_y: Whether to flip Y coordinates (for coordinate system conversion)

    Returns:
        list: List of converted polygons with scaled coordinates
    """
    if not data:
        return []

    xs = []
    ys = []

    for poly in data:
        for i in range(0, len(poly), 2):
            xs.append(poly[i])
            ys.append(poly[i+1])

    if not xs or not ys:
        return []

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    range_x = max_x - min_x
    range_y = max_y - min_y

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
                cy = height - ((y - min_y) * scale + pad)
            else:
                cy = (y - min_y) * scale + pad

            converted.extend([cx, cy])

        result.append(converted)

    return result


def render_sight_to_image(file_path, size=100):
    """
    Render a sight file to a PIL Image.

    Parses the .blk file and renders draw lines and quads as polygons.
    Uses caching to avoid re-parsing the same file multiple times.

    Args:
        file_path: Path to .blk sight file
        size: Output image size (square, in pixels)

    Returns:
        PIL.Image: Rendered sight image, or blank/error image if parsing fails
    """
    try:
        # use parse cache to avoid re-parsing the same file many times
        key = str(file_path)
        if key in PARSE_CACHE:
            points = PARSE_CACHE[key]
        else:
            lines = parse_draw_lines(file_path)
            quads = parse_draw_quads(file_path)
            points = []
            if lines:
                points.extend([[x * 1000 for x in line] for line in lines])
            if quads:
                points.extend([[x * 1000 for x in quad] for quad in quads])
            PARSE_CACHE[key] = points

        img = Image.new("RGB", (size, size), color="white")
        draw = ImageDraw.Draw(img)

        if points:
            converted = convert_coordinates(points, size, size, padding=0.05, flip_y=False)
            for polygon in converted:
                if len(polygon) >= 4:
                    draw.polygon(polygon, fill="lightblue", outline="black")

        return img
    except Exception as e:
        # Return blank image on error
        img = Image.new("RGB", (size, size), color="white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size-1, size-1], outline="red")
        return img


# ============================================================================
# FILE MANAGEMENT FUNCTIONS
# ============================================================================

def load_sight_files():
    """
    Load all .blk files from the currently selected folder.

    Scans SIGHTFOLDER for .blk files and populates SIGHT_FILES list
    in sorted order for stable display.
    """
    global SIGHT_FILES
    SIGHT_FILES = []

    if not SIGHTFOLDER or not Path(SIGHTFOLDER).exists():
        return

    for file_path in sorted(Path(SIGHTFOLDER).glob("*.blk")):
        SIGHT_FILES.append(file_path)


def browse_folder():
    """Handle folder selection dialog and refresh grid."""
    global SIGHTFOLDER
    folder = filedialog.askdirectory(title="Select folder with sight files (.blk)")
    if folder:
        SIGHTFOLDER = folder
        path_var.set(folder)
        load_sight_files()
        update_title()
        refresh_grid()


def on_scale_change(*_):
    """
    Handle changes to the thumbnail size scale control.

    Updates GRIDSCALE and recalculates grid layout when user changes
    the thumbnail size spinbox.
    """
    global GRIDSCALE
    try:
        val = int(scale_var.get())
        if val <= 0:
            return
        GRIDSCALE = val
    except Exception:
        return
    on_canvas_configure()


def update_title():
    """Update window title to show file count and folder name."""
    remaining = max(0, len(SIGHT_FILES) - len(DELETED_FILES))
    title = f"SightViewer - {remaining} files"
    if SIGHTFOLDER:
        folder_name = Path(SIGHTFOLDER).name
        title += f" ({folder_name})"
    root.title(title)


def delete_file_to_trash(file_path):
    """
    Move file to system trash/recycle bin.

    Uses send2trash module for safe deletion. Updates UI to reflect
    the deleted state without requiring a full grid refresh.

    Args:
        file_path: Path object of the file to delete
    """
    try:
        send2trash.send2trash(str(file_path))
        DELETED_FILES.add(file_path)
        update_title()
        if file_path in CELL_WIDGETS:
            mark_cell_deleted(file_path)
        else:
            if file_path in SIGHT_FILES:
                SIGHT_FILES.remove(file_path)
            refresh_grid()
    except Exception as e:
        print(f"Error deleting file: {e}")


def mark_cell_deleted(file_path):
    """
    Visually mark a grid cell as deleted with a gray overlay.

    Updates the cell in-place without redrawing the entire grid,
    providing immediate visual feedback.

    Args:
        file_path: Path object corresponding to the cell to mark
    """
    meta = CELL_WIDGETS.get(file_path)
    if not meta:
        return

    cell_frame = meta.get('frame')
    delete_btn = meta.get('delete_btn')
    filename_label = meta.get('filename_label')

    try:
        delete_btn.config(state="disabled", text="Deleted", bg="#888888")
    except Exception:
        pass

    overlay = Frame(cell_frame, bg="#dddddd")
    overlay.place(relx=0, rely=0, relwidth=1.0, relheight=0.75)
    lbl = Label(overlay, text="Deleted", bg="#dddddd", fg="#666666", font=("Arial", 10, "bold"))
    lbl.place(relx=0.5, rely=0.5, anchor="center")
    meta['overlay'] = overlay


# ============================================================================
# PREVIEW WINDOW FUNCTIONS
# ============================================================================

def open_fullscreen_preview(file_path):
    """
    Open or toggle a fullscreen/maximized preview window.

    Clicking the same file again closes the window. The preview is rendered
    at a larger size than thumbnails and cached for reuse.

    Args:
        file_path: Path object of the file to preview
    """
    fp_str = str(file_path)

    # If already open, close it
    if fp_str in FULLSCREEN_WINDOWS:
        try:
            win = FULLSCREEN_WINDOWS[fp_str]['win']
            win.destroy()
        except Exception:
            pass
        FULLSCREEN_WINDOWS.pop(fp_str, None)
        return

    try:
        win = Toplevel()
        try:
            win.state("zoomed")
        except Exception:
            try:
                win.attributes("-fullscreen", True)
            except Exception:
                pass
        win.configure(bg="black")

        def on_close(event=None):
            """Close preview window and cleanup."""
            try:
                win.destroy()
            except Exception:
                pass
            FULLSCREEN_WINDOWS.pop(fp_str, None)

        win.bind("<Button-1>", on_close)
        win.bind("<Key-Escape>", on_close)

        lbl = Label(win, bg="black")
        lbl.pack(expand=True)

        FULLSCREEN_WINDOWS[fp_str] = {'win': win, 'label': lbl}

        # Use cached render if available, otherwise schedule background render
        preview_size = max(FULLSCREEN_MIN_SIZE, GRIDSCALE * 4)
        key = (fp_str, preview_size)

        if key in RENDER_CACHE:
            try:
                lbl.config(image=RENDER_CACHE[key])
                lbl.image = RENDER_CACHE[key]
            except Exception:
                pass
        elif key in PIL_CACHE:
            try:
                photo = ImageTk.PhotoImage(PIL_CACHE[key])
                RENDER_CACHE[key] = photo
                lbl.config(image=photo)
                lbl.image = photo
            except Exception:
                pass
        else:
            def worker_full():
                pil = render_sight_to_image(file_path, preview_size)
                RENDER_QUEUE.put((key, pil, fp_str, preview_size))

            RENDER_EXECUTOR.submit(worker_full)

    except Exception as e:
        print(f"Error opening fullscreen preview: {e}")


# ============================================================================
# GRID RENDERING FUNCTIONS
# ============================================================================

def create_grid_cell(parent, file_path, row, col):
    """
    Create a single grid cell widget for a sight file.

    Each cell contains a canvas with the rendered sight image, a filename label,
    and a delete button that appears on hover.

    Args:
        parent: Parent frame to attach cell to
        file_path: Path object of the sight file
        row: Row index in grid
        col: Column index in grid
    """
    cell_frame = Frame(parent, bg="lightgray", bd=1, relief="solid")
    cell_frame.grid(row=row, column=col, padx=0, pady=2, sticky="nsew")

    # Inner frame for overlay effect
    inner_frame = Frame(cell_frame, bg="white")
    inner_frame.pack(expand=True, fill="both", padx=1, pady=1)

    # Canvas for image
    canvas = Canvas(inner_frame, width=GRIDSCALE, height=GRIDSCALE, bg="white", bd=0, highlightthickness=0)
    canvas.pack(expand=True)
    # create a cheap placeholder image so layout is stable
    try:
        placeholder = Image.new("RGB", (GRIDSCALE, GRIDSCALE), color="#f6f6f6")
        ph = ImageTk.PhotoImage(placeholder)
        image_id = canvas.create_image(GRIDSCALE//2, GRIDSCALE//2, image=ph)
        canvas.image = ph
    except Exception:
        image_id = canvas.create_rectangle(0, 0, GRIDSCALE, GRIDSCALE, fill="#f6f6f6")

    # store image id and thumbnail size so we can update it later
    CELL_WIDGETS[file_path] = CELL_WIDGETS.get(file_path, {})
    CELL_WIDGETS[file_path]['canvas_image_id'] = image_id
    CELL_WIDGETS[file_path]['thumb_size'] = GRIDSCALE

    # Filename label
    filename_label = Label(cell_frame, text=file_path.name, bg="lightgray", wraplength=GRIDSCALE,
                          font=("Arial", 7), fg="#333333")
    filename_label.pack(fill="x", padx=2, pady=2)

    # Delete button (hidden by default) - styled as a button
    delete_btn = Button(
        cell_frame,
        text="🗑️ Delete",
        command=lambda: delete_file_to_trash(file_path),
        bg="#ff4444",
        fg="white",
        bd=1,
        relief="raised",
        padx=4,
        pady=2,
        font=("Arial", 9),
        activebackground="#cc0000",
        activeforeground="white"
    )
    # position the delete button with place so showing/hiding doesn't affect layout
    # place it top-right inside the cell
    delete_btn.place_forget()

    # store widget refs for in-place updates (delete -> gray)
    # ensure meta exists (might have been set earlier)
    meta = CELL_WIDGETS.get(file_path, {})
    meta.update({
        'frame': cell_frame,
        'canvas': canvas,
        'delete_btn': delete_btn,
        'filename_label': filename_label
    })
    CELL_WIDGETS[file_path] = meta

    # Hover handlers
    def on_enter(event=None):
        # show delete button using place (absolute overlay)
        try:
            delete_btn.place(relx=1.0, x=-6, y=6, anchor="ne")
        except Exception:
            pass
        cell_frame.config(bg="#e0e0e0", relief="sunken")

    def on_leave(event=None):
        try:
            delete_btn.place_forget()
        except Exception:
            pass
        cell_frame.config(bg="lightgray", relief="solid")

    canvas.bind("<Enter>", on_enter)
    canvas.bind("<Leave>", on_leave)
    filename_label.bind("<Enter>", on_enter)
    filename_label.bind("<Leave>", on_leave)
    cell_frame.bind("<Enter>", on_enter)
    cell_frame.bind("<Leave>", on_leave)
    delete_btn.bind("<Enter>", on_enter)
    delete_btn.bind("<Leave>", on_leave)

    # click to open fullscreen preview
    def on_click(event=None):
        open_fullscreen_preview(file_path)

    canvas.bind("<Button-1>", on_click)
    filename_label.bind("<Button-1>", on_click)
    # Schedule background render with cache lookup
    key = (str(file_path), int(GRIDSCALE))
    if key in RENDER_CACHE:
        try:
            photo = RENDER_CACHE[key]
            canvas.itemconfigure(CELL_WIDGETS[file_path].get('canvas_image_id'), image=photo)
            canvas.image = photo
        except Exception:
            pass
    else:
        schedule_render(file_path, GRIDSCALE, canvas, CELL_WIDGETS[file_path].get('canvas_image_id'))


def refresh_grid():
    """
    Refresh the entire grid with current sight files.

    Clears existing cells and recreates them based on SIGHT_FILES list.
    Recalculates column layout based on window width.
    """
    # Clear existing grid
    for widget in grid_frame.winfo_children():
        widget.destroy()
    # clear widget registry
    CELL_WIDGETS.clear()

    # Configure grid columns based on current column count
    for i in range(CURRENT_COLS):
        grid_frame.columnconfigure(i, weight=1)

    # Show status
    if not SIGHT_FILES:
        info_label = Label(grid_frame, text="No sight files loaded. Click Browse to select a folder.",
                          bg="white", fg="gray", font=("Arial", 12))
        info_label.grid(row=0, column=0, columnspan=CURRENT_COLS, pady=20)
        grid_frame.update_idletasks()
        return

    # Create cells
    for idx, file_path in enumerate(SIGHT_FILES):
        row = idx // CURRENT_COLS
        col = idx % CURRENT_COLS
        create_grid_cell(grid_frame, file_path, row, col)

        # Prevent UI freezing for large numbers of files
        if idx % 10 == 0:
            grid_frame.update()

    grid_frame.update_idletasks()


def schedule_render(file_path, size, canvas, image_item):
    """Schedule background rendering of a thumbnail. When done, put result into RENDER_QUEUE."""
    key = (str(file_path), int(size))
    # if already have PhotoImage in cache, apply immediately
    if key in RENDER_CACHE:
        photo = RENDER_CACHE[key]
        try:
            canvas.itemconfigure(image_item, image=photo)
            canvas.image = photo
        except Exception:
            pass
        return

    # if PIL image already rendered, convert to PhotoImage in main thread
    if key in PIL_CACHE:
        pil = PIL_CACHE[key]
        try:
            photo = ImageTk.PhotoImage(pil)
            RENDER_CACHE[key] = photo
            canvas.itemconfigure(image_item, image=photo)
            canvas.image = photo
        except Exception:
            pass
        return

    # submit background job if not already running
    with RENDER_LOCK:
        if key in RENDER_IN_PROGRESS:
            return
        RENDER_IN_PROGRESS.add(key)

    def worker():
        try:
            pil = render_sight_to_image(file_path, size)
            PIL_CACHE[key] = pil
            RENDER_QUEUE.put((key, pil, str(file_path), size))
        except Exception:
            # put a marker to allow retry
            RENDER_QUEUE.put((key, None, str(file_path), size))
        finally:
            try:
                with RENDER_LOCK:
                    RENDER_IN_PROGRESS.discard(key)
            except Exception:
                pass

    RENDER_EXECUTOR.submit(worker)


def process_render_queue():
    """Process items rendered by background threads and update UI (must be called in main thread)."""
    updated = False
    while True:
        try:
            key, pil, fp_str, size = RENDER_QUEUE.get_nowait()
        except queue.Empty:
            break

        try:
            if pil is None:
                continue
            photo = ImageTk.PhotoImage(pil)
            RENDER_CACHE[key] = photo
            # if widget present, update its canvas image
            for fpath, meta in list(CELL_WIDGETS.items()):
                try:
                    if str(fpath) == fp_str:
                        # only update grid cell if rendered size matches this cell's thumbnail size
                        meta_thumb = meta.get('thumb_size')
                        if meta_thumb is not None and key[1] != meta_thumb:
                            continue
                        canvas = meta.get('canvas')
                        image_id = meta.get('canvas_image_id')
                        if canvas and image_id:
                            try:
                                canvas.itemconfigure(image_id, image=photo)
                                canvas.image = photo
                            except Exception:
                                pass
                except Exception:
                    pass

            # if fullscreen window open for this file, update it as well
            try:
                fw = FULLSCREEN_WINDOWS.get(fp_str)
                if fw and 'label' in fw:
                    try:
                        fw['label'].config(image=photo)
                        fw['label'].image = photo
                    except Exception:
                        pass
            except Exception:
                pass
            updated = True
        except Exception:
            pass

    # schedule next check
    root.after(100, process_render_queue)


# ============================================================================
# UI INITIALIZATION AND LAYOUT
# ============================================================================

root.state("zoomed")

# Top toolbar
toolbar = Frame(root, relief="raised", bd=1)
toolbar.pack(fill="x", side="top")

path_var = StringVar(value=SIGHTFOLDER)
scale_var = StringVar(value=str(GRIDSCALE))

lbl_path = Label(toolbar, text="Folder:")
lbl_path.pack(side="left", padx=(8, 4), pady=6)

entry_path = Entry(toolbar, textvariable=path_var, width=60)
entry_path.pack(side="left", padx=(0, 4), pady=6, fill="x", expand=False)

btn_browse = Button(toolbar, text="Browse...", command=browse_folder)
btn_browse.pack(side="left", padx=4, pady=6)

lbl_scale = Label(toolbar, text="Thumbnail size (px):")
lbl_scale.pack(side="left", padx=(16, 4), pady=6)

spin = Spinbox(toolbar, from_=50, to=300, increment=10, textvariable=scale_var, width=6, command=on_scale_change)
spin.pack(side="left", padx=(0, 8), pady=6)

scale_var.trace_add("write", on_scale_change)

# Grid canvas with scrollbar
canvas_container = Frame(root)
canvas_container.pack(fill="both", expand=True)

canvas = Canvas(canvas_container, bg="white")
scrollbar = Scrollbar(canvas_container, orient="vertical", command=canvas.yview)
scrollbar.pack(side="right", fill="y")

canvas.configure(yscrollcommand=scrollbar.set)
canvas.pack(side="left", fill="both", expand=True)

grid_frame = Frame(canvas, bg="white")
canvas_window = canvas.create_window((0, 0), window=grid_frame, anchor="nw")

# ============================================================================
# SCROLL AND EVENT HANDLERS
# ============================================================================

def on_mousewheel(event):
    """
    Handle mouse wheel scroll events across platforms.

    Normalizes scroll delta across Windows, Mac, and X11 to provide
    consistent scrolling behavior.

    Args:
        event: tk event object with platform-specific scroll data
    """
    delta = 0
    if hasattr(event, 'delta') and event.delta:
        # Windows and Mac (delta positive when scrolling up)
        delta = int(-1 * (event.delta / 120))
    elif hasattr(event, 'num'):
        # X11: Button-4 = up, Button-5 = down
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
    if delta:
        canvas.yview_scroll(delta, "units")


def _bind_mousewheel_all():
    """Enable mouse wheel scrolling globally."""
    try:
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_mousewheel)
        canvas.bind_all("<Button-5>", on_mousewheel)
    except Exception:
        pass


def _unbind_mousewheel_all():
    """Disable mouse wheel scrolling globally."""
    try:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")
    except Exception:
        pass


def on_canvas_configure(event=None):
    """
    Handle canvas resize and recalculate grid layout.

    Called when window is resized. Recalculates number of columns
    needed to fill the available width and refreshes grid if needed.

    Args:
        event: tk event (unused, can be None)
    """
    global CURRENT_COLS
    try:
        canvas.itemconfig(canvas_window, width=canvas.winfo_width())
    except Exception:
        pass

    # Compute optimal number of columns to fill width
    try:
        width = max(1, canvas.winfo_width())
        cols = max(1, (width + CELL_GUTTER) // (GRIDSCALE + CELL_GUTTER))
    except Exception:
        cols = CURRENT_COLS

    if cols != CURRENT_COLS:
        CURRENT_COLS = cols
        refresh_grid()


def on_grid_configure(event=None):
    """Update canvas scroll region when grid layout changes."""
    canvas.configure(scrollregion=canvas.bbox("all"))


# ============================================================================
# EVENT BINDINGS
# ============================================================================

# Enable scrolling when pointer is over canvas area
canvas_container.bind("<Enter>", lambda e: _bind_mousewheel_all())
canvas_container.bind("<Leave>", lambda e: _unbind_mousewheel_all())

# Recalculate layout when canvas is resized
canvas.bind("<Configure>", on_canvas_configure)

# Update scroll region when grid changes
grid_frame.bind("<Configure>", on_grid_configure)

# ============================================================================
# APPLICATION ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    """Start the SightViewer application."""
    # Start processing render queue periodically
    root.after(RENDER_QUEUE_CHECK_INTERVAL, process_render_queue)
    root.mainloop()
