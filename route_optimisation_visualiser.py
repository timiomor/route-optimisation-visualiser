import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import networkx as nx
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import time
import string
import json

# =========================================================
# database manager
# handles saving loading and storing matrices and results
# =========================================================

class DatabaseManager:
    def __init__(self, db_name="matrices.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        # create required tables if they do not already exist
        cursor = self.conn.cursor()
        # matrices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matrices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                n INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # matrix entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matrix_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matrix_id INTEGER NOT NULL,
                row INTEGER,
                col INTEGER,
                value REAL,
                FOREIGN KEY (matrix_id) REFERENCES matrices(id)
            )
        """)
        # results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matrix_id INTEGER NOT NULL,
                algorithm_name TEXT NOT NULL,
                total_weight REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (matrix_id) REFERENCES matrices(id)
            )
        """)
        self.conn.commit()

    def save_matrix(self, name, matrix):
        # save a matrix and all values into the database
        cursor = self.conn.cursor()
        n = len(matrix)
        cursor.execute("INSERT INTO matrices (name, n) VALUES (?, ?)", (name, n)) # insert matrix metadata
        matrix_id = cursor.lastrowid
        for i in range(n):
            for j in range(n):
                cursor.execute(
                    "INSERT INTO matrix_entries (matrix_id, row, col, value) VALUES (?, ?, ?, ?)",
                    (matrix_id, i, j, matrix[i][j])
                )
        self.conn.commit()
        return matrix_id

    def load_matrix(self, matrix_name):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, n FROM matrices WHERE name = ?", (matrix_name,))
        row = cursor.fetchone()
        if not row:
            return None, None
        matrix_id, n = row
        cursor.execute("SELECT row, col, value FROM matrix_entries WHERE matrix_id = ?", (matrix_id,))
        entries = cursor.fetchall()
        matrix = [[0.0]*n for _ in range(n)]
        for r, c, v in entries:
            matrix[r][c] = v
        return matrix_id, matrix

    def list_matrix_names(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM matrices ORDER BY created_at DESC")
        return [row[0] for row in cursor.fetchall()]

    def save_result(self, matrix_id, algorithm_name, total_weight):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO results (matrix_id, algorithm_name, total_weight) VALUES (?, ?, ?)",
            (matrix_id, algorithm_name, total_weight)
        )
        self.conn.commit()

# =========================================================
# main app
# =========================================================

class RouteOptimisationApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Route Optimisation Simulation")
        self.geometry("1000x1000")
        self.minsize(500, 800)

        # database
        self.db_manager = DatabaseManager()

        # ui elements
        self.create_top_controls()
        self.create_persistent_buttons()
        self.progress = ttk.Progressbar(self, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)

        self.controls_frame = tk.Frame(self)
        self.controls_frame.pack(pady=5)

        self.canvas_frame = tk.Frame(self)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.graph_manager = GraphManager(self.controls_frame)
        self.visualiser = GraphVisualiser(self.canvas_frame)

        self.button_validate = None
        self.button_lower_bound = None
        self.button_nna = None
        self.button_download = None

    # =========================================================
    # ui
    # =========================================================

    def create_top_controls(self):
        self.label_nodes = tk.Label(self, text="Number of Nodes:")
        self.label_nodes.pack(pady=5)

        self.entry_nodes = tk.Entry(self)
        self.entry_nodes.pack(pady=5)

        self.button_create = tk.Button(self, text="Create Matrix", command=self.create_matrix)
        self.button_create.pack(pady=10)

        self.button_load_test = tk.Button(self, text="Load Test Matrix", command=self.load_test_matrix)
        self.button_load_test.pack(anchor="nw", pady=5, padx=5)

        self.button_upload = tk.Button(self, text="Upload Matrix", command=self.upload_matrix)
        self.button_upload.pack(anchor="nw", pady=5, padx=5)

    def create_persistent_buttons(self):
        self.persistent_frame = tk.Frame(self)
        self.persistent_frame.pack(anchor="nw")

        self.button_save_db = tk.Button(self.persistent_frame, text="Save Matrix to DB", command=self.save_to_db)
        self.button_save_db.pack(pady=5)

        self.button_load_db = tk.Button(self.persistent_frame, text="Load Matrix from DB", command=self.load_from_db)
        self.button_load_db.pack(pady=5)

    # =========================================================
    # matrix handling
    # =========================================================


    def create_matrix(self):
        try:
            n = int(self.entry_nodes.get())
            if n <= 0 or n > 10:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a positive integer < 11") # constraint
            return

        self.graph_manager.clear()
        self.graph_manager.create_name_entries(n)
        self.graph_manager.create_matrix_entries(n)

        if self.button_validate:
            self.button_validate.destroy()
        self.button_validate = tk.Button(self.controls_frame, text="Validate & Draw", command=self.validate_and_prepare)
        self.button_validate.pack(pady=5)

        if self.button_lower_bound: # initialises all the algorithm buttons, makes sure they wont show up until validated
            self.button_lower_bound.destroy()
            self.button_lower_bound = None
        if self.button_nna:
            self.button_nna.destroy()
            self.button_nna = None
        if self.button_download:
            self.button_download.destroy()
            self.button_download = None

    def load_test_matrix(self):
        test_matrix = [
            [0, 9.1, 10.0, 12.3, 17.1],
            [9.1, 0, 15.5, 17.8, 22.7],
            [10.0, 15.5, 0, 2.4, 7.6],
            [12.3, 17.8, 2.4, 0, 8.0],
            [17.1, 22.7, 7.6, 8.0, 0]
        ]
        names = ['Aber', 'Bangor', 'Conwy', 'Deganwy', 'Ebach']
        n = len(test_matrix)

        if not self.graph_manager.matrix_entries or len(self.graph_manager.matrix_entries) != n:
            self.entry_nodes.delete(0, tk.END)
            self.entry_nodes.insert(0, str(n))
            self.create_matrix()

        for i in range(n):
            self.graph_manager.name_entries[i].delete(0, tk.END)
            self.graph_manager.name_entries[i].insert(0, names[i])

        for i in range(n):
            for j in range(n):
                e = self.graph_manager.matrix_entries[i][j]
                if i != j:
                    e.config(state="normal")
                    e.delete(0, tk.END)
                    e.insert(0, str(test_matrix[i][j]))

    def upload_matrix(self):
        f_in = filedialog.askopenfilename(filetypes=[('txt', '*.txt')])
        if f_in:
            with open(f_in, "r") as u:
                data = json.load(u)
                names = data['nodes']
                upload_matrix = data['matrix']
                n = len(upload_matrix)

            if not self.graph_manager.matrix_entries or len(self.graph_manager.matrix_entries) != n:
                self.entry_nodes.delete(0, tk.END)
                self.entry_nodes.insert(0, str(n))
                self.create_matrix()

            for i in range(n):
                self.graph_manager.name_entries[i].delete(0, tk.END)
                self.graph_manager.name_entries[i].insert(0, names[i])
            for i in range(n):
                for j in range(n):
                    e = self.graph_manager.matrix_entries[i][j]
                    if i != j:
                        e.config(state="normal")
                        e.delete(0, tk.END)
                        e.insert(0, str(upload_matrix[i][j]))

    # # =========================================================
    # database
    # =========================================================


    def save_to_db(self):
        valid, matrix, names = self.graph_manager.read_matrix_and_names() # gets the matrix and names from other methods
        if not valid:
            return
        name = simpledialog.askstring("Save Matrix", "Enter name for this matrix:")  
        if not name:
            return
        try:
            self.db_manager.save_matrix(name, matrix)
            messagebox.showinfo("Success", f"Matrix '{name}' saved to database.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save matrix:\n{str(e)}") # error handling with reason

    def load_from_db(self):
        names = self.db_manager.list_matrix_names()
        if not names:
            messagebox.showerror("Error", "No matrices in DB")
            return

        selected = simpledialog.askstring("Load Matrix", f"Available matrices:\n{', '.join(names)}\nEnter name:")
        if not selected:
            return
        matrix_id, matrix = self.db_manager.load_matrix(selected)
        if matrix is None:
            messagebox.showerror("Error", f"No matrix named '{selected}'")
            return

        n = len(matrix)
        self.entry_nodes.delete(0, tk.END)
        self.entry_nodes.insert(0, str(n))
        self.create_matrix()

        for i in range(n):
            for j in range(n):
                e = self.graph_manager.matrix_entries[i][j]
                if i != j:
                    e.config(state="normal")
                    e.delete(0, tk.END)
                    e.insert(0, str(matrix[i][j]))

    # =========================================================
    # validate and draw
    # buttons frame linked to user entering number of nodes correctly first
    # =========================================================


    def validate_and_prepare(self):
        valid, matrix, names = self.graph_manager.read_matrix_and_names()
        if not valid:
            return

        self.visualiser.draw(names, matrix)

        if not self.button_lower_bound:
            self.button_lower_bound = tk.Button(
                self.controls_frame,
                text="Find Lower Bound (Prim+P+Q)",
                command=lambda: self.run_lower_bound(matrix, names)
            )
            self.button_lower_bound.pack(pady=5)
        if not self.button_nna:
            self.button_nna = tk.Button(
                self.controls_frame,
                text="Find Upper Bound (NNA)",
                command=lambda: self.run_nna(matrix, names)
            )
            self.button_nna.pack(pady=5)
        if not self.button_download:
            self.button_download = tk.Button(self.controls_frame, text="Download Matrix", command=self.download_current_matrix)
            self.button_download.pack(pady=5)

    # =========================================================
    # algorithms
    # =========================================================


    def run_lower_bound(self, matrix, names):
        choice = simpledialog.askstring("Lower Bound", f"Enter node to delete ({', '.join(names)}):")
        if choice not in names:
            messagebox.showerror("Error", "Invalid node selected")
            return
        idx = names.index(choice)
        reduced_names = [n for i, n in enumerate(names) if i != idx]
        reduced_matrix = [
            [matrix[i][j] for j in range(len(matrix)) if j != idx]
            for i in range(len(matrix)) if i != idx
        ]

        alg = PrimsAlgorithm(reduced_matrix, reduced_names, self.visualiser, self.progress, master=self)
        alg.run()
        m = alg.total_weight

        reconnector_edges = [(names[idx], names[j], matrix[idx][j]) for j in range(len(matrix)) if j != idx] # p and q summing and calculating
        reconnector_edges.sort(key=lambda x: x[2])
        p = reconnector_edges[0]
        q = reconnector_edges[1]
        lb = m + p[2] + q[2]

        highlight_edges = [(p[0], p[1]), (q[0], q[1])]
        self.visualiser.draw(names, matrix, mst_edges=None, highlight_edge=highlight_edges)

        messagebox.showinfo("Lower Bound Result", f"Lower bound = {lb}")

        # save result to db
        matrix_name = simpledialog.askstring("Matrix Name", "Enter matrix name for saving result:")
        if matrix_name:
            matrix_id, _ = self.db_manager.load_matrix(matrix_name)
            if matrix_id:
                self.db_manager.save_result(matrix_id, "Lower Bound (Prim+P+Q)", lb)
            else:
                messagebox.showerror("Error", f"No matrix named '{matrix_name}' in database. Result not saved.")

    def run_nna(self, matrix, names):
        start_choice = simpledialog.askstring( # allows user to enter start node for nna
            "Start Node", f"Select start node ({', '.join(names)}):"
        )
        if start_choice not in names:
            messagebox.showerror("Error", "Invalid start node")
            return
        start_node = names.index(start_choice)

        alg = NearestNeighbourAlgorithm(matrix, names, self.visualiser, self.progress, master=self, start_node=start_node) # star node pass

        alg.run()
        total_weight = alg.total_weight

        # save result to db
        matrix_name = simpledialog.askstring("Matrix Name", "Enter matrix name for saving result:")
        if matrix_name:
            matrix_id, _ = self.db_manager.load_matrix(matrix_name)
            if matrix_id:
                self.db_manager.save_result(matrix_id, "Nearest Neighbour", total_weight)
            else:
                messagebox.showerror("Error", f"No matrix named '{matrix_name}' in database. Result not saved.")

    # =========================================================
    # download as json
    # =========================================================


    def download_current_matrix(self):
        valid, matrix, names = self.graph_manager.read_matrix_and_names()
        if not valid:
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            try:
                data = {"nodes": names, "matrix": matrix}
                with open(file_path, 'w') as file: # saves in text file
                    json.dump(data, file, indent=2)
                messagebox.showinfo("Success", f"File saved as: {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file:\n{str(e)}")

