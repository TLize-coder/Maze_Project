import random
import sys
import os

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance, isValid
    from PySide6.QtGui import QIntValidator, QDoubleValidator
    from PySide6.QtCore import Qt, QTimer
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
        from shiboken2 import wrapInstance, isValid
        from PySide2.QtGui import QIntValidator, QDoubleValidator
        from PySide2.QtCore import Qt, QTimer
    except ImportError:
        print("Error: PySide6 or PySide2 not found.")
        sys.exit()

ROOT_RESOURCE_DIR = 'C:/Users/User/Documents/maya/2025/scripts/MazeProject/images'
IMAGE_PATH = os.path.join(ROOT_RESOURCE_DIR, 'Illustration.jpg').replace('\\', '/')

try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
except ImportError:
    class CmdsStub:
        def objExists(self, *args): return False
        def evalDeferred(self, *args): pass
        def delete(self, *args): pass
        def warning(self, *args): print("Warning:", *args)
        def xform(self, *args, **kwargs): return [0, 0, 0]
        def move(self, *args): pass
        def polyCube(self, *args, **kwargs): return ['dummy']
        def polySphere(self, *args, **kwargs): return ['dummy']
        def setAttr(self, *args, **kwargs): pass
        def confirmDialog(self, *args, **kwargs): return 'OK'
        def promptDialog(self, *args, **kwargs): return 'OK'
        def group(self, *args, **kwargs): return 'dummy_group'
        def select(self, *args): pass
        def hyperShade(self, *args, **kwargs): pass
        def shadingNode(self, *args, **kwargs): return 'lambertDummy'
    cmds = CmdsStub()
    omui = None

M = {
    'mode': 'Normal', 'size': 7, 'wall_height': 1.0, 'player_color': 6,
    'start': (0, 0), 'finish': None, 'walls': [], 'map': [], 
    'player': None, 'steps': 0, 'time_limit': 0, 'time_left': 0,
    'timer': None, 'running': False 
}

ui = None
TIME_PENALTY_PER_STEP = 2 


def get_rgb_from_color_index(index):
    colors = {
        6: (0.0, 0.0, 1.0), 14: (0.0, 1.0, 0.0), 17: (1.0, 1.0, 0.0), 
        13: (1.0, 0.0, 0.0), 27: (0.0, 1.0, 1.0), 9: (1.0, 0.0, 1.0), 
        16: (1.0, 1.0, 1.0), 4: (0.5, 0.5, 0.5)
    }
    return colors.get(index, (1.0, 0.5, 0.0))

def create_and_assign_color_material(obj_name, color_index, material_name):
    try:
        if not cmds.objExists(material_name):
            material = cmds.shadingNode('lambert', asShader=True, n=material_name)
            cmds.setAttr(f'{material}.ambientColor', 0.1, 0.1, 0.1)
            cmds.setAttr(f'{material}.diffuse', 0.8)
        else:
            material = material_name

        r, g, b = get_rgb_from_color_index(color_index)
        cmds.setAttr(f'{material}.color', r, g, b, type='double3')

        cmds.select(obj_name, replace=True)
        cmds.hyperShade(assign=material)
        cmds.select(clear=True) 

        cmds.setAttr(f'{obj_name}.overrideEnabled', 0) 
        return material
    except Exception as e:
        cmds.warning(f"Error assigning material to {obj_name}: {e}")
        return None

