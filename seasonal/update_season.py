"""Monthly burned-area product, May-Oct; daily refresh into isolated PostGIS DB.

MODIS 500m classifications are kept separate from Sentinel-2 dNBR candidates.
Credentials come only from environment/private mounted files.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import uuid

if sys.platform == 'win32':
    import truststore
    truststore.inject_into_ssl()
import ee
import psycopg
from psycopg.types.json import Jsonb
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union
from shapely import make_valid
from shapely.prepared import prep

SOURCE = 'MODIS/061/MCD64A1'
BOUNDARIES = 'USDOS/LSIB_SIMPLE/2017'
ROOT = Path(__file__).resolve().parent


def season_dates(year, today=None):
    today = today or datetime.now(timezone.utc).date()
    start, end = date(year, 5, 1), min(date(year, 11, 1), today)
    if end <= start:
        raise ValueError('A época maio-outubro ainda não começou para este ano.')
    return start, end


def authenticate():
    path = os.environ.get('GEE_KEY_FILE')
    raw = Path(path).read_text(encoding='utf-8') if path else os.environ['GEE_SERVICE_ACCOUNT_KEY']
    key = json.loads(raw)
    creds = ee.ServiceAccountCredentials(key['client_email'], key_data=raw)
    options = {'project': os.environ['GEE_PROJECT']} if os.environ.get('GEE_PROJECT') else {}
    ee.Initialize(creds, **options)
    ee.data.setDeadline(180000)


def regions():
    countries = ee.FeatureCollection(BOUNDARIES)
    extent = ee.Geometry.Rectangle([-25, 34, 60, 72], geodesic=False)
    europe_countries = countries.filter(ee.Filter.eq('wld_rgn', 'Europe'))
    # Include transcontinental states explicitly, then clip to documented extent.
    trans = countries.filter(ee.Filter.inList('country_na', ['Russia', 'Turkey', 'Cyprus']))
    data = europe_countries.merge(trans).getInfo()['features']
    europe = unary_union([make_valid(shape(f['geometry'])) for f in data]).intersection(box(-25,34,60,72))
    portugal = unary_union([make_valid(shape(f['geometry'])) for f in data if f['properties']['country_na']=='Portugal']).intersection(box(-9.6,36.8,-6.0,42.3))
    return {'europa': europe, 'portugal_continental': portugal}, sorted({f['properties']['country_na'] for f in data})


def extract(year, start, end, output):
    roi, country_names = regions()
    collection = ee.ImageCollection(SOURCE).filterDate(start.isoformat(), end.isoformat())
    logging.info('Consultar disponibilidade MODIS para %s a %s', start, end)
    info = ee.Dictionary({
        'months_ms': collection.aggregate_array('system:time_start'),
        'asset_ids': collection.aggregate_array('system:index'),
    }).getInfo()
    months = sorted({datetime.fromtimestamp(ms/1000, timezone.utc).date().isoformat() for ms in info['months_ms']})
    metadata = {
        'source': SOURCE, 'nominal_resolution_m': 500,
        'requested_start': start.isoformat(), 'requested_end_exclusive': end.isoformat(),
        'available_months': months, 'asset_ids': info['asset_ids'],
        'latest_source_month': months[-1] if months else None,
        'region_definition': 'LSIB Europe + Russia/Turkey/Cyprus; clipped [-25,34,60,72]; Portugal mainland',
        'lsib_europe_countries': country_names,
        'quality_filter': 'QA land=1 and valid=1; BurnDate within requested dates',
        'deduplication': 'earliest burn day per pixel across monthly products',
        'validation': 'satellite classification; not official fire perimeters',
    }
    output.mkdir(parents=True, exist_ok=True)
    (output/'availability.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    logging.info('Meses disponíveis: %s', months)
    if not months:
        return metadata, {}, []
    start_doy = (start-date(year,1,1)).days+1
    end_doy = (end-date(year,1,1)).days+1

    def valid_burn(image):
        burn = image.select('BurnDate')
        valid = image.select('QA').bitwiseAnd(3).eq(3)
        return burn.updateMask(valid.And(burn.gte(start_doy)).And(burn.lt(end_doy)))

    burn = collection.map(valid_burn).min().rename('burn_doy').toInt16()
    # Preserve the MODIS sinusoidal grid; 500m is nominal, native grid ~463.3m.
    projection = ee.Image(collection.first()).select('BurnDate').projection()
    scale = projection.nominalScale()
    pixel_area = ee.Image.pixelArea().divide(10000).rename('area_ha')
    cells = []
    for x in range(-25,60,5):
        for y in range(34,72,5):
            bounds = [x,y,min(x+5,60),min(y+5,72)]
            if roi['europa'].intersects(box(*bounds)):
                cells.append({'tile':f'{x}_{y}','bounds':bounds})
    occupied = sorted(cells,key=lambda f: abs(f['bounds'][0]+10)+abs(f['bounds'][1]-39))
    logging.info('Blocos a verificar: %d',len(occupied))
    prepared = prep(roi['europa'])
    features = []
    for i, cell in enumerate(occupied):
        tile = ee.Geometry.Rectangle(cell['bounds'],geodesic=False)
        vectors = burn.addBands(pixel_area).reduceToVectors(
            geometry=tile,crs=projection,scale=scale,geometryType='polygon',
            eightConnected=False,labelProperty='burn_doy',reducer=ee.Reducer.sum(),
            maxPixels=1e8,tileScale=4,geometryInNativeProjection=False,
        ).map(lambda f: ee.Feature(f).setGeometry(ee.Feature(f).geometry().intersection(tile,1)))
        tile_features, token = [], None
        while True:
            request = {'expression':vectors,'pageSize':1000}
            if token:
                request['pageToken'] = token
            page = ee.data.computeFeatures(request)
            tile_features.extend(page.get('features',[]))
            token = page.get('nextPageToken')
            if not token:
                break
        clipped = []
        for feature in tile_features:
            geom = make_valid(shape(feature['geometry']))
            if not prepared.intersects(geom):
                continue
            if not prepared.covers(geom):
                geom = geom.intersection(roi['europa'])
            if geom.is_empty or geom.area == 0:
                continue
            if geom.geom_type == 'GeometryCollection':
                geom = unary_union([g for g in geom.geoms if g.geom_type in ('Polygon','MultiPolygon')])
            if geom.is_empty:
                continue
            feature['geometry'] = mapping(geom)
            clipped.append(feature)
        features.extend(clipped)
        (output/f"tile_{cell['tile']}.geojson").write_text(
            json.dumps({'type':'FeatureCollection','features':clipped}),encoding='utf-8')
        logging.info('Bloco %d/%d %s: %d polígonos; acumulado=%d',i+1,len(occupied),cell['tile'],len(clipped),len(features))
    metadata['tile_count'] = len(occupied)
    metadata['polygon_note'] = 'polygons fragmented at 5-degree processing grid; counts are not fire events'
    geometries = {name: mapping(geometry) for name,geometry in roi.items()}
    metadata['feature_count'] = len(features)
    metadata['native_scale_m'] = scale.getInfo()
    (output/'burned_europe.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}),encoding='utf-8')
    (output/'regions.json').write_text(json.dumps(geometries),encoding='utf-8')
    (output/'availability.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    return metadata, geometries, features


def store(conn, run_id, year, metadata, geometries, features):
    with conn.transaction():
        for name, geom in geometries.items():
            conn.execute('''INSERT INTO regions(name,definition,geom)
                VALUES(%s,%s,ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3)))
                ON CONFLICT(name) DO UPDATE SET definition=excluded.definition,geom=excluded.geom''',
                (name,metadata['region_definition'],json.dumps(geom)))
        records = []
        for feature in features:
            geom = json.dumps(feature['geometry'],sort_keys=True,separators=(',',':'))
            doy = int(feature['properties']['burn_doy'])
            burn_date = date(year,1,1)+timedelta(days=doy-1)
            feature_id = hashlib.sha256((str(doy)+geom).encode()).hexdigest()
            records.append((geom,run_id,feature_id,burn_date,float(feature['properties']['sum'])))
        with conn.cursor() as cursor:
            cursor.executemany('''WITH g AS (SELECT ST_Multi(ST_CollectionExtract(
                ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)),3)) geom)
                INSERT INTO burned_polygons(run_id,feature_id,burn_date,raster_area_ha,geometry_area_ha,geom)
                SELECT %s,%s,%s,%s,ST_Area(geom::geography)/10000.0,geom FROM g
                WHERE NOT ST_IsEmpty(geom) AND ST_Area(geom::geography)>0
                ON CONFLICT(run_id,feature_id) DO NOTHING''',
                records)
        conn.execute('''UPDATE runs SET status=%s,finished_at=now(),latest_source_month=%s,metadata=%s WHERE id=%s''',
            ('completed' if metadata['available_months'] else 'no_data',metadata['latest_source_month'],Jsonb(metadata),run_id))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year',type=int,default=datetime.now(timezone.utc).year)
    parser.add_argument('--output',type=Path,default=Path('seasonal_outputs'))
    parser.add_argument('--extract-only',action='store_true')
    parser.add_argument('--import-directory',type=Path,help='Importar extração já concluída, sem recalcular GEE')
    args = parser.parse_args()
    start,end = season_dates(args.year)
    run_id = uuid.uuid4()
    output = args.output/str(run_id)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    conn = None
    try:
        if not args.extract_only:
            conn = psycopg.connect(os.environ['DATABASE_URL'],autocommit=True)
            if not conn.execute('SELECT pg_try_advisory_lock(%s)',(84621000+args.year,)).fetchone()[0]:
                logging.info('Outra atualização da época está em curso; execução omitida.')
                return
            conn.execute('''INSERT INTO runs(id,year,source,status,requested_start,requested_end_exclusive)
                VALUES(%s,%s,%s,'running',%s,%s)''',(run_id,args.year,SOURCE,start,end))
        if args.import_directory:
            directory = args.import_directory
            metadata = json.loads((directory/'availability.json').read_text(encoding='utf-8'))
            if metadata['requested_start'] != start.isoformat():
                raise ValueError('Ano da extração não corresponde ao ano pedido.')
            geometries = json.loads((directory/'regions.json').read_text(encoding='utf-8'))
            features = json.loads((directory/'burned_europe.geojson').read_text(encoding='utf-8'))['features']
            metadata['imported_from_run'] = directory.name
            output.mkdir(parents=True,exist_ok=True)
        else:
            authenticate()
            metadata,geometries,features = extract(args.year,start,end,output)
        if conn:
            store(conn,run_id,args.year,metadata,geometries,features)
            rows = conn.execute('SELECT region,year,burn_month,polygons,area_ha FROM resumo_mensal WHERE year=%s ORDER BY region,burn_month',(args.year,)).fetchall()
            logging.info('Resumo base dados: %s',rows)
            (output/'database_summary.json').write_text(json.dumps(rows,default=str,indent=2),encoding='utf-8')
            portugal = conn.execute('''SELECT jsonb_build_object('type','FeatureCollection','features',
                COALESCE(jsonb_agg(jsonb_build_object('type','Feature','geometry',ST_AsGeoJSON(geom)::jsonb,
                'properties',jsonb_build_object('burn_date',burn_date,'area_ha',area_ha,'source',source))), '[]'::jsonb))
                FROM areas_portugal WHERE year=%s''',(args.year,)).fetchone()[0]
            (output/'burned_portugal.geojson').write_text(json.dumps(portugal),encoding='utf-8')
        logging.info('Concluído: run=%s, polígonos=%d, último mês=%s',run_id,len(features),metadata['latest_source_month'])
    except Exception as exc:
        # Avoid persisting potential credential/URL fragments from exceptions.
        if conn:
            conn.execute("UPDATE runs SET status='failed',finished_at=now(),error=%s WHERE id=%s",(type(exc).__name__,run_id))
        logging.error('Falha: %s',type(exc).__name__)
        raise
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    main()
