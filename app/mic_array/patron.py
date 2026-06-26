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
    tensor     : np.ndarray  shape (n_angles, n_thetas, n_samples)
    sr         : int         sample rate in Hz
    angles     : list        azimuth angles in degrees  [0, 10, ..., 180]
    thetas : list        theta labels — 'ref' or degrees [0, 10, ..., 180]
    """

    def __init__(self, tensor, sr=44100, angles=None, thetas=None):
        self.tensor = tensor   # (n_angles, n_thetas, n_samples)
        self.sr     = sr

        self.n_angles, self.n_thetas, self.n_samples = tensor.shape

        # Azimuth values: [0, 10, ..., 180] by default
        self.angles = angles if angles is not None \
                      else list(range(0, self.n_angles * 10, 10))

        # Theta labels: ['ref', 0, 10, ..., 180] by default
        self.thetas = thetas if thetas is not None \
                          else ['ref'] + list(range(0, (self.n_thetas - 1) * 10, 10))

        # Downsampling factor for plots (1 = no downsampling)
        self.downsampling_graph = 10

        # Smoothing window for envelope in ms (0 = no smoothing)
        self.smoothing_ms = 20

        # Calibration factors in dB (K per theta), None until calibrate() is called
        self.calibration     = None
        self._is_spl         = False
        self._is_compensated = False
        self._is_normalized  = False

        # Leq results, None until compute_leq() is called
        self.leq_freqs  = None
        self.leq_levels = None
        self.leq_bands  = None
        self.leq_global = None

        # SPL results (RMS over active frames), None until compute_spl() is called
        self.spl_freqs  = None
        self.spl_levels = None
        self.spl_global = None

        # Directivity results (relative to ref mic per take), None until compute_directivity()
        self.dir_freqs  = None
        self.dir_levels = None
        self.dir_global = None

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

        .npz files also restore sr, angles and thetas saved by save().
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
        if path.suffix in ('.npz', '.cclp'):
            data       = np.load(path, allow_pickle=True)
            tensor     = data['tensor']
            sr         = int(data['sr'])
            angles     = data['azimuth'].tolist()
            # backward compat: archivos viejos guardaban la clave como 'elevation'
            thetas = (data['theta'].tolist() if 'theta' in data
                      else data['elevation'].tolist())
            obj = cls(tensor, sr=sr, angles=angles, thetas=thetas)
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
          {MIC} → mic number (1–19), converted to theta angle: (mic-1)*10
          {V}   → theta angle in degrees (0, 10 .. 180), used directly

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

        # ── Step 1: discover azimuths, thetas and sr ─────────────────────
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
        # Convert v_values to theta angles
        th_angles   = sorted(v_values) if v_is_angle \
                      else sorted((v - 1) * 10 for v in v_values)
        thetas  = (['ref'] if ref_regex else []) + th_angles

        print(f"  Azimuths   : {azimuths}")
        print(f"  Thetas : {thetas}")
        print(f"  Sample rate: {sr} Hz")

        # ── Step 2: find max length ───────────────────────────────────────────
        max_len = 0
        for f in path.glob("*.wav"):
            if arr_regex.search(f.name) or (ref_regex and ref_regex.search(f.name)):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        # ── Step 3: build tensor (zero-padded) ────────────────────────────────
        data = np.zeros((len(azimuths), len(thetas), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = arr_regex.search(f.name)
            if m:
                i_az = azimuths.index(int(m.group('H')))
                v    = int(m.group(v_key))
                el   = v if v_is_angle else (v - 1) * 10
                i_th = thetas.index(el)
                sig, _ = sf.read(f)
                data[i_az, i_th, :len(sig)] = sig
                continue
            if ref_regex:
                m = ref_regex.search(f.name)
                if m:
                    i_az = azimuths.index(int(m.group('H')))
                    i_th = thetas.index('ref')
                    sig, _ = sf.read(f)
                    data[i_az, i_th, :len(sig)] = sig

        for az in azimuths:
            print(f"    {az:>4}° → OK")

        print(f"\n  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, thetas=thetas)

    @classmethod
    def from_export(cls, path, pattern='mic_{H}_{V}.wav'):
        """
        Load a MicArray from a flat folder of WAV files exported by export_wavs().

        {H} = azimuth angle, {V} = theta angle in degrees.

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
        thetas = sorted(el_set)   # V is already theta angle

        print(f"  Azimuths   : {azimuths}")
        print(f"  Thetas : {thetas}")
        print(f"  Sample rate: {sr} Hz")

        max_len = 0
        for f in path.glob("*.wav"):
            if regex.search(f.name):
                sig, _ = sf.read(f)
                max_len = max(max_len, len(sig))

        print(f"  Max length : {max_len} samples  ({max_len / sr:.2f} s)")

        data = np.zeros((len(azimuths), len(thetas), max_len), dtype=np.float32)

        print(f"\n  Building tensor {data.shape} ...")
        for f in sorted(path.glob("*.wav")):
            m = regex.search(f.name)
            if not m:
                continue
            i_az = azimuths.index(int(m.group('H')))
            i_th = thetas.index(int(m.group('V')))
            sig, _ = sf.read(f)
            data[i_az, i_th, :len(sig)] = sig

        print(f"  Done. Shape: {data.shape}  ({data.nbytes/1024/1024:.1f} MB)")

        return cls(data, sr, angles=azimuths, thetas=thetas)


    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _az_to_row(self, azimuth):
        """Maps an azimuth angle value to its row index in the tensor."""
        if azimuth not in self.angles:
            raise ValueError(f"Azimuth {azimuth}° not found. Available: {self.angles}")
        return self.angles.index(azimuth)

    def _th_to_col(self, theta):
        """Maps an theta label to its column index in the tensor."""
        if theta not in self.thetas:
            raise ValueError(f"Theta '{theta}' not found. Available: {self.thetas}")
        return self.thetas.index(theta)

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
            thetas = self.thetas.copy(),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Export / Save
    # ──────────────────────────────────────────────────────────────────────────

    def export_wavs(self, path, nota=''):
        """
        Exports all thetas and takes as individual WAV files.

        File naming: mic_{azimuth}_{theta}_{nota}.wav
        theta 'ref' is skipped.

        Parameters
        ----------
        path : str or Path   output directory
        nota : str           note label for the filename (default: '')
        """
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)

        count = 0
        for i_az, azimuth in enumerate(self.angles):
            for i_th, el in enumerate(self.thetas):
                if el == 'ref':
                    continue
                filename = f"mic_{azimuth}_{el}_{nota}.wav"
                signal   = self.tensor[i_az, i_th, :].astype(np.float32)
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
        path = Path(path)
        if path.suffix not in ('.npz', '.cclp'):
            path = path.with_suffix('.npz')
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
            theta = np.array(self.thetas, dtype=object),
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
        Loads calibration WAV files and computes a K factor (dB) per theta.

        Each file must contain a 1kHz tone recorded at spl_cal dB SPL.
        K[i_th] = spl_cal - 20*log10(RMS_cal)  →  stored in self.calibration.

        Parameters
        ----------
        path          : str or Path   directory with calibration WAV files
        array_pattern : str           pattern with {MIC} or {V} (same as from_audio)
        ref_pattern   : str or None   pattern for the reference mic (optional)
        spl_cal       : float         SPL level of the calibration tone (default: 94)
        """
        if self.calibration is not None:
            print("  [WARN] Already calibrated. Run calibrate() only once.")
            return

        path      = Path(path)
        arr_regex = _pattern_to_regex(array_pattern)
        ref_regex = _pattern_to_regex(ref_pattern) if ref_pattern else None
        v_key     = 'MIC' if '{MIC' in array_pattern else 'V'

        calibration = np.full(self.n_thetas, np.nan)

        for f in sorted(path.glob('*.wav')):
            m = arr_regex.search(f.name)
            if m:
                v  = int(m.group(v_key))
                el = v if v_key == 'V' else (v - 1) * 10
                if el not in self.thetas:
                    continue
                i_th = self._th_to_col(el)
                sig, _ = sf.read(f)
                rms    = np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2))
                calibration[i_th] = spl_cal - 20 * np.log10(rms + 1e-12)
                continue

            if ref_regex:
                m = ref_regex.search(f.name)
                if m and 'ref' in self.thetas:
                    i_th   = self._th_to_col('ref')
                    sig, _ = sf.read(f)
                    rms    = np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2))
                    calibration[i_th] = spl_cal - 20 * np.log10(rms + 1e-12)

        missing = [self.thetas[i] for i in range(self.n_thetas) if np.isnan(calibration[i])]
        if missing:
            print(f"  [WARN] No calibration file found for thetas: {missing}")

        self.calibration = calibration
        print(f"\n  Calibration done — {np.sum(~np.isnan(calibration))} / {self.n_thetas} thetas")
        for i_th, el in enumerate(self.thetas):
            label = 'ref' if el == 'ref' else f'{el}°'
            k     = calibration[i_th]
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
        self._is_spl         = True
        self._is_compensated = False
        self._is_normalized  = False
        print("  Tensor converted to Pa (SPL units). Use save() safely — it undoes this before writing.")

    # ──────────────────────────────────────────────────────────────────────────
    # Alignment / Processing methods
    # ──────────────────────────────────────────────────────────────────────────

    def align_takes(self, target_onset=1.0, theta='ref', threshold_dB=-40, window_ms=50):
        """
        Aligns all azimuth takes so their onset lands at target_onset seconds.

        For each take, detects the onset of the specified theta and shifts
        ALL thetas of that take by the same amount, so all takes share
        a common absolute time position.

        Run this BEFORE align_ref. Modifies the tensor in-place.

        Parameters
        ----------
        target_onset  : float          desired onset time in seconds (default: 1.0)
        theta         : int or 'ref'   theta used to detect onset (default: 'ref')
        threshold_dB  : float          RMS level in dBFS that defines the onset
                                       (default: -40). Lower → more sensitive.
        window_ms     : float          sliding window size in ms for onset detection
                                       (default: 50). Uses 50% overlap.
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_th           = self._th_to_col(theta)
        target_samples = int(target_onset * self.sr)
        th_label       = 'ref' if theta == 'ref' else f'{theta}°'

        print(f"  Target onset : {target_onset:.2f} s  ({target_samples} smp)")
        print(f"  Ref theta: {th_label}  |  threshold = {threshold_dB} dBFS"
              f"  |  window = {window_ms:.0f} ms\n")

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_th, :].astype(np.float64)
            onset  = _detect_onset(signal, self.sr, window_ms=window_ms, threshold_dB=threshold_dB)
            shift  = target_samples - onset  # >0 → retrasa  |  <0 → adelanta

            if shift != 0:
                tmp = np.zeros((self.n_thetas, self.n_samples), dtype=np.float32)
                if shift > 0:
                    tmp[:, shift:] = self.tensor[i_az, :, :self.n_samples - shift]
                else:
                    tmp[:, :self.n_samples + shift] = self.tensor[i_az, :, -shift:]
                self.tensor[i_az] = tmp

            print(f"  {self.angles[i_az]:>4}°  onset = {onset:>6} smp"
                  f"  ({onset / self.sr * 1000:.0f} ms)"
                  f"  shift = {shift:+d} smp  ({shift / self.sr * 1000:+.0f} ms)")

        print("\n  Take alignment done.")

    def align_to_ref(self, theta='ref', energy_threshold_dB=None):
        """
        Aligns each theta to the reference using GCC-PHAT.

        For each azimuth take and each non-ref theta:
          1. Computes GCC-PHAT(ref, el_i) → TDOA τᵢ
          2. Shifts el_i by τᵢ so it aligns temporally with ref

        The reference theta is left untouched.
        Modifies the tensor in-place.

        Parameters
        ----------
        theta                : int or 'ref'   reference theta label (default: 'ref')
        energy_threshold_dB  : float or None  if set, only samples where the ref signal
                                              exceeds this RMS level (dBFS) are used for
                                              GCC-PHAT. Silences the noise-only regions.
        """
        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_ref    = self._th_to_col(theta)
        other_ix = [i for i in range(self.n_thetas) if i != i_ref]

        thr_str = f"{energy_threshold_dB} dBFS" if energy_threshold_dB is not None else "desactivado"
        print(f"  Aligning {len(other_ix)} thetas to '{theta}'  |  umbral energía GCC: {thr_str}\n")

        for i_az in range(self.n_angles):
            ref_sig = self.tensor[i_az, i_ref, :].astype(np.float64)

            tdoas = [_gcc_phat(ref_sig, self.tensor[i_az, i_e, :].astype(np.float64),
                               energy_threshold_dB=energy_threshold_dB)
                     for i_e in other_ix]

            tau = int(np.round(np.mean(tdoas)))

            # shift all thetas by the same tau — ref stays untouched
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

    def level_compensation(self, theta='ref', ref_azimuth=0):
        """
        Equalizes the level of all azimuth takes on the tensor in-place.

        Computes the RMS of the specified theta in each take and applies a gain
        to ALL thetas of that take so every take matches the reference level.
        Compensates for the singer singing louder or softer on each rotation.

        Must be called after to_spl() and before compute_leq() / compute_spl().
        Resets any previously computed leq/spl results.

        Parameters
        ----------
        theta       : int or 'ref'   theta used to measure level (default: 'ref')
        ref_azimuth : int            azimuth take used as the reference (default: 0)
        """
        if not self._is_spl:
            raise RuntimeError("Run calibrate() + to_spl() first.")

        if not self.tensor.flags['WRITEABLE']:
            self.tensor = np.array(self.tensor, dtype=np.float32)

        i_th     = self._th_to_col(theta)
        i_ref_az = self._az_to_row(ref_azimuth)
        rms_ref  = np.sqrt(np.mean(self.tensor[i_ref_az, i_th, :] ** 2))
        ref_spl  = 20 * np.log10(rms_ref / 20e-6)

        print(f"  Reference: theta '{theta}' at {ref_azimuth}°"
              f"  SPL = {ref_spl:.1f} dB SPL\n")

        for i_az in range(self.n_angles):
            rms_i   = np.sqrt(np.mean(self.tensor[i_az, i_th, :] ** 2))
            gain    = rms_ref / (rms_i + 1e-12)
            self.tensor[i_az, :, :] *= gain
            diff_dB = 20 * np.log10(gain)
            marker  = "  ← ref" if i_az == i_ref_az else ""
            print(f"  {self.angles[i_az]:>4}°  {20*np.log10(rms_i/20e-6):.1f} → "
                  f"{20*np.log10(rms_i*gain/20e-6):.1f} dB SPL"
                  f"  Δ = {diff_dB:+.1f} dB{marker}")

        self._is_compensated = True
        self._is_normalized  = False
        self.leq_freqs  = self.leq_levels = self.leq_bands = self.leq_global = None
        self.spl_freqs  = self.spl_levels = self.spl_global = None
        print("\n  level_compensation done.")

    def hpf(self, cutoff_hz):
        """
        Applies a 4th-order Butterworth high-pass filter to every theta
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
            for i_th in range(self.n_thetas):
                self.tensor[i_az, i_th, :] = sosfilt(
                    sos, self.tensor[i_az, i_th, :]
                ).astype(np.float32)

        print(f"  HPF applied — {cutoff_hz} Hz, 4th-order Butterworth"
              f"  ({self.n_angles} takes × {self.n_thetas} thetas)")

    # ──────────────────────────────────────────────────────────────────────────
    # Note detection methods
    # ──────────────────────────────────────────────────────────────────────────

    def detect_notes(self, scale=None, theta='ref', hop_length=512,
                     tolerance_cents=50, min_purity=0.8, confidence=None,
                     start_s=0.0, gradient_thresh=25.0):
        """
        Detects the interval (start/end in samples) of each note of a scale
        in every take, using pyin on the specified theta.

        Combines pyin F0 tracking with gradient analysis: frames where the F0
        is moving faster than gradient_thresh cents/frame are classified as
        "in transition" and excluded when determining segment boundaries.
        This trims portamento/glide regions from note edges and anchors start/end
        to the stable (settled) portion of each note.

        Segments with purity below min_purity are rejected (treated as not detected),
        so contaminated takes are zeroed during extract_note rather than silently used.

        Parameters
        ----------
        scale            : dict           {note_name: freq_hz} — uses self.scale if None
        theta        : int or 'ref'   theta to analyze (default: 'ref')
        hop_length       : int            pyin hop length in samples (default: 512)
        tolerance_cents  : float          max deviation in cents to assign a frame (default: 50)
        min_purity       : float          minimum fraction of correctly assigned frames
                                          within the stable segment (default: 0.8)
        confidence       : float or None  alias for min_purity — overrides it when provided
        start_s          : float          skip this many seconds at the start of each take (default: 0.0)
        gradient_thresh  : float          F0 rate-of-change threshold in cents/frame above which
                                          a frame is considered "in transition" and excluded from
                                          segment boundaries (default: 25.0).
                                          Lower → more aggressive trimming of transitions.
                                          Raise if valid note frames are being excluded.
        Returns
        -------
        segmentos : list of dicts  (one per azimuth take)
            segmentos[i_az][note_name] = {'start': int, 'end': int, 'purity': float}
        """
        import librosa

        if confidence is not None:
            min_purity = confidence

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

        i_th       = self._th_to_col(theta)
        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1
        start_sample = int(start_s * self.sr)

        col_w  = 8
        header = f"{'Toma':>6}  " + "  ".join(f"{n:<{col_w}}" for n in note_names)
        print(header)
        print("─" * len(header))

        segmentos = []

        for i_az in range(self.n_angles):
            signal = self.tensor[i_az, i_th, start_sample:].astype(np.float32)

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

            # ── Gradient-based transition detection ──────────────────────────
            # Compute F0 gradient in cents/frame over a fully interpolated curve
            # (NaN frames are bridged by linear interpolation so np.gradient
            # doesn't spike at voiced/unvoiced boundaries).
            voiced_ix = np.where(~np.isnan(f0))[0]
            if len(voiced_ix) > 1:
                cents_voiced = 1200.0 * np.log2(f0[voiced_ix] / note_freqs[0])
                f0_interp    = np.interp(np.arange(len(f0)), voiced_ix, cents_voiced)
                grad         = np.abs(np.gradient(f0_interp))   # cents / frame
            else:
                grad = np.zeros(len(f0))

            # Frames where F0 is moving faster than the threshold are "in transition":
            # portamento, glide between notes, attack onset.
            in_transition = grad > gradient_thresh

            segs = {}
            for note in note_names:
                all_frames = [i for i, a in enumerate(assigned) if a == note]
                if not all_frames:
                    continue

                # Stable frames: assigned to this note AND not mid-transition.
                # Fall back to all assigned frames if too few stable ones.
                stable = [i for i in all_frames if not in_transition[i]]
                work   = stable if len(stable) >= 3 else all_frames

                # Build consecutive groups from the working frame set.
                groups, s, p = [], work[0], work[0]
                for fi in work[1:]:
                    if fi > p + 1:
                        groups.append((s, p))
                        s = fi
                    p = fi
                groups.append((s, p))

                best      = max(groups, key=lambda g: g[1] - g[0])
                seg_start = best[0]
                seg_end   = best[1] + 1

                # Purity: fraction of frames inside the stable segment that are
                # correctly assigned to this note (based on original assignment,
                # not filtered by gradient, to be honest about segment quality).
                total_frames   = seg_end - seg_start
                correct_frames = sum(1 for i in range(seg_start, seg_end)
                                     if assigned[i] == note)
                purity = correct_frames / total_frames if total_frames > 0 else 0.0

                if purity >= min_purity:
                    segs[note] = {
                        'start' : seg_start * hop_length + start_sample,
                        'end'   : min(seg_end * hop_length + start_sample, self.n_samples),
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

    def edit_segment(self, segments, azimuth, note, start_s, end_s):
        """
        Manually set the boundaries of a note segment for one azimuth take.

        Use this to correct or add a detection after detect_notes().
        Times are in seconds, absolute (same reference as the tensor — i.e. from
        the start of the file, NOT relative to the start_s used in detect_notes).
        Purity is set to 1.0 for manually defined segments.

        Call plot_f0(azimuth=az, segments=segments) before and after to verify.

        Parameters
        ----------
        segments : list   output of detect_notes() — modified in-place
        azimuth  : int    azimuth take to edit (e.g. 40)
        note     : str    note name (e.g. 'La4')
        start_s  : float  new segment start in seconds
        end_s    : float  new segment end in seconds

        Example
        -------
        ma.edit_segment(segments, azimuth=40, note='La4', start_s=1.45, end_s=2.10)
        """
        i_az  = self._az_to_row(azimuth)
        start = int(start_s * self.sr)
        end   = min(int(end_s * self.sr), self.n_samples)

        if start >= end:
            raise ValueError(
                f"start_s ({start_s:.3f}s) must be less than end_s ({end_s:.3f}s)"
            )

        action = "editado" if note in segments[i_az] else "agregado"
        segments[i_az][note] = {'start': start, 'end': end, 'purity': 1.0}

        dur = (end - start) / self.sr
        print(f"  [{action}]  az={azimuth}°  {note}  →  "
              f"{start_s:.3f}s – {end_s:.3f}s  ({dur*1000:.0f} ms)")

    def remove_segment(self, segments, azimuth, note):
        """
        Remove a detected segment for a note in one azimuth take.

        The take will be zeroed in extract_note() as if it was never detected.
        Useful for false positives: a segment that pyin assigned incorrectly.

        Parameters
        ----------
        segments : list   output of detect_notes() — modified in-place
        azimuth  : int    azimuth take (e.g. 40)
        note     : str    note name (e.g. 'La4')

        Example
        -------
        ma.remove_segment(segments, azimuth=40, note='La4')
        """
        i_az = self._az_to_row(azimuth)
        if note not in segments[i_az]:
            print(f"  [warn]  az={azimuth}°  '{note}' no estaba en segments — nada que eliminar")
            return
        del segments[i_az][note]
        print(f"  [eliminado]  az={azimuth}°  '{note}' removido — la toma quedará en cero")

    def show_segments(self, segments, scale=None):
        """
        Re-displays the detection table from a (possibly edited) segments list.

        Useful to review the current state of segments after manual edits via
        edit_segment() or remove_segment().

        Parameters
        ----------
        segments : list   output of detect_notes(), optionally modified
        scale    : dict or None  {note_name: freq_hz} — uses self.scale if None
        """
        import pandas as pd
        from IPython.display import display

        scale      = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

        note_names = list(scale.keys())
        az_labels  = [f"{a}°" for a in self.angles]
        dur_data   = {}
        pur_data   = {}

        for note in note_names:
            dur_col, pur_col = [], []
            for segs in segments:
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
            if pur >= 1.0:   # manual edit
                return 'background-color: #d0e8ff; color: #003580'
            if pur >= 0.9:
                return 'background-color: #c6efce; color: #276221'
            if pur >= 0.0:
                return 'background-color: #ffeb9c; color: #9c5700'
            return 'background-color: #ffc7ce; color: #9c0006'

        styled = df_dur.style.apply(
            lambda row: [_color(row[n], df_pur.loc[row.name, n]) for n in note_names],
            axis=1
        ).set_caption(
            "Segmentos actuales  |  🔵 manual  🟢 purity ≥90%  🟡 purity <90%  ⬜ no detectado"
        )
        display(styled)

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
        MicArray with shape (n_angles, n_thetas, max_note_length)
        """
        lengths = [
            seg[note]['end'] - seg[note]['start']
            for seg in segmentos if note in seg
        ]
        if not lengths:
            raise ValueError(f"Note '{note}' not found in any take.")

        max_len = max(lengths)
        data    = np.zeros((self.n_angles, self.n_thetas, max_len), dtype=np.float32)

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
                       thetas=self.thetas.copy())
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
            self.leq_levels  : np.ndarray  Leq in dB           (n_angles, n_thetas, n_bands)
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
        levels  = np.zeros((self.n_angles, self.n_thetas, n_bands), dtype=np.float32)

        total = self.n_angles * self.n_thetas
        done  = 0
        for i_az in range(self.n_angles):
            for i_th in range(self.n_thetas):
                signal = self.tensor[i_az, i_th, :].astype(np.float64)
                _, lev = fb.leq(signal, p_ref=p_ref, method=method)
                levels[i_az, i_th, :] = lev
                done += 1
                print(f"\r  {done}/{total}  az={self.angles[i_az]}°"
                      f"  el={self.thetas[i_th]}", end='')

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

    def compute_directivity_notes(self, bands='1/3',
                                   ref_azimuth=0, ref_theta_plot=0):
        """
        Runs compute_directivity() on each note in self.notes.
        Requires extract_all_notes() and to_spl() to have been called first.

        Parameters
        ----------
        bands          : str    '1/3' or 'octave'
        ref_azimuth    : int    reference azimuth for normalization (default 0)
        ref_theta_plot : int    reference theta for normalization (default 0)
        """
        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")

        for nota, ma_nota in self.notes.items():
            print(f"  {nota} ...", end=' ')
            ma_nota.compute_directivity(
                bands=bands,
                ref_azimuth=ref_azimuth,
                ref_theta_plot=ref_theta_plot,
            )
            print("OK")

        print(f"\n  compute_directivity_notes done — {len(self.notes)} notas  |  bands={bands}")

    def compute_spl(self, bands='1/3'):
        """
        Computes RMS-based SPL over the full signal for every position.

        Requires to_spl() to have been called first.
        Per-band SPL uses FFT-based rectangular bands (same as method='fft' in compute_leq).

        Parameters
        ----------
        bands : str   '1/3' or 'octave' (default: '1/3')

        Stores
        ------
        self.spl_freqs   : np.ndarray  center frequencies         (n_bands,)
        self.spl_levels  : np.ndarray  SPL per band in dB SPL     (n_angles, n_thetas, n_bands)
        self.spl_global  : np.ndarray  broadband SPL in dB SPL    (n_angles, n_thetas)
        """
        if not self._is_spl:
            raise RuntimeError("Run to_spl() first.")

        from filterbank import FilterBank

        P_REF   = 20e-6
        fb      = FilterBank(sr=self.sr, bands=bands)
        n_bands = len(fb.center_freqs_nominal)
        levels  = np.zeros((self.n_angles, self.n_thetas, n_bands), dtype=np.float32)
        global_ = np.zeros((self.n_angles, self.n_thetas), dtype=np.float32)

        total = self.n_angles * self.n_thetas
        done  = 0

        for i_az in range(self.n_angles):
            for i_th in range(self.n_thetas):
                signal = self.tensor[i_az, i_th, :].astype(np.float64)

                if len(signal) >= 2:
                    rms = np.sqrt(np.mean(signal ** 2))
                    global_[i_az, i_th] = 20 * np.log10(rms / P_REF + 1e-12)
                    _, band_levels = fb.leq(signal, p_ref=P_REF, method='fft')
                    levels[i_az, i_th, :] = band_levels

                done += 1
                print(f"\r  {done}/{total}  az={self.angles[i_az]}°"
                      f"  el={self.thetas[i_th]}", end='')

        self.spl_freqs  = np.array(fb.center_freqs_nominal, dtype=float)
        self.spl_levels = levels
        self.spl_global = global_

        print(f"\n  compute_spl done — {bands} octava  |  shape {levels.shape}")

    def compute_directivity(self, bands='1/3',
                            ref_theta='ref', ref_azimuth=0, ref_theta_plot=0):
        """
        Computes the directivity pattern in 1/3-octave bands.

        Three-step process:
          1. Compute SPL per band for every mic position (n_az, n_th, n_bands).

          2. Per-take emission correction via reference mic:
             delta[az, f] = SPL[az=ref_azimuth, ref_theta, f] - SPL[az, ref_theta, f]
             SPL_corr[az, theta, f] = SPL[az, theta, f] + delta[az, f]
             Cancels take-to-take emission variability — all takes are brought
             to the emission level of the reference azimuth.

          3. Normalization to on-axis reference position:
             dir[az, theta, f] = SPL_corr[az, theta, f] - SPL_corr[ref_azimuth, ref_theta_plot, f]
             Makes (ref_azimuth, ref_theta_plot) = 0 dB in every band.

        Does NOT require level_compensation() or normalize().

        Parameters
        ----------
        bands           : str          '1/3' or 'octave' (default: '1/3')
        ref_theta       : int or 'ref' mic used as per-take emission reference (default: 'ref')
        ref_azimuth     : int          azimuth used as emission reference and plot origin (default: 0)
        ref_theta_plot  : int or 'ref' theta of the plot reference direction (default: 0)

        Stores
        ------
        self.dir_freqs          : np.ndarray  center frequencies           (n_bands,)
        self.dir_levels         : np.ndarray  directivity in dB            (n_angles, n_thetas, n_bands)
        self.dir_global         : np.ndarray  broadband directivity in dB  (n_angles, n_thetas)
        self.dir_delta          : np.ndarray  per-take correction in dB    (n_angles, n_bands)
        self.dir_ref_spl        : np.ndarray  absolute SPL at ref pos      (n_bands,)
        self.dir_ref_spl_global : float       broadband SPL at ref pos
        """
        if not self._is_spl:
            raise RuntimeError("Run calibrate() + to_spl() first.")

        from filterbank import FilterBank

        P_REF   = 20e-6
        fb      = FilterBank(sr=self.sr, bands=bands)
        n_bands = len(fb.center_freqs_nominal)

        spl_levels = np.zeros((self.n_angles, self.n_thetas, n_bands), dtype=np.float32)
        spl_global = np.zeros((self.n_angles, self.n_thetas),          dtype=np.float32)

        total = self.n_angles * self.n_thetas
        done  = 0

        # Step 1 — compute SPL for all positions
        for i_az in range(self.n_angles):
            for i_th in range(self.n_thetas):
                signal = self.tensor[i_az, i_th, :].astype(np.float64)

                if len(signal) >= 2:
                    rms = np.sqrt(np.mean(signal ** 2))
                    spl_global[i_az, i_th] = 20 * np.log10(rms / P_REF + 1e-12)
                    _, band_levels = fb.leq(signal, p_ref=P_REF, method='fft')
                    spl_levels[i_az, i_th, :] = band_levels

                done += 1
                print(f"\r  {done}/{total}  az={self.angles[i_az]}°"
                      f"  el={self.thetas[i_th]}", end='')

        # Step 2 — per-take emission correction
        # delta[az, f] = SPL(az=0, ref, f) - SPL(az, ref, f)
        i_ref    = self._th_to_col(ref_theta)
        i_ref_az = self._az_to_row(ref_azimuth)

        delta        = spl_levels[i_ref_az, i_ref, :] - spl_levels[:, i_ref, :]  # (n_angles, n_bands)
        delta_global = spl_global[i_ref_az, i_ref]    - spl_global[:, i_ref]     # (n_angles,)

        spl_corr        = spl_levels + delta[:, np.newaxis, :]      # (n_angles, n_thetas, n_bands)
        spl_corr_global = spl_global + delta_global[:, np.newaxis]  # (n_angles, n_thetas)

        # Step 3 — normalize to on-axis reference position
        i_ref_th = self._th_to_col(ref_theta_plot)
        self.dir_ref_spl        = spl_corr[i_ref_az, i_ref_th, :].copy()  # (n_bands,) dB SPL
        self.dir_ref_spl_global = float(spl_corr_global[i_ref_az, i_ref_th])

        dir_levels = spl_corr        - spl_corr[i_ref_az, i_ref_th, :]
        dir_global = spl_corr_global - float(spl_corr_global[i_ref_az, i_ref_th])

        self.dir_freqs  = np.array(fb.center_freqs_nominal, dtype=float)
        self.dir_levels = dir_levels
        self.dir_global = dir_global
        self.dir_delta  = delta
        self._is_normalized = True

        th_plot_label = 'ref' if ref_theta_plot == 'ref' else f'{ref_theta_plot}°'
        print(f"\n  compute_directivity done — {bands} octava  |  shape {dir_levels.shape}"
              f"  |  ref_mic='{ref_theta}'  |  ref_plot=({ref_azimuth}°, {th_plot_label})")

    def plot_leq_global(self, theta='ref', yrange=None, title=None):
        """
        Bar chart of global Leq per azimuth for a given theta.

        Parameters
        ----------
        theta : int or 'ref'          theta to plot (default: 'ref')
        yrange    : [float, float] or None  y-axis range, e.g. [60, 100]
        title     : str or None             plot title (auto-generated if None)
        """
        if self.leq_global is None:
            raise RuntimeError("Run compute_leq() first.")

        i_th     = self._th_to_col(theta)
        th_label = 'ref' if theta == 'ref' else f'{theta}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'
        levels   = self.leq_global[:, i_th]
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
            title=title or f"Leq global — theta {th_label}",
            xaxis_title="Azimut",
            yaxis=dict(title=y_label, range=yrange, gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=450,
        )
        fig.show()

    def report_leq_global(self, theta='ref'):
        """
        Returns a pandas DataFrame with the global Leq per azimuth for a given
        theta, plus an energy-averaged summary row.

        Parameters
        ----------
        theta : int or 'ref'   theta to report (default: 'ref')
        """
        import pandas as pd
        from IPython.display import display

        if self.leq_global is None:
            raise RuntimeError("Run compute_leq() first.")

        i_th     = self._th_to_col(theta)
        th_label = 'ref' if theta == 'ref' else f'{theta}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'
        levels   = self.leq_global[:, i_th]
        mean_e   = 10 * np.log10(np.mean(10 ** (levels / 10)))

        cols = {f"{az}°": round(float(lev), 1) for az, lev in zip(self.angles, levels)}
        cols['Media'] = round(float(mean_e), 1)

        df = pd.DataFrame(cols, index=[f'Leq [{y_label}]  el: {th_label}'])
        display(df)
        return df

    def plot_leq_by_note(self, theta='ref', yrange=None, title=None):
        """
        For each note in self.notes, plots mean ± std of Leq global across azimuths.

        Interpretation depends on theta:
          theta='ref'  → level consistency of the singer between takes
          theta=N°     → directivity of the voice for that theta angle

        Requires extract_all_notes() and compute_leq_notes() first.

        Parameters
        ----------
        theta : int or 'ref'            theta to analyze (default: 'ref')
        yrange    : [float, float] or None  y-axis range, e.g. [70, 100]
        title     : str or None             plot title (auto-generated if None)
        """
        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")
        if next(iter(self.notes.values())).leq_global is None:
            raise RuntimeError("Run compute_leq_notes() first.")

        i_th     = self._th_to_col(theta)
        th_label = 'ref' if theta == 'ref' else f'{theta}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'

        note_names = list(self.notes.keys())
        means, stds = [], []
        for nota, ma_nota in self.notes.items():
            levels = ma_nota.leq_global[:, i_th]
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
            title=title or f"Leq global por nota — theta {th_label}",
            xaxis_title="Nota",
            yaxis=dict(title=y_label, range=yrange, gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=450,
        )
        fig.show()

    def report_leq_by_note(self, theta='ref'):
        """
        Returns a pandas DataFrame with mean, std, min and max Leq across
        azimuths for each note in self.notes.

        Requires extract_all_notes() and compute_leq_notes() first.

        Parameters
        ----------
        theta : int or 'ref'   theta to analyze (default: 'ref')
        """
        import pandas as pd
        from IPython.display import display

        if self.notes is None:
            raise RuntimeError("Run extract_all_notes() first.")
        if next(iter(self.notes.values())).leq_global is None:
            raise RuntimeError("Run compute_leq_notes() first.")

        i_th     = self._th_to_col(theta)
        th_label = 'ref' if theta == 'ref' else f'{theta}°'
        y_label  = 'dB SPL' if self._is_spl else 'dBFS'

        rows = []
        for nota, ma_nota in self.notes.items():
            levels = ma_nota.leq_global[:, i_th]
            rows.append({
                'Nota'               : nota,
                f'Media [{y_label}]' : round(float(10 * np.log10(np.mean(10 ** (levels / 10)))), 1),
                'Std'                : round(float(levels.std()), 1),
                'Mín'                : round(float(levels.min()), 1),
                'Máx'                : round(float(levels.max()), 1),
            })

        df = pd.DataFrame(rows).set_index('Nota')
        df.index.name = f'Nota  —  el: {th_label}'
        display(df)
        return df

    # ──────────────────────────────────────────────────────────────────────────
    # Directivity normalization
    # ──────────────────────────────────────────────────────────────────────────

    def normalize(self, type='leq', ref_azimuth=0, ref_theta=0):
        """
        Normalizes computed levels so that the reference position = 0 dB.

        All other positions are expressed relative to (ref_azimuth, ref_theta),
        giving negative values where the source is less directive. This is the
        standard directivity normalization for polar patterns.

        Must be called after compute_leq() or compute_spl() depending on type.

        Parameters
        ----------
        type        : str            'leq' — normalize leq_levels / leq_global
                                     'spl' — normalize spl_levels / spl_global
        ref_azimuth : int            reference azimuth in degrees (default: 0)
        ref_theta   : int or 'ref'   reference theta (default: 0)
        """
        if type == 'leq':
            if self.leq_global is None:
                raise RuntimeError("Run compute_leq() first.")
            data_global = self.leq_global
            data_levels = self.leq_levels
        elif type == 'spl':
            if self.spl_global is None:
                raise RuntimeError("Run compute_spl() first.")
            data_global = self.spl_global
            data_levels = self.spl_levels
        elif type == 'directivity':
            if self.dir_global is None:
                raise RuntimeError("Run compute_directivity() first.")
            data_global = self.dir_global
            data_levels = self.dir_levels
        else:
            raise ValueError("type must be 'leq', 'spl' or 'directivity'")

        i_ref_az  = self._az_to_row(ref_azimuth)
        i_ref_th  = self._th_to_col(ref_theta)
        ref_val   = float(data_global[i_ref_az, i_ref_th])
        th_label  = 'ref' if ref_theta == 'ref' else f'{ref_theta}°'

        print(f"  Reference: az={ref_azimuth}°  theta={th_label}"
              f"  level={ref_val:.1f} dB SPL\n")

        data_global -= ref_val
        if data_levels is not None:
            # normalize each band by its own reference value so that
            # the reference position is 0 dB in every band independently
            ref_band_vals = data_levels[i_ref_az, i_ref_th, :].copy()  # (n_bands,)
            data_levels  -= ref_band_vals  # broadcasts over (n_az, n_th, n_bands)

        self._is_normalized = True
        print(f"  normalize done — reference position set to 0 dB  [{type}]")

    # ──────────────────────────────────────────────────────────────────────────
    # Directivity plots
    # ──────────────────────────────────────────────────────────────────────────

    def _check_ready_to_plot(self, source='leq'):
        if not self._is_spl:
            raise RuntimeError("Run calibrate() + to_spl() first.")
        if source == 'directivity':
            if self.dir_global is None:
                raise RuntimeError("Run compute_directivity() first.")
            return
        if not self._is_compensated:
            raise RuntimeError("Run level_compensation() first.")
        if source == 'leq' and self.leq_global is None:
            raise RuntimeError("Run compute_leq() first.")
        if source == 'spl' and self.spl_global is None:
            raise RuntimeError("Run compute_spl() first.")
        if not self._is_normalized:
            raise RuntimeError("Run normalize() first.")

    def plot_spectrum(self, azimuth=0, theta=0, title=None):
        """
        Bar chart of per-band spectrum at a given mic position.

        Uses spl_levels if available (active-frame-gated), otherwise leq_levels.
        Works on the full MicArray or on ma.notes['X'].

        Parameters
        ----------
        azimuth : int or 'ref'   azimuth position (default 0)
        theta   : int or 'ref'   theta position   (default 0)
        title   : str or None    auto-generated if None
        """
        import plotly.graph_objects as go

        if hasattr(self, 'spl_levels') and self.spl_levels is not None:
            levels = self.spl_levels
            freqs  = self.spl_freqs
            source_label = 'SPL (frames activos)'
        elif hasattr(self, 'leq_levels') and self.leq_levels is not None:
            levels = self.leq_levels
            freqs  = self.leq_freqs
            source_label = 'LEQ'
        else:
            raise RuntimeError("Run compute_spl() or compute_leq() first.")

        i_az = self._az_to_row(azimuth)
        i_th = self._th_to_col(theta)

        band_levels = levels[i_az, i_th, :]
        freqs_str   = [str(int(f)) for f in freqs]

        az_label = f'{azimuth}°' if azimuth != 'ref' else 'ref'
        th_label = f'{theta}°'   if theta   != 'ref' else 'ref'

        fig = go.Figure(go.Bar(
            x=freqs_str,
            y=band_levels,
            marker_color='steelblue',
        ))
        fig.update_layout(
            title=title or f'Espectro 1/3 octava — az={az_label}  θ={th_label}  [{source_label}]',
            xaxis_title='Frecuencia (Hz)',
            yaxis_title='dB SPL',
            xaxis=dict(tickangle=-45),
            height=450,
        )
        fig.show()

    def plot_polar_2d(self, theta=0, freq=None, title=None, source='leq',
                      db_range=None, tick_step=None,
                      interp_deg=1, interp_method='cubic'):
        """
        Plots a 2D polar directivity pattern at a given standard elevation.

        Constructs a 360° azimuthal trace combining the front mic (θ) and its
        paired back mic (180°−θ), with energy-averaged seams at φ=0° and φ=180°.

        Special cases:
          theta='ref'  → 19 direct values at φ=0°–180° (no pairing, half plot)
          theta=90     → energy average of all 19 cenit readings (constant circle)

        Parameters
        ----------
        theta          : int or 'ref'           theta 0°–90° or 'ref' (default: 0)
        freq           : float or None          center frequency in Hz; None = broadband
        title          : str or None            auto-generated if None
        source         : str                    'leq' or 'spl' (default: 'leq')
        range          : [float, float] or None dB range to display, e.g. [-30, 0].
                                                None → auto (min to max of data)
        db_range       : [float, float] or None dB range to display, e.g. [-30, 0].
        tick_step      : float or None          spacing between gridlines in dB (auto if None)
        interp_deg     : float or None          interpolation resolution in degrees (default: 1).
                                                None → no interpolation, raw 10° data.
        interp_method  : str                    'cubic' (spline, default) or 'linear'
        """
        self._check_ready_to_plot(source)

        if source == 'directivity':
            global_levels = self.dir_global
            band_levels   = self.dir_levels
            band_freqs    = self.dir_freqs
        elif source == 'spl':
            global_levels = self.spl_global
            band_levels   = self.spl_levels
            band_freqs    = self.spl_freqs
        else:
            global_levels = self.leq_global
            band_levels   = self.leq_levels
            band_freqs    = self.leq_freqs

        # ── Levels matrix (n_angles, n_thetas) ───────────────────────────────
        if freq is None:
            levels     = global_levels
            freq_label = 'broadband'
        else:
            i_band     = int(np.argmin(np.abs(band_freqs - freq)))
            freq_label = f'{band_freqs[i_band]:.0f} Hz'
            levels     = band_levels[:, :, i_band]

        y_label  = 'dB' if source == 'directivity' or self._is_normalized \
                   else ('dB SPL' if self._is_spl else 'dBFS')
        th_label = 'ref' if theta == 'ref' else f'{theta}°'

        # ── Build radial trace ────────────────────────────────────────────────
        if theta == 'ref':
            i_th  = self._th_to_col('ref')
            r_dB  = levels[:, i_th].copy()              # 19 values, φ 0°→180°
            phi   = list(self.angles)                    # [0, 10, ..., 180]
            filled = False

        elif theta == 90:
            i_th  = self._th_to_col(90)
            r_avg = 10 * np.log10(np.mean(10 ** (levels[:, i_th] / 10)))
            r_dB  = np.full(37, r_avg)
            phi   = list(range(0, 370, 10))
            filled = True

        else:
            if theta not in self.thetas or (180 - theta) not in self.thetas:
                raise ValueError(
                    f"theta={theta}° or its pair {180 - theta}° not in "
                    f"self.thetas. Available: {self.thetas}"
                )
            i_th_front = self._th_to_col(theta)
            i_th_back  = self._th_to_col(180 - theta)
            r_front    = levels[:, i_th_front]           # φ 0°→180° (front mic)
            r_back     = levels[:, i_th_back]            # φ 0°→180° → std azimuth 180°→360°

            def _enavg(a, b):
                return 10 * np.log10((10 ** (a / 10) + 10 ** (b / 10)) / 2)

            r_dB        = np.empty(37)
            r_dB[0]     = _enavg(r_front[0], r_back[18])  # φ=0°   costura frontal
            r_dB[1:18]  = r_front[1:18]                    # φ=10°…170°
            r_dB[18]    = _enavg(r_front[18], r_back[0])  # φ=180° costura posterior
            r_dB[19:36] = r_back[1:18]                     # φ=190°…350°
            r_dB[36]    = r_dB[0]                          # φ=360° cierra la traza
            phi         = list(range(0, 370, 10))
            filled       = True

        # ── Shift to display space ────────────────────────────────────────────
        if db_range is not None:
            vmin, vmax = float(db_range[0]), float(db_range[1])
        else:
            vmin = float(np.min(r_dB))
            vmax = float(np.max(r_dB))

        span      = vmax - vmin
        r_display = np.clip(r_dB - vmin, 0, span)

        # ── Tick labels ───────────────────────────────────────────────────────
        step         = float(tick_step) if tick_step is not None else span / 4
        tick_abs     = np.arange(vmin, vmax + step * 0.01, step)
        tick_display = tick_abs - vmin
        tick_text    = [f'{v:.0f}' for v in tick_abs]
        tick_suffix  = f' {y_label}'

        # ── Interpolation ─────────────────────────────────────────────────────
        if interp_deg is not None:
            from scipy.interpolate import interp1d
            phi_arr  = np.array(phi, dtype=float)
            r_arr    = np.array(r_display, dtype=float)
            phi_new  = np.arange(phi_arr[0], phi_arr[-1] + interp_deg * 0.01, interp_deg)
            f_interp = interp1d(phi_arr, r_arr, kind=interp_method)
            r_display = f_interp(phi_new).clip(0, span).tolist()
            phi       = phi_new.tolist()

        # ── Figure ────────────────────────────────────────────────────────────
        if source == 'directivity' and hasattr(self, 'dir_ref_spl'):
            if freq is None:
                ref_spl = self.dir_ref_spl_global
            else:
                ref_spl = float(self.dir_ref_spl[i_band])
            spl_note = f"  |  ref {ref_spl:.1f} dB SPL"
        else:
            spl_note = ''
        auto_title = f"Directividad — θ {th_label}  |  {freq_label}{spl_note}  [{y_label}]"

        trace_kw = dict(r=r_display, theta=phi, mode='lines',
                        line=dict(color='steelblue', width=2))
        if filled:
            trace = go.Scatterpolar(**trace_kw, fill='toself',
                                    fillcolor='rgba(70,130,180,0.2)',
                                    name=f'θ {th_label}')
        else:
            trace = go.Scatterpolar(**trace_kw, name='ref mic')

        fig = go.Figure(trace)
        fig.update_layout(
            title=title or auto_title,
            polar=dict(
                radialaxis=dict(
                    range=[0, span],
                    tickvals=tick_display.tolist(),
                    ticktext=[t + tick_suffix for t in tick_text],
                    tickfont=dict(size=10),
                    gridcolor='lightgrey',
                    showline=True,
                    linecolor='grey',
                ),
                angularaxis=dict(
                    rotation=90,
                    direction='clockwise',
                    tickmode='array',
                    tickvals=list(range(0, 360, 30)),
                    ticktext=[f'{v}°' for v in range(0, 360, 30)],
                    gridcolor='lightgrey',
                ),
            ),
            width=600,
            height=600,
        )
        fig.show()

    # ──────────────────────────────────────────────────────────────────────────

    def plot_polar_3d(self, freq=None, source='directivity', db_range=None,
                      mirror=False, interp_deg=2, interp_method='cubic',
                      title=None):
        """
        3D directivity balloon (upper hemisphere by default).

        Reconstructs the hemisphere by combining front/back mic pairs for each
        elevation (same pairing logic as plot_polar_2d). Includes azimuth and
        elevation reference rings.

        Parameters
        ----------
        freq          : float or None    center frequency in Hz; None = broadband
        source        : str              'directivity', 'spl', or 'leq'
        db_range      : [float, float]   dB range; None = auto
        mirror        : bool             reflect upper hemisphere below horizontal (default False)
        interp_deg    : float or None    interpolated grid resolution in degrees (default 2). None = raw data.
        interp_method : str              'cubic' (spline) or 'linear' (default 'cubic')
        title         : str or None      auto-generated if None
        """
        import plotly.graph_objects as go

        self._check_ready_to_plot(source)

        if source == 'directivity':
            global_levels = self.dir_global
            band_levels   = self.dir_levels
            band_freqs    = self.dir_freqs
        elif source == 'spl':
            global_levels = self.spl_global
            band_levels   = self.spl_levels
            band_freqs    = self.spl_freqs
        else:
            global_levels = self.leq_global
            band_levels   = self.leq_levels
            band_freqs    = self.leq_freqs

        if freq is None:
            levels     = global_levels
            freq_label = 'broadband'
        else:
            i_band     = int(np.argmin(np.abs(band_freqs - freq)))
            freq_label = f'{band_freqs[i_band]:.0f} Hz'
            levels     = band_levels[:, :, i_band]

        def _enavg(a, b):
            return 10 * np.log10((10 ** (a / 10) + 10 ** (b / 10)) / 2)

        # Elevations 0°→90° (unique, sorted)
        elevs = sorted(th for th in self.thetas
                       if isinstance(th, (int, float)) and 0 <= th <= 90)
        n_elev = len(elevs)   # typically 10: 0°,10°,...,90°
        n_phi  = 37           # 0°→360° in 10° steps (closed ring)

        # ── Build R_dB  (n_elev × n_phi) ─────────────────────────────────────
        R_dB = np.zeros((n_elev, n_phi))
        for i_e, e in enumerate(elevs):
            i_f = self._th_to_col(e)
            if e == 90:
                avg           = 10 * np.log10(np.mean(10 ** (levels[:, i_f] / 10)))
                R_dB[i_e, :] = avg
            else:
                i_b = self._th_to_col(180 - e)
                rf  = levels[:, i_f]
                rb  = levels[:, i_b]
                row        = np.empty(37)
                row[0]     = _enavg(rf[0], rb[18])   # φ=0°   seam
                row[1:18]  = rf[1:18]                 # φ=10°→170°
                row[18]    = _enavg(rf[18], rb[0])   # φ=180° seam
                row[19:36] = rb[1:18]                 # φ=190°→350°
                row[36]    = row[0]                   # close ring
                R_dB[i_e, :] = row

        vmin   = float(db_range[0]) if db_range else float(R_dB.min())
        vmax   = float(db_range[1]) if db_range else float(R_dB.max())
        span   = (vmax - vmin) or 1.0
        R_clip = np.clip(R_dB, vmin, vmax)
        R_r    = (R_clip - vmin) / span   # radius ∈ [0, 1]

        # ── Interpolation ─────────────────────────────────────────────────────
        phi_orig  = np.arange(0, 361, 10, dtype=float)   # 0°→360°, 37 pts
        elev_orig = np.array(elevs, dtype=float)

        if interp_deg is not None:
            phi_new  = np.arange(0, 360 + interp_deg, interp_deg, dtype=float)
            elev_new = np.arange(0,  90 + interp_deg, interp_deg, dtype=float)
            phi_new  = phi_new[phi_new <= 360]
            elev_new = elev_new[elev_new <= 90]

            if interp_method == 'cubic':
                from scipy.interpolate import RectBivariateSpline
                R_r    = np.clip(
                    RectBivariateSpline(elev_orig, phi_orig, R_r,    kx=3, ky=3)(elev_new, phi_new),
                    0, 1)
                R_clip = np.clip(
                    RectBivariateSpline(elev_orig, phi_orig, R_clip, kx=3, ky=3)(elev_new, phi_new),
                    vmin, vmax)
            else:
                from scipy.interpolate import RegularGridInterpolator
                E_g, P_g = np.meshgrid(elev_new, phi_new, indexing='ij')
                pts      = np.c_[E_g.ravel(), P_g.ravel()]
                R_r    = RegularGridInterpolator(
                    (elev_orig, phi_orig), R_r,    method='linear')(pts
                ).clip(0, 1).reshape(len(elev_new), len(phi_new))
                R_clip = RegularGridInterpolator(
                    (elev_orig, phi_orig), R_clip, method='linear')(pts
                ).clip(vmin, vmax).reshape(len(elev_new), len(phi_new))

            phi_rad  = np.radians(phi_new)
            elev_rad = np.radians(elev_new)
        else:
            phi_rad  = np.radians(phi_orig)
            elev_rad = np.radians(elev_orig)

        # ── Cartesian (elevation measured from horizontal plane) ──────────────
        E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')

        X = R_r * np.cos(E) * np.cos(P)
        Y = R_r * np.cos(E) * np.sin(P)
        Z = R_r * np.sin(E)

        if mirror:
            X = np.vstack([np.flipud(X[1:]), X])
            Y = np.vstack([np.flipud(Y[1:]), Y])
            Z = np.vstack([-np.flipud(Z[1:]), Z])
            C = np.vstack([np.flipud(R_clip[1:]), R_clip])
        else:
            C = R_clip

        # ── Reference protractors ─────────────────────────────────────────────
        r_ref = 1.10   # slightly outside the unit balloon

        # Horizontal ring (azimuth protractor)
        phi_d    = np.linspace(0, 2 * np.pi, 361)
        h_ring   = go.Scatter3d(
            x=r_ref * np.cos(phi_d), y=r_ref * np.sin(phi_d), z=np.zeros(361),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )

        # Azimuth tick marks and labels every 30°
        az_ticks = list(range(0, 360, 30))
        r_lbl    = r_ref * 1.20
        r_tk0, r_tk1 = r_ref * 0.95, r_ref * 1.05
        az_tick_lines = []
        for a in az_ticks:
            ar = np.radians(a)
            az_tick_lines.append(go.Scatter3d(
                x=[r_tk0 * np.cos(ar), r_tk1 * np.cos(ar)],
                y=[r_tk0 * np.sin(ar), r_tk1 * np.sin(ar)],
                z=[0, 0],
                mode='lines', line=dict(color='rgba(60,60,60,0.8)', width=2),
                showlegend=False, hoverinfo='none',
            ))
        az_labels = go.Scatter3d(
            x=[r_lbl * np.cos(np.radians(a)) for a in az_ticks],
            y=[r_lbl * np.sin(np.radians(a)) for a in az_ticks],
            z=[0] * len(az_ticks),
            mode='text',
            text=[f'{a}°' for a in az_ticks],
            textfont=dict(size=12, color='rgba(40,40,40,1.0)'),
            showlegend=False, hoverinfo='none',
        )

        # Vertical arc (front-back plane, y=0): elevation 0°→90° both sides
        elev_d    = np.linspace(0, np.pi / 2, 91)
        v_front   = go.Scatter3d(
            x=r_ref * np.cos(elev_d), y=np.zeros(91), z=r_ref * np.sin(elev_d),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )
        v_back    = go.Scatter3d(
            x=-r_ref * np.cos(elev_d), y=np.zeros(91), z=r_ref * np.sin(elev_d),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )

        # Elevation tick marks and labels on front arc
        el_ticks  = [30, 60, 90]
        r_lbl_v   = r_ref * 1.20
        el_tick_lines = []
        for e in el_ticks:
            er = np.radians(e)
            el_tick_lines.append(go.Scatter3d(
                x=[r_ref * 0.95 * np.cos(er), r_ref * 1.05 * np.cos(er)],
                y=[0, 0],
                z=[r_ref * 0.95 * np.sin(er), r_ref * 1.05 * np.sin(er)],
                mode='lines', line=dict(color='rgba(60,60,60,0.8)', width=2),
                showlegend=False, hoverinfo='none',
            ))
        el_labels = go.Scatter3d(
            x=[r_lbl_v * np.cos(np.radians(e)) for e in el_ticks],
            y=[-0.04] * len(el_ticks),
            z=[r_lbl_v * np.sin(np.radians(e)) for e in el_ticks],
            mode='text',
            text=[f'{e}°' for e in el_ticks],
            textfont=dict(size=12, color='rgba(40,40,40,1.0)'),
            showlegend=False, hoverinfo='none',
        )

        # ── Figure ────────────────────────────────────────────────────────────
        y_label = 'dB' if source == 'directivity' or self._is_normalized \
                  else ('dB SPL' if self._is_spl else 'dBFS')

        surf = go.Surface(
            x=X, y=Y, z=Z,
            surfacecolor=C,
            colorscale=[[0.0, 'blue'], [1.0, 'red']],
            cmin=vmin, cmax=vmax,
            colorbar=dict(title=y_label, ticksuffix=f' {y_label}'),
        )

        all_traces = ([surf, h_ring, az_labels, v_front, v_back, el_labels]
                      + az_tick_lines + el_tick_lines)
        fig = go.Figure(data=all_traces)
        fig.update_layout(
            title=title or f'Directividad 3D — {freq_label}  [{y_label}]',
            scene=dict(
                xaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                yaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                zaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                aspectmode='cube',
            ),
            width=750,
            height=750,
        )
        fig.show()

    # ──────────────────────────────────────────────────────────────────────────

    def plot_directivity_sphere(self, freq=None, source='directivity', db_range=None,
                                mirror=False, interp_deg=2, interp_method='cubic',
                                colorscale='plasma', title=None):
        """
        3D unit sphere with surface color encoding the directivity level.

        Same data and interpolation logic as plot_polar_3d, but the radius is
        constant (r=1) — the shape is always a perfect sphere. The level is
        encoded only through color (blue = low, red = high).

        Parameters
        ----------
        freq          : float or None    center frequency in Hz; None = broadband
        source        : str              'directivity', 'spl', or 'leq'
        db_range      : [float, float]   dB range for colorscale; None = auto
        mirror        : bool             reflect upper hemisphere below horizontal (default False)
        interp_deg    : float or None    interpolated grid resolution in degrees (default 2). None = raw data.
        interp_method : str              'cubic' (spline) or 'linear' (default 'cubic')
        title         : str or None      auto-generated if None
        """
        import plotly.graph_objects as go

        self._check_ready_to_plot(source)

        if source == 'directivity':
            global_levels = self.dir_global
            band_levels   = self.dir_levels
            band_freqs    = self.dir_freqs
        elif source == 'spl':
            global_levels = self.spl_global
            band_levels   = self.spl_levels
            band_freqs    = self.spl_freqs
        else:
            global_levels = self.leq_global
            band_levels   = self.leq_levels
            band_freqs    = self.leq_freqs

        if freq is None:
            levels     = global_levels
            freq_label = 'broadband'
        else:
            i_band     = int(np.argmin(np.abs(band_freqs - freq)))
            freq_label = f'{band_freqs[i_band]:.0f} Hz'
            levels     = band_levels[:, :, i_band]

        def _enavg(a, b):
            return 10 * np.log10((10 ** (a / 10) + 10 ** (b / 10)) / 2)

        # ── Build R_dB  (n_elev × n_phi) ─────────────────────────────────────
        elevs  = sorted(th for th in self.thetas
                        if isinstance(th, (int, float)) and 0 <= th <= 90)
        n_phi  = 37
        R_dB   = np.zeros((len(elevs), n_phi))

        for i_e, e in enumerate(elevs):
            i_f = self._th_to_col(e)
            if e == 90:
                avg           = 10 * np.log10(np.mean(10 ** (levels[:, i_f] / 10)))
                R_dB[i_e, :] = avg
            else:
                i_b = self._th_to_col(180 - e)
                rf, rb     = levels[:, i_f], levels[:, i_b]
                row        = np.empty(37)
                row[0]     = _enavg(rf[0], rb[18])
                row[1:18]  = rf[1:18]
                row[18]    = _enavg(rf[18], rb[0])
                row[19:36] = rb[1:18]
                row[36]    = row[0]
                R_dB[i_e, :] = row

        vmin   = float(db_range[0]) if db_range else float(R_dB.min())
        vmax   = float(db_range[1]) if db_range else float(R_dB.max())
        R_clip = np.clip(R_dB, vmin, vmax)

        # ── Interpolation ─────────────────────────────────────────────────────
        phi_orig  = np.arange(0, 361, 10, dtype=float)
        elev_orig = np.array(elevs, dtype=float)

        if interp_deg is not None:
            phi_new  = np.arange(0, 360 + interp_deg, interp_deg, dtype=float)
            elev_new = np.arange(0,  90 + interp_deg, interp_deg, dtype=float)
            phi_new  = phi_new[phi_new <= 360]
            elev_new = elev_new[elev_new <= 90]

            if interp_method == 'cubic':
                from scipy.interpolate import RectBivariateSpline
                R_clip = np.clip(
                    RectBivariateSpline(elev_orig, phi_orig, R_clip, kx=3, ky=3)(elev_new, phi_new),
                    vmin, vmax)
            else:
                from scipy.interpolate import RegularGridInterpolator
                E_g, P_g = np.meshgrid(elev_new, phi_new, indexing='ij')
                pts      = np.c_[E_g.ravel(), P_g.ravel()]
                R_clip   = RegularGridInterpolator(
                    (elev_orig, phi_orig), R_clip, method='linear')(pts
                ).clip(vmin, vmax).reshape(len(elev_new), len(phi_new))

            phi_rad  = np.radians(phi_new)
            elev_rad = np.radians(elev_new)
        else:
            phi_rad  = np.radians(phi_orig)
            elev_rad = np.radians(elev_orig)

        # ── Cartesian — unit sphere (r = 1 constant) ──────────────────────────
        E, P = np.meshgrid(elev_rad, phi_rad, indexing='ij')
        X = np.cos(E) * np.cos(P)
        Y = np.cos(E) * np.sin(P)
        Z = np.sin(E)

        if mirror:
            X = np.vstack([np.flipud(X[1:]), X])
            Y = np.vstack([np.flipud(Y[1:]), Y])
            Z = np.vstack([-np.flipud(Z[1:]), Z])
            C = np.vstack([np.flipud(R_clip[1:]), R_clip])
        else:
            C = R_clip

        # ── Reference protractors ─────────────────────────────────────────────
        r_ref = 1.10
        phi_d = np.linspace(0, 2 * np.pi, 361)
        h_ring = go.Scatter3d(
            x=r_ref * np.cos(phi_d), y=r_ref * np.sin(phi_d), z=np.zeros(361),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )

        az_ticks = list(range(0, 360, 30))
        r_lbl    = r_ref * 1.20
        r_tk0, r_tk1 = r_ref * 0.95, r_ref * 1.05
        az_tick_lines = []
        for a in az_ticks:
            ar = np.radians(a)
            az_tick_lines.append(go.Scatter3d(
                x=[r_tk0 * np.cos(ar), r_tk1 * np.cos(ar)],
                y=[r_tk0 * np.sin(ar), r_tk1 * np.sin(ar)],
                z=[0, 0],
                mode='lines', line=dict(color='rgba(60,60,60,0.8)', width=2),
                showlegend=False, hoverinfo='none',
            ))
        az_labels = go.Scatter3d(
            x=[r_lbl * np.cos(np.radians(a)) for a in az_ticks],
            y=[r_lbl * np.sin(np.radians(a)) for a in az_ticks],
            z=[0] * len(az_ticks),
            mode='text', text=[f'{a}°' for a in az_ticks],
            textfont=dict(size=12, color='rgba(40,40,40,1.0)'),
            showlegend=False, hoverinfo='none',
        )

        elev_d = np.linspace(0, np.pi / 2, 91)
        v_front = go.Scatter3d(
            x=r_ref * np.cos(elev_d), y=np.zeros(91), z=r_ref * np.sin(elev_d),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )
        v_back = go.Scatter3d(
            x=-r_ref * np.cos(elev_d), y=np.zeros(91), z=r_ref * np.sin(elev_d),
            mode='lines', line=dict(color='rgba(60,60,60,0.7)', width=2),
            showlegend=False, hoverinfo='none',
        )

        el_ticks = [30, 60, 90]
        r_lbl_v  = r_ref * 1.20
        el_tick_lines = []
        for e in el_ticks:
            er = np.radians(e)
            el_tick_lines.append(go.Scatter3d(
                x=[r_ref * 0.95 * np.cos(er), r_ref * 1.05 * np.cos(er)],
                y=[0, 0],
                z=[r_ref * 0.95 * np.sin(er), r_ref * 1.05 * np.sin(er)],
                mode='lines', line=dict(color='rgba(60,60,60,0.8)', width=2),
                showlegend=False, hoverinfo='none',
            ))
        el_labels = go.Scatter3d(
            x=[r_lbl_v * np.cos(np.radians(e)) for e in el_ticks],
            y=[-0.04] * len(el_ticks),
            z=[r_lbl_v * np.sin(np.radians(e)) for e in el_ticks],
            mode='text', text=[f'{e}°' for e in el_ticks],
            textfont=dict(size=12, color='rgba(40,40,40,1.0)'),
            showlegend=False, hoverinfo='none',
        )

        # ── Figure ────────────────────────────────────────────────────────────
        y_label = 'dB' if source == 'directivity' or self._is_normalized \
                  else ('dB SPL' if self._is_spl else 'dBFS')

        surf = go.Surface(
            x=X, y=Y, z=Z,
            surfacecolor=C,
            colorscale=colorscale,
            cmin=vmin, cmax=vmax,
            colorbar=dict(title=y_label, ticksuffix=f' {y_label}'),
        )

        all_traces = ([surf, h_ring, az_labels, v_front, v_back, el_labels]
                      + az_tick_lines + el_tick_lines)
        fig = go.Figure(data=all_traces)
        fig.update_layout(
            title=title or f'Esfera de directividad — {freq_label}  [{y_label}]',
            scene=dict(
                xaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                yaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                zaxis=dict(showbackground=False, showticklabels=False, title='', range=[-1.3, 1.3]),
                aspectmode='cube',
            ),
            width=750,
            height=750,
        )
        fig.show()

    # ──────────────────────────────────────────────────────────────────────────

    def listen(self, azimuth, theta):
        """
        Returns an IPython Audio widget to listen to a specific take and theta.

        Parameters
        ----------
        azimuth   : int              azimuth angle value (e.g. 0, 90, 180)
        theta : int or 'ref'     theta label (e.g. 0, 90, 'ref')
        """
        from IPython.display import Audio, display

        i_az   = self._az_to_row(azimuth)
        i_th   = self._th_to_col(theta)
        signal = self.tensor[i_az, i_th, :].astype(np.float32)

        # Trim trailing zeros (from extract_note padding)
        nonzero = np.nonzero(signal)[0]
        if len(nonzero):
            signal = signal[:nonzero[-1] + 1]

        label = f"ref" if theta == 'ref' else f"{theta}°"
        print(f"  theta {label}  |  {azimuth}°  |  {len(signal)/self.sr:.2f}s")
        display(Audio(signal, rate=self.sr))

    def listen_band(self, freq, azimuth=0, theta=0):
        """
        Plays the audio of a mic position filtered to the 1/3 octave band
        centered at freq. Works on full audio and ma.notes['X'].

        Parameters
        ----------
        freq    : float          nominal 1/3 octave center frequency in Hz
        azimuth : int            azimuth angle (default 0)
        theta   : int or 'ref'  theta position  (default 0)
        """
        from IPython.display import Audio, display
        from scipy.signal import butter, sosfilt

        i_az   = self._az_to_row(azimuth)
        i_th   = self._th_to_col(theta)
        signal = self.tensor[i_az, i_th, :].astype(np.float64)

        # Trim trailing zeros (note padding)
        nonzero = np.nonzero(signal)[0]
        if len(nonzero):
            signal = signal[:nonzero[-1] + 1]

        # 1/3 octave band limits
        flo = max(freq * 2 ** (-1 / 6),  20.0)
        fhi = min(freq * 2 ** ( 1 / 6), self.sr / 2 * 0.95)

        sos      = butter(6, [flo, fhi], btype='band', fs=self.sr, output='sos')
        filtered = sosfilt(sos, signal)

        # Normalize for playback
        peak = np.max(np.abs(filtered))
        if peak > 0:
            filtered = filtered / peak * 0.9

        az_label = f'{azimuth}°'
        th_label = 'ref' if theta == 'ref' else f'{theta}°'
        print(f"  {freq} Hz  (1/3 oct: {flo:.0f}–{fhi:.0f} Hz)"
              f"  |  az={az_label}  θ={th_label}  |  {len(filtered)/self.sr:.2f}s")
        display(Audio(filtered, rate=self.sr))

    # ──────────────────────────────────────────────────────────────────────────
    # Analysis plots
    # ──────────────────────────────────────────────────────────────────────────

    def plot_rms_takes(self, theta='ref', floor_dB=-60, yrange=None):
        """
        Plots the RMS level (dBFS) of an theta across all takes as a
        VU-meter style bar chart.

        Parameters
        ----------
        theta : int or 'ref'       theta to measure (default: 'ref')
        floor_dB  : float              bottom of the y-axis in dBFS (default: -60)
        yrange    : [float, float]     optional y-axis zoom, e.g. [-40, -20]
        """
        i_th = self._th_to_col(theta)

        rms_dB = [
            20 * np.log10(np.sqrt(np.mean(self.tensor[i_az, i_th, :] ** 2)) + 1e-12)
            for i_az in range(self.n_angles)
        ]

        label = "ref" if theta == 'ref' else f"{theta}°"
        fig = go.Figure(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=[r - floor_dB for r in rms_dB],
            base=floor_dB,
            marker_color='steelblue',
            text=[f"{r:.1f}" for r in rms_dB],
            textposition='outside',
        ))
        fig.update_layout(
            title=f"RMS por toma — theta {label}",
            xaxis_title="Azimut",
            yaxis=dict(title="dBFS", range=yrange if yrange else [floor_dB, 0],
                       gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            width=900, height=400,
        )
        fig.show()

    def plot_tune(self, azimuth, scale=None, theta='ref', hop_length=512,
                  confidence_threshold=0.5):
        """
        Plots the tuning deviation (cents) of each note for a given take.

        Parameters
        ----------
        scale                : dict           {note_name: freq_hz}
        azimuth              : int            azimuth take to analyze
        theta            : int or 'ref'   theta to use (default: 'ref')
        hop_length           : int            pyin hop length (default: 512)
        confidence_threshold : float          min pyin confidence (default: 0.5)
        """
        import librosa

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

        i_az = self._az_to_row(azimuth)
        i_th = self._th_to_col(theta)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        fmin       = min(note_freqs) * 0.9
        fmax       = max(note_freqs) * 1.1

        signal = self.tensor[i_az, i_th, :].astype(np.float32)

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

        label = "ref" if theta == 'ref' else f"{theta}°"
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
            title=f"Afinación — theta {label}  |  {azimuth}°",
            xaxis_title="Nota",
            yaxis_title="Desviación (cents)",
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            yaxis=dict(gridcolor='lightgrey', zeroline=False),
            width=800, height=450,
        )
        fig.show()

    def plot_f0(self, azimuth, scale=None, theta='ref', hop_length=512,
                band_cents=50, segments=None):
        """
        Plots the pyin f0 tracking for a specific take against the scale notes.

        Parameters
        ----------
        scale      : dict            {note_name: freq_hz}
        azimuth    : int             azimuth take to analyze
        theta  : int or 'ref'    theta to use (default: 'ref')
        hop_length : int             pyin hop length in samples (default: 512)
        band_cents : float           half-width of shaded band per note (default: 50)
        segments   : list or None    output of detect_notes(); if provided, draws vertical
                                     lines at the start/end of each detected note segment
        """
        import librosa

        scale = scale or self.scale
        if scale is None:
            raise RuntimeError("Provide a scale or set self.scale first.")

        i_az = self._az_to_row(azimuth)
        i_th = self._th_to_col(theta)

        note_names = list(scale.keys())
        note_freqs = np.array(list(scale.values()))
        f_ref      = note_freqs[0]
        fmin       = note_freqs[0] * 0.9
        fmax       = note_freqs[-1] * 1.1

        signal = self.tensor[i_az, i_th, :].astype(np.float32)

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

        if segments is not None:
            i_az = self._az_to_row(azimuth)
            segs_az = segments[i_az]
            for i, (name, seg) in enumerate(segs_az.items()):
                color = palette[list(scale.keys()).index(name) % len(palette)]
                for edge in (seg['start'], seg['end']):
                    t_edge = edge / self.sr
                    fig.add_vline(
                        x=t_edge,
                        line=dict(color='black', width=1.5, dash='dash'),
                        annotation_text=name if edge == seg['start'] else '',
                        annotation_position='top',
                    )

        label = "ref" if theta == 'ref' else f"{theta}°"
        fig.update_layout(
            title=f"F0 tracking — theta {label}  |  {azimuth}°",
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

    def plot(self, azimuth=None, theta=None, title=None,
             envelope=True, dB=False, floor_dB=-80, yrange=None):
        """
        Plots time-domain signals from the tensor.

        Dispatch rules:
          azimuth + theta  → single signal at that position
          azimuth only         → all thetas for that azimuth
          theta only       → all azimuths for that theta

        Parameters
        ----------
        azimuth   : int or None           azimuth angle (e.g. 0, 90, 180)
        theta : int, 'ref', or None   theta label (e.g. 0, 90, 'ref')
        title     : str or None           plot title (auto-generated if None)
        envelope  : bool                  if True, shows smooth abs envelope (default: True)
        dB        : bool                  if True, converts amplitude to dB (default: False)
        floor_dB  : float                 noise floor clipping when dB=True (default: -80)
        yrange    : [float, float] or None  y-axis range, e.g. [40, 100]. Auto if None.
        """
        if azimuth is None and theta is None:
            raise ValueError("Provide at least 'azimuth' or 'theta'.")

        P_REF = 20e-6 if self._is_spl else 1.0
        def to_dB(ds):
            return np.maximum(20 * np.log10(np.abs(ds) / P_REF + 1e-12), floor_dB)

        fig = go.Figure()

        if azimuth is not None and theta is not None:
            i_az       = self._az_to_row(azimuth)
            i_th       = self._th_to_col(theta)
            signal     = self.tensor[i_az, i_th, :]
            ds, factor = self._prepare(signal, envelope)
            if dB: ds  = to_dB(ds)
            t          = np.arange(len(ds)) * factor / self.sr
            th_label   = "ref" if theta == 'ref' else f"{theta}°"
            fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                     line=dict(width=1),
                                     name=f"{th_label} — {azimuth}°"))
            auto_title = f"theta {th_label} dado el azimut {azimuth}°"
            height     = 400

        elif azimuth is not None:
            i_az = self._az_to_row(azimuth)
            for el in self.thetas:
                i_th       = self._th_to_col(el)
                signal     = self.tensor[i_az, i_th, :]
                ds, factor = self._prepare(signal, envelope)
                if dB: ds  = to_dB(ds)
                t          = np.arange(len(ds)) * factor / self.sr
                label      = "ref" if el == 'ref' else f"{el}°"
                fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                         line=dict(width=1), name=label))
            auto_title = f"thetaes dado el azimut {azimuth}°"
            height     = 500

        else:
            i_th     = self._th_to_col(theta)
            th_label = "ref" if theta == 'ref' else f"{theta}°"
            for az in self.angles:
                i_az       = self._az_to_row(az)
                signal     = self.tensor[i_az, i_th, :]
                ds, factor = self._prepare(signal, envelope)
                if dB: ds  = to_dB(ds)
                t          = np.arange(len(ds)) * factor / self.sr
                fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                         line=dict(width=1), name=f"{az}°"))
            auto_title = f"Azimuts dada la theta {th_label}"
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

    def plot_html(self, azimuth=None, theta=None, title=None,
                  envelope=True, dB=False, floor_dB=-80, yrange=None,
                  max_pts=3000) -> str:
        """Igual a plot() pero devuelve el HTML en lugar de mostrarlo.
        max_pts limita los puntos por traza para mantener el HTML liviano."""
        orig = self.downsampling_graph
        n_samples = self.tensor.shape[2]
        self.downsampling_graph = max(1, n_samples // max_pts)
        try:
            # Construimos la figura de la misma forma que plot() pero sin fig.show()
            P_REF = 20e-6 if self._is_spl else 1.0
            def to_dB(ds):
                return np.maximum(20 * np.log10(np.abs(ds) / P_REF + 1e-12), floor_dB)

            fig = go.Figure()

            if azimuth is not None and theta is not None:
                i_az       = self._az_to_row(azimuth)
                i_th       = self._th_to_col(theta)
                signal     = self.tensor[i_az, i_th, :]
                ds, factor = self._prepare(signal, envelope)
                if dB: ds  = to_dB(ds)
                t          = np.arange(len(ds)) * factor / self.sr
                th_label   = "ref" if theta == 'ref' else f"{theta}°"
                fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                         line=dict(width=1),
                                         name=f"{th_label} — {azimuth}°"))
                auto_title = f"theta {th_label} dado el azimut {azimuth}°"
                height     = 400

            elif azimuth is not None:
                i_az = self._az_to_row(azimuth)
                for el in self.thetas:
                    i_th       = self._th_to_col(el)
                    signal     = self.tensor[i_az, i_th, :]
                    ds, factor = self._prepare(signal, envelope)
                    if dB: ds  = to_dB(ds)
                    t          = np.arange(len(ds)) * factor / self.sr
                    label      = "ref" if el == 'ref' else f"{el}°"
                    fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                             line=dict(width=1), name=label))
                auto_title = f"Thetaes dado el azimut {azimuth}°"
                height     = 500

            else:
                i_th     = self._th_to_col(theta)
                th_label = "ref" if theta == 'ref' else f"{theta}°"
                for az in self.angles:
                    i_az       = self._az_to_row(az)
                    signal     = self.tensor[i_az, i_th, :]
                    ds, factor = self._prepare(signal, envelope)
                    if dB: ds  = to_dB(ds)
                    t          = np.arange(len(ds)) * factor / self.sr
                    fig.add_trace(go.Scatter(x=t, y=ds, mode='lines',
                                             line=dict(width=1), name=f"{az}°"))
                auto_title = f"Azimuts dada la theta {th_label}"
                height     = 500

            axis_style = dict(gridcolor='lightgrey', showline=True,
                              linecolor='black', linewidth=1, mirror=False)
            if dB:
                if yrange is not None:
                    y_axis = dict(**axis_style, range=yrange)
                else:
                    all_y = [tr.y for tr in fig.data if tr.y is not None]
                    # Ignorar el piso de ruido (valores en floor_dB) para
                    # que el rango muestre la señal útil, no el silencio
                    all_vals = np.concatenate([np.asarray(y) for y in all_y])
                    signal_vals = all_vals[all_vals > floor_dB + 3]
                    if len(signal_vals):
                        y_min = float(np.percentile(signal_vals, 5))
                        y_max = float(np.max(all_vals))
                    else:
                        y_min, y_max = floor_dB, 0.0
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
                autosize=True,
                margin=dict(l=60, r=20, t=50, b=50),
            )
            html = fig.to_html(
                full_html=True,
                include_plotlyjs='cdn',
                config={'responsive': True},
            )
            # Forzar que body y su div hijo ocupen el 100% del viewport
            css = ('<style>'
                   'html,body{margin:0;padding:0;height:100%;overflow:hidden;}'
                   'body>div{height:100%;}'
                   '</style>')
            return html.replace('</head>', css + '</head>', 1)
        finally:
            self.downsampling_graph = orig

    def plot_rms_takes_html(self, theta='ref', floor_dB=-60, yrange=None) -> str:
        """Igual a plot_rms_takes() pero devuelve el HTML."""
        i_th = self._th_to_col(theta)
        rms_dB = [
            20 * np.log10(np.sqrt(np.mean(self.tensor[i_az, i_th, :] ** 2)) + 1e-12)
            for i_az in range(self.n_angles)
        ]
        label = "ref" if theta == 'ref' else f"{theta}°"
        fig = go.Figure(go.Bar(
            x=[f"{a}°" for a in self.angles],
            y=[r - floor_dB for r in rms_dB],
            base=floor_dB,
            marker_color='steelblue',
            text=[f"{r:.1f}" for r in rms_dB],
            textposition='outside',
        ))
        fig.update_layout(
            title=f"RMS por toma — theta {label}",
            xaxis_title="Azimut",
            yaxis=dict(title="dBFS", range=yrange if yrange else [floor_dB, 0],
                       gridcolor='lightgrey'),
            plot_bgcolor='white',
            xaxis=dict(gridcolor='lightgrey'),
            autosize=True,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        html = fig.to_html(
            full_html=True,
            include_plotlyjs='cdn',
            config={'responsive': True},
        )
        css = ('<style>'
               'html,body{margin:0;padding:0;height:100%;overflow:hidden;}'
               'body>div{height:100%;}'
               '</style>')
        return html.replace('</head>', css + '</head>', 1)

    def plot_leq(self, azimuth=None, theta=None, title=None, vrange=None,
                 colorscale='Viridis', frange=None):
        """
        Plots Leq per band. Requires compute_leq() to have been called first.

        Dispatch rules:
          azimuth + theta  → bar chart — single spectrum at that position
          azimuth only         → heatmap   — thetaes × bandas
          theta only       → heatmap   — azimuts × bandas

        Parameters
        ----------
        azimuth   : int or None           azimuth angle
        theta : int, 'ref', or None   theta label
        title       : str or None           plot title (auto-generated if None)
        vrange      : [float, float] or None  dB range. Auto if None.
                                              For bar: y-axis. For heatmap: colorscale.
        colorscale  : str   colorscale para heatmap (default: 'Viridis')
                            Opciones: 'Viridis', 'Turbo', 'Jet', 'Hot', 'RdYlGn'
        frange      : (float, float) or None  frequency range in Hz, e.g. (200, 8000)
        """
        if self.leq_levels is None:
            raise RuntimeError("Run compute_leq() first.")
        if azimuth is None and theta is None:
            raise ValueError("Provide at least 'azimuth' or 'theta'.")

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

        if azimuth is not None and theta is not None:
            # ── Bar chart — single position ───────────────────────────────────
            i_az     = self._az_to_row(azimuth)
            i_th     = self._th_to_col(theta)
            levels   = self.leq_levels[i_az, i_th, band_mask]
            th_label = 'ref' if theta == 'ref' else f'{theta}°'

            fig = go.Figure(go.Bar(
                x=band_labels, y=levels,
                marker_color='steelblue',
                text=[f"{v:.1f}" for v in levels],
                textposition='outside',
            ))
            auto_title = f"Leq — az {azimuth}°  el {th_label}"
            y_axis = dict(**axis_style, range=vrange) if vrange else axis_style
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title=y_label,
                plot_bgcolor='white', xaxis=axis_style, yaxis=y_axis,
                width=1200, height=500,
            )

        elif azimuth is not None:
            # ── Heatmap — theta × bandas ────────────────────────────────
            i_az     = self._az_to_row(azimuth)
            z        = self.leq_levels[i_az, :, :][:, band_mask]
            y_labels = ['ref' if e == 'ref' else f'{e}°' for e in self.thetas]

            fig = go.Figure(go.Heatmap(
                x=band_labels, y=y_labels, z=z,
                colorscale=colorscale,
                zmin=vrange[0] if vrange else None,
                zmax=vrange[1] if vrange else None,
                colorbar=dict(title=y_label),
            ))
            auto_title = f"Leq por theta — azimut {azimuth}°"
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title="theta",
                width=1200, height=550,
            )

        else:
            # ── Heatmap — azimuts × bandas ────────────────────────────────────
            i_th     = self._th_to_col(theta)
            z        = self.leq_levels[:, i_th, :][:, band_mask]
            y_labels = [f'{a}°' for a in self.angles]
            th_label = 'ref' if theta == 'ref' else f'{theta}°'

            fig = go.Figure(go.Heatmap(
                x=band_labels, y=y_labels, z=z,
                colorscale=colorscale,
                zmin=vrange[0] if vrange else None,
                zmax=vrange[1] if vrange else None,
                colorbar=dict(title=y_label),
            ))
            auto_title = f"Leq por azimut — theta {th_label}"
            fig.update_layout(
                title=title or auto_title,
                xaxis_title="Banda (Hz)", yaxis_title="Azimut",
                width=1200, height=550,
            )

        fig.show()


