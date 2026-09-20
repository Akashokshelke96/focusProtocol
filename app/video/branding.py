"""Reusable Camping With Blues artwork, editorial session names and subtle effects."""
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.youtube.state import write_json, publishing_lock

CHANNEL = 'Camping With Blues'


def loop_branding(directory, settings, metadata):
    """Draw the two static text marks once without editing any source artwork."""
    w, h = settings.video_width, settings.video_height
    image = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    regions = []
    scale = h / 1080
    margin = max(8, round(25 * scale))
    for position, maximum, size, alpha in [('top_right', 310, 30, 235), ('bottom_right', 190, 19, 160)]:
        face = font(round(size * scale))
        while draw.textlength(CHANNEL, font=face) > maximum * scale and face.size > 8:
            face = font(face.size-1)
        left, top, right, bottom = draw.textbbox((0,0), CHANNEL, font=face, stroke_width=1)
        text_w, text_h = right-left, bottom-top
        cap = draw.textbbox((0, 0), 'H', font=face)
        icon_h = cap[3] - cap[1] if position == 'top_right' else 0
        icon_w = round(icon_h * 1.45)
        gap = max(3, round(8 * scale)) if icon_h else 0
        total_w = text_w + icon_w + gap
        x, y = w-total_w-margin, margin if position == 'top_right' else h-text_h-margin
        text_x = x + icon_w + gap
        draw.text((text_x-left,y-top), CHANNEL, font=face, fill=(245,237,223,alpha),
                  stroke_width=1, stroke_fill=(20,17,13,alpha))
        region = dict(position=position, bounds=[x,y,total_w,text_h], text=CHANNEL,
                      text_bounds=[text_x,y,text_w,text_h])
        if icon_h:
            iy = y - top + cap[1]
            draw.rounded_rectangle((x, iy, x+icon_w-1, iy+icon_h-1), radius=max(2, icon_h//4), fill=(255,0,0,255))
            draw.polygon([(x+icon_w*.4,iy+icon_h*.23), (x+icon_w*.4,iy+icon_h*.77),
                          (x+icon_w*.73,iy+icon_h*.5)], fill=(255,255,255,255))
            region['icon_bounds'] = [x,iy,icon_w,icon_h]
        regions.append(region)
    output = Path(directory) / 'output' / 'loop_branding.png'
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    metadata.update(channel_brand_name=CHANNEL, channel_branding_enabled=True,
                    watermark_enabled=True, branding_regions=regions,
                    branding_overlay_path=str(output), branding_source='existing_typography')
    return output


def font(size, script=False, bold=False):
    names = ['SCRIPTBL.TTF', 'georgiai.ttf'] if script else (['BOD_B.TTF', 'georgiab.ttf'] if bold else ['georgia.ttf'])
    for name in names:
        path = Path('C:/Windows/Fonts') / name
        if path.exists():
            return ImageFont.truetype(str(path), max(8, round(size)))
    return ImageFont.truetype('DejaVuSerif.ttf', max(8, round(size)))


def session_metadata(llm, job_id, minutes, concept=''):
    """Names are editorial chapters, never invented source-track attribution."""
    import json
    state_path = Path('jobs/branding_titles.json')
    with publishing_lock(Path('jobs/branding_titles')):
        used = json.loads(state_path.read_text('utf-8')) if state_path.exists() else []
        source, error = 'llm', None
        try:
            response = llm._generate_with_retry(
                f'Create exactly 12 original short evocative blues session titles for {CHANNEL}. '
                f'Concept: {concept}. Unique session: {job_id}. Use 2-5 words per title, at most 32 characters. '
                'Themes: midnight bourbon, lost love, rain, last calls, soulful guitar. '
                'Return only JSON {"titles": [strings]}. Do not copy artists or existing songs. '
                f'Avoid these previously used titles: {used[-240:]}', max_retries=1)
            titles = llm._extract_json(response)['titles']
            if len(titles) != 12 or any(not isinstance(t, str) or not 3 <= len(t) <= 32 or '\n' in t for t in titles):
                raise ValueError('Expected 12 short single-line titles')
            if len({t.casefold() for t in titles}) != 12 or {t.casefold() for t in titles} & {t.casefold() for t in used}:
                raise ValueError('Repeated session names')
        except Exception as exc:
            source, error = 'local_fallback', str(exc)
            choices = [f'{a} {b}' for a in ['Velvet', 'Bourbon', 'Midnight', 'Faded', 'Amber', 'Rainy', 'Lonesome', 'Smoky', 'Broken', 'Silver', 'Last', 'Quiet', 'Forgotten', 'Blue', 'Autumn', 'Neon', 'Empty', 'Tender', 'Distant', 'Restless'] for b in ['Confession', 'Goodbye', 'Memories', 'Promises', 'Window', 'Embers', 'Letters', 'Heart', 'Road', 'Reverie', 'Whispers', 'Rain', 'Moon', 'Lullaby', 'Shadows', 'Dreams', 'Prayer', 'Echoes', 'Waltz', 'Hour']]
            choices = [t for t in choices if t.casefold() not in {u.casefold() for u in used}]
            if len(choices) < 12:
                raise ValueError('Session name library exhausted; restore the LLM connection') from exc
            titles = random.SystemRandom().sample(choices, 12)
        write_json(state_path, used + titles)
    chapters = [{'start_seconds': round(i * minutes * 60 / 12), 'title': t} for i, t in enumerate(titles)]
    def timestamp(seconds):
        return f'{seconds//3600:02}:{seconds%3600//60:02}:{seconds%60:02}'
    description = (f'{titles[0]} — {minutes:g} minutes of late-night blues.\n\n'
        f'Welcome to {CHANNEL}. Dim the lights and settle into warm guitar tones, smoky lounge atmosphere and a little room to breathe. '
        'A slow soundtrack for quiet evenings, reading, reflection and winding down after a long day.\n\n'
        'SESSION CHAPTERS\n' + '\n'.join(f"{timestamp(c['start_seconds'])} {c['title']}" for c in chapters) +
        '\n\nThese are original editorial chapter names for a continuous mix; music may repeat at most twice per source track. They are not source song titles.\n\n'
        'PERFECT FOR\n• Late-night relaxation\n• Rainy evenings and quiet reflection\n• Reading and background listening\n\n'
        f'ABOUT {CHANNEL.upper()}\nA home for slow blues, warm late-night moods and unhurried listening. '
        'If this session belongs in your evening, like the video, subscribe and share it with someone who loves the blues.\n\n'
        '#CampingWithBlues #SlowBlues #WhiskeyBlues #LateNightBlues #BluesMusic')
    return dict(session_titles=titles, session_chapters=chapters, session_title_source=source, session_title_error=error,
                youtube_title=f'{titles[0]} | Midnight Whiskey Blues & Slow Guitar'[:100], youtube_description=description,
                youtube_tags=['Camping With Blues', 'whiskey blues', 'slow blues', 'late night blues', 'blues guitar', 'relaxing blues', 'blues mix'], thumbnail_text=titles[0])


def brand_image(path, settings, metadata):
    """Composite typography once; the one source background remains static."""
    image = Image.open(path).convert('RGBA')
    w, h = image.size
    overlay = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(overlay)
    cream, gold = '#F5EDDF', '#D7B677'
    small = font(w * .011)
    name = settings.channel_brand_name
    text_w = d.textlength(name, font=small)
    x, y = w - text_w - w*.035, h*.04
    d.rounded_rectangle((x-w*.03, y, x-w*.007, y+h*.025), radius=h*.006, fill='#CF2929')
    d.polygon([(x-w*.022, y+h*.006), (x-w*.022, y+h*.019), (x-w*.013, y+h*.0125)], fill='white')
    d.text((x,y), name, font=small, fill=cream, stroke_width=1, stroke_fill='#15110D')
    if settings.song_panel_enabled:
        for px in range(round(w*.46)):
            d.line((px, 0, px, h), fill=(0,0,0,round(180*(1-px/(w*.46)))))
        x = w*.045
        d.text((x,h*.075), 'Camping', font=font(w*.057, script=True), fill=gold)
        d.text((x,h*.20), 'WITH BLUES', font=font(w*.025,bold=True), fill=cream)
        d.line((x,h*.273,w*.31,h*.273),fill=gold,width=max(1,round(w*.001)))
        face = font(w*.0125)
        while max(d.textlength(t,font=face) for t in metadata['session_titles']) > w*.285 and face.size > 8:
            face=font(face.size-1)
        for i, title in enumerate(metadata['session_titles']):
            d.text((x,h*(.31+i*.029)),f'{i+1:02}',font=font(w*.009),fill=gold)
            d.text((x+w*.024,h*(.306+i*.029)),title,font=face,fill=cream)
    Image.alpha_composite(image,overlay).convert('RGB').save(path)
    metadata.update(channel_brand_name=name, channel_branding_enabled=True, song_panel_enabled=settings.song_panel_enabled)


def effect_filter(mode, opacity, fps=15):
    """Background-only grades; dashboard 0.06/0.12/0.20 map to 30/60/100%.

    Color mixes are convex and RGB curves stay inside their input range.
    Grain reserves headroom before adding bounded uniform noise. The final
    intensity-scaled inset protects shadows/highlights without hard clipping.
    None/zero deliberately return before any format conversion or processing.
    """
    if mode == 'none' or opacity <= 0:
        return ''
    modes = {'sepia', 'noir', 'warm_film', 'cool_cinematic', 'faded_film',
             'vintage', 'film_grain', 'soft_vignette', 'old_film'}
    if mode not in modes:
        raise ValueError(f'Unknown visual effect: {mode}')
    amount = min(1.5, max(0.0, float(opacity) / .20))
    # Values above dashboard Strong continue to increase without unsafe extrapolation.
    amount = amount if amount <= 1 else 1 + (amount - 1) * .2
    filters = ['format=gbrp']

    def desaturate(weight):
        weight = min(1., weight)
        luma = (.2126, .7152, .0722)
        names = (('rr','rg','rb'), ('gr','gg','gb'), ('br','bg','bb'))
        return 'colorchannelmixer=' + ':'.join(
            f'{names[i][j]}={(1-weight)*(i==j)+weight*luma[j]:.8f}'
            for i in range(3) for j in range(3))

    if mode == 'sepia':
        matrix = ((.393,.769,.189),(.349,.686,.168),(.272,.534,.131))
        names = (('rr','rg','rb'), ('gr','gg','gb'), ('br','bg','bb'))
        weight = min(1., amount)
        filters.append('colorchannelmixer=' + ':'.join(
            f'{names[i][j]}={(1-weight)*(i==j)+weight*matrix[i][j]/sum(matrix[i])*(1,.90,.72)[i]:.8f}'
            for i in range(3) for j in range(3)))
    elif mode == 'noir':
        filters.append(desaturate(amount))
    elif mode in ('warm_film', 'cool_cinematic', 'vintage', 'old_film'):
        if mode in ('vintage', 'old_film'):
            filters.append(desaturate(amount * (.45 if mode == 'vintage' else .65)))
        warmth = amount * (.18 if mode in ('warm_film', 'cool_cinematic') else .13)
        if mode == 'cool_cinematic':
            filters.append(f"lutrgb=r='val*(1-{warmth})':b='val+(255-val)*{warmth}'")
        else:
            filters.append(f"lutrgb=r='val+(255-val)*{warmth}':b='val*(1-{warmth})'")
    elif mode == 'faded_film':
        filters.append(desaturate(.4 * amount))
        filters.append(f"lutrgb=r='{35*amount}+val*{1-.3*amount}':"
                       f"g='{35*amount}+val*{1-.3*amount}':b='{35*amount}+val*{1-.3*amount}'")
    if mode in ('film_grain', 'old_film'):
        # A perceptual fifth-root curve keeps even Subtle grain above the
        # existing encoder's quantization floor, rather than freezing after I-frames.
        strength = round(32 * amount ** .2)
        # FFmpeg uniform noise spans approximately +/- strength/2 in 8-bit RGB.
        headroom = 2 + .55 * strength
        filters.append(f"lutrgb=r='{headroom}+val*{1-2*headroom/255}':"
                       f"g='{headroom}+val*{1-2*headroom/255}':b='{headroom}+val*{1-2*headroom/255}'")
        # Loop a bounded, independent grayscale grain layer forward/backward.
        # Matching first/last grain states prevent an I-frame reset from exposing
        # a texture jump after packet-copy looping. Background motion is untouched.
        half = 3 * fps
        filters.append(
            f"split[fx_base][fx_seed];[fx_seed]format=gray,lutyuv=y=128,"
            f"noise=alls={strength}:allf=t+u:all_seed=1729,trim=end_frame={half},"
            "setpts=PTS-STARTPTS,split[fx_forward][fx_reverse];"
            "[fx_reverse]reverse,setpts=PTS-STARTPTS[fx_backward];"
            "[fx_forward][fx_backward]concat=n=2:v=1:a=0,"
            f"loop=loop=-1:size={2*half}:start=0,setpts=N/({fps}*TB),format=gbrp[fx_noise];"
            "[fx_base][fx_noise]blend=all_mode=grainmerge:shortest=1")
    if mode in ('soft_vignette', 'old_film'):
        filters.append(f'vignette=angle={amount * (.85 if mode == "soft_vignette" else .48)}:eval=init')
    inset = 10 * amount
    filters.append(f"lutrgb=r='{inset}+val*{1-2*inset/255}':"
                   f"g='{inset}+val*{1-2*inset/255}':b='{inset}+val*{1-2*inset/255}'")
    return ',' + ','.join(filters)
