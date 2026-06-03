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
        Load a MicArray from a .npy or .npz file.

        .npz files also restore sr, angles and mics saved by save().
        For .npy files, sr must be provided manually.

        Parameters
        ----------
        path : str or Path   path to the .npy or .npz file
        sr   : int           sample rate in Hz, only used for .npy (default: 44100)

        Returns
        -------
        MicArray instance

        Example
        -------
        ma = MicArray.from_tensor("data/tensores/forte_aligned.npz")
        ma = MicArray.from_tensor("data/tensores/forte.npy")
        """
        path = Path(path)
        if path.suffix == '.npz':
            data   = np.load(path, allow_pickle=True)
            tensor = data['tensor']
            sr     = int(data['sr'])
            angles = data['azimuth'].tolist()
            mics   = data['elevation'].tolist()
            return cls(tensor, sr=sr, angles=angles, mics=mics)
        else:
            tensor = np.load(path, mmap_mode='r')
            return cls(tensor, sr)

    @classmethod
    def from_audio(cls, path, array_pattern, ref_pattern=None):
        """
        Load a MicArray from a flat directory of WAV files.

        Uses regex patterns to identify array mic files and optionally the
        reference mic files. {H} captures the azimuth angle and {V} captures
        the elevation angle (array mics only).

        Parameters
        ----------
        path          : str or Path   directory containing the WAV files
        array_pattern : str           pattern for array mic files, must contain
                                      {H} (azimuth) and {V} (elevation)
                                      e.g. 'mic_{H:03d}_{V:03d}_forte.wav'
        ref_pattern   : str or None   pattern for reference mic files, must
                                      contain {H} (azimuth)
                                      e.g. 'ref_{H:03d}_forte.wav'
                                      None if there is no reference mic.

        Vertical axis convention (auto-detected from array_pattern):
          {MIC} → mic number directly (1–19)
          {V}   → elevation angle in degrees (0,10..180), converted to mic number

        Returns
        -------
        MicArray instance

        Example
        -------
        ma = MicArray.from_audio(
            "data/audio/forte",
            array_pattern = "mic_{H:03d}_{V:03d}_forte.wav",
            ref_pattern   = "ref_{H:03d}_forte.wav",
        )
        """
        path       = Path(path)
        arr_regex  = _pattern_to_regex(array_pattern)
        ref_regex  = _pattern_to_regex(ref_pattern) if ref_pattern else None

        azimuths   = set()
        elevations = set()
        sr         = None

        # ── Step 1: discover azimuths, elevations and sr ─────────────────────
        v_key      = 'MIC' if '{MIC' in array_pattern else 'V'
        v_is_angle = v_key == 'V'

        for f in sorted(path.glob("*.wav")):
            m = arr_regex.search(f.name)
            if m:
                azimuths.add(int(m.group('H')))
                elevations.add(int(m.group(v_key)))
                if sr is None:
                    _, sr = sf.read(f)
                continue
            if ref_regex:
                m = ref_regex.search(f.name)
                if m:
                    azimuths.add(int(m.group('H')))
                    if sr is None:
                        _, sr = sf.read(f)

        v_is_angle = v_key == 'V'
        azimuths   = sorted(azimuths)
        mic_nums   = [e // 10 + 1 for e in sorted(elevations)] if v_is_angle \
                     else sorted(elevations)
        mics       = (['ref'] if ref_regex else []) + mic_nums

        print(f"  Azimuths   : {azimuths}")
        print(f"  Mics       : {mics}")
        print(f"  Sample rate: {sr} Hz")

        # ── Step 2: find max length ───────────────────────────────────────────
        max_len = 0
        for f in path.glob("*.wav"):
            if arr_regex.search(f.name) or (ref_regex and ref_regex.search(f.name)):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        # ── Step 3: build tensor (zero-padded) ────────────────────────────────
        data = np.zeros((len(azimuths), len(mics), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = arr_regex.search(f.name)
            if m:
                i_az  = azimuths.index(int(m.group('H')))
                v     = int(m.group('MIC') if not v_is_angle else m.group('V'))
                i_mic = mics.index(v // 10 + 1 if v_is_angle else v)
                sig, _ = sf.read(f)
                data[i_az, i_mic, :len(sig)] = sig
                continue
            if ref_regex:
                m = ref_regex.search(f.name)
                if m:
                    i_az  = azimuths.index(int(m.group('H')))
                    i_mic = mics.index('ref')
                    sig, _ = sf.read(f)
                    data[i_az, i_mic, :len(sig)] = sig

        for i_az, az in enumerate(azimuths):
            print(f"    {az:>4}° → OK")

        print(f"\n  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, mics=mics)

    @classmethod
    def from_export(cls, path, pattern='mic_{H}_{V}.wav'):
        """
        Load a MicArray from a flat folder of WAV files.

        The filename pattern uses {H} for the horizontal (azimuth) angle and
        {V} for the vertical (elevation) angle. Format specs are supported.

        Parameters
        ----------
        path    : str or Path   folder containing the WAV files
        pattern : str           filename pattern with {H} and {V} placeholders
                                e.g. 'mic_{H:03d}_ang_forte_{V:03d}.wav'
                                     'mic_{H}_{V}_Fa4.wav'

        Returns
        -------
        MicArray instance

        Example
        -------
        ma = MicArray.from_export("data/audio/forte_export",
                                   pattern="mic_{H:03d}_ang_forte_{V:03d}.wav")
        """
        path  = Path(path)
        regex = _pattern_to_regex(pattern)

        azimuths   = set()
        elevations = set()
        sr         = None

        for f in sorted(path.glob("*.wav")):
            m = regex.search(f.name)
            if not m:
                continue
            azimuths.add(int(m.group('H')))
            elevations.add(int(m.group('V')))
            if sr is None:
                _, sr = sf.read(f)

        azimuths   = sorted(azimuths)
        elevations = sorted(elevations)
        mics       = [e // 10 + 1 for e in elevations]

        print(f"  Azimuths   : {azimuths}")
        print(f"  Elevations : {elevations}  → mics: {mics}")
        print(f"  Sample rate: {sr} Hz")

        max_len = 0
        for f in path.glob("*.wav"):
            if regex.search(f.name):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        data = np.zeros((len(azimuths), len(mics), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = regex.search(f.name)
            if not m:
                continue
            i_az  = azimuths.index(int(m.group('H')))
            i_mic = elevations.index(int(m.group('V')))
            sig, _ = sf.read(f)
            data[i_az, i_mic, :len(sig)] = sig

        print(f"  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, mics=mics)


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

    def export_wavs(self, path, nota=''):
        """
        Exports all mics and takes as individual WAV files to a directory.

        File naming: mic_{azimuth}_{elevation}_{nota}.wav
          azimuth   : take angle in degrees (0–180)
          elevation : mic elevation in degrees — mic_1=0°, mic_2=10°, ..., mic_19=180°
          nota      : note name passed as parameter (e.g. 'Fa4')

        mic_ref is skipped (no elevation mapping).

        Parameters
        ----------
        path : str or Path   output directory
        nota : str           note label for the filename (default: '')
        """
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)

        count = 0
        for i_az, azimuth in enumerate(self.angles):
            for i_mic, mic in enumerate(self.mics):
                if mic == 'ref':
                    continue
                elevation = (mic - 1) * 10
                filename  = f"mic_{azimuth}_{elevation}_{nota}.wav"
                signal    = self.tensor[i_az, i_mic, :].astype(np.float32)
                sf.write(out / filename, signal, self.sr)
                count += 1

        print(f"  Exported {count} files → {out}")

    def save(self, path):
        """
        Saves the tensor and metadata (sr, angles, mics) to a .npz file.

        Parameters
        ----------
        path : str or Path   destination file (e.g. "data/tensores/forte_aligned.npz")
        """
        path = Path(path).with_suffix('.npz')
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path,
                 tensor    = self.tensor,
                 sr        = np.array(self.sr),
                 azimuth   = np.array(self.angles),
                 elevation = np.array(self.mics, dtype=object),
        )
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

    def normalize_takes(self, mic='ref', ref_azimuth=0):
        """
        Normalizes the level of all takes relative to a reference take.

        Computes the global RMS of the specified mic in each take and scales
        ALL mics in that take so its RMS matches the reference take.

        Parameters
        ----------
        mic         : int or 'ref'   mic used to measure level (default: 'ref')
        ref_azimuth : int            azimuth of the reference take (default: 0)
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_mic    = self._mic_to_col(mic)
        i_ref_az = self._az_to_row(ref_azimuth)

        rms_ref = np.sqrt(np.mean(self.tensor[i_ref_az, i_mic, :] ** 2))

        print(f"  Reference: mic_{mic} at {ref_azimuth}°  RMS = {20*np.log10(rms_ref):.1f} dBFS\n")

        for i_az in range(self.n_angles):
            rms_i = np.sqrt(np.mean(self.tensor[i_az, i_mic, :] ** 2))
            gain  = rms_ref / (rms_i + 1e-12)
            self.tensor[i_az, :, :] *= gain

            diff_db = 20 * np.log10(gain)
            marker  = "  ← ref" if i_az == i_ref_az else ""
            print(f"  {self.angles[i_az]:>4}°  RMS = {20*np.log10(rms_i):.1f} dBFS"
                  f"  gain = {diff_db:+.1f} dB{marker}")

        print("\n  Normalization done.")

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

    def plot_rms_takes(self, mic='ref', floor_db=-60, yrange=None):
        """
        Plots the RMS level (dBFS) of a mic across all takes as a VU-meter style
        bar chart: bars rise from floor_db up to the dBFS value of each take.

        Parameters
        ----------
        mic      : int or 'ref'        mic to measure (default: 'ref')
        floor_db : float               bottom of the y-axis in dBFS (default: -60)
        yrange   : [float, float]      optional y-axis zoom, e.g. [-40, -20]
        """
        i_mic = self._mic_to_col(mic)

        rms_db = [
            20 * np.log10(np.sqrt(np.mean(self.tensor[i_az, i_mic, :] ** 2)) + 1e-12)
            for i_az in range(self.n_angles)
        ]

        fig = go.Figure(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=[r - floor_db for r in rms_db],
            base=floor_db,
            marker_color='steelblue',
            text=[f"{r:.1f}" for r in rms_db],
            textposition='outside',
        ))
        fig.update_layout(
            title=f"RMS por toma — mic_{mic}",
            xaxis_title="Azimut",
            yaxis=dict(title="dBFS", range=yrange if yrange else [floor_db, 0], gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=400,
        )
        fig.show()

    def detect_notes(self, scale, mic='ref', hop_length=512, tolerance_cents=50):
        """
        Detects the interval (start/end in samples) of each note of a scale
        in every take, using pyin on the specified mic.

        Parameters
        ----------
        scale           : dict   {note_name: freq_hz}, e.g. FA_MAYOR
        mic             : int or 'ref'   mic to analyze (default: 'ref')
        hop_length      : int    pyin hop length in samples (default: 512)
        tolerance_cents : float  max deviation in cents to assign a frame to a note (default: 50)

        Returns
        -------
        segmentos : list of dicts  (one per azimuth take)
            segmentos[i_az][note_name] = {'start': int, 'end': int}  in samples
        """
        import librosa

        i_mic       = self._mic_to_col(mic)
        note_names  = list(scale.keys())
        note_freqs  = np.array(list(scale.values()))
        fmin        = min(note_freqs) * 0.9
        fmax        = max(note_freqs) * 1.1

        col_w = 6
        header = f"{'Toma':>6}  " + "  ".join(f"{n:<{col_w}}" for n in note_names)
        print(header)
        print("─" * len(header))

        segmentos = []

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_mic, :].astype(np.float32)

            f0, _, _ = librosa.pyin(
                signal, fmin=fmin, fmax=fmax,
                sr=self.sr, hop_length=hop_length, fill_na=np.nan,
            )

            # Assign each voiced frame to the closest note within tolerance
            assigned = []
            for freq in f0:
                if np.isnan(freq):
                    assigned.append(None)
                    continue
                cents     = np.abs(1200 * np.log2(freq / note_freqs))
                i_closest = int(np.argmin(cents))
                assigned.append(note_names[i_closest] if cents[i_closest] <= tolerance_cents else None)

            # Extract the longest contiguous segment per note
            segs = {}
            for note in note_names:
                frames = [i for i, a in enumerate(assigned) if a == note]
                if not frames:
                    continue
                groups, start, prev = [], frames[0], frames[0]
                for f in frames[1:]:
                    if f > prev + 1:
                        groups.append((start, prev))
                        start = f
                    prev = f
                groups.append((start, prev))
                best = max(groups, key=lambda g: g[1] - g[0])
                segs[note] = {
                    'start': best[0] * hop_length,
                    'end':   min(best[1] * hop_length + hop_length, self.n_samples),
                }

            segmentos.append(segs)

            row = []
            for note in note_names:
                if note in segs:
                    dur = (segs[note]['end'] - segs[note]['start']) / self.sr
                    row.append(f"{dur:.2f}s ")
                else:
                    row.append("--    ")
            print(f"{self.angles[i_az]:>5}°  " + "  ".join(row))

        print(f"\n  Notas detectadas: {len(note_names)} notas × {self.n_angles} tomas")
        return segmentos

    def extract_note(self, segmentos, note):
        """
        Returns a new MicArray containing only the audio of a given note,
        cropped from each take. Takes with missing note detection are zeroed.

        Parameters
        ----------
        segmentos : list   output of detect_notes()
        note      : str    note name, e.g. 'Fa4'

        Returns
        -------
        MicArray with shape (n_angles, n_mics, max_note_length)
        """
        lengths = [
            seg[note]['end'] - seg[note]['start']
            for seg in segmentos if note in seg
        ]
        if not lengths:
            raise ValueError(f"Note '{note}' not found in any take.")

        max_len = max(lengths)
        data    = np.zeros((self.n_angles, self.n_mics, max_len), dtype=np.float32)

        for i_az, seg in enumerate(segmentos):
            if note not in seg:
                print(f"  [WARN] {self.angles[i_az]}°: '{note}' not detected, take zeroed")
                continue
            s = seg[note]['start']
            e = seg[note]['end']
            data[i_az, :, :e - s] = self.tensor[i_az, :, s:e]

        print(f"  extract_note('{note}')  shape: {data.shape}"
              f"  ({max_len / self.sr * 1000:.0f} ms max)")

        return MicArray(data, sr=self.sr, angles=self.angles.copy(), mics=self.mics.copy())

    def listen(self, azimuth, mic):
        """
        Returns an IPython Audio widget to listen to a specific take and mic.

        Parameters
        ----------
        azimuth : int          azimuth angle value (e.g. 0, 90, 180)
        mic     : int or 'ref' mic label (e.g. 1, 10, 'ref')
        """
        from IPython.display import Audio, display

        i_az   = self._az_to_row(azimuth)
        i_mic  = self._mic_to_col(mic)
        signal = self.tensor[i_az, i_mic, :].astype(np.float32)

        # Trim trailing zeros (from extract_note padding)
        nonzero = np.nonzero(signal)[0]
        if len(nonzero):
            signal = signal[:nonzero[-1] + 1]

        print(f"  mic_{mic}  |  {azimuth}°  |  {len(signal)/self.sr:.2f}s")
        display(Audio(signal, rate=self.sr))

    def extract_all_notes(self, segmentos, scale):
        """
        Extracts all notes in a scale and returns them as a dict of MicArrays.

        Parameters
        ----------
        segmentos : list   output of detect_notes()
        scale     : dict   {note_name: freq_hz}

        Returns
        -------
        dict  {note_name: MicArray}
        """
        return {note: self.extract_note(segmentos, note) for note in scale}

    def plot_tune(self, scale, azimuth, mic='ref', hop_length=512, confidence_threshold=0.5):
        """
        Plots the tuning deviation (in cents) of each note in a scale for a given take.

        For each note, computes the mean and std of the pyin f0 deviation
        relative to the theoretical frequency. Shows ±50 cent tolerance bands.

        Parameters
        ----------
        scale                : dict   {note_name: freq_hz}
        azimuth              : int    azimuth take to analyze
        mic                  : int or 'ref'   mic to use (default: 'ref')
        hop_length           : int    pyin hop length in samples (default: 512)
        confidence_threshold : float  min pyin confidence to accept a frame (default: 0.5)
        """
        import librosa

        i_az  = self._az_to_row(azimuth)
        i_mic = self._mic_to_col(mic)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1

        signal = self.tensor[i_az, i_mic, :].astype(np.float32)

        f0, _, voiced_prob = librosa.pyin(
            signal, fmin=fmin, fmax=fmax,
            sr=self.sr, hop_length=hop_length, fill_na=np.nan,
        )

        # Group f0 frames by note
        cents_per_note = {n: [] for n in note_names}
        for freq, prob in zip(f0, voiced_prob):
            if np.isnan(freq) or prob < confidence_threshold:
                continue
            dists = np.abs(1200 * np.log2(freq / note_freqs))
            i_closest = int(np.argmin(dists))
            if dists[i_closest] <= 100:   # within a semitone
                deviation = 1200 * np.log2(freq / note_freqs[i_closest])
                cents_per_note[note_names[i_closest]].append(deviation)

        means = [np.mean(cents_per_note[n]) if cents_per_note[n] else np.nan for n in note_names]
        stds  = [np.std(cents_per_note[n])  if cents_per_note[n] else 0      for n in note_names]

        colors = []
        for m in means:
            if np.isnan(m):       colors.append('lightgrey')
            elif abs(m) <= 25:    colors.append('seagreen')
            elif abs(m) <= 50:    colors.append('goldenrod')
            else:                 colors.append('crimson')

        fig = go.Figure()

        # ±50 cent tolerance band
        fig.add_hrect(y0=-50, y1=50, fillcolor='lightgreen', opacity=0.1, line_width=0)

        fig.add_trace(go.Bar(
            x=note_names,
            y=means,
            error_y=dict(type='data', array=stds, visible=True),
            marker_color=colors,
            text=[f"{m:.1f}¢" if not np.isnan(m) else "—" for m in means],
            textposition='outside',
        ))

        fig.add_hline(y=0,   line=dict(color='black', width=1))
        fig.add_hline(y=50,  line=dict(color='green',  width=1, dash='dash'))
        fig.add_hline(y=-50, line=dict(color='green',  width=1, dash='dash'))

        fig.update_layout(
            title=f"Afinación — mic_{mic}  |  {azimuth}°",
            xaxis_title="Nota",
            yaxis_title="Desviación (cents)",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey', zeroline=False),
            width=800, height=450,
        )
        fig.show()

    def plot_f0(self, scale, azimuth, mic='ref', hop_length=512, band_cents=50):
        """
        Plots the pyin f0 tracking for a specific take against the scale notes.

        Shows the detected fundamental frequency over time (in cents relative to
        the lowest note), with horizontal bands marking each note's target position
        and ±50 cent tolerance zones.

        Parameters
        ----------
        scale      : dict          {note_name: freq_hz}
        azimuth    : int           azimuth take to analyze
        mic        : int or 'ref'  mic to use (default: 'ref')
        hop_length : int           pyin hop length in samples (default: 512)
        band_cents : float         half-width of the shaded band per note in cents (default: 50)
        """
        import librosa

        i_az  = self._az_to_row(azimuth)
        i_mic = self._mic_to_col(mic)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        f_ref      = note_freqs[0]   # lowest note as cents reference
        fmin       = note_freqs[0] * 0.9
        fmax       = note_freqs[-1] * 1.1

        signal = self.tensor[i_az, i_mic, :].astype(np.float32)

        f0, voiced, _ = librosa.pyin(
            signal, fmin=fmin, fmax=fmax,
            sr=self.sr, hop_length=hop_length, fill_na=np.nan,
        )

        t         = np.arange(len(f0)) * hop_length / self.sr
        note_cents = {n: 1200 * np.log2(f / f_ref) for n, f in scale.items()}
        f0_cents   = np.where(voiced, 1200 * np.log2(np.where(voiced, f0, f_ref) / f_ref), np.nan)

        fig = go.Figure()

        import plotly.colors as pc
        palette = pc.qualitative.Plotly

        for i, (name, c) in enumerate(note_cents.items()):
            color = palette[i % len(palette)]
            fig.add_hrect(y0=c - band_cents, y1=c + band_cents,
                          fillcolor=color, opacity=0.15, line_width=0)
            fig.add_hline(y=c, line=dict(color=color, width=1.5))

        # Detected f0
        fig.add_trace(go.Scatter(
            x=t, y=f0_cents,
            mode='lines',
            line=dict(color='crimson', width=1.5),
            name='f0 detectada',
        ))

        fig.update_layout(
            title=f"F0 tracking — mic_{mic}  |  {azimuth}°",
            xaxis_title="Tiempo (s)",
            yaxis=dict(
                title="Nota",
                tickvals=list(note_cents.values()),
                ticktext=list(note_cents.keys()),
                gridcolor='lightgrey',
            ),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=1200, height=500,
        )
        fig.show()

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


def _pattern_to_regex(pattern):
    """
    Converts a filename pattern with {H} and {V} placeholders to a regex
    with named groups. Format specs (e.g. :03d) are ignored.

    Example
    -------
    'mic_{H:03d}_ang_forte_{V:03d}.wav'  →  'mic_(?P<H>\\d+)_ang_forte_(?P<V>\\d+)\\.wav'
    """
    result = ''
    last   = 0
    for m in re.finditer(r'\{(\w+)(?::[^}]*)?\}', pattern):
        result += re.escape(pattern[last:m.start()])
        result += f'(?P<{m.group(1)}>\\d+)'
        last = m.end()
    result += re.escape(pattern[last:])
    return re.compile(result, re.IGNORECASE)
