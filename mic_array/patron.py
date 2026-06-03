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
    tensor     : np.ndarray  shape (n_angles, n_elevations, n_samples)
    sr         : int         sample rate in Hz
    angles     : list        azimuth angles in degrees  [0, 10, ..., 180]
    elevations : list        elevation labels — 'ref' or degrees [0, 10, ..., 180]
    """

    def __init__(self, tensor, sr=44100, angles=None, elevations=None):
        self.tensor = tensor   # (n_angles, n_elevations, n_samples)
        self.sr     = sr

        self.n_angles, self.n_elevations, self.n_samples = tensor.shape

        # Azimuth values: [0, 10, ..., 180] by default
        self.angles = angles if angles is not None \
                      else list(range(0, self.n_angles * 10, 10))

        # Elevation labels: ['ref', 0, 10, ..., 180] by default
        self.elevations = elevations if elevations is not None \
                          else ['ref'] + list(range(0, (self.n_elevations - 1) * 10, 10))

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

        .npz files also restore sr, angles and elevations saved by save().
        For .npy files, sr must be provided manually.

        Parameters
        ----------
        path : str or Path   path to the .npy or .npz file
        sr   : int           sample rate in Hz, only used for .npy (default: 44100)

        Example
        -------
        ma = MicArray.from_tensor("data/tensores/forte_aligned.npz")
        ma = MicArray.from_tensor("data/tensores/forte.npy")
        """
        path = Path(path)
        if path.suffix == '.npz':
            data       = np.load(path, allow_pickle=True)
            tensor     = data['tensor']
            sr         = int(data['sr'])
            angles     = data['azimuth'].tolist()
            elevations = data['elevation'].tolist()
            return cls(tensor, sr=sr, angles=angles, elevations=elevations)
        else:
            tensor = np.load(path, mmap_mode='r')
            return cls(tensor, sr)

    @classmethod
    def from_audio(cls, path, array_pattern, ref_pattern=None):
        """
        Load a MicArray from a flat directory of WAV files.

        Uses regex patterns to identify array mic files and optionally the
        reference mic files. {H} captures the azimuth angle.

        Vertical axis convention (auto-detected from array_pattern):
          {MIC} → mic number (1–19), converted to elevation angle: (mic-1)*10
          {V}   → elevation angle in degrees (0, 10 .. 180), used directly

        Parameters
        ----------
        path          : str or Path   directory containing the WAV files
        array_pattern : str           pattern with {H} and {MIC} or {V}
                                      e.g. 'mic_{MIC}_ang_forte_{H}.wav'
                                           'mic_{V}_ang_forte_{H}.wav'
        ref_pattern   : str or None   pattern with {H} for reference mic
                                      e.g. 'mic_ref_ang_forte_{H}.wav'

        Example
        -------
        ma = MicArray.from_audio(
            "data/audio/forte",
            array_pattern = "mic_{MIC}_ang_forte_{H}.wav",
            ref_pattern   = "mic_ref_ang_forte_{H}.wav",
        )
        """
        path      = Path(path)
        arr_regex = _pattern_to_regex(array_pattern)
        ref_regex = _pattern_to_regex(ref_pattern) if ref_pattern else None

        v_key      = 'MIC' if '{MIC' in array_pattern else 'V'
        v_is_angle = v_key == 'V'

        azimuths = set()
        v_values = set()
        sr       = None

        # ── Step 1: discover azimuths, elevations and sr ─────────────────────
        for f in sorted(path.glob("*.wav")):
            m = arr_regex.search(f.name)
            if m:
                azimuths.add(int(m.group('H')))
                v_values.add(int(m.group(v_key)))
                if sr is None:
                    _, sr = sf.read(f)
                continue
            if ref_regex:
                m = ref_regex.search(f.name)
                if m:
                    azimuths.add(int(m.group('H')))
                    if sr is None:
                        _, sr = sf.read(f)

        azimuths    = sorted(azimuths)
        # Convert v_values to elevation angles
        el_angles   = sorted(v_values) if v_is_angle \
                      else sorted((v - 1) * 10 for v in v_values)
        elevations  = (['ref'] if ref_regex else []) + el_angles

        print(f"  Azimuths   : {azimuths}")
        print(f"  Elevations : {elevations}")
        print(f"  Sample rate: {sr} Hz")

        # ── Step 2: find max length ───────────────────────────────────────────
        max_len = 0
        for f in path.glob("*.wav"):
            if arr_regex.search(f.name) or (ref_regex and ref_regex.search(f.name)):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        # ── Step 3: build tensor (zero-padded) ────────────────────────────────
        data = np.zeros((len(azimuths), len(elevations), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = arr_regex.search(f.name)
            if m:
                i_az = azimuths.index(int(m.group('H')))
                v    = int(m.group(v_key))
                el   = v if v_is_angle else (v - 1) * 10
                i_el = elevations.index(el)
                sig, _ = sf.read(f)
                data[i_az, i_el, :len(sig)] = sig
                continue
            if ref_regex:
                m = ref_regex.search(f.name)
                if m:
                    i_az = azimuths.index(int(m.group('H')))
                    i_el = elevations.index('ref')
                    sig, _ = sf.read(f)
                    data[i_az, i_el, :len(sig)] = sig

        for az in azimuths:
            print(f"    {az:>4}° → OK")

        print(f"\n  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, elevations=elevations)

    @classmethod
    def from_export(cls, path, pattern='mic_{H}_{V}.wav'):
        """
        Load a MicArray from a flat folder of WAV files exported by export_wavs().

        {H} = azimuth angle, {V} = elevation angle in degrees.

        Parameters
        ----------
        path    : str or Path   folder containing the WAV files
        pattern : str           filename pattern with {H} and {V}
                                e.g. 'mic_{H:03d}_ang_forte_{V:03d}.wav'

        Example
        -------
        ma = MicArray.from_export("data/export/fa4",
                                   pattern="mic_{H}_{V}_Fa4.wav")
        """
        path  = Path(path)
        regex = _pattern_to_regex(pattern)

        azimuths = set()
        el_set   = set()
        sr       = None

        for f in sorted(path.glob("*.wav")):
            m = regex.search(f.name)
            if not m:
                continue
            azimuths.add(int(m.group('H')))
            el_set.add(int(m.group('V')))
            if sr is None:
                _, sr = sf.read(f)

        azimuths   = sorted(azimuths)
        elevations = sorted(el_set)   # V is already elevation angle

        print(f"  Azimuths   : {azimuths}")
        print(f"  Elevations : {elevations}")
        print(f"  Sample rate: {sr} Hz")

        max_len = 0
        for f in path.glob("*.wav"):
            if regex.search(f.name):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        data = np.zeros((len(azimuths), len(elevations), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = regex.search(f.name)
            if not m:
                continue
            i_az = azimuths.index(int(m.group('H')))
            i_el = elevations.index(int(m.group('V')))
            sig, _ = sf.read(f)
            data[i_az, i_el, :len(sig)] = sig

        print(f"  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, elevations=elevations)


    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _az_to_row(self, azimuth):
        """Maps an azimuth angle value to its row index in the tensor."""
        if azimuth not in self.angles:
            raise ValueError(f"Azimuth {azimuth}° not found. Available: {self.angles}")
        return self.angles.index(azimuth)

    def _el_to_col(self, elevation):
        """Maps an elevation label to its column index in the tensor."""
        if elevation not in self.elevations:
            raise ValueError(f"Elevation '{elevation}' not found. Available: {self.elevations}")
        return self.elevations.index(elevation)

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
        """Returns a new MicArray with an independent copy of the tensor."""
        return MicArray(
            tensor     = self.tensor.copy(),
            sr         = self.sr,
            angles     = self.angles.copy(),
            elevations = self.elevations.copy(),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Export / Save
    # ──────────────────────────────────────────────────────────────────────────

    def export_wavs(self, path, nota=''):
        """
        Exports all elevations and takes as individual WAV files.

        File naming: mic_{azimuth}_{elevation}_{nota}.wav
        elevation 'ref' is skipped.

        Parameters
        ----------
        path : str or Path   output directory
        nota : str           note label for the filename (default: '')
        """
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)

        count = 0
        for i_az, azimuth in enumerate(self.angles):
            for i_el, el in enumerate(self.elevations):
                if el == 'ref':
                    continue
                filename = f"mic_{azimuth}_{el}_{nota}.wav"
                signal   = self.tensor[i_az, i_el, :].astype(np.float32)
                sf.write(out / filename, signal, self.sr)
                count += 1

        print(f"  Exported {count} files → {out}")

    def save(self, path):
        """
        Saves the tensor and metadata to a .npz file.

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
                 elevation = np.array(self.elevations, dtype=object),
        )
        print(f"  Saved: {path}  {self.tensor.shape}  ({self.tensor.nbytes/1024**2:.1f} MB)")

    # ──────────────────────────────────────────────────────────────────────────
    # Alignment / Processing methods
    # ──────────────────────────────────────────────────────────────────────────

    def align_takes(self, target_onset=1.0, elevation='ref', threshold_db=-40):
        """
        Aligns all azimuth takes so their onset lands at target_onset seconds.

        For each take, detects the onset of the specified elevation and shifts
        ALL elevations of that take by the same amount, so all takes share
        a common absolute time position.

        Run this BEFORE align_ref. Modifies the tensor in-place.

        Parameters
        ----------
        target_onset  : float          desired onset time in seconds (default: 1.0)
        elevation     : int or 'ref'   elevation used to detect onset (default: 'ref')
        threshold_db  : float          RMS level in dBFS that defines the onset
                                       (default: -40). Lower → more sensitive.
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_el           = self._el_to_col(elevation)
        target_samples = int(target_onset * self.sr)
        el_label       = 'ref' if elevation == 'ref' else f'{elevation}°'

        print(f"  Target onset : {target_onset:.2f} s  ({target_samples} smp)")
        print(f"  Ref elevation: {el_label}  |  threshold = {threshold_db} dBFS\n")

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_el, :].astype(np.float64)
            onset  = _detect_onset(signal, self.sr, threshold_db=threshold_db)
            shift  = target_samples - onset  # >0 → retrasa  |  <0 → adelanta

            if shift != 0:
                tmp = np.zeros((self.n_elevations, self.n_samples), dtype=np.float32)
                if shift > 0:
                    tmp[:, shift:] = self.tensor[i_az, :, :self.n_samples - shift]
                else:
                    tmp[:, :self.n_samples + shift] = self.tensor[i_az, :, -shift:]
                self.tensor[i_az] = tmp

            print(f"  {self.angles[i_az]:>4}°  onset = {onset:>6} smp"
                  f"  ({onset / self.sr * 1000:.0f} ms)"
                  f"  shift = {shift:+d} smp  ({shift / self.sr * 1000:+.0f} ms)")

        print("\n  Take alignment done.")

    def align_to_ref(self, elevation='ref'):
        """
        Aligns each elevation to the reference using GCC-PHAT.

        For each azimuth take and each non-ref elevation:
          1. Computes GCC-PHAT(ref, el_i) → TDOA τᵢ
          2. Shifts el_i by τᵢ so it aligns temporally with ref

        The reference elevation is left untouched.
        Modifies the tensor in-place.

        Parameters
        ----------
        elevation : int or 'ref'   reference elevation label (default: 'ref')
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_ref    = self._el_to_col(elevation)
        other_ix = [i for i in range(self.n_elevations) if i != i_ref]

        print(f"  Aligning {len(other_ix)} elevations to '{elevation}'...\n")

        for i_az in range(self.n_angles):
            ref_sig = self.tensor[i_az, i_ref, :].astype(np.float64)

            tdoas = [_gcc_phat(ref_sig, self.tensor[i_az, i_e, :].astype(np.float64))
                     for i_e in other_ix]

            tau = int(np.round(np.mean(tdoas)))

            # shift all elevations by the same tau — ref stays untouched
            tmp = np.zeros((len(other_ix), self.n_samples), dtype=np.float32)
            if tau > 0:
                tmp[:, tau:] = self.tensor[i_az][other_ix, :-tau]
            elif tau < 0:
                tmp[:, :self.n_samples + tau] = self.tensor[i_az][other_ix, -tau:]
            else:
                tmp = self.tensor[i_az][other_ix, :].copy()
            self.tensor[i_az][other_ix] = tmp

            print(f"  {self.angles[i_az]:>4}°  τ = {tau:+d} smp"
                  f"  ({tau / self.sr * 1000:+.2f} ms)"
                  f"  std = {np.std(tdoas):.1f} smp")

        print("\n  Alignment done.")

    def normalize_takes(self, elevation='ref', ref_azimuth=0):
        """
        Normalizes the level of all takes relative to a reference take.

        Computes the global RMS of the specified elevation in each take and
        scales ALL elevations in that take to match the reference.

        Parameters
        ----------
        elevation   : int or 'ref'   elevation used to measure level (default: 'ref')
        ref_azimuth : int            azimuth of the reference take (default: 0)
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_el     = self._el_to_col(elevation)
        i_ref_az = self._az_to_row(ref_azimuth)

        rms_ref = np.sqrt(np.mean(self.tensor[i_ref_az, i_el, :] ** 2))

        print(f"  Reference: elevation '{elevation}' at {ref_azimuth}°"
              f"  RMS = {20*np.log10(rms_ref):.1f} dBFS\n")

        for i_az in range(self.n_angles):
            rms_i  = np.sqrt(np.mean(self.tensor[i_az, i_el, :] ** 2))
            gain   = rms_ref / (rms_i + 1e-12)
            self.tensor[i_az, :, :] *= gain

            diff_db = 20 * np.log10(gain)
            marker  = "  ← ref" if i_az == i_ref_az else ""
            print(f"  {self.angles[i_az]:>4}°  RMS = {20*np.log10(rms_i):.1f} dBFS"
                  f"  gain = {diff_db:+.1f} dB{marker}")

        print("\n  Normalization done.")

    def hpf(self, cutoff_hz):
        """
        Applies a 4th-order Butterworth high-pass filter to every elevation
        of every take. Modifies the tensor in-place.

        Parameters
        ----------
        cutoff_hz : float   cutoff frequency in Hz (e.g. 200)
        """
        from scipy.signal import butter, sosfilt

        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        sos = butter(4, cutoff_hz, btype='high', fs=self.sr, output='sos')

        for i_az in range(self.n_angles):
            for i_el in range(self.n_elevations):
                self.tensor[i_az, i_el, :] = sosfilt(
                    sos, self.tensor[i_az, i_el, :]
                ).astype(np.float32)

        print(f"  HPF applied — {cutoff_hz} Hz, 4th-order Butterworth"
              f"  ({self.n_angles} takes × {self.n_elevations} elevations)")

    # ──────────────────────────────────────────────────────────────────────────
    # Note detection methods
    # ──────────────────────────────────────────────────────────────────────────

    def detect_notes(self, scale, elevation='ref', hop_length=512, tolerance_cents=50):
        """
        Detects the interval (start/end in samples) of each note of a scale
        in every take, using pyin on the specified elevation.

        Parameters
        ----------
        scale           : dict           {note_name: freq_hz}
        elevation       : int or 'ref'   elevation to analyze (default: 'ref')
        hop_length      : int            pyin hop length in samples (default: 512)
        tolerance_cents : float          max deviation in cents to assign a frame

        Returns
        -------
        segmentos : list of dicts  (one per azimuth take)
            segmentos[i_az][note_name] = {'start': int, 'end': int}  in samples
        """
        import librosa

        i_el       = self._el_to_col(elevation)
        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1

        col_w  = 6
        header = f"{'Toma':>6}  " + "  ".join(f"{n:<{col_w}}" for n in note_names)
        print(header)
        print("─" * len(header))

        segmentos = []

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_el, :].astype(np.float32)

            f0, _, _ = librosa.pyin(
                signal, fmin=fmin, fmax=fmax,
                sr=self.sr, hop_length=hop_length, fill_na=np.nan,
            )

            assigned = []
            for freq in f0:
                if np.isnan(freq):
                    assigned.append(None)
                    continue
                cents     = np.abs(1200 * np.log2(freq / note_freqs))
                i_closest = int(np.argmin(cents))
                assigned.append(note_names[i_closest] if cents[i_closest] <= tolerance_cents else None)

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
        cropped from each take. Takes with missing detection are zeroed.

        Parameters
        ----------
        segmentos : list   output of detect_notes()
        note      : str    note name, e.g. 'Fa4'

        Returns
        -------
        MicArray with shape (n_angles, n_elevations, max_note_length)
        """
        lengths = [
            seg[note]['end'] - seg[note]['start']
            for seg in segmentos if note in seg
        ]
        if not lengths:
            raise ValueError(f"Note '{note}' not found in any take.")

        max_len = max(lengths)
        data    = np.zeros((self.n_angles, self.n_elevations, max_len), dtype=np.float32)

        for i_az, seg in enumerate(segmentos):
            if note not in seg:
                print(f"  [WARN] {self.angles[i_az]}°: '{note}' not detected, take zeroed")
                continue
            s = seg[note]['start']
            e = seg[note]['end']
            data[i_az, :, :e - s] = self.tensor[i_az, :, s:e]

        print(f"  extract_note('{note}')  shape: {data.shape}"
              f"  ({max_len / self.sr * 1000:.0f} ms max)")

        return MicArray(data, sr=self.sr, angles=self.angles.copy(),
                        elevations=self.elevations.copy())

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

    # ──────────────────────────────────────────────────────────────────────────
    # Listen
    # ──────────────────────────────────────────────────────────────────────────

    def listen(self, azimuth, elevation):
        """
        Returns an IPython Audio widget to listen to a specific take and elevation.

        Parameters
        ----------
        azimuth   : int              azimuth angle value (e.g. 0, 90, 180)
        elevation : int or 'ref'     elevation label (e.g. 0, 90, 'ref')
        """
        from IPython.display import Audio, display

        i_az   = self._az_to_row(azimuth)
        i_el   = self._el_to_col(elevation)
        signal = self.tensor[i_az, i_el, :].astype(np.float32)

        # Trim trailing zeros (from extract_note padding)
        nonzero = np.nonzero(signal)[0]
        if len(nonzero):
            signal = signal[:nonzero[-1] + 1]

        label = f"ref" if elevation == 'ref' else f"{elevation}°"
        print(f"  elevation {label}  |  {azimuth}°  |  {len(signal)/self.sr:.2f}s")
        display(Audio(signal, rate=self.sr))

    # ──────────────────────────────────────────────────────────────────────────
    # Analysis plots
    # ──────────────────────────────────────────────────────────────────────────

    def plot_rms_takes(self, elevation='ref', floor_db=-60, yrange=None):
        """
        Plots the RMS level (dBFS) of an elevation across all takes as a
        VU-meter style bar chart.

        Parameters
        ----------
        elevation : int or 'ref'       elevation to measure (default: 'ref')
        floor_db  : float              bottom of the y-axis in dBFS (default: -60)
        yrange    : [float, float]     optional y-axis zoom, e.g. [-40, -20]
        """
        i_el = self._el_to_col(elevation)

        rms_db = [
            20 * np.log10(np.sqrt(np.mean(self.tensor[i_az, i_el, :] ** 2)) + 1e-12)
            for i_az in range(self.n_angles)
        ]

        label = "ref" if elevation == 'ref' else f"{elevation}°"
        fig = go.Figure(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=[r - floor_db for r in rms_db],
            base=floor_db,
            marker_color='steelblue',
            text=[f"{r:.1f}" for r in rms_db],
            textposition='outside',
        ))
        fig.update_layout(
            title=f"RMS por toma — elevation {label}",
            xaxis_title="Azimut",
            yaxis=dict(title="dBFS", range=yrange if yrange else [floor_db, 0],
                       gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=400,
        )
        fig.show()

    def plot_tune(self, scale, azimuth, elevation='ref', hop_length=512,
                  confidence_threshold=0.5):
        """
        Plots the tuning deviation (cents) of each note for a given take.

        Parameters
        ----------
        scale                : dict           {note_name: freq_hz}
        azimuth              : int            azimuth take to analyze
        elevation            : int or 'ref'   elevation to use (default: 'ref')
        hop_length           : int            pyin hop length (default: 512)
        confidence_threshold : float          min pyin confidence (default: 0.5)
        """
        import librosa

        i_az = self._az_to_row(azimuth)
        i_el = self._el_to_col(elevation)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1

        signal = self.tensor[i_az, i_el, :].astype(np.float32)

        f0, _, voiced_prob = librosa.pyin(
            signal, fmin=fmin, fmax=fmax,
            sr=self.sr, hop_length=hop_length, fill_na=np.nan,
        )

        cents_per_note = {n: [] for n in note_names}
        for freq, prob in zip(f0, voiced_prob):
            if np.isnan(freq) or prob < confidence_threshold:
                continue
            dists     = np.abs(1200 * np.log2(freq / note_freqs))
            i_closest = int(np.argmin(dists))
            if dists[i_closest] <= 100:
                deviation = 1200 * np.log2(freq / note_freqs[i_closest])
                cents_per_note[note_names[i_closest]].append(deviation)

        means = [np.mean(cents_per_note[n]) if cents_per_note[n] else np.nan
                 for n in note_names]
        stds  = [np.std(cents_per_note[n])  if cents_per_note[n] else 0
                 for n in note_names]

        colors = []
        for mv in means:
            if np.isnan(mv):      colors.append('lightgrey')
            elif abs(mv) <= 25:   colors.append('seagreen')
            elif abs(mv) <= 50:   colors.append('goldenrod')
            else:                 colors.append('crimson')

        label = "ref" if elevation == 'ref' else f"{elevation}°"
        fig = go.Figure()
        fig.add_hrect(y0=-50, y1=50, fillcolor='lightgreen', opacity=0.1, line_width=0)
        fig.add_trace(go.Bar(
            x=note_names, y=means,
            error_y=dict(type='data', array=stds, visible=True),
            marker_color=colors,
            text=[f"{mv:.1f}¢" if not np.isnan(mv) else "—" for mv in means],
            textposition='outside',
        ))
        fig.add_hline(y=0,   line=dict(color='black', width=1))
        fig.add_hline(y=50,  line=dict(color='green', width=1, dash='dash'))
        fig.add_hline(y=-50, line=dict(color='green', width=1, dash='dash'))
        fig.update_layout(
            title=f"Afinación — elevation {label}  |  {azimuth}°",
            xaxis_title="Nota",
            yaxis_title="Desviación (cents)",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey', zeroline=False),
            width=800, height=450,
        )
        fig.show()

    def plot_f0(self, scale, azimuth, elevation='ref', hop_length=512, band_cents=50):
        """
        Plots the pyin f0 tracking for a specific take against the scale notes.

        Parameters
        ----------
        scale      : dict            {note_name: freq_hz}
        azimuth    : int             azimuth take to analyze
        elevation  : int or 'ref'    elevation to use (default: 'ref')
        hop_length : int             pyin hop length in samples (default: 512)
        band_cents : float           half-width of shaded band per note (default: 50)
        """
        import librosa

        i_az = self._az_to_row(azimuth)
        i_el = self._el_to_col(elevation)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        f_ref      = note_freqs[0]
        fmin       = note_freqs[0] * 0.9
        fmax       = note_freqs[-1] * 1.1

        signal = self.tensor[i_az, i_el, :].astype(np.float32)

        f0, voiced, _ = librosa.pyin(
            signal, fmin=fmin, fmax=fmax,
            sr=self.sr, hop_length=hop_length, fill_na=np.nan,
        )

        t          = np.arange(len(f0)) * hop_length / self.sr
        note_cents = {n: 1200 * np.log2(f / f_ref) for n, f in scale.items()}
        f0_cents   = np.where(voiced,
                              1200 * np.log2(np.where(voiced, f0, f_ref) / f_ref),
                              np.nan)

        import plotly.colors as pc
        palette = pc.qualitative.Plotly

        fig = go.Figure()
        for i, (name, c) in enumerate(note_cents.items()):
            color = palette[i % len(palette)]
            fig.add_hrect(y0=c - band_cents, y1=c + band_cents,
                          fillcolor=color, opacity=0.15, line_width=0)
            fig.add_hline(y=c, line=dict(color=color, width=1.5))

        fig.add_trace(go.Scatter(
            x=t, y=f0_cents,
            mode='lines',
            line=dict(color='crimson', width=1.5),
            name='f0 detectada',
        ))

        label = "ref" if elevation == 'ref' else f"{elevation}°"
        fig.update_layout(
            title=f"F0 tracking — elevation {label}  |  {azimuth}°",
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

    def plot(self, azimuth=None, elevation=None, title=None,
             envelope=True, db=False, floor_db=-80):
        """
        Plots time-domain signals from the tensor.

        Dispatch rules:
          azimuth + elevation  → single signal at that position
          azimuth only         → all elevations for that azimuth
          elevation only       → all azimuths for that elevation

        Parameters
        ----------
        azimuth   : int or None           azimuth angle (e.g. 0, 90, 180)
        elevation : int, 'ref', or None   elevation label (e.g. 0, 90, 'ref')
        title     : str or None           plot title (auto-generated if None)
        envelope  : bool                  if True, shows smooth abs envelope (default: False)
        db        : bool                  if True, converts amplitude to dBFS (default: False)
        floor_db  : float                 minimum dBFS value shown when db=True (default: -80)
        """
        if azimuth is None and elevation is None:
            raise ValueError("Provide at least 'azimuth' or 'elevation'.")

        def to_db(ds):
            return np.maximum(20 * np.log10(np.abs(ds) + 1e-12), floor_db)

        fig = go.Figure()

        if azimuth is not None and elevation is not None:
            i_az       = self._az_to_row(azimuth)
            i_el       = self._el_to_col(elevation)
            signal     = self.tensor[i_az, i_el, :]
            ds, factor = self._prepare(signal, envelope)
            if db: ds  = to_db(ds)
            t          = np.arange(len(ds)) * factor / self.sr
            el_label   = "ref" if elevation == 'ref' else f"{elevation}°"
            fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                     line=dict(width=1),
                                     name=f"{el_label} — {azimuth}°"))
            auto_title = f"Elevación {el_label} dado el azimut {azimuth}°"
            height     = 400

        elif azimuth is not None:
            i_az = self._az_to_row(azimuth)
            for el in self.elevations:
                i_el       = self._el_to_col(el)
                signal     = self.tensor[i_az, i_el, :]
                ds, factor = self._prepare(signal, envelope)
                if db: ds  = to_db(ds)
                t          = np.arange(len(ds)) * factor / self.sr
                label      = "ref" if el == 'ref' else f"{el}°"
                fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                         line=dict(width=1), name=label))
            auto_title = f"Elevaciones dado el azimut {azimuth}°"
            height     = 500

        else:
            i_el     = self._el_to_col(elevation)
            el_label = "ref" if elevation == 'ref' else f"{elevation}°"
            for az in self.angles:
                i_az       = self._az_to_row(az)
                signal     = self.tensor[i_az, i_el, :]
                ds, factor = self._prepare(signal, envelope)
                if db: ds  = to_db(ds)
                t          = np.arange(len(ds)) * factor / self.sr
                fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                         line=dict(width=1), name=f"{az}°"))
            auto_title = f"Azimuts dada la elevación {el_label}"
            height     = 500

        axis_style = dict(
            gridcolor='lightgrey',
            showline=True, linecolor='black', linewidth=1,
            mirror=False,
        )
        fig.update_layout(
            title=title if title is not None else auto_title,
            xaxis_title="Time (s)",
            yaxis_title="dBFS" if db else "Amplitude",
            plot_bgcolor='white',
            xaxis=axis_style,
            yaxis=dict(**axis_style, range=[floor_db, 0]) if db else axis_style,
            width=1200, height=height,
        )
        fig.show()


# ── Module-level helpers (not part of the class) ─────────────────────────────

def _gcc_phat(sig1, sig2):
    """
    Estimates the TDOA between sig1 and sig2 using GCC-PHAT.

    Returns the delay in samples: positive means sig1 arrives later than sig2.
    """
    n     = len(sig1) + len(sig2) - 1
    n_fft = 2 ** int(np.ceil(np.log2(n)))

    S1 = np.fft.rfft(sig1, n=n_fft)
    S2 = np.fft.rfft(sig2, n=n_fft)

    G      = S1 * np.conj(S2)
    G_phat = G / (np.abs(G) + 1e-10)
    gcc    = np.fft.irfft(G_phat, n=n_fft)

    tau = int(np.argmax(np.abs(gcc)))
    if tau > n_fft // 2:
        tau -= n_fft

    return tau


def _detect_onset(signal, sr, window_ms=50, threshold_db=-40):
    """
    Detects the onset of a signal using a fixed absolute RMS threshold in dBFS.
    Returns the sample index of the first window that exceeds threshold_db.
    """
    window    = int(window_ms / 1000 * sr)
    threshold = 10 ** (threshold_db / 20)

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
    Converts a filename pattern with placeholders to a named-group regex.
    Format specs (e.g. :03d) are ignored.

    Example
    -------
    'mic_{MIC}_ang_forte_{H}.wav'  →  'mic_(?P<MIC>\\d+)_ang_forte_(?P<H>\\d+)\\.wav'
    """
    result = ''
    last   = 0
    for m in re.finditer(r'\{(\w+)(?::[^}]*)?\}', pattern):
        result += re.escape(pattern[last:m.start()])
        result += f'(?P<{m.group(1)}>\\d+)'
        last = m.end()
    result += re.escape(pattern[last:])
    return re.compile(result, re.IGNORECASE)
