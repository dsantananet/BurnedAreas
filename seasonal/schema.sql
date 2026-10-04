CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS runs (
 id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz, year integer NOT NULL, source text NOT NULL,
 status text NOT NULL, requested_start date NOT NULL, requested_end_exclusive date NOT NULL,
 latest_source_month date, metadata jsonb NOT NULL DEFAULT '{}', error text
);
CREATE TABLE IF NOT EXISTS regions (
 name text PRIMARY KEY, definition text NOT NULL,
 geom geometry(MultiPolygon,4326) NOT NULL
);
CREATE TABLE IF NOT EXISTS burned_polygons (
 run_id uuid NOT NULL REFERENCES runs(id), feature_id text NOT NULL,
 burn_date date NOT NULL, raster_area_ha double precision NOT NULL,
 geometry_area_ha double precision NOT NULL,
 geom geometry(MultiPolygon,4326) NOT NULL,
 PRIMARY KEY(run_id,feature_id)
);
CREATE INDEX IF NOT EXISTS burned_polygons_geom_idx ON burned_polygons USING gist(geom);
CREATE INDEX IF NOT EXISTS runs_year_status_idx ON runs(year,status,finished_at DESC);
CREATE OR REPLACE VIEW latest_successful_runs AS
 SELECT DISTINCT ON (year,source) * FROM runs WHERE status='completed'
 ORDER BY year,source,finished_at DESC;
CREATE OR REPLACE VIEW areas_europa AS
 SELECT p.*, r.year, r.source, r.latest_source_month
 FROM burned_polygons p JOIN latest_successful_runs r ON p.run_id=r.id;
CREATE OR REPLACE VIEW areas_portugal AS
 SELECT p.run_id,p.feature_id,p.burn_date,p.year,p.source,p.latest_source_month,
 ST_Area(ST_Intersection(p.geom,r.geom)::geography)/10000.0 AS area_ha,
 ST_Multi(ST_CollectionExtract(ST_Intersection(p.geom,r.geom),3))::geometry(MultiPolygon,4326) AS geom
 FROM areas_europa p JOIN regions r ON r.name='portugal_continental'
 WHERE ST_Intersects(p.geom,r.geom) AND ST_Area(ST_Intersection(p.geom,r.geom)::geography)>0;
CREATE OR REPLACE VIEW resumo_mensal AS
 SELECT 'europa'::text region,year,source,date_trunc('month',burn_date)::date AS burn_month,
 count(*) polygons,sum(geometry_area_ha) area_ha
 FROM areas_europa GROUP BY year,source,date_trunc('month',burn_date)
 UNION ALL
 SELECT 'portugal_continental',year,source,date_trunc('month',burn_date)::date,
 count(*),sum(area_ha) FROM areas_portugal
 GROUP BY year,source,date_trunc('month',burn_date);
