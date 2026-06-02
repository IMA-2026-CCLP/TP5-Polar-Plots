# mic_array/patron.py

import re
import numpy as np
import soundfile as sf
import plotly.graph_objects as go
from pathlib import Path
from scipy.signal import hilbert


class MicArray:
    """
    Represents a polar directivity measurement of the singing voice.

    The array consists of 19 microphones arranged in a vertical semicircle
    around the singer, at 2.5m from the mouth. A turntable rotates the singer
    from 0° to 180° in azimuth.

    Attributes
    ----------
    tensor : np.ndarray  shape (n_angles, n_mics, n_samples)
    sr     : int         sample rate in Hz
    """

    def __init__(self, tensor, sr=44100, angles=None, mics=None):
        self.tensor = tensor   # (n_angles, n_mics, n_samples)
        self.sr     = sr

        # Derived from tensor shape
        self.n_angles, self.n_mics, self.n_samples = tensor.shape

        # Angle values: [0, 10, 20, ..., 180] by default
        self.angles = angles if angles is not None \
                      else list(range(0, self.n_angles * 10, 10))

        # Mic labels: ['ref', 1, 2, ..., 19] by default
        self.mics = mics if mics is not None \
                    else ['ref'] + list(range(1, self.n_mics))

        # Downsampling factor for plots (1 = no downsampling)
        self.downsampling_graph = 10

        # Smoothing window for envelope in ms (0 = no smoothing)
        self.smoothing_ms = 20

        print(f"MicArray loaded — shape: {tensor.shape}  sr: {sr} Hz")

    # ──────────────────────────────────────────────────────────────────────────
    # Constructors
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_tensor(cls, path, sr=44100):
        """
        Load a MicArray from a pre-built .npy tensor file.

        Parameters
        ----------
        path : str or Path   path to the .npy file
        sr   : int           sample rate in Hz (default: 44100)

        Returns
        -------
        MicArray instance

        Example
        -------
        ma = MicArray.from_tensor("data/tensores/forte.npy")
        """
        tensor = np.load(path, mmap_mode='r')
        return cls(tensor, sr)

    @classmethod
    def from_audio(cls, path):
        """
        Load a MicArray from a folder of WAV audio files.
        Builds the tensor from scratch.

        Expected folder structure:
            path/
                mic_ref/   mic_ref_ang_forte_0.wav ...
                mic_1/     mic_1_ang_forte_0.wav   ...
                mic_19/    ...

        Parameters
        ----------
        path : str or Path   path to the folder containing the WAV files

        Returns
        -------
        MicArray instance

        Example
        -------
        ma = MicArray.from_audio("data/audio/array/forte")
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        # Patterns to identify mic folders and audio files
        pat_num  = re.compile(r"^mic_(\d+)$")
        pat_ref  = re.compile(r"^mic_ref$", re.IGNORECASE)
        pat_file = re.compile(r"_ang_\w+_(\d+)\.wav$", re.IGNORECASE)

        # ── Step 1: discover mics and angles ──────────────────────────────────
        mics_num  = set()
        has_ref   = False
        angles    = set()
        sr        = None

        for folder in path.iterdir():
            if not folder.is_dir():
                continue

            if pat_ref.match(folder.name):
                has_ref = True
                for f in folder.glob("*.wav"):
                    m = pat_file.search(f.name)
                    if m:
                        angles.add(int(m.group(1)))
                if sr is None:
                    for f in folder.glob("*.wav"):
                        _, sr = sf.read(f)
                        break
                continue

            m = pat_num.match(folder.name)
            if not m:
                continue
            mics_num.add(int(m.group(1)))
            for f in folder.glob("*.wav"):
                fm = pat_file.search(f.name)
                if fm:
                    angles.add(int(fm.group(1)))
            if sr is None:
                for f in folder.glob("*.wav"):
                    _, sr = sf.read(f)
                    break

        angles = sorted(angles)
        mics   = (['ref'] if has_ref else []) + sorted(mics_num)

        print(f"  Mics found   : {mics}")
        print(f"  Angles found : {angles}")
        print(f"  Sample rate  : {sr} Hz")

        # ── Step 2: find max length ───────────────────────────────────────────
        max_len = 0
        for mic in mics:
            for angle in angles:
                f = _find_wav(path, mic, angle, pat_file)
                if f is None:
                    continue
                sig, _ = sf.read(f)
                if len(sig) > max_len:
                    max_len = len(sig)

        print(f"  Max length   : {max_len} samples  ({max_len / sr:.2f} s)")

        # ── Step 3: build tensor (zero-padded) ────────────────────────────────
        data = np.zeros((len(angles), len(mics), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for i_az, angle in enumerate(angles):
            for i_mic, mic in enumerate(mics):
                f = _find_wav(path, mic, angle, pat_file)
                if f is None:
                    print(f"    [SKIP] mic_{mic}  {angle}° → not found")
                    continue
                sig, _ = sf.read(f)
                data[i_az, i_mic, :len(sig)] = sig
            print(f"    Angle {angle:>4}° → OK")

        print(f"\n  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=angles, mics=mics)


    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _az_to_row(self, azimuth):
        """Maps an azimuth angle value to its row index in the tensor."""
        if azimuth not in self.angles:
            raise ValueError(f"Azimuth {azimuth}° not found. Available: {self.angles}")
        return self.angles.index(azimuth)

    def _mic_to_col(self, mic):
        """Maps a mic label to its column index in the tensor."""
        if mic not in self.mics:
            raise ValueError(f"Mic '{mic}' not found. Available: {self.mics}")
        return self.mics.index(mic)

    def _prepare(self, signal, envelope):
        """
        Prepares a signal for plotting.
        - envelope=True : computes smooth envelope via Hilbert transform,
                          then applies a moving average of self.smoothing_ms ms.
        - envelope=False: uses the raw signal.
        Then downsamples by self.downsampling_graph.
        """
        factor = max(1, self.downsampling_graph)

        if envelope:
            s = np.abs(hilbert(signal))

            # Apply moving average smoothing if smoothing_ms > 0
            window = int(self.smoothing_ms / 1000 * self.sr)
            if window > 1:
                kernel = np.ones(window) / window
                s = np.convolve(s, kernel, mode='same')
        else:
            s = signal

        return s[::factor], factor

    # ──────────────────────────────────────────────────────────────────────────
    # Copy
    # ──────────────────────────────────────────────────────────────────────────

    def copy(self):
        """
        Returns a new MicArray with an independent copy of the tensor.
        Changes to the copy do not affect the original.
        """
        return MicArray(
            tensor = self.tensor.copy(),   # .copy() garantiza array nuevo e independiente
            sr     = self.sr,
            angles = self.angles.copy(),
            mics   = self.mics.copy(),
        )

    def save(self, path):
        """
        Saves the tensor to a .npy file.

        Parameters
        ----------
        path : str or Path   destination file (e.g. "data/tensores/forte_aligned.npy")
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, self.tensor)
        print(f"  Saved: {path}  {self.tensor.shape}  ({self.tensor.nbytes/1024**2:.1f} MB)")

    # ──────────────────────────────────────────────────────────────────────────
    # Alignment methods
    # ──────────────────────────────────────────────────────────────────────────

    def align_ref(self, mic='ref'):
        """
        Aligns the reference mic to the array mics using GCC-PHAT.

        For each azimuth take:
          1. Computes GCC-PHAT(mic_ref, mic_i) for each array mic i → TDOA τᵢ
          2. Averages all τᵢ → τ_mean
          3. Shifts mic_ref by τ_mean samples

        τ > 0 means mic_ref arrives later than the array → shift left (advance).
        τ < 0 means mic_ref arrives earlier than the array → shift right (delay).
        Only mic_ref is moved; all other mics remain untouched.

        Modifies the tensor in-place.

        Parameters
        ----------
        mic : int or 'ref'   reference mic label to align (default: 'ref')
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_ref    = self._mic_to_col(mic)
        other_ix = [i for i in range(self.n_mics) if i != i_ref]

        print(f"  Aligning mic_{mic} against {len(other_ix)} mics...\n")

        for i_az in range(self.n_angles):
            ref_sig = self.tensor[i_az, i_ref, :].astype(np.float64)

            tdoas = [_gcc_phat(ref_sig, self.tensor[i_az, i_m, :].astype(np.float64))
                     for i_m in other_ix]

            tau = int(np.round(np.mean(tdoas)))

            shifted = np.zeros(self.n_samples, dtype=np.float64)
            if tau > 0:
                shifted[:-tau] = ref_sig[tau:]      # advance: remove first τ samples
            elif tau < 0:
                shifted[-tau:] = ref_sig[:tau]      # delay:   pad τ zeros at front
            else:
                shifted = ref_sig.copy()

            self.tensor[i_az, i_ref, :] = shifted.astype(np.float32)

            print(f"  {self.angles[i_az]:>4}°  τ = {tau:>6} smp"
                  f"  ({tau / self.sr * 1000:.1f} ms)"
                  f"  std = {np.std(tdoas):.1f} smp")

        print("\n  Alignment done.")

    def hpf(self, cutoff_hz):
        """
        Applies a 4th-order Butterworth high-pass filter to every mic of every
        take in the tensor. Modifies the tensor in-place.

        Parameters
        ----------
        cutoff_hz : float   cutoff frequency in Hz (e.g. 200)
        """
        from scipy.signal import butter, sosfilt

        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        sos = butter(4, cutoff_hz, btype='high', fs=self.sr, output='sos')

        for i_az in range(self.n_angles):
            for i_m in range(self.n_mics):
                self.tensor[i_az, i_m, :] = sosfilt(
                    sos, self.tensor[i_az, i_m, :]
                ).astype(np.float32)

        print(f"  HPF applied — {cutoff_hz} Hz, 4th-order Butterworth"
              f"  ({self.n_angles} takes × {self.n_mics} mics)")

    # ──────────────────────────────────────────────────────────────────────────
    # Plotting methods
    # ──────────────────────────────────────────────────────────────────────────

    def plot_takes(self, azimuth, mics="all", title=None, envelope=False):
        """
        For a single azimuth angle, plots the signal of each mic.

        Parameters
        ----------
        azimuth  : int              azimuth angle value (e.g. 0, 10, 90, 180)
        mics     : "all" or list    mic labels to plot (e.g. [1, 5, 10, 'ref'])
        title    : str or None      plot title, no title if None
        envelope : bool             if True, shows abs envelope (default: True)
        """
        i_az  = self._az_to_row(azimuth)
        mics_ = self.mics if mics == "all" else mics

        fig = go.Figure()
        for mic in mics_:
            i_mic      = self._mic_to_col(mic)
            signal     = self.tensor[i_az, i_mic, :]
            ds, factor = self._prepare(signal, envelope)
            t          = np.arange(len(ds)) * factor / self.sr
            fig.add_trace(go.Scatter(
                x=t, y=ds,
                mode='lines', line=dict(width=1),
                name=f"mic_{mic}",
            ))

        fig.update_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title="Amplitude",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey'),
            width=1200, height=500,
        )
        fig.show()

    def plot_mics(self, mic, azimuths="all", title=None, envelope=False):
        """
        For a single mic (elevation), plots the signal of each azimuth take.

        Parameters
        ----------
        mic      : int or 'ref'    mic label (e.g. 1, 10, 'ref')
        azimuths : "all" or list   azimuth values to plot (e.g. [0, 90, 180])
        title    : str or None     plot title, no title if None
        envelope : bool            if True, shows abs envelope (default: True)
        """
        i_mic     = self._mic_to_col(mic)
        azimuths_ = self.angles if azimuths == "all" else azimuths

        fig = go.Figure()
        for az in azimuths_:
            i_az       = self._az_to_row(az)
            signal     = self.tensor[i_az, i_mic, :]
            ds, factor = self._prepare(signal, envelope)
            t          = np.arange(len(ds)) * factor / self.sr
            fig.add_trace(go.Scatter(
                x=t, y=ds,
                mode='lines', line=dict(width=1),
                name=f"{az}°",
            ))

        fig.update_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title="Amplitude",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey'),
            width=1200, height=500,
        )
        fig.show()

    def plot_take(self, azimuth, mic, title=None, envelope=False):
        """
        Plots the time-domain signal for a single azimuth and mic.

        Parameters
        ----------
        azimuth  : int              azimuth angle value (e.g. 0, 90, 180)
        mic      : int or 'ref'     mic label (e.g. 1, 10, 'ref')
        title    : str or None      plot title, no title if None
        envelope : bool             if True, shows abs envelope (default: False)
        """
        i_az       = self._az_to_row(azimuth)
        i_mic      = self._mic_to_col(mic)
        signal     = self.tensor[i_az, i_mic, :]
        ds, factor = self._prepare(signal, envelope)
        t          = np.arange(len(ds)) * factor / self.sr

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=t, y=ds,
            mode='lines', line=dict(width=1),
            name=f"mic_{mic} — {azimuth}°",
        ))

        fig.update_layout(
            title=title,
            xaxis_title="Time (s)",
            yaxis_title="Amplitude",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey'),
            width=1200, height=400,
        )
        fig.show()


# ── Module-level helpers (not part of the class) ─────────────────────────────

def _gcc_phat(sig1, sig2):
    """
    Estimates the TDOA between sig1 and sig2 using GCC-PHAT.

    Returns the delay in samples: positive means sig1 arrives later than sig2
    (sig1 is delayed), negative means sig1 arrives earlier.

    Parameters
    ----------
    sig1 : np.ndarray 1D   reference signal (e.g. mic_ref)
    sig2 : np.ndarray 1D   array mic signal

    Returns
    -------
    tau : int   delay in samples
    """
    n     = len(sig1) + len(sig2) - 1
    n_fft = 2 ** int(np.ceil(np.log2(n)))   # next power of 2 → fast FFT

    S1 = np.fft.rfft(sig1, n=n_fft)
    S2 = np.fft.rfft(sig2, n=n_fft)

    # Cross-spectrum with PHAT weighting (keep only phase)
    G      = S1 * np.conj(S2)
    G_phat = G / (np.abs(G) + 1e-10)

    # IFFT → GCC-PHAT function in the lag domain
    gcc = np.fft.irfft(G_phat, n=n_fft)

    # Find the lag with the highest peak
    tau = int(np.argmax(np.abs(gcc)))

    # Convert to signed delay (lags > n_fft/2 are negative delays)
    if tau > n_fft // 2:
        tau -= n_fft

    return tau


def _detect_onset(signal, sr, window_ms=50, noise_s=2.0, margin_db=10):
    """
    Detects the onset of a signal using a threshold relative to the noise floor.

    Parameters
    ----------
    signal    : np.ndarray   audio signal
    sr        : int          sample rate
    window_ms : float        RMS window size in ms
    noise_s   : float        seconds at the start used to estimate noise floor
    margin_db : float        dB above noise floor to set the threshold

    Returns
    -------
    onset : int   sample index of the detected onset
    """
    window      = int(window_ms / 1000 * sr)
    noise_samps = int(noise_s * sr)

    # Estimate noise floor from the first noise_s seconds
    rms_noise = np.sqrt(np.mean(signal[:noise_samps] ** 2)) + 1e-12
    threshold = rms_noise * 10 ** (margin_db / 20)

    for i in range(0, len(signal) - window, window):
        rms = np.sqrt(np.mean(signal[i:i + window] ** 2))
        if rms > threshold:
            return i

    return 0


def _find_wav(root, mic, angle, pat_file):
    """Returns the Path of the WAV for a given mic and angle, or None."""
    folder = root / f"mic_{mic}"
    if not folder.exists():
        return None
    pat = re.compile(rf"mic_{mic}_ang_\w+_{angle}\.wav$", re.IGNORECASE)
    for f in folder.glob("*.wav"):
        if pat.search(f.name):
            return f
    return None
