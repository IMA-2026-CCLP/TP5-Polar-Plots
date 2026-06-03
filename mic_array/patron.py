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

        # Calibration factors in dB (K per elevation), None until calibrate() is called
        self.calibration = None
        self._is_spl     = False

        # Leq results, None until compute_leq() is called
        self.leq_freqs  = None
        self.leq_levels = None
        self.leq_bands  = None
        self.leq_global = None

        # Note segments, None until extract_all_notes() is called
        self.notes = None

        # Scale definition, e.g. {'Fa4': 349.23, ...}
        self.scale = None

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
            obj = cls(tensor, sr=sr, angles=angles, elevations=elevations)
            if 'calibration' in data:
                obj.calibration = data['calibration']
            return obj
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
        If to_spl() was applied, the tensor is converted back to linear before saving.

        Parameters
        ----------
        path : str or Path   destination file (e.g. "data/tensores/forte_aligned.npz")
        """
        path = Path(path).with_suffix('.npz')
        path.parent.mkdir(parents=True, exist_ok=True)

        tensor_to_save = self.tensor
        if self._is_spl:
            scale = 20e-6 * 10 ** (self.calibration / 20)   # mismo factor que to_spl()
            tensor_to_save = self.tensor / scale[np.newaxis, :, np.newaxis]
            print("  [info] SPL conversion undone before saving — tensor saved in FS units.")

        kwargs = dict(
            tensor    = tensor_to_save,
            sr        = np.array(self.sr),
            azimuth   = np.array(self.angles),
            elevation = np.array(self.elevations, dtype=object),
        )
        if self.calibration is not None:
            kwargs['calibration'] = self.calibration

        np.savez(path, **kwargs)
        print(f"  Saved: {path}  {tensor_to_save.shape}  ({tensor_to_save.nbytes/1024**2:.1f} MB)")

    # ──────────────────────────────────────────────────────────────────────────
    # Calibration
    # ──────────────────────────────────────────────────────────────────────────

    def calibrate(self, path, array_pattern, ref_pattern=None, spl_cal=94):
        """
        Loads calibration WAV files and computes a K factor (dB) per elevation.

        Each file must contain a 1kHz tone recorded at spl_cal dB SPL.
        K[i_el] = spl_cal - 20*log10(RMS_cal)  →  stored in self.calibration.

        Parameters
        ----------
        path          : str or Path   directory with calibration WAV files
        array_pattern : str           pattern with {MIC} or {V} (same as from_audio)
        ref_pattern   : str or None   pattern for the reference mic (optional)
        spl_cal       : float         SPL level of the calibration tone (default: 94)
        """
        path      = Path(path)
        arr_regex = _pattern_to_regex(array_pattern)
        ref_regex = _pattern_to_regex(ref_pattern) if ref_pattern else None
        v_key     = 'MIC' if '{MIC' in array_pattern else 'V'

        calibration = np.full(self.n_elevations, np.nan)

        for f in sorted(path.glob('*.wav')):
            m = arr_regex.search(f.name)
            if m:
                v  = int(m.group(v_key))
                el = v if v_key == 'V' else (v - 1) * 10
                if el not in self.elevations:
                    continue
                i_el = self._el_to_col(el)
                sig, _ = sf.read(f)
                rms    = np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2))
                calibration[i_el] = spl_cal - 20 * np.log10(rms + 1e-12)
                continue

            if ref_regex:
                m = ref_regex.search(f.name)
                if m and 'ref' in self.elevations:
                    i_el   = self._el_to_col('ref')
                    sig, _ = sf.read(f)
                    rms    = np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2))
                    calibration[i_el] = spl_cal - 20 * np.log10(rms + 1e-12)

        missing = [self.elevations[i] for i in range(self.n_elevations) if np.isnan(calibration[i])]
        if missing:
            print(f"  [WARN] No calibration file found for elevations: {missing}")

        self.calibration = calibration
        print(f"\n  Calibration done — {np.sum(~np.isnan(calibration))} / {self.n_elevations} elevations")
        for i_el, el in enumerate(self.elevations):
            label = 'ref' if el == 'ref' else f'{el}°'
            k     = calibration[i_el]
            print(f"    {label:>5}  K = {k:.2f} dB" if not np.isnan(k) else f"    {label:>5}  K = —")

    def to_spl(self):
        """
        Converts the tensor in-place to physical units (Pa) using self.calibration.

        After this call, RMS of any signal gives dB SPL via:
            20 * log10(RMS / 20e-6)

        Requires calibrate() to have been called first.
        Modifies the tensor in-place and sets self._is_spl = True.
        """
        if self.calibration is None:
            raise RuntimeError("Run calibrate() before to_spl().")
        if self._is_spl:
            print("  [info] Already in SPL units, skipping.")
            return

        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        # scale = p_ref × 10^(K/20)  converts FS → Pa
        # K = spl_cal - 20*log10(RMS_cal), so 10^(K/20) = 10^(spl_cal/20) / RMS_cal
        # and p_ref × 10^(K/20) = p_cal / RMS_cal  ← the correct FS→Pa factor
        P_REF = 20e-6
        scale = (P_REF * 10 ** (self.calibration / 20)).astype(np.float32)
        self.tensor *= scale[np.newaxis, :, np.newaxis]
        self._is_spl = True
        print("  Tensor converted to Pa (SPL units). Use save() safely — it undoes this before writing.")

    # ──────────────────────────────────────────────────────────────────────────
    # Alignment / Processing methods
    # ──────────────────────────────────────────────────────────────────────────

    def align_takes(self, target_onset=1.0, elevation='ref', threshold_dB=-40):
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
        threshold_dB  : float          RMS level in dBFS that defines the onset
                                       (default: -40). Lower → more sensitive.
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_el           = self._el_to_col(elevation)
        target_samples = int(target_onset * self.sr)
        el_label       = 'ref' if elevation == 'ref' else f'{elevation}°'

        print(f"  Target onset : {target_onset:.2f} s  ({target_samples} smp)")
        print(f"  Ref elevation: {el_label}  |  threshold = {threshold_dB} dBFS\n")

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_el, :].astype(np.float64)
            onset  = _detect_onset(signal, self.sr, threshold_dB=threshold_dB)
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

            diff_dB = 20 * np.log10(gain)
            marker  = "  ← ref" if i_az == i_ref_az else ""
            print(f"  {self.angles[i_az]:>4}°  RMS = {20*np.log10(rms_i):.1f} dBFS"
                  f"  gain = {diff_dB:+.1f} dB{marker}")

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

    def detect_notes(self, scale=None, elevation='ref', hop_length=512,
                     tolerance_cents=50, min_purity=0.8):
        """
        Detects the interval (start/end in samples) of each note of a scale
        in every take, using pyin on the specified elevation.

        Segments with purity below min_purity are rejected (treated as not detected),
        so contaminated takes are zeroed during extract_note rather than silently used.

        Parameters
        ----------
        scale           : dict           {note_name: freq_hz} — uses self.scale if None
        elevation       : int or 'ref'   elevation to analyze (default: 'ref')
        hop_length      : int            pyin hop length in samples (default: 512)
        tolerance_cents : float          max deviation in cents to assign a frame (default: 50)
        min_purity      : float          minimum fraction of correctly assigned frames
                                         within a segment to accept it (default: 0.8)
        Returns
        -------
        segmentos : list of dicts  (one per azimuth take)
            segmentos[i_az][note_name] = {'start': int, 'end': int, 'purity': float}
        """
        import librosa

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

        i_el       = self._el_to_col(elevation)
        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1

        col_w  = 8
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

                # Build consecutive groups of target frames
                groups, start, prev = [], frames[0], frames[0]
                for f in frames[1:]:
                    if f > prev + 1:
                        groups.append((start, prev))
                        start = f
                    prev = f
                groups.append((start, prev))

                best      = max(groups, key=lambda g: g[1] - g[0])
                seg_start = best[0]
                seg_end   = best[1] + 1

                # Purity over the full span first→last occurrence of this note
                # so intruding frames between occurrences are counted
                full_start     = frames[0]
                full_end       = frames[-1] + 1
                total_frames   = full_end - full_start
                correct_frames = sum(1 for i in range(full_start, full_end)
                                     if assigned[i] == note)
                purity = correct_frames / total_frames if total_frames > 0 else 0.0

                if purity >= min_purity:
                    segs[note] = {
                        'start' : seg_start * hop_length,
                        'end'   : min(seg_end * hop_length, self.n_samples),
                        'purity': purity,
                    }

            segmentos.append(segs)

        # ── Build styled DataFrame ────────────────────────────────────────────
        import pandas as pd
        from IPython.display import display

        az_labels = [f"{a}°" for a in self.angles]
        dur_data  = {}
        pur_data  = {}
        for note in note_names:
            dur_col = []
            pur_col = []
            for i_az, segs in enumerate(segmentos):
                if note in segs:
                    dur = (segs[note]['end'] - segs[note]['start']) / self.sr
                    pur = segs[note]['purity']
                    dur_col.append(f"{dur:.2f}s")
                    pur_col.append(pur)
                else:
                    dur_col.append("--")
                    pur_col.append(None)
            dur_data[note] = dur_col
            pur_data[note] = pur_col

        df_dur = pd.DataFrame(dur_data, index=az_labels)
        df_pur = pd.DataFrame(pur_data, index=az_labels)

        def _color(val, pur):
            if pur is None:
                return 'background-color: #e0e0e0; color: #888'
            if pur >= 0.9:
                return 'background-color: #c6efce; color: #276221'
            if pur >= min_purity:
                return 'background-color: #ffeb9c; color: #9c5700'
            return 'background-color: #ffc7ce; color: #9c0006'

        def _style(row):
            note = row.name if hasattr(row, 'name') else None
            return [_color(row[n], df_pur.loc[row.name, n])
                    if hasattr(row, 'name') else '' for n in note_names]

        styled = df_dur.style.apply(
            lambda row: [_color(row[n], df_pur.loc[row.name, n]) for n in note_names],
            axis=1
        ).set_caption(
            f"Detección de notas  |  tolerance={tolerance_cents}¢  "
            f"min_purity={min_purity*100:.0f}%  "
            f"(🟢 ≥90%  🟡 ≥{min_purity*100:.0f}%  ⬜ rechazado)"
        )
        display(styled)
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

        obj = MicArray(data, sr=self.sr, angles=self.angles.copy(),
                       elevations=self.elevations.copy())
        obj.calibration = self.calibration.copy() if self.calibration is not None else None
        obj._is_spl     = self._is_spl
        return obj

    def extract_all_notes(self, segmentos, scale=None):
        """
        Extracts all notes in a scale and saves them in self.notes.

        Parameters
        ----------
        segmentos : list         output of detect_notes()
        scale     : dict or None {note_name: freq_hz} — uses self.scale if None
        """
        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")
        self.notes = {note: self.extract_note(segmentos, note) for note in scale}
        print(f"  Notes saved in self.notes: {list(self.notes.keys())}")

    # ──────────────────────────────────────────────────────────────────────────
    # Listen
    # ──────────────────────────────────────────────────────────────────────────

    def compute_leq(self, bands='1/3', p_ref=20e-6, method='iir'):
        """
        Computes Leq per band for every position in the tensor.

        Results are stored as attributes:
            self.leq_freqs   : np.ndarray  center frequencies  (n_bands,)
            self.leq_levels  : np.ndarray  Leq in dB           (n_angles, n_elevations, n_bands)
            self.leq_bands   : str         band resolution used ('1/3' or 'octave')

        Parameters
        ----------
        bands  : str     '1/3' or 'octave' (default: '1/3')
        p_ref  : float   reference pressure (default: 20e-6 Pa for dB SPL)
        method : str     'iir' — IEC 61260 compliant (default)
                         'fft' — rectangular bands, rápido
        """
        from filterbank import FilterBank

        if bands not in ('1/3', 'octave', '1/1'):
            raise ValueError("MicArray.compute_leq only supports '1/3' and 'octave'")

        fb      = FilterBank(sr=self.sr, bands=bands)
        n_bands = len(fb.center_freqs_nominal)
        levels  = np.zeros((self.n_angles, self.n_elevations, n_bands), dtype=np.float32)

        total = self.n_angles * self.n_elevations
        done  = 0
        for i_az in range(self.n_angles):
            for i_el in range(self.n_elevations):
                signal = self.tensor[i_az, i_el, :].astype(np.float64)
                _, lev = fb.leq(signal, p_ref=p_ref, method=method)
                levels[i_az, i_el, :] = lev
                done += 1
                print(f"\r  {done}/{total}  az={self.angles[i_az]}°"
                      f"  el={self.elevations[i_el]}", end='')

        self.leq_freqs  = np.array(fb.center_freqs_nominal, dtype=float)
        self.leq_levels = levels
        self.leq_bands  = bands
        self.leq_global = 10 * np.log10(np.sum(10 ** (levels / 10), axis=-1))
        print(f"\n  compute_leq done — {bands} octava  |  shape {levels.shape}"
              f"  |  method={method}")

    def compute_leq_notes(self, bands='1/3', p_ref=20e-6, method='fft'):
        """
        Computes Leq per band for each note in self.notes.
        Requires extract_all_notes() to have been called first.

        Parameters
        ----------
        bands  : str     '1/3' or 'octave' (default: '1/3')
        p_ref  : float   reference pressure (default: 20e-6 Pa for dB SPL)
        method : str     'fft' — rápido (default) | 'iir' — IEC 61260 compliant
        """
        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")

        for nota, ma_nota in self.notes.items():
            print(f"  {nota} ...", end=' ')
            ma_nota.compute_leq(bands=bands, p_ref=p_ref, method=method)
            print(f"OK")

        print(f"\n  compute_leq_notes done — {len(self.notes)} notas  |  bands={bands}  method={method}")

    def plot_leq_global(self, elevation='ref', yrange=None, title=None):
        """
        Bar chart of global Leq per azimuth for a given elevation.

        Parameters
        ----------
        elevation : int or 'ref'          elevation to plot (default: 'ref')
        yrange    : [float, float] or None  y-axis range, e.g. [60, 100]
        title     : str or None             plot title (auto-generated if None)
        """
        if self.leq_global is None:
            raise RuntimeError("Run compute_leq() first.")

        i_el     = self._el_to_col(elevation)
        el_label = 'ref' if elevation == 'ref' else f'{elevation}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'
        levels   = self.leq_global[:, i_el]
        mean_e   = 10 * np.log10(np.mean(10 ** (levels / 10)))

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=levels,
            marker_color='steelblue',
            text=[f"{v:.1f}" for v in levels],
            textposition='outside',
            name='Leq',
        ))
        fig.add_hline(y=mean_e,
                      line=dict(color='crimson', width=1.5, dash='dash'),
                      annotation_text=f"media {mean_e:.1f} {y_label}",
                      annotation_position="top right")
        fig.update_layout(
            title=title or f"Leq global — elevation {el_label}",
            xaxis_title="Azimut",
            yaxis=dict(title=y_label, range=yrange, gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=450,
        )
        fig.show()

    def report_leq_global(self, elevation='ref'):
        """
        Returns a pandas DataFrame with the global Leq per azimuth for a given
        elevation, plus an energy-averaged summary row.

        Parameters
        ----------
        elevation : int or 'ref'   elevation to report (default: 'ref')
        """
        import pandas as pd
        from IPython.display import display

        if self.leq_global is None:
            raise RuntimeError("Run compute_leq() first.")

        i_el     = self._el_to_col(elevation)
        el_label = 'ref' if elevation == 'ref' else f'{elevation}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'
        levels   = self.leq_global[:, i_el]
        mean_e   = 10 * np.log10(np.mean(10 ** (levels / 10)))

        cols = {f"{az}°": round(float(lev), 1) for az, lev in zip(self.angles, levels)}
        cols['Media'] = round(float(mean_e), 1)

        df = pd.DataFrame(cols, index=[f'Leq [{y_label}]  el: {el_label}'])
        display(df)
        return df

    def plot_leq_by_note(self, elevation='ref', yrange=None, title=None):
        """
        For each note in self.notes, plots mean ± std of Leq global across azimuths.

        Interpretation depends on elevation:
          elevation='ref'  → level consistency of the singer between takes
          elevation=N°     → directivity of the voice for that elevation angle

        Requires extract_all_notes() and compute_leq_notes() first.

        Parameters
        ----------
        elevation : int or 'ref'            elevation to analyze (default: 'ref')
        yrange    : [float, float] or None  y-axis range, e.g. [70, 100]
        title     : str or None             plot title (auto-generated if None)
        """
        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")
        if next(iter(self.notes.values())).leq_global is None:
            raise RuntimeError("Run compute_leq_notes() first.")

        i_el     = self._el_to_col(elevation)
        el_label = 'ref' if elevation == 'ref' else f'{elevation}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'

        note_names = list(self.notes.keys())
        means, stds = [], []
        for nota, ma_nota in self.notes.items():
            levels = ma_nota.leq_global[:, i_el]
            means.append(10 * np.log10(np.mean(10 ** (levels / 10))))
            stds.append(levels.std())

        means = np.array(means)
        stds  = np.array(stds)

        fig = go.Figure(go.Bar(
            x=note_names, y=means,
            error_y=dict(type='data', array=stds, visible=True, color='dimgray'),
            marker_color='steelblue',
            text=[f"{v:.1f}" for v in means],
            textposition='outside',
        ))
        fig.update_layout(
            title=title or f"Leq global por nota — elevation {el_label}",
            xaxis_title="Nota",
            yaxis=dict(title=y_label, range=yrange, gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=450,
        )
        fig.show()

    def report_leq_by_note(self, elevation='ref'):
        """
        Returns a pandas DataFrame with mean, std, min and max Leq across
        azimuths for each note in self.notes.

        Requires extract_all_notes() and compute_leq_notes() first.

        Parameters
        ----------
        elevation : int or 'ref'   elevation to analyze (default: 'ref')
        """
        import pandas as pd
        from IPython.display import display

        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")
        if next(iter(self.notes.values())).leq_global is None:
            raise RuntimeError("Run compute_leq_notes() first.")

        i_el     = self._el_to_col(elevation)
        el_label = 'ref' if elevation == 'ref' else f'{elevation}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'

        rows = []
        for nota, ma_nota in self.notes.items():
            levels = ma_nota.leq_global[:, i_el]
            rows.append({
                'Nota'               : nota,
                f'Media [{y_label}]' : round(float(10 * np.log10(np.mean(10 ** (levels / 10)))), 1),
                'Std'                : round(float(levels.std()), 1),
                'Mín'                : round(float(levels.min()), 1),
                'Máx'                : round(float(levels.max()), 1),
            })

        df = pd.DataFrame(rows).set_index('Nota')
        df.index.name = f'Nota  —  el: {el_label}'
        display(df)
        return df

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

    def plot_rms_takes(self, elevation='ref', floor_dB=-60, yrange=None):
        """
        Plots the RMS level (dBFS) of an elevation across all takes as a
        VU-meter style bar chart.

        Parameters
        ----------
        elevation : int or 'ref'       elevation to measure (default: 'ref')
        floor_dB  : float              bottom of the y-axis in dBFS (default: -60)
        yrange    : [float, float]     optional y-axis zoom, e.g. [-40, -20]
        """
        i_el = self._el_to_col(elevation)

        rms_dB = [
            20 * np.log10(np.sqrt(np.mean(self.tensor[i_az, i_el, :] ** 2)) + 1e-12)
            for i_az in range(self.n_angles)
        ]

        label = "ref" if elevation == 'ref' else f"{elevation}°"
        fig = go.Figure(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=[r - floor_dB for r in rms_dB],
            base=floor_dB,
            marker_color='steelblue',
            text=[f"{r:.1f}" for r in rms_dB],
            textposition='outside',
        ))
        fig.update_layout(
            title=f"RMS por toma — elevation {label}",
            xaxis_title="Azimut",
            yaxis=dict(title="dBFS", range=yrange if yrange else [floor_dB, 0],
                       gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=400,
        )
        fig.show()

    def plot_tune(self, azimuth, scale=None, elevation='ref', hop_length=512,
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

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

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

    def plot_f0(self, azimuth, scale=None, elevation='ref', hop_length=512, band_cents=50):
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

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

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
             envelope=True, dB=False, floor_dB=-80, yrange=None):
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
        envelope  : bool                  if True, shows smooth abs envelope (default: True)
        dB        : bool                  if True, converts amplitude to dB (default: False)
        floor_dB  : float                 noise floor clipping when dB=True (default: -80)
        yrange    : [float, float] or None  y-axis range, e.g. [40, 100]. Auto if None.
        """
        if azimuth is None and elevation is None:
            raise ValueError("Provide at least 'azimuth' or 'elevation'.")

        P_REF = 20e-6 if self._is_spl else 1.0
        def to_dB(ds):
            return np.maximum(20 * np.log10(np.abs(ds) / P_REF + 1e-12), floor_dB)

        fig = go.Figure()

        if azimuth is not None and elevation is not None:
            i_az       = self._az_to_row(azimuth)
            i_el       = self._el_to_col(elevation)
            signal     = self.tensor[i_az, i_el, :]
            ds, factor = self._prepare(signal, envelope)
            if dB: ds  = to_dB(ds)
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
                if dB: ds  = to_dB(ds)
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
                if dB: ds  = to_dB(ds)
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

        if dB:
            if yrange is not None:
                y_axis = dict(**axis_style, range=yrange)
            else:
                all_y = [t.y for t in fig.data if t.y is not None]
                y_min = min(np.nanmin(y) for y in all_y)
                y_max = max(np.nanmax(y) for y in all_y)
                margin = (y_max - y_min) * 0.05
                y_axis = dict(**axis_style, range=[y_min - margin, y_max + margin])
            y_label = "dB SPL" if self._is_spl else "dBFS"
        else:
            y_axis  = dict(**axis_style, range=yrange) if yrange else axis_style
            y_label = "Amplitude"

        fig.update_layout(
            title=title if title is not None else auto_title,
            xaxis_title="Time (s)",
            yaxis_title=y_label,
            plot_bgcolor='white',
            xaxis=axis_style,
            yaxis=y_axis,
            width=1200, height=height,
        )
        fig.show()

    def plot_leq(self, azimuth=None, elevation=None, title=None, vrange=None,
                 colorscale='Viridis', frange=None):
        """
        Plots Leq per band. Requires compute_leq() to have been called first.

        Dispatch rules:
          azimuth + elevation  → bar chart — single spectrum at that position
          azimuth only         → heatmap   — elevaciones × bandas
          elevation only       → heatmap   — azimuts × bandas

        Parameters
        ----------
        azimuth   : int or None           azimuth angle
        elevation : int, 'ref', or None   elevation label
        title       : str or None           plot title (auto-generated if None)
        vrange      : [float, float] or None  dB range. Auto if None.
                                              For bar: y-axis. For heatmap: colorscale.
        colorscale  : str   colorscale para heatmap (default: 'Viridis')
                            Opciones: 'Viridis', 'Turbo', 'Jet', 'Hot', 'RdYlGn'
        frange      : (float, float) or None  frequency range in Hz, e.g. (200, 8000)
        """
        if self.leq_levels is None:
            raise RuntimeError("Run compute_leq() first.")
        if azimuth is None and elevation is None:
            raise ValueError("Provide at least 'azimuth' or 'elevation'.")

        def _fmt_freq(f):
            if f >= 1000:
                v = f / 1000
                return f"{v:.0f}k" if v == int(v) else f"{v:.3g}k"
            return f"{f:.0f}" if f == int(f) else f"{f:.4g}"

        if frange is not None:
            band_mask = (self.leq_freqs >= frange[0]) & (self.leq_freqs <= frange[1])
        else:
            band_mask = np.ones(len(self.leq_freqs), dtype=bool)

        freqs_vis  = self.leq_freqs[band_mask]
        band_labels = [_fmt_freq(f) for f in freqs_vis]
        y_label     = "dB SPL" if self._is_spl else "dBFS"
        axis_style  = dict(gridcolor='lightgrey',
                           showline=True, linecolor='black', linewidth=1, mirror=False)

        if azimuth is not None and elevation is not None:
            # ── Bar chart — single position ───────────────────────────────────
            i_az     = self._az_to_row(azimuth)
            i_el     = self._el_to_col(elevation)
            levels   = self.leq_levels[i_az, i_el, band_mask]
            el_label = 'ref' if elevation == 'ref' else f'{elevation}°'

            fig = go.Figure(go.Bar(
                x=band_labels, y=levels,
                marker_color='steelblue',
                text=[f"{v:.1f}" for v in levels],
                textposition='outside',
            ))
            auto_title = f"Leq — az {azimuth}°  el {el_label}"
            y_axis = dict(**axis_style, range=vrange) if vrange else axis_style
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title=y_label,
                plot_bgcolor='white', xaxis=axis_style, yaxis=y_axis,
                width=1200, height=500,
            )

        elif azimuth is not None:
            # ── Heatmap — elevaciones × bandas ────────────────────────────────
            i_az     = self._az_to_row(azimuth)
            z        = self.leq_levels[i_az, :, :][:, band_mask]
            y_labels = ['ref' if e == 'ref' else f'{e}°' for e in self.elevations]

            fig = go.Figure(go.Heatmap(
                x=band_labels, y=y_labels, z=z,
                colorscale=colorscale,
                zmin=vrange[0] if vrange else None,
                zmax=vrange[1] if vrange else None,
                colorbar=dict(title=y_label),
            ))
            auto_title = f"Leq por elevación — azimut {azimuth}°"
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title="Elevación",
                width=1200, height=550,
            )

        else:
            # ── Heatmap — azimuts × bandas ────────────────────────────────────
            i_el     = self._el_to_col(elevation)
            z        = self.leq_levels[:, i_el, :][:, band_mask]
            y_labels = [f'{a}°' for a in self.angles]
            el_label = 'ref' if elevation == 'ref' else f'{elevation}°'

            fig = go.Figure(go.Heatmap(
                x=band_labels, y=y_labels, z=z,
                colorscale=colorscale,
                zmin=vrange[0] if vrange else None,
                zmax=vrange[1] if vrange else None,
                colorbar=dict(title=y_label),
            ))
            auto_title = f"Leq por azimut — elevación {el_label}"
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title="Azimut",
                width=1200, height=550,
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


def _detect_onset(signal, sr, window_ms=50, threshold_dB=-40):
    """
    Detects the onset of a signal using a fixed absolute RMS threshold in dBFS.
    Returns the sample index of the first window that exceeds threshold_dB.
    """
    window    = int(window_ms / 1000 * sr)
    threshold = 10 ** (threshold_dB / 20)

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