# =========================================================
# graph manager
# handles node names matrix input and validation
# =========================================================

class GraphManager:
    def __init__(self, master):
        self.master = master
        self.name_frame = None
        self.matrix_frame = None
        self.name_entries = []
        self.matrix_entries = []

    def clear(self):
        # remove current matrix and input widgets
        if self.name_frame:
            self.name_frame.destroy()
            self.name_frame = None
        if self.matrix_frame:
            self.matrix_frame.destroy()
            self.matrix_frame = None
        self.name_entries = []
        self.matrix_entries = []

    def create_name_entries(self, n):
        # create entry boxes for node names
        self.name_frame = tk.Frame(self.master)
        self.name_frame.pack(pady=5)
        tk.Label(self.name_frame, text="Node Names:").pack()
        row = tk.Frame(self.name_frame)
        row.pack()
        for i in range(n):
            e = tk.Entry(row, width=10, justify="center")
            e.pack(side="left", padx=2)
            # default names a b c d
            e.insert(0, string.ascii_uppercase[i % 26])
            self.name_entries.append(e)

    def create_matrix_entries(self, n):
        self.matrix_frame = tk.Frame(self.master)
        self.matrix_frame.pack(pady=5)

        # validation for numeric inputs
        def validate_number(P):
            if P == "":
                return True
            try:
                float(P)
                return True
            except ValueError:
                return False

        vcmd = (self.master.register(validate_number), '%P')

        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    e = tk.Entry(self.matrix_frame, width=6, justify="center")
                    e.grid(row=i, column=j, padx=1, pady=1)
                    e.insert(0, "0")
                    e.config(state="disabled")
                else:
                    e = tk.Entry(self.matrix_frame, width=6, justify="center",
                                 validate="key", validatecommand=vcmd)
                    e.grid(row=i, column=j, padx=1, pady=1)
                    # now calls the proper method
                    e.bind("<FocusOut>", lambda event, r=i, c=j: self.copy_symmetric(r, c))
                row.append(e)
            self.matrix_entries.append(row)

    
    def copy_symmetric(self, r, c):
        # enforce matrix symmetry
        # value entered in r c is copied to c r
        val = self.matrix_entries[r][c].get().strip()
        sym = self.matrix_entries[c][r]

        if val == "":
            sym.config(state="normal")
            sym.delete(0, tk.END)
            if r == c:
                sym.insert(0, "0")
                sym.config(state="disabled")
            return

        try:
            float(val)
        except ValueError: # general error handling
            messagebox.showerror("Error", "Matrix must only contain numbers")
            self.matrix_entries[r][c].focus_set()
            return

        sym.config(state="normal")
        sym.delete(0, tk.END)
        sym.insert(0, val)
        if r == c:
            sym.config(state="disabled")

    def read_matrix_and_names(self): 
        n = len(self.matrix_entries)
        if n == 0:
            messagebox.showerror("Error", "Create a matrix first") # no 0 amount of nodes
            return False, None, None
        
        matrix = [[0.0]*n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i != j:
                    try:
                        matrix[i][j] = float(self.matrix_entries[i][j].get())
                    except ValueError:
                        messagebox.showerror("Error", "Matrix must contain numbers") # general error handle
                        return False, None, None
        for i in range(n):
            for j in range(n):
                if matrix[i][j] != matrix[j][i]: # symmetry check
                    messagebox.showerror("Error", "Matrix must be symmetric")
                    return False, None, None
        names = [e.get() or string.ascii_uppercase[i % 26] for i, e in enumerate(self.name_entries)]
        return True, matrix, names

# =========================================================
# graph visualiser
# converts matrix into weighted graph using networkx
# =========================================================
class GraphVisualiser:
    def __init__(self, master):
        self.master = master
         # canvas used for matplotlib graph
        self.graph_canvas = None

    def draw(self, node_names, matrix, mst_edges=None, highlight_edge=None):
        G = nx.Graph()  # build graph structure
        n = len(matrix)
        G.add_nodes_from(node_names) # partial pass fix - adds nodes before edges to make sure they always show even if no weight connected
         # add weighted edges
        for i in range(n):
            for j in range(i+1, n):
                if matrix[i][j] != 0:
                    G.add_edge(node_names[i], node_names[j], weight=matrix[i][j])
        fig = Figure(figsize=(6,6))
        ax = fig.add_subplot(111)
        ax.set_axis_off()
        pos = nx.spring_layout(G, seed=42)
        nx.draw(G, pos, ax=ax, with_labels=True, node_size=800)
        labels = nx.get_edge_attributes(G, 'weight')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=labels, ax=ax)
        if mst_edges:
            nx.draw_networkx_edges(G, pos, edgelist=mst_edges, edge_color='green', width=2.5, ax=ax)
        if highlight_edge:
            if isinstance(highlight_edge[0], tuple):
                nx.draw_networkx_edges(G, pos, edgelist=highlight_edge, edge_color='red', width=3, ax=ax)
            else:
                nx.draw_networkx_edges(G, pos, edgelist=[highlight_edge], edge_color='red', width=3, ax=ax)
        if self.graph_canvas:
            self.graph_canvas.get_tk_widget().destroy()
        self.graph_canvas = FigureCanvasTkAgg(fig, master=self.master)
        self.graph_canvas.draw()
        self.graph_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