# ── Module-level helpers (not part of the class) ─────────────────────────────


def _gcc_phat(sig1, sig2, energy_threshold_dB=None):
    """
    Estimates the TDOA between sig1 and sig2 using GCC-PHAT.

    Returns the delay in samples: positive means sig1 arrives later than sig2.

    If energy_threshold_dB is set, samples where sig1 RMS (in 512-sample frames)
    is below that level are zeroed out in both signals before correlation, so
    silent/noisy regions don't contaminate the result.
    """
    if energy_threshold_dB is not None:
        threshold = 10 ** (energy_threshold_dB / 20)
        frame     = 512
        mask      = np.zeros(len(sig1), dtype=np.float64)
        for i in range(0, len(sig1) - frame + 1, frame):
            if np.sqrt(np.mean(sig1[i:i + frame] ** 2)) > threshold:
                mask[i:i + frame] = 1.0
        sig1 = sig1 * mask
        sig2 = sig2 * mask

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
    Detects the onset of a signal using a sliding median with 50% overlap.

    Uses the median of |signal| within each window (more robust to click noise
    than RMS/mean). Returns the sample index of the first window that exceeds
    threshold_dB.
    """
    window    = max(1, int(window_ms / 1000 * sr))
    hop       = window // 2
    threshold = 10 ** (threshold_dB / 20)

    for i in range(0, len(signal) - window, hop):
        if np.median(np.abs(signal[i:i + window])) > threshold:
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
