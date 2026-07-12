"""
plot/waveform.py — Wrappers que delegan en MicArray.plot_html() y
                   MicArray.plot_rms_takes_html().
"""


def build_waveform_html(
    ma,
    theta=None,
    azimuth=None,
    envelope: bool = True,
    dB: bool = False,
    floor_dB: float = -80,
    yrange=None,
) -> str:
    if ma is None:
        return _placeholder()
    if theta is None and azimuth is None:
        theta = 'ref'
    if dB:
        envelope = True
    return ma.plot_html(
        azimuth=azimuth,
        theta=theta,
        envelope=envelope,
        dB=dB,
        floor_dB=floor_dB,
        yrange=yrange,
    )


def build_rms_html(ma, floor_dB: float = -60, yrange=None) -> str:
    if ma is None:
        return _placeholder()
    return ma.plot_rms_takes_html(floor_dB=floor_dB, yrange=yrange)


def _placeholder() -> str:
    return "<html><body style='background:#fff;color:#888;display:flex;align-items:center;justify-content:center;height:100%;'><p>Sin datos cargados.</p></body></html>"