# =========================================================
# prims algorithm
# generates mst
# =========================================================

class PrimsAlgorithm:
    def __init__(self, matrix, node_names, visualiser, progressbar, master=None):
        self.matrix = matrix
        self.node_names = node_names
        self.visualiser = visualiser
        self.progressbar = progressbar
        self.master = master
        self.total_weight = 0

    def run(self):
        n = len(self.matrix)
        # track nodes already added to mst
        selected = [False]*n
        selected[0] = True
        edges_in_mst = []
        total_weight = 0.0
        self.progressbar['value'] = 0 # reset progress bar
        self.progressbar['maximum'] = n-1 if n>1 else 1
        for step in range(n-1):
            min_edge = None
            min_weight = float('inf')
            best_j = None
             # search for smallest edge connecting visited and unvisited nodes
            for i in range(n):
                if selected[i]:
                    for j in range(n):
                        if not selected[j] and self.matrix[i][j] != 0:
                            if self.matrix[i][j] < min_weight:
                                min_weight = self.matrix[i][j]
                                min_edge = (self.node_names[i], self.node_names[j])
                                best_j = j
            if min_edge is None:
                break
            edges_in_mst.append(min_edge)
            selected[best_j] = True
            total_weight += min_weight
            self.visualiser.draw(self.node_names, self.matrix, mst_edges=edges_in_mst, highlight_edge=min_edge)
            self.progressbar['value'] = step+1
            if self.master: self.master.update()
            time.sleep(0.7)
        self.total_weight = total_weight
        messagebox.showinfo("Prim's Result", f"MST complete.\nTotal weight: {total_weight}")
# =========================================================
# nearest neighbour algorithm
# for upper bound
# =========================================================
class NearestNeighbourAlgorithm:
    def __init__(self, matrix, node_names, visualiser, progressbar, master=None, start_node=0): #now passes startnode
        self.matrix = matrix
        self.node_names = node_names
        self.visualiser = visualiser
        self.progressbar = progressbar
        self.master = master
        self.start_node = start_node
        self.total_weight = 0 # changed

    def run(self):
        n = len(self.matrix)
        if n==0: return
        start_node = self.start_node # changed from 0 to start node
        visited = [start_node]
        edges_in_path = []
        total_weight = 0.0
        self.progressbar['value'] = 0
        self.progressbar['maximum'] = n
        current = start_node
        for step in range(n-1):
            min_edge = None
            min_weight = float('inf')
            best_j = None
            # find nearest unvisited neighbour
            for j in range(n):
                if j not in visited and self.matrix[current][j]!=0:
                    if self.matrix[current][j] < min_weight:
                        min_weight = self.matrix[current][j]
                        min_edge = (self.node_names[current], self.node_names[j])
                        best_j = j
            if min_edge is None: break
            edges_in_path.append(min_edge)
            visited.append(best_j)
            total_weight += min_weight
            current = best_j
            self.visualiser.draw(self.node_names, self.matrix, mst_edges=edges_in_path, highlight_edge=min_edge)
            self.progressbar['value'] = step+1
            if self.master: self.master.update()
            time.sleep(0.7)
        if current != start_node:
            edges_in_path.append((self.node_names[current], self.node_names[start_node]))
            total_weight += self.matrix[current][start_node]
        self.visualiser.draw(self.node_names, self.matrix, mst_edges=edges_in_path)
        self.progressbar['value'] = n
        if self.master: self.master.update()
        time.sleep(0.5)
        self.total_weight = total_weight
        messagebox.showinfo("NNA Result", f"Path complete.\nTotal weight: {total_weight}")

# =========================================================
# run
# =========================================================

if __name__ == '__main__':
    app = RouteOptimisationApp()
    app.mainloop()
