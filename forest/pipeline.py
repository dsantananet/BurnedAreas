"""Read-only GEE products: national NDVI/NDMI and queued perimeter severity.

No credentials are written to products. Raster calculations stay in Earth Engine.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path

SOURCE = 'COPERNICUS/S2_SR_HARMONIZED'
VERSION = 'forest-v1-scl-20m-20261025'
CLASSES = [
    ('Aumento de verdura', None, -0.1, '#259b80'),
    ('Sem alteração / não ardido', -0.1, 0.1, '#c9d5c7'),
    ('Baixa', 0.1, 0.27, '#eddc80'),
    ('Moderada-baixa', 0.27, 0.44, '#e6aa58'),
    ('Moderada-alta', 0.44, 0.66, '#d96e39'),
    ('Alta', 0.66, None, '#9f3544'),
]
REGIONS = {
    'continente': [-9.6, 36.8, -6.0, 42.3],
    'madeira': [-17.5, 32.2, -16.1, 33.3],
    'acores': [-31.5, 36.5, -24.5, 40.0],
}


def severity_class(value):
    if value is None or not math.isfinite(value):
        return None
    for i, (_, lo, hi, _) in enumerate(CLASSES):
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return i


def windows(burn_date, as_of):
    burn = date.fromisoformat(burn_date)
    end = min(burn + timedelta(days=46), as_of)
    return {'pre_start': (burn-timedelta(days=45)).isoformat(),
            'pre_end_exclusive': (burn-timedelta(days=5)).isoformat(),
            'post_start': (burn+timedelta(days=1)).isoformat(),
            'post_end_exclusive': end.isoformat()}


def stable_id(feature):
    raw = json.dumps({'geometry': feature['geometry'], 'burn_date': feature['properties']['burn_date']}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def authenticate():
    import ee
    raw = os.environ['GEE_SERVICE_ACCOUNT_KEY']
    key = json.loads(raw)
    creds = ee.ServiceAccountCredentials(key['client_email'], key_data=raw)
    # Match the existing working BurnedAreas authentication. The key's owning
    # project need not be the Earth Engine quota project authorized for this account.
    options = {'project': os.environ['GEE_PROJECT']} if os.environ.get('GEE_PROJECT') else {}
    ee.Initialize(creds, **options)
    ee.data.setDeadline(180000)
    return ee


def clear_s2(image):
    # SCL excludes no-data, saturated, cloud shadow, unclassified, cloud, cirrus, snow and water.
    # Dark pixels (2) are retained to avoid systematically excluding dark burned surfaces.
    scl = image.select('SCL')
    mask = scl.eq(2).Or(scl.eq(4)).Or(scl.eq(5))
    return image.select(['B4', 'B8', 'B11', 'B12']).multiply(0.0001).updateMask(mask).copyProperties(image, ['system:time_start'])


def ratio(image, a, b, name):
    x, y = image.select(a), image.select(b)
    den = x.add(y)
    return x.subtract(y).divide(den).updateMask(den.neq(0)).rename(name)


def composite(ee, geometry, start, end):
    col = ee.ImageCollection(SOURCE).filterBounds(geometry).filterDate(start, end)
    info = ee.Dictionary({'count': col.size(), 'first': col.aggregate_min('system:time_start'),
                          'last': col.aggregate_max('system:time_start')}).getInfo()
    if not info['count']:
        return None, info
    return col.map(clear_s2).median().clip(geometry), info


def download_png(image, geometry, path, vis):
    import requests
    url = image.getThumbURL({**vis, 'region': geometry, 'dimensions': 1000, 'format': 'png', 'crs': 'EPSG:4326'})
    result = requests.get(url, timeout=180)
    result.raise_for_status()
    if not result.content.startswith(b'\x89PNG'):
        raise ValueError('GEE did not return a PNG')
    path.write_bytes(result.content)


def plot_bars(values, labels, colors, path, title, unit):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(labels, values, color=colors)
    ax.set_xlabel(unit)
    ax.set_title(title, loc='left', fontweight='bold')
    ax.spines[['top', 'right']].set_visible(False)
    ax.invert_yaxis()
    ax.set_xlim(left=0)
    for i, value in enumerate(values):
        ax.text(value, i, f' {value:,.1f}', va='center')
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(fig)


def national(ee, as_of, output):
    country = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017').filter(ee.Filter.eq('country_na', 'Portugal')).geometry()
    report = {'source': SOURCE, 'boundary': 'Continente: USDOS/LSIB_SIMPLE/2017; ilhas: USDOS/LSIB/2017 detalhado, recortado por região oceânica',
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'requested_end_exclusive': as_of.isoformat(), 'scale_m': 250, 'crs': 'EPSG:3035',
              'regions': [], 'status': 'processed', 'interpretation':
              'NDVI descreve verdura relativa; NDMI é um índice espectral de humidade, não humidade medida do combustível. '
              'Médias sobre píxeis válidos em grelha de 250 m; sem inferir áreas sem observação. '
              'Janelas de 30 dias; a diferença para a janela anterior não é anomalia sazonal.'}
    for name, bounds in REGIONS.items():
        print('National region: '+name, flush=True)
        box = ee.Geometry.Rectangle(bounds, geodesic=False)
        land = country if name=='continente' else ee.FeatureCollection('USDOS/LSIB/2017').filterBounds(box).geometry()
        region = land.intersection(box, 100)
        if region.area(100).getInfo() < 1:
            report['regions'].append({'id': name, 'status': 'boundary_missing'})
            continue
        start, end = as_of-timedelta(days=30), as_of
        image, scenes = composite(ee, region, start.isoformat(), end.isoformat())
        row = {'id': name, 'period_start': start.isoformat(), 'period_end_exclusive': end.isoformat(), 'scenes': scenes,
               'status': 'processed', 'indices': {}}
        if image is None:
            row['status'] = 'no_images'
            report['regions'].append(row)
            continue
        prev, prev_scenes = composite(ee, region, (start-timedelta(days=30)).isoformat(), start.isoformat())
        row['previous_scenes'] = prev_scenes
        for index, band in [('ndvi', 'B4'), ('ndmi', 'B11')]:
            layer = ratio(image, 'B8', band, index)
            area = ee.Image.pixelArea().rename('area')
            valid = layer.mask()
            area_stats = area.addBands(area.updateMask(valid).rename('valid')).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=region, scale=250, crs='EPSG:3035', maxPixels=1e8, tileScale=4).getInfo()
            reducer = ee.Reducer.mean().combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True)
            stats = layer.reduceRegion(reducer=reducer, geometry=region, scale=250, crs='EPSG:3035', maxPixels=1e8, tileScale=4).getInfo()
            valid_area = area_stats.get('valid') or 0
            product = {'statistics': stats, 'valid_area_ha': valid_area/10000,
                       'valid_fraction': valid_area/area_stats['area'] if area_stats.get('area') else None,
                       'map': None, 'change': None, 'unit': 'índice adimensional'}
            if valid_area > 0:
                filename = f'{index}-{name}.png'
                download_png(layer, region, output/filename, {'min': -1, 'max': 1, 'palette': ['9f582a', 'e9dfbe', 'd8ead2', '187e66'] if index=='ndvi' else ['a45d2b', 'e8d6ac', 'cee3e1', '276ca3']})
                product['map'] = filename
                if prev is not None:
                    # Changes are computed on the same pixels, not a difference of different-coverage means.
                    delta = layer.subtract(ratio(prev, 'B8', band, index)).rename('delta')
                    product['change'] = delta.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True), geometry=region, scale=250, crs='EPSG:3035', maxPixels=1e8, tileScale=4).getInfo()
            row['indices'][index] = product
        report['regions'].append(row)
    if not any(r.get('indices') for r in report['regions']):
        report['status'] = 'no_images'
    save_json(output/'national.json', report)
    return report


def discover_events(ee, as_of, existing):
    """Add MODIS polygons, retaining every queued/past event in the durable ledger."""
    region = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017').filter(ee.Filter.eq('country_na', 'Portugal')).geometry()
    start = date(as_of.year, 1, 1)
    col = ee.ImageCollection('MODIS/061/MCD64A1').filterBounds(region).filterDate(start.isoformat(), as_of.isoformat())
    count = col.size().getInfo()
    if not count:
        return existing, {'status': 'no_source_images', 'year': as_of.year}
    def burn(im):
        b = im.select('BurnDate')
        return b.updateMask(im.select('QA').bitwiseAnd(3).eq(3).And(b.gt(0)))
    layer = col.map(burn).min().rename('burn_doy').toInt16()
    projection = ee.Image(col.first()).select('BurnDate').projection()
    fc = layer.reduceToVectors(geometry=region, crs=projection, scale=projection.nominalScale(), labelProperty='burn_doy', geometryType='polygon', eightConnected=False, maxPixels=1e8)
    features = fc.getInfo()['features']
    for old in existing.values():
        if old.get('source')=='MODIS/061/MCD64A1':
            old['active'] = False
    added = 0
    for f in features:
        f['properties']['burn_date'] = (start+timedelta(days=int(f['properties']['burn_doy'])-1)).isoformat()
        key = stable_id(f)
        if key not in existing:
            existing[key] = {'id': key, 'feature': f, 'source': 'MODIS/061/MCD64A1', 'source_scale_m': 500,
                             'status': 'queued', 'note': 'Polígono de classificação satélite, não ocorrência nem perímetro oficial.'}
            added += 1
        existing[key]['active'] = True
    latest = col.aggregate_max('system:time_start').getInfo()
    return existing, {'status': 'processed', 'year': as_of.year, 'source_image_count': count, 'source_polygons': len(features), 'new_events': added,
                      'latest_source_month': datetime.fromtimestamp(latest/1000, timezone.utc).date().isoformat() if latest else None,
                      'note': 'Produto mensal com atraso; polígonos supersedidos são preservados mas excluídos da fila ativa.'}


def process_event(ee, event, as_of, output):
    geometry = ee.Geometry(event['feature']['geometry'])
    dates = windows(event['feature']['properties']['burn_date'], as_of)
    event.update(windows=dates, method=VERSION)
    if dates['post_start'] >= dates['post_end_exclusive']:
        event['status'] = 'awaiting_postfire'
        return event
    pre, pre_info = composite(ee, geometry, dates['pre_start'], dates['pre_end_exclusive'])
    post, post_info = composite(ee, geometry, dates['post_start'], dates['post_end_exclusive'])
    event.update(pre_scenes=pre_info, post_scenes=post_info)
    if pre is None or post is None:
        event['status'] = 'awaiting_images'
        return event
    dnbr = ratio(pre, 'B8', 'B12', 'nbr').subtract(ratio(post, 'B8', 'B12', 'nbr')).rename('dnbr')
    projection = post.select('B12').projection()
    area = ee.Image.pixelArea().divide(10000)
    layers = area.rename('total').addBands(area.updateMask(dnbr.mask()).rename('valid'))
    for i, (_, lo, hi, _) in enumerate(CLASSES):
        mask = dnbr.mask()
        if lo is not None:
            mask = mask.And(dnbr.gte(lo))
        if hi is not None:
            mask = mask.And(dnbr.lt(hi))
        layers = layers.addBands(area.updateMask(mask).rename(f'class_{i}'))
    stats = layers.reduceRegion(reducer=ee.Reducer.sum(), geometry=geometry, scale=20, crs='EPSG:3035', maxPixels=1e8, tileScale=4).getInfo()
    valid = stats.get('valid') or 0
    total = stats.get('total') or 0
    event.update(area_ha=total, valid_ha=valid, valid_fraction=valid/total if total else 0,
                 missing_ha=max(0, total-valid), scale_m=20,
                 classes=[{'name': label, 'min_inclusive': lo, 'max_exclusive': hi, 'area_ha': stats.get(f'class_{i}') or 0, 'color': color} for i, (label, lo, hi, color) in enumerate(CLASSES)])
    if valid <= 0:
        event['status'] = 'awaiting_clear_pixels'
        return event
    event['dnbr_stats'] = dnbr.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True), geometry=geometry, scale=20, crs='EPSG:3035', maxPixels=1e8, tileScale=4).getInfo()
    class_image = dnbr.multiply(0).toInt8()
    for cutoff in [-0.1, 0.1, 0.27, 0.44, 0.66]:
        class_image = class_image.add(dnbr.gte(cutoff))
    key = event['id']
    download_png(class_image, geometry.bounds(), output/f'severity-{key}.png', {'min': 0, 'max': 5, 'palette': [c[3] for c in CLASSES]})
    plot_bars([c['area_ha'] for c in event['classes']]+[event['missing_ha']], [c['name'] for c in event['classes']]+['Sem dados'], [c['color'] for c in event['classes']]+['#808080'], output/f'classes-{key}.png', 'Severidade espectral por classe · área analisada', 'Área (ha)')
    event.update(status='processed' if valid/total >= .8 else 'partial', map=f'severity-{key}.png', chart=f'classes-{key}.png',
                 description=f"Área {total:.1f} ha; {valid/total*100:.1f}% com pares de observações válidos. dNBR médio {event['dnbr_stats'].get('dnbr_mean', 0):.3f}. Classes exploratórias, sem calibração de campo em Portugal.")
    return event


def run(args):
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    try:
        ee = authenticate()
    except Exception as exc:
        save_json(output/'forest-status.json', {'generated_at': datetime.now(timezone.utc).isoformat(), 'as_of': as_of.isoformat(),
                  'status': 'authentication_failed', 'error_type': type(exc).__name__, 'method': VERSION})
        raise SystemExit('Earth Engine authentication failed; product state preserved') from None
    old = output/'events.json'
    events = json.loads(old.read_text(encoding='utf-8')) if old.exists() else {}
    if args.events:
        for feature in json.loads(Path(args.events).read_text(encoding='utf-8'))['features']:
            key = stable_id(feature)
            events.setdefault(key, {'id': key, 'feature': feature, 'source': 'supplied_perimeter', 'status': 'queued'})
    # Each independent product can fail while preserving previous products and its error state.
    errors = []
    national_report, discovery = {}, {}
    if args.mode!='severity':
        try:
            national_report = national(ee, as_of, output)
        except Exception as exc:
            national_report = {'status': 'failed', 'error_type': type(exc).__name__}
            errors.append('national')
        try:
            events, discovery = discover_events(ee, as_of, events)
        except Exception as exc:
            discovery = {'status': 'failed', 'error_type': type(exc).__name__}
            errors.append('discovery')
    processed = 0
    # Oldest waiting events first. Finalized products are only rerun if the method changes.
    queue = sorted(events.values(), key=lambda e: (e.get('last_attempt', ''), -date.fromisoformat(e['feature']['properties']['burn_date']).toordinal(), e['id']))
    for event in queue:
        if event.get('active') is False or int(event['id'][:8],16)%args.shards!=args.shard:
            continue
        burn = date.fromisoformat(event['feature']['properties']['burn_date'])
        final_age = 46 if event.get('status')=='processed' else 90
        finalized = event.get('status') in ('processed','partial') and event.get('method')==VERSION and as_of>=burn+timedelta(days=final_age)
        if finalized or processed>=args.max_events or args.mode=='prepare':
            continue
        event['last_attempt'] = datetime.now(timezone.utc).isoformat()
        try:
            process_event(ee, event, as_of, output)
        except Exception as exc:
            event.update(status='retry_pending', error_type=type(exc).__name__)
            errors.append('event:'+event['id'])
        processed += 1
        print('Severity '+event['id']+': '+event['status'], flush=True)
        save_json(output/'events.json', events)
    save_json(output/'events.json', events)
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'as_of': as_of.isoformat(), 'method': VERSION,
              'national': national_report, 'discovery': discovery, 'events_count': len(events),
              'events_attempted': processed, 'queue_remaining': sum(e.get('status')!='processed' for e in events.values()),
              'errors': errors, 'status': 'partial_failure' if errors else 'processed', 'shard': args.shard, 'shards': args.shards,
              'severity_note': 'dNBR pré menos pós; classes exploratórias, não validadas no terreno. Alteração espectral não é intensidade de fogo.',
              'sources': ['https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED',
                          'https://burnseverity.cr.usgs.gov/glossary']}
    save_json(output/'forest-status.json', report)
    print(json.dumps({k: report[k] for k in ['status', 'events_count', 'events_attempted', 'queue_remaining', 'errors']}))
    if errors:
        raise SystemExit(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of')
    parser.add_argument('--output', default='forest-products')
    parser.add_argument('--events', help='GeoJSON Polygon/MultiPolygon features with properties.burn_date (ISO date)')
    parser.add_argument('--max-events', type=int, default=15)
    parser.add_argument('--mode', choices=['all','prepare','severity'], default='all')
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--shards', type=int, default=1)
    run(parser.parse_args())
