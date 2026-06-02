import os
from tqdm import tqdm
import math
import random
import pesto
import torchaudio
import torch
import numpy as np
import pandas as pd

# Cargo el modelo una única vez y lo llamo de acá después.
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(device)
pesto_model = pesto.load_model("mir-1k_g7", step_size=20.).to(device)

def CalcularF0_pesto(path, umbral_confianza, name=""):
    """
    Calcula el F0 de un archivo de audio usando PESTO.
    Retorna una lista de valores de pitch filtrados por umbral de confianza.
    """
    print(f"Calculando F0 para: {path}")

    # Cargar audio (mono obligatorio para pesto)
    x, sr = torchaudio.load(path)
    if x.dim() > 1:
        x = x.mean(dim=0)  # convertir a mono
    
    # print(f'path {path}')
    # print(f'sr {sr}')
    # print(f'x {x}')
    # print(f'pitch {x.detach().cpu().tolist()}')
    x = x.to(device)

    # Ejecutar PESTO
    # timesteps, pitch, confidence, activations = pesto.predict(x, sr) Cambio el predcit que carga el modelo en cada llamada por la llamada al modelo precargado.
    pitch, confidence, amplitude = pesto_model(x, sr=sr, convert_to_freq = True, return_activations = False)
    # print(f'pitch {pitch.detach().cpu().tolist()}')
    # print(f'confidence {confidence.detach().cpu().tolist()}')
    # print(f'amplitude {amplitude.detach().cpu().tolist()}')
    # print(f'activations {activations.detach().cpu().tolist()}')

    # pitch_filtrado = []
    # for i in range(len(confidence)):
    #     if confidence[i] > umbral_confianza:
    #         pitch_filtrado.append(pitch[i])

    mask = confidence > umbral_confianza
    pitch_filtrado = pitch[mask]

    return pitch_filtrado.detach().cpu().tolist()

def compute_vals_batch(folder_path, N, umbral_confianza=0.80):
    """
    Computa métricas de F0 (mean y std) por subcarpeta dentro de folder_path.
    Guarda los resultados en un DataFrame.
    """
    resultados = []
        
    for folder in tqdm(os.listdir(folder_path), desc="Procesando carpetas"):
        path_folder = os.path.join(folder_path, folder)
        if not os.path.isdir(path_folder):
            continue

        F0_folder = []
        resultados_folder = []

        path_audios_iter = os.listdir(path_folder)
        if len(path_audios_iter) == 0:
            continue

        F0_audios = {}
        F0 = []
        for audio_path in path_audios_iter:
            print(audio_path)
            if audio_path.endswith(".wav"):
                path = os.path.join(path_folder, audio_path)
                pitch_filtrado = CalcularF0_pesto(path, umbral_confianza)
                F0.extend(pitch_filtrado)
                F0_audios[audio_path] = pitch_filtrado
                F0_folder.extend(pitch_filtrado)

        if len(F0) > 0:
            F0 = np.array(F0)
            mean_val = np.mean(F0)
            std_val = np.std(F0)
        else:
            mean_val = np.nan
            std_val = np.nan

        resultados_folder.append({
            "Nombre": folder,
            "mean": mean_val,
            "std": std_val
        })

        df_resultados_folder = pd.DataFrame(F0_audios.items(), columns=["Audio", "F0_filtrado"])
        df_resultados_folder.to_csv(os.path.join(path_folder, f"resultados_pitch_{folder}.csv"), index=False)

        # df_resultados_dataset = pd.DataFrame(resultados_folder)
        # df_resultados_dataset.to_csv(os.path.join(folder_path, "resultados_pitch_dataset.csv"), index=False)

    if len(F0_folder) > 0:
        F0_folder = np.array(F0_folder)
        mean_val_dataset = np.mean(F0_folder)
        std_val_dataset = np.std(F0_folder)
    else:
        mean_val_dataset = np.nan
        std_val_dataset = np.nan

    resultados.append({
        "Nombre": folder,
        "mean": mean_val_dataset,
        "std": std_val_dataset
    })

    df_resultados = pd.DataFrame(resultados)
    return df_resultados


# === CONFIGURACIÓN ===
# folder_path = 'C:/Users/emman/OneDrive/Intercambios Transorganicos/CalculadorDePitch/Dataset_mas_corto/Cadena Sin Denoising'
folder_path = 'D:/Ing. de Sonido/IMA/TPs/TP 5/TP5-Polar-Plots/medicion_juli_mic_ref'
umbral_confianza = 0.80
N = 3
output_csv = os.path.join(folder_path, "resultados_pitch.csv")

# === EJECUCIÓN ===
df_resultados = compute_vals_batch(folder_path, N, umbral_confianza)
print(df_resultados)

# Guardar a CSV
df_resultados.to_csv(output_csv, index=False)
print(f"Resultados guardados en: {output_csv}")