def generateMaze(N):
    S = 2 * N + 1
    maze = [[1] * S for _ in range(S)]
    def carve(x, y):
        directions = [(2, 0), (-2, 0), (0, 2), (0, -2)]
        random.shuffle(directions)
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            if 0 <= nx < S and 0 <= ny < S and maze[ny][nx] == 1:
                maze[y + dy // 2][x + dx // 2] = 0
                maze[ny][nx] = 0
                carve(nx, ny)
    maze[1][1] = 0 
    carve(1, 1)
    return maze

def stop_game_timer():
    global M
    M['running'] = False
    t = M.get('timer')
    dlg = MazeConfigDialog.instance
    
    if t and isValid(t):
        if t.isActive(): t.stop()
        if dlg and isValid(dlg):
            try: t.timeout.disconnect(dlg._tick_timer)
            except Exception: pass 
        try: t.deleteLater()
        except Exception: pass
        
    M['timer'] = None

def resetMaze(clearOnly=False):
    stop_game_timer()
    
    to_delete = []
    if cmds.objExists('playerMat'): to_delete.append('playerMat')
    if cmds.objExists('finishMat'): to_delete.append('finishMat')
    if cmds.objExists('wallMat'): to_delete.append('wallMat')
    if cmds.objExists('Maze_GRP'): to_delete.append('Maze_GRP')
    
    if to_delete: cmds.evalDeferred(lambda: cmds.delete(to_delete))

    M['walls'].clear(); M['player'] = None; M['map'].clear()
    M['steps'] = 0; M['finish'] = None
    M['time_left'] = M['time_limit'] 

    if not clearOnly and MazeConfigDialog.instance and isValid(MazeConfigDialog.instance):
        dlg = MazeConfigDialog.instance
        dlg.stepCount_field.setText('0')
        if M['mode'] == 'Timed':
            dlg.timeLeft_field.setText(str(M['time_limit']))
        else:
            dlg.timeLeft_field.setText('-')
        
        cmds.warning('Maze reset.')

def move_player(direction):
    if not M['player'] or not cmds.objExists(M['player']) or not M['map']:
        cmds.warning("No player or map built.")
        return
    
    if M['mode'] == 'Timed' and M['running'] and M['time_left'] <= 0: 
        cmds.warning("Time is up! Game Over.")
        return

    x, y, z = cmds.xform(M['player'], q=True, ws=True, t=True)
    
    dx, dz = 0, 0
    if direction == "up": dz = -2
    elif direction == "down": dz = 2
    elif direction == "left": dx = -2
    elif direction == "right": dx = 2

    wall_gx, wall_gz = int(round(x + dx // 2)), int(round(z + dz // 2))
    new_x, new_z = x + dx, z + dz
    map_size = len(M['map'])

    if 0 <= wall_gz < map_size and 0 <= wall_gx < map_size and M['map'][wall_gz][wall_gx] == 0: 
        if 0 <= new_z < map_size and 0 <= new_x < map_size:
            cmds.move(new_x, y, new_z, M['player'])
            M['steps'] += 1

            if M['mode'] == 'Timed' and M['running']:
                if M['time_left'] <= 0:
                    stop_game_timer()
                    cmds.confirmDialog(t='Game Over', m="Time's up! You did not reach the finish.", b='OK')
                    resetMaze()
                    return

            dlg = MazeConfigDialog.instance
            if dlg and isValid(dlg): dlg.stepCount_field.setText(str(M['steps']))

            if not cmds.objExists('finishSphere'): return
            
            FX, FZ = cmds.xform('finishSphere', q=True, ws=True, t=True)[0:3:2]
            new_gx, new_gz = int(round(new_x)), int(round(new_z))
            
            if int(round(FX)) == new_gx and int(round(FZ)) == new_gz:
                stop_game_timer()
                cmds.confirmDialog(t="You Win!", m=f"Congratulations! You reached the finish in {M['steps']} steps!", b=["OK"])
                resetMaze()
        else:
            cmds.warning("Cannot move — out of maze boundary!")
    else:
        cmds.warning("Cannot move — wall ahead!")

def maya_main_window():
    if omui:
        ptr = omui.MQtUtil.mainWindow()
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    return None


class MazeConfigDialog(QtWidgets.QDialog):
    instance = None

    def __init__(self, parent=maya_main_window()):
        if MazeConfigDialog.instance and isValid(MazeConfigDialog.instance):
            MazeConfigDialog.instance.close()
            
        super().__init__(parent)
        self.setWindowTitle("Maze Escape Game")
        self.resize(320, 700)

        self.setStyleSheet("background-color: #13212E; color: #FFFFFF;")
        
        MazeConfigDialog.instance = self
        stop_game_timer() 

        self.qt_timer = QtCore.QTimer()
        self.qt_timer.setInterval(1000)
        M['timer'] = self.qt_timer 

        self.mainLayout = QtWidgets.QVBoxLayout(self)
        self.setup_ui()
        self.setFocusPolicy(Qt.StrongFocus)

    def setup_ui(self):
        group_style = """
            QGroupBox {
                background-color: #13212E; 
                color: white; 
                border: 2px solid #334D80; 
                border-radius: 8px; 
                margin-top: 1ex; 
            } 
            QGroupBox::title { 
                subcontrol-origin: margin; 
                subcontrol-position: top left; 
                padding: 0 10px; 
                background-color: #13212E; 
                color: white; 
            }
            QLineEdit, QComboBox {
                background-color: #1F3041; 
                border: 1px solid #4A6E9C;
                color: white;
                padding: 3px;
                border-radius: 3px;
            }
        """

        header_widget = QtWidgets.QWidget() 
        header_layout = QtWidgets.QVBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setAlignment(Qt.AlignCenter)

        image_label = QtWidgets.QLabel()
        try:
            if not os.path.exists(IMAGE_PATH):
                raise FileNotFoundError(f"Image file not found at: {IMAGE_PATH}")
                
            imagePixmap = QtGui.QPixmap(IMAGE_PATH)
            
            if not imagePixmap.isNull():
                scaled_pixmap = imagePixmap.scaled(
                    QtCore.QSize(100, 100),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )
                image_label.setPixmap(scaled_pixmap)
                image_label.setAlignment(Qt.AlignCenter)
                header_layout.addWidget(image_label)
            else:
                cmds.warning(f"Could not load QPixmap from valid file: {IMAGE_PATH}")
                header_layout.addSpacing(100)
                
        except FileNotFoundError as e:
            cmds.warning(f"Warning: {e}")
            header_layout.addSpacing(100) 
        except Exception as e:
            cmds.warning(f"Error loading image: {e}")
            header_layout.addSpacing(100)

        header_text = QtWidgets.QLabel("Build your maze")
        header_text.setStyleSheet("color:white;font-weight:bold;font-size:14px;")
        header_text.setAlignment(Qt.AlignCenter) 
        header_layout.addWidget(header_text)

        header_widget.setStyleSheet("background-color:#334D80;border-radius:4px;")
        self.mainLayout.addWidget(header_widget)


        mode_group = QtWidgets.QGroupBox("Select Mode:")
        mode_group.setStyleSheet(group_style) 
        h = QtWidgets.QHBoxLayout(mode_group)
        self.mode_normal_radio = QtWidgets.QRadioButton("Normal")
        self.mode_timed_radio = QtWidgets.QRadioButton("Timed")
        self.mode_normal_radio.setChecked(True)
        h.addWidget(self.mode_normal_radio); h.addWidget(self.mode_timed_radio)
        self.mode_normal_radio.toggled.connect(self.on_mode_change)
        self.mainLayout.addWidget(mode_group)

        self.size_field = QtWidgets.QLineEdit(str(M['size']))
        self.size_slider = self._create_slider_group("Maze Size (N):", self.size_field, 3, 25, M['size'], int)
        self.mainLayout.addLayout(self.size_slider)

        self.height_field = QtWidgets.QLineEdit(str(M['wall_height']))
        self.height_slider = self._create_slider_group("Wall Height:", self.height_field, 5, 50, int(M['wall_height'] * 10), float, 10)
        self.mainLayout.addLayout(self.height_slider)

        color_layout = QtWidgets.QHBoxLayout()
        color_layout.addWidget(QtWidgets.QLabel("Player Color:"))
        self.color_combo = QtWidgets.QComboBox()
        self.color_options = [
            ("Blue (Default)", 6), ("Green", 14), ("Yellow", 17), 
            ("Cyan", 27), ("Magenta", 9), ("White", 16)
        ]
        for name, index in self.color_options:
            self.color_combo.addItem(name, index)
        self.color_combo.setCurrentIndex(self.color_combo.findData(M['player_color']))
        self.color_combo.currentIndexChanged.connect(self.on_color_change)
        color_layout.addWidget(self.color_combo)
        self.mainLayout.addLayout(color_layout)

        start_group = QtWidgets.QGroupBox("Start Position (Grid Index 0..N-1):")
        start_group.setStyleSheet(group_style) 
        s_layout = QtWidgets.QHBoxLayout(start_group)
        self.start_x = QtWidgets.QLineEdit(str(M['start'][0])); self.start_z = QtWidgets.QLineEdit(str(M['start'][1]))
        self.start_x.setValidator(QIntValidator(0, 99)); self.start_z.setValidator(QIntValidator(0, 99))
        s_layout.addWidget(QtWidgets.QLabel("X:")); s_layout.addWidget(self.start_x)
        s_layout.addWidget(QtWidgets.QLabel("Z:")); s_layout.addWidget(self.start_z)
        self.mainLayout.addWidget(start_group)

        self.mainLayout.addWidget(self._create_separator())

        self.build_button = QtWidgets.QPushButton("Build Maze (Start Game)")
        self.build_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4CAF50, stop:1 #FFC107);
                color: white;
                padding: 10px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5CB85C, stop:1 #FFD740);
            }
        """)
        self.build_button.clicked.connect(self.build_maze_action)

        self.reset_button = QtWidgets.QPushButton("Reset Game & Scene")
        self.reset_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f44336, stop:1 #FF9800);
                color: white;
                padding: 10px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E53935, stop:1 #FFA726);
            }
        """)
        self.reset_button.clicked.connect(lambda: resetMaze())

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.build_button); btn_layout.addWidget(self.reset_button)
        self.mainLayout.addLayout(btn_layout)

        self.mainLayout.addWidget(self._create_separator())

        stats_group = QtWidgets.QGroupBox("Game Status:")
        stats_group.setStyleSheet(group_style) 
        form = QtWidgets.QFormLayout(stats_group)

        self.stepCount_field = QtWidgets.QLineEdit("0"); self.stepCount_field.setReadOnly(True); self.stepCount_field.setAlignment(Qt.AlignRight)
        self.timeLeft_field = QtWidgets.QLineEdit("-"); self.timeLeft_field.setReadOnly(True); self.timeLeft_field.setAlignment(Qt.AlignRight)
        
        form.addRow("Steps Taken:", self.stepCount_field); form.addRow("Time Left (s):", self.timeLeft_field)
        self.mainLayout.addWidget(stats_group)

        self.mainLayout.addWidget(self._create_separator())

        control_group = QtWidgets.QGroupBox("Move Player (Arrows):")
        control_group.setStyleSheet(group_style)
        control_layout = QtWidgets.QGridLayout(control_group)

        btn_style = """
            QPushButton {
                font-size: 18px; 
                font-weight: bold; 
                padding: 4px; 
                min-width: 25px; 
                min-height: 25px;
                background-color: #334D80; 
                color: white; 
                border-radius: 4px;
                border: 1px solid #4A6E9C;
            }
            QPushButton:hover {
                background-color: #4A6E9C;
            }
        """

        self.up_btn = QtWidgets.QPushButton("↑"); self.down_btn = QtWidgets.QPushButton("↓")
        self.left_btn = QtWidgets.QPushButton("←"); self.right_btn = QtWidgets.QPushButton("→")
        self.up_btn.setStyleSheet(btn_style); self.down_btn.setStyleSheet(btn_style)
        self.left_btn.setStyleSheet(btn_style); self.right_btn.setStyleSheet(btn_style)

        control_layout.addWidget(self.up_btn, 0, 1); control_layout.addWidget(self.left_btn, 1, 0)
        control_layout.addWidget(self.right_btn, 1, 2); control_layout.addWidget(self.down_btn, 2, 1)

        self.up_btn.clicked.connect(lambda: move_player("up"))
        self.down_btn.clicked.connect(lambda: move_player("down"))
        self.left_btn.clicked.connect(lambda: move_player("left"))
        self.right_btn.clicked.connect(lambda: move_player("right"))

        self.mainLayout.addWidget(control_group)
        close_button = QtWidgets.QPushButton("Close UI")
        close_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2196F3, stop:1 #000000);
                color: white;
                padding: 8px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1976D2, stop:1 #111111);
            }
        """)
        close_button.clicked.connect(self.close)
        self.mainLayout.addWidget(close_button)
        self.mainLayout.addStretch()

    def _create_separator(self):
        s = QtWidgets.QFrame()
        s.setFrameShape(QtWidgets.QFrame.HLine)
        s.setFrameShadow(QtWidgets.QFrame.Sunken)
        s.setStyleSheet("color: #4A6E9C;") 
        s.setLineWidth(1)
        return s

    def _create_slider_group(self, label, field, min_val, max_val, val, dtype, scale=1):
        layout = QtWidgets.QHBoxLayout()
        label_widget = QtWidgets.QLabel(label)
        label_widget.setFixedWidth(120)
        layout.addWidget(label_widget)
        
        slider = QtWidgets.QSlider(Qt.Horizontal)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #4A6E9C;
                height: 8px; 
                background: #1F3041;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #FFC107;
                border: 1px solid #FF9800;
                width: 12px;
                margin: -2px 0; 
                border-radius: 6px;
            }
        """)

        slider.setMinimum(min_val); slider.setMaximum(max_val); slider.setValue(val)
        field.setFixedWidth(50); field.setAlignment(Qt.AlignRight)

        if dtype == int:
            field.setValidator(QIntValidator(min_val, max_val))
            slider.valueChanged.connect(lambda v: field.setText(str(v)))
            field.editingFinished.connect(lambda: slider.setValue(int(field.text()) if field.text().isdigit() else min_val))
        else:
            field.setValidator(QDoubleValidator(min_val / scale, max_val / scale, 1))
            slider.valueChanged.connect(lambda v: field.setText(f"{v / scale:.1f}"))
            def update_slider():
                try:
                    val = float(field.text())
                    slider.setValue(int(val * scale))
                except ValueError:
                    slider.setValue(min_val)
            field.editingFinished.connect(update_slider)

        layout.addWidget(slider); layout.addWidget(field)
        return layout
        
    def on_color_change(self, index):
        M['player_color'] = self.color_combo.itemData(index)
        if M['player'] and cmds.objExists(M['player']):
            create_and_assign_color_material(M['player'], M['player_color'], 'playerMat')

    def closeEvent(self, event):
        resetMaze() 
        MazeConfigDialog.instance = None
        super().closeEvent(event)

    def on_mode_change(self):
        if self.mode_timed_radio.isChecked():
            M['mode'] = 'Timed'
            self.set_time_limit()
        else:
            M['mode'] = 'Normal'
            M['time_limit'] = 0; M['time_left'] = 0
            self.timeLeft_field.setText('-')
            
        stop_game_timer()

    def set_time_limit(self):
        dialog = QtWidgets.QInputDialog(self)
        dialog.setWindowTitle('Time Limit'); dialog.setLabelText('Enter time limit in seconds (10-300):')
        dialog.setInputMode(QtWidgets.QInputDialog.IntInput); dialog.setIntRange(10, 300); dialog.setIntValue(60)
        
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            t = dialog.intValue()
            M['time_limit'] = M['time_left'] = t
            self.timeLeft_field.setText(str(t))
        else:
            self.mode_normal_radio.setChecked(True); M['mode'] = 'Normal'
            self.timeLeft_field.setText('-')

    def build_maze_action(self):

        resetMaze(clearOnly=True) 
        
        try:
            N = int(self.size_field.text())
            H = float(self.height_field.text())
            SX = int(self.start_x.text())
            SZ = int(self.start_z.text())
        except ValueError:
            cmds.warning("Invalid input. Please check Maze Size, Wall Height, and Start Position.")
            return

        if not (0 <= SX < N and 0 <= SZ < N):
            cmds.warning(f"Start coords must be 0..{N-1}.")
            return

        M['map'] = generateMaze(N)
        map_s = len(M['map']) 
        walls_group = cmds.group(empty=True, name='Maze_Walls_GRP')

        create_and_assign_color_material(walls_group, 4, 'wallMat')

        for z in range(map_s):
            for x in range(map_s):
                if M['map'][z][x] == 1:
                    w = cmds.polyCube(w=1, h=H, d=1, n=f'wall_{x}_{z}')[0]
                    cmds.move(x, H / 2.0, z, w)
                    M['walls'].append(w)
                    cmds.parent(w, walls_group) 

        PX, PZ = SX * 2 + 1, SZ * 2 + 1
        M['start'] = (SX, SZ)

        available_cells = [(i, j) for i in range(N) for j in range(N) if (i, j) != (SX, SZ)]
        if not available_cells:
            cmds.warning("Maze too small. Increase N.")
            return

        M['finish'] = random.choice(available_cells)
        FX, FZ = M['finish'][0] * 2 + 1, M['finish'][1] * 2 + 1

        M['player'] = cmds.polySphere(r=0.4, n='playerBall')[0]
        cmds.move(PX, 0.4, PZ, M['player'])
        create_and_assign_color_material(M['player'], M['player_color'], 'playerMat')

        finish_sphere = cmds.polySphere(r=0.4, n='finishSphere')[0]
        cmds.move(FX, 0.4, FZ, finish_sphere)
        create_and_assign_color_material(finish_sphere, 13, 'finishMat') # Red

        cmds.group(M['player'], 'finishSphere', walls_group, name='Maze_GRP')
        cmds.select(M['player'], replace=True)

        cmds.warning('Maze built successfully! Use WASD or Arrow Keys to move.')

        M['steps'] = 0
        self.stepCount_field.setText('0')
        
        if M['mode'] == 'Timed' and M['time_limit'] > 0:
            M['time_left'] = M['time_limit'] 
            self.timeLeft_field.setText(str(M['time_left']))
            self.start_timer()

    def _tick_timer(self):
        if not isValid(self) or not M['player'] or not cmds.objExists(M['player']) or not M['running']:
            stop_game_timer()
            if isValid(self): self.timeLeft_field.setText('GAME STOPPED')
            return

        M['time_left'] -= 1
        self.timeLeft_field.setText(str(M['time_left']))
        
        if M['time_left'] <= 0:
            stop_game_timer()
            
            current_x, _, current_z = cmds.xform(M['player'], q=True, ws=True, t=True)
            
            if cmds.objExists('finishSphere'):
                FX, FZ = cmds.xform('finishSphere', q=True, ws=True, t=True)[0:3:2]
            else:
                FX, FZ = -999, -999

            if int(round(FX)) == int(round(current_x)) and int(round(FZ)) == int(round(current_z)):
                cmds.confirmDialog(t="You Win!", m=f"Congratulations! You reached the finish in {M['steps']} steps!", b=["OK"])
            else:
                cmds.confirmDialog(t='Game Over', m="Time's up! You did not reach the finish.", b='OK')
            
            resetMaze()

    def start_timer(self):
        t = M.get('timer')
        if not t or not isValid(t): 
            self.qt_timer = QtCore.QTimer()
            self.qt_timer.setInterval(1000) 
            M['timer'] = self.qt_timer
            t = M['timer']

        try: t.timeout.connect(self._tick_timer)
        except TypeError: pass

        M['running'] = True
        t.start()
        
    def keyPressEvent(self, event):
        if not M['player'] or not cmds.objExists(M['player']):
            return super().keyPressEvent(event)

        direction = None
        key = event.key()

        if key in (Qt.Key_W, Qt.Key_Up): direction = "up"
        elif key in (Qt.Key_S, Qt.Key_Down): direction = "down"
        elif key in (Qt.Key_A, Qt.Key_Left): direction = "left"
        elif key in (Qt.Key_D, Qt.Key_Right): direction = "right"

        if direction:
            move_player(direction)
            event.accept() 
        else:
            return super().keyPressEvent(event)

def run():
    global ui
    if ui and isValid(ui):
        try: ui.close()
        except RuntimeError: pass 
        ui = None
        
    ui = MazeConfigDialog()
    ui.show()

if __name__ == '__main__':
    if 'maya.cmds' not in sys.modules:
        app = QtWidgets.QApplication(sys.argv)
        run()
        sys.exit(app.exec())
    else:
        run()
