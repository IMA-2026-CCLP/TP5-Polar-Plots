import sys
import numpy as np
import pyqtgraph.opengl as gl
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
from scipy.interpolate import RectBivariateSpline

class VisorAnimacion3D(QMainWindow):
    def __init__(self, ruta_npz, indice_banda=0):
        super().__init__()
        self.setWindowTitle(f"Animación Patrón Polar 3D - Banda {indice_banda}")
        self.resize(800, 600)

        # 1. Configurar la vista OpenGL
        self.view = gl.GLViewWidget()
        self.setCentralWidget(self.view)
        
        # Agregamos una grilla en el piso como referencia
        grid = gl.GLGridItem()
        self.view.addItem(grid)

        # Creamos el objeto Mesh (la piel del globo)
        # smooth=True interpola las normales para que la luz lo haga ver redondo
        self.mesh_item = gl.GLMeshItem(smooth=True, color=(1, 0.2, 0.2, 0.8), shader='balloon')
        self.view.addItem(self.mesh_item)

        # 2. Cargar los Datos
        self.cargar_datos(ruta_npz, indice_banda)

        # 3. Configurar la Animación
        self.frame_actual = 0
        self.fps = 30
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.actualizar_frame)
        self.timer.start(int(1000 / self.fps)) # Calcula los milisegundos por frame
        self.actualizar_frame()

    def cargar_datos(self, ruta_npz, indice_banda):
        print("Cargando matriz...")
        data = np.load(ruta_npz)
        tensor_4d = data['tensor'] # Forma esperada: (Bandas, Theta, Phi, Frames)
        
        # Extraemos SOLO la banda que queremos ver. 
        # Ahora la matriz es 3D: (Theta, Phi, Frames)
        self.datos_banda = tensor_4d[indice_banda] 
        self.total_frames = self.datos_banda.shape[2]
        
        # Ángulos de medición (Ajustá esto a los grados reales de tu medición)
        self.theta_medido = np.radians(np.arange(0, 190, 10)) # Elevación
        self.phi_medido = np.radians(np.arange(0, 190, 10))   # Azimut media esfera
        
        # Ángulos de alta resolución para suavizar el globo
        self.theta_fino = np.radians(np.arange(0, 182, 2))
        self.phi_fino = np.radians(np.arange(0, 362, 2))
        
        print(f"Carga completa. Total frames a reproducir: {self.total_frames}")

    def actualizar_frame(self):
        """Esta función se ejecuta en cada 'tick' del reloj (ej: 30 veces por segundo)"""
        if self.frame_actual >= self.total_frames:
            self.frame_actual = 0 # Loop: Volver al principio al terminar

        # 1. Extraemos la "hoja" del frame actual: Matriz 2D (Theta x Phi)
        frame_db = self.datos_banda[:, :, self.frame_actual]

        # --- ACONDICIONAMIENTO DEL RADIO ---
        # Los decibeles pueden ser negativos. Si el radio es negativo, el globo colapsa.
        # Desplazamos la escala para que el valor más bajo sea el origen (radio ~0)
        min_db = -60 # Asumimos un rango dinámico de 60dB hacia abajo
        radio_lineal = np.clip((frame_db - min_db) / abs(min_db), 0.05, None)

        # 2. Simetría de media esfera a esfera completa
        radio_esfera_completa = np.concatenate(
            (radio_lineal, radio_lineal[:, 1:-1][:, ::-1]), axis=1
        )
        phi_completo = np.radians(np.arange(0, 360, 10))

        # 3. Interpolación (El Suavizado)
        interpolador = RectBivariateSpline(self.theta_medido, phi_completo, radio_esfera_completa)
        radio_suave = interpolador(self.theta_fino, self.phi_fino)

        # 4. Conversión a Cartesianas
        THETA, PHI = np.meshgrid(self.theta_fino, self.phi_fino, indexing='ij')
        X = radio_suave * np.sin(THETA) * np.cos(PHI)
        Y = radio_suave * np.sin(THETA) * np.sin(PHI)
        Z = radio_suave * np.cos(THETA)

        # 5. Generar Vértices y Caras para el 3D
        vertices, caras = self.generar_malla(X, Y, Z)
        self.mesh_item.setMeshData(vertexes=vertices, faces=caras)

        # Avanzamos al siguiente frame
        self.frame_actual += 1

    def generar_malla(self, X, Y, Z):
        """Convierte las matrices X, Y, Z en vértices y triángulos para OpenGL"""
        filas, cols = Z.shape
        
        # Aplanar vértices: shape (N, 3)
        vertices = np.column_stack((X.flatten(), Y.flatten(), Z.flatten()))
        
        # Generar las caras (triángulos) uniendo los puntos de la grilla
        caras = []
        for i in range(filas - 1):
            for j in range(cols - 1):
                p1 = i * cols + j
                p2 = p1 + 1
                p3 = (i + 1) * cols + j
                p4 = p3 + 1
                # Dos triángulos por cada cuadrado de la grilla
                caras.append([p1, p2, p3])
                caras.append([p3, p2, p4])
                
        return vertices, np.array(caras)

# ========================================================
# CÓDIGO DE PRUEBA
# ========================================================
if __name__ == '__main__':
    # 1. Generamos un archivo .npz FALSO temporal para probar la GUI
    # Emulamos un globo que "late" (crece y se achica con el tiempo)
    # print("Creando archivo de prueba temporal...")
    # frames_falsos = 100
    # tensor_falso = np.zeros((1, 19, 19, frames_falsos)) # 1 Banda, 19 Theta, 19 Phi
    
    # for f in range(frames_falsos):
    #     # Generamos una base de dB (ej: -20 dB) que oscila con un seno
    #     latido = -20 + 15 * np.sin(f * 0.2)
    #     tensor_falso[0, :, :, f] = latido
        
    # np.savez_compressed('datos_prueba.npz', tensor=tensor_falso)

    # 2. Iniciamos la Interfaz
    app = QApplication(sys.argv)
    
    # Le pasamos la ruta del archivo y el índice de la banda que queremos ver
    visor = VisorAnimacion3D(ruta_npz='datos_prueba.npz', indice_banda=0)
    visor.show()
    
    sys.exit(app.exec())