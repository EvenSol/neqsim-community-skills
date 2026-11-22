"""Matplotlib figures for pipeline profiles: stacked profile, P-T path, combined.

All figures share one visual language:

* status colours (fixed): ok ``#0ca30c``, watch ``#fab219``, high/hydrate
  ``#d03b3b`` - always paired with a text label in the legend,
* series colours: fluid temperature / pressure in blue ``#2a78d6``, hydrate
  equilibrium temperature in orange ``#eb6834``,
* one y-axis per panel (no dual axes); panels share the KP axis.

Requires ``matplotlib`` (``pip install matplotlib``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from .profile import PipelineProfile, ProfileScreeningResult, margin_status

STATUS_COLOURS = {"ok": "#0ca30c", "watch": "#fab219", "high": "#d03b3b", "unknown": "#898781"}
SERIES_BLUE = "#2a78d6"
SERIES_ORANGE = "#eb6834"
SEABED = "#c3c2b7"
INK = "#0b0b0b"
INK_MUTED = "#6b6a64"
GRID = "#e1e0d9"


def _plt():
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise ImportError("matplotlib is required for plotting: pip install matplotlib") from exc
    return plt


def _style(ax) -> None:
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(SEABED)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)


def _status_segments(ax, x: Sequence[float], y: Sequence[float], statuses: Sequence[str], lw: float = 2.0) -> None:
    for i in range(len(x) - 1):
        if not (isfinite(y[i]) and isfinite(y[i + 1])):
            continue
        worst = statuses[i] if _rank(statuses[i]) >= _rank(statuses[i + 1]) else statuses[i + 1]
        ax.plot(x[i : i + 2], y[i : i + 2], color=STATUS_COLOURS[worst], lw=lw, solid_capstyle="round")


def _rank(status: str) -> int:
    return {"unknown": 0, "ok": 1, "watch": 2, "high": 3}[status]


def _status_legend(ax, min_margin: float, loc: str = "best") -> None:
    from matplotlib.lines import Line2D

    handles = [
        Line2D([], [], color=STATUS_COLOURS["ok"], lw=3, label=f"ok (margin >= {min_margin:g} C)"),
        Line2D([], [], color=STATUS_COLOURS["watch"], lw=3, label=f"watch (0 - {min_margin:g} C)"),
        Line2D([], [], color=STATUS_COLOURS["high"], lw=3, label="high (in hydrate region)"),
    ]
    ax.legend(handles=handles, fontsize=7, loc=loc, framealpha=0.9)


def plot_profile(
    profile: PipelineProfile,
    *,
    min_margin: float = 3.0,
    result: ProfileScreeningResult | None = None,
    axes: Sequence[Any] | None = None,
    title: str | None = None,
):
    """Stacked panels sharing KP: elevation, pressure, temperature vs hydrate T, margin.

    Panels without data (no depth, no hydrate temperatures) are skipped.
    Returns the matplotlib ``Figure``.
    """
    plt = _plt()
    result = result or profile.evaluate(min_margin)
    margin = profile.hydrate_margin_c
    panels = []
    if profile.depth_m is not None:
        panels.append("elevation")
    panels += ["pressure", "temperature"]
    if margin is not None:
        panels.append("margin")

    own_figure = axes is None
    if axes is None:
        heights = {"elevation": 1.0, "pressure": 1.0, "temperature": 1.4, "margin": 1.1}
        fig, axes = plt.subplots(
            len(panels), 1, sharex=True, figsize=(8, 1.9 * len(panels) + 0.6),
            gridspec_kw={"height_ratios": [heights[p] for p in panels]},
        )
        axes = list(axes) if len(panels) > 1 else [axes]
    else:
        axes = list(axes)
        if len(axes) != len(panels):
            raise ValueError(f"need {len(panels)} axes for panels {panels}")
        fig = axes[0].figure

    kp = profile.kp_km
    for ax, panel in zip(axes, panels):
        _style(ax)
        if panel == "elevation":
            elev = profile.elevation_m
            floor = min(elev) - 0.08 * (max(elev) - min(elev) + 10.0)  # type: ignore[arg-type]
            ax.fill_between(kp, elev, floor, color=SEABED, alpha=0.6, lw=0, label="seabed")  # type: ignore[arg-type]
            ax.plot(kp, elev, color=INK, lw=1.6, label="pipeline")  # type: ignore[arg-type]
            ax.set_ylim(bottom=floor)
            ax.set_ylabel("Elevation [m]")
            ax.legend(fontsize=7, loc="lower right", framealpha=0.9)
        elif panel == "pressure":
            ax.plot(kp, profile.pressure_bara, color=SERIES_BLUE, lw=2.0)
            ax.set_ylabel("Pressure [bara]")
            ax.annotate(f"{profile.pressure_bara[-1]:.1f} bara", (kp[-1], profile.pressure_bara[-1]),
                        xytext=(-8, 14), textcoords="offset points", ha="right", fontsize=7, color=INK_MUTED)
        elif panel == "temperature":
            temp = profile.temperature_c
            ax.plot(kp, temp, color=SERIES_BLUE, lw=2.0, label="fluid temperature")
            if profile.hydrate_temperature_c is not None:
                hyd = profile.hydrate_temperature_c
                ax.plot(kp, hyd, color=SERIES_ORANGE, lw=2.0, ls="--", label="hydrate equilibrium T")
                watch_line = [h + min_margin if isfinite(h) else float("nan") for h in hyd]
                ax.fill_between(kp, hyd, watch_line, color=STATUS_COLOURS["watch"], alpha=0.18, lw=0,
                                label=f"{min_margin:g} C margin band")
                inside = [t <= h if isfinite(h) else False for t, h in zip(temp, hyd)]
                if any(inside):
                    ax.fill_between(kp, temp, hyd, where=inside, interpolate=True,
                                    color=STATUS_COLOURS["high"], alpha=0.30, lw=0, label="subcooled (hydrate region)")
            ax.set_ylabel("Temperature [C]")
            ax.legend(fontsize=7, loc="upper right", framealpha=0.9)
        elif panel == "margin":
            statuses = [margin_status(m, min_margin) for m in margin]  # type: ignore[union-attr]
            ax.axhline(0.0, color=STATUS_COLOURS["high"], lw=1.0, ls=":")
            ax.axhline(min_margin, color=STATUS_COLOURS["watch"], lw=1.0, ls=":")
            _status_segments(ax, kp, margin, statuses)  # type: ignore[arg-type]
            ax.set_ylabel("Hydrate margin [C]")
            if result.min_hydrate_margin_c is not None and result.min_margin_kp_km is not None:
                ax.plot([result.min_margin_kp_km], [result.min_hydrate_margin_c], "o", ms=8,
                        mfc="white", mec=INK, mew=1.5, zorder=5)
                ax.annotate(f"min {result.min_hydrate_margin_c:.1f} C @ KP {result.min_margin_kp_km:.1f}",
                            (result.min_margin_kp_km, result.min_hydrate_margin_c),
                            xytext=(-12, 0), textcoords="offset points", ha="right", va="center", fontsize=7,
                            color=INK, bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.9})
            _status_legend(ax, min_margin, loc="upper right")
    axes[-1].set_xlabel("KP [km]")
    head = title or profile.name
    status = result.margin_warning
    fig.suptitle(f"{head} - hydrate margin: {status}", fontsize=11, color=INK, x=0.01, ha="left")
    fig.text(0.01, 0.005, "Screening illustration; P/T and hydrate T from NeqSim. Not a design document.",
             fontsize=6, color=INK_MUTED)
    if own_figure:
        fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    return fig


def plot_pt_trajectory(
    profile: PipelineProfile,
    *,
    hydrate_curve: Any = None,
    envelope: Mapping[str, Sequence[float]] | None = None,
    min_margin: float = 3.0,
    ax=None,
):
    """Pipeline P-T path over the hydrate curve and (optionally) phase envelope.

    ``hydrate_curve`` is a :class:`~pipeline_profile_plot.neqsim_bridge.HydrateCurve`
    or any object with ``pressure_bara`` and ``temperature_c`` lists.
    ``envelope`` is the mapping returned by ``neqsim_bridge.phase_envelope``.
    """
    plt = _plt()
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 4.5))
    _style(ax)
    if envelope:
        for branch, ls, label in (("dew", "-", "dew point line"), ("bub", "-.", "bubble point line")):
            ts = envelope.get(f"{branch}_temperature_c") or []
            ps = envelope.get(f"{branch}_pressure_bara") or []
            if ts:
                ax.plot(ts, ps, color=INK_MUTED, lw=1.2, ls=ls, label=label)
    if hydrate_curve is not None:
        pts = [(t, p) for t, p in zip(hydrate_curve.temperature_c, hydrate_curve.pressure_bara) if isfinite(t)]
        if pts:
            ts, ps = zip(*pts)
            ax.plot(ts, ps, color=SERIES_ORANGE, lw=2.0, ls="--", label="hydrate curve")
            ax.plot([t + min_margin for t in ts], ps, color=STATUS_COLOURS["watch"], lw=1.0, ls=":",
                    label=f"hydrate curve + {min_margin:g} C")
            ax.fill_betweenx(ps, [min(ts) - 50] * len(ts), ts, color=STATUS_COLOURS["high"], alpha=0.08, lw=0)
    margin = profile.hydrate_margin_c
    statuses = [margin_status(m, min_margin) for m in margin] if margin is not None else ["unknown"] * len(profile.kp_km)
    _status_segments(ax, profile.temperature_c, profile.pressure_bara, statuses, lw=2.6)
    ax.plot(profile.temperature_c[0], profile.pressure_bara[0], "o", ms=8, mfc=SERIES_BLUE, mec="white", zorder=5)
    ax.annotate("inlet", (profile.temperature_c[0], profile.pressure_bara[0]), xytext=(6, 4),
                textcoords="offset points", fontsize=7, color=INK)
    ax.plot(profile.temperature_c[-1], profile.pressure_bara[-1], "s", ms=8, mfc=INK, mec="white", zorder=5)
    ax.annotate("arrival", (profile.temperature_c[-1], profile.pressure_bara[-1]), xytext=(6, -10),
                textcoords="offset points", fontsize=7, color=INK)
    t_all = list(profile.temperature_c)
    p_all = list(profile.pressure_bara)
    ax.set_xlim(min(t_all) - 15, max(t_all) + 15)
    ax.set_ylim(0, max(p_all) * 1.25)
    ax.set_xlabel("Temperature [C]")
    ax.set_ylabel("Pressure [bara]")
    ax.set_title("P-T path along the pipeline", fontsize=10, color=INK, loc="left")
    from matplotlib.lines import Line2D

    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([], [], color=STATUS_COLOURS["ok"], lw=3))
    labels.append("pipeline path (coloured by margin status)")
    ax.legend(handles, labels, fontsize=7, loc="upper left", framealpha=0.9)
    return ax


def plot_planform(profile: PipelineProfile, *, min_margin: float = 3.0, map_builder: Any = None, ax=None):
    """Route on a lon/lat planform, coloured by hydrate-margin status.

    If ``map_builder`` (an ``offshore_field_map.FieldMapBuilder``) is given, its
    static map (fields, Sodir pipelines, facilities, nodes) is drawn first.
    """
    plt = _plt()
    if profile.lon is None or profile.lat is None:
        raise ValueError("profile has no lon/lat; add them with with_coordinates()")
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 5))
    if map_builder is not None:
        map_builder.plot_static(ax=ax, title=False, attribution=False)
    else:
        from math import cos, radians

        mid = sum(profile.lat) / len(profile.lat)
        ax.set_aspect(1.0 / max(0.05, cos(radians(mid))))
        ax.set_xlabel("Longitude [deg E]")
        ax.set_ylabel("Latitude [deg N]")
    _style(ax)
    margin = profile.hydrate_margin_c
    statuses = [margin_status(m, min_margin) for m in margin] if margin is not None else ["unknown"] * len(profile.kp_km)
    _status_segments(ax, profile.lon, profile.lat, statuses, lw=3.4)
    ax.plot(profile.lon[0], profile.lat[0], "o", ms=8, mfc=SERIES_BLUE, mec="white", zorder=7)
    ax.plot(profile.lon[-1], profile.lat[-1], "s", ms=8, mfc=INK, mec="white", zorder=7)
    step = max(1, len(profile.kp_km) // 6)
    for i in range(0, len(profile.kp_km), step):
        ax.annotate(f"KP {profile.kp_km[i]:.0f}", (profile.lon[i], profile.lat[i]), xytext=(4, 4),
                    textcoords="offset points", fontsize=6, color=INK_MUTED)
    if margin is not None:
        _status_legend(ax, min_margin, loc="lower left")
    return ax


def plot_combined(
    profile: PipelineProfile,
    *,
    min_margin: float = 3.0,
    map_builder: Any = None,
    hydrate_curve: Any = None,
    envelope: Mapping[str, Sequence[float]] | None = None,
    title: str | None = None,
):
    """One-page dashboard: planform map + P-T path (left), stacked profile (right).

    The map panel is drawn when the profile has lon/lat or a ``map_builder`` is
    given. Returns the matplotlib ``Figure``.
    """
    plt = _plt()
    result = profile.evaluate(min_margin)
    has_map = profile.lon is not None
    panels = (1 if profile.depth_m is not None else 0) + 2 + (1 if profile.hydrate_margin_c is not None else 0)

    fig = plt.figure(figsize=(14, 8.5))
    outer = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.25], wspace=0.18)
    left = outer[0].subgridspec(2 if has_map else 1, 1, height_ratios=[1.2, 1.0] if has_map else [1.0], hspace=0.3)
    if has_map:
        plot_planform(profile, min_margin=min_margin, map_builder=map_builder, ax=fig.add_subplot(left[0]))
    plot_pt_trajectory(profile, hydrate_curve=hydrate_curve, envelope=envelope, min_margin=min_margin,
                       ax=fig.add_subplot(left[1] if has_map else left[0]))
    right = outer[1].subgridspec(panels, 1, hspace=0.12)
    first = fig.add_subplot(right[0])
    axes = [first] + [fig.add_subplot(right[i], sharex=first) for i in range(1, panels)]
    for ax in axes[:-1]:
        ax.tick_params(labelbottom=False)
    # Reuse the stacked-profile renderer on the supplied axes.
    plot_profile(profile, min_margin=min_margin, result=result, axes=axes, title=title)
    fig.suptitle(
        f"{title or profile.name} - {profile.length_km:.1f} km, arrival {result.arrival_pressure_bara:.1f} bara / "
        f"{result.arrival_temperature_c:.1f} C, hydrate margin: {result.margin_warning}",
        fontsize=12, color=INK, x=0.01, ha="left",
    )
    sources = "; ".join(map_builder.attributions()) if map_builder is not None else ""
    footer = "Screening illustration; P/T and hydrate T from NeqSim. Not a design document."
    fig.texts = [t for t in fig.texts if not t.get_text().startswith("Screening illustration")]
    fig.text(0.01, 0.005, footer + (f"  Sources: {sources}" if sources else ""), fontsize=6, color=INK_MUTED)
    fig.subplots_adjust(left=0.05, right=0.98, top=0.93, bottom=0.07)
    return fig


def save_figure(fig, path: str, dpi: int = 160) -> str:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    return path
