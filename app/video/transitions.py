"""Whole-frame intro/outro fades, after all overlays have been composed."""
def fade_filter(duration, settings):
    intro = min(settings.intro_fade_seconds, duration / 2)
    outro = min(settings.outro_fade_seconds, duration / 2)
    filters = []
    if intro:
        filters.append(f'fade=t=in:st=0:d={intro}')
    if outro:
        start = max(0, duration - outro - 1 / settings.video_fps)
        filters.append(f'fade=t=out:st={start:.6f}:d={outro}')
    return ','.join(filters)
