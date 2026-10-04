"""Generate a transactional, repeatable PostGIS import from an archived extraction."""
import argparse
import csv
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import uuid

def literal(value):
    return "'"+str(value).replace("'","''")+"'"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('sql_file',type=Path)
    args = parser.parse_args()
    metadata = json.loads((args.directory/'availability.json').read_text(encoding='utf-8'))
    regions = json.loads((args.directory/'regions.json').read_text(encoding='utf-8'))
    features = json.loads((args.directory/'burned_europe.geojson').read_text(encoding='utf-8'))['features']
    run_id = str(uuid.UUID(args.directory.name))
    year = date.fromisoformat(metadata['requested_start']).year
    with args.sql_file.open('w',encoding='utf-8',newline='') as f:
        f.write('BEGIN;\n')
        f.write(f"INSERT INTO runs(id,year,source,status,requested_start,requested_end_exclusive) VALUES({literal(run_id)},{year},{literal(metadata['source'])},'running',{literal(metadata['requested_start'])},{literal(metadata['requested_end_exclusive'])}) ON CONFLICT(id) DO NOTHING;\n")
        for name,geom in regions.items():
            f.write(f"INSERT INTO regions(name,definition,geom) VALUES({literal(name)},{literal(metadata['region_definition'])},ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON({literal(json.dumps(geom))}),4326)),3))) ON CONFLICT(name) DO UPDATE SET definition=excluded.definition,geom=excluded.geom;\n")
        f.write('CREATE TEMP TABLE stage(feature_id text,burn_date date,raster_area_ha double precision,geojson text) ON COMMIT DROP;\n')
        f.write('COPY stage FROM STDIN WITH (FORMAT csv);\n')
        writer = csv.writer(f,lineterminator='\n')
        for feature in features:
            geom = json.dumps(feature['geometry'],sort_keys=True,separators=(',',':'))
            doy = int(feature['properties']['burn_doy'])
            key = hashlib.sha256((str(doy)+geom).encode()).hexdigest()
            writer.writerow([key,(date(year,1,1)+timedelta(days=doy-1)).isoformat(),feature['properties']['sum'],geom])
        f.write('\\.\n')
        f.write(f"WITH geometries AS (SELECT *,ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(geojson),4326)),3)) geom FROM stage) INSERT INTO burned_polygons(run_id,feature_id,burn_date,raster_area_ha,geometry_area_ha,geom) SELECT {literal(run_id)},feature_id,burn_date,raster_area_ha,ST_Area(geom::geography)/10000.0,geom FROM geometries WHERE NOT ST_IsEmpty(geom) AND ST_Area(geom::geography)>0 ON CONFLICT(run_id,feature_id) DO NOTHING;\n")
        f.write(f"UPDATE runs SET status='completed',finished_at=now(),latest_source_month={literal(metadata['latest_source_month'])},metadata={literal(json.dumps(metadata))}::jsonb WHERE id={literal(run_id)};\nCOMMIT;\n")
    print(f'Prepared {len(features)} polygons, run {run_id}')

if __name__ == '__main__':
    main()
