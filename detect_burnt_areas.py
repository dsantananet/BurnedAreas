import os
import json
from datetime import datetime, timedelta
import ee

# ---------------------------------------------------------------------------
# AUTENTICAÇÃO NO GOOGLE EARTH ENGINE
# ---------------------------------------------------------------------------
service_account_key = os.environ.get("GEE_SERVICE_ACCOUNT_KEY")
if not service_account_key:
    raise ValueError("A variável de ambiente GEE_SERVICE_ACCOUNT_KEY não está configurada.")

key_dict = json.loads(service_account_key)
credentials = ee.ServiceAccountCredentials(
    key_dict['client_email'],
    key_data=service_account_key
)
ee.Initialize(credentials)

print("Autenticação no Google Earth Engine realizada com sucesso.")

# ---------------------------------------------------------------------------
# PROCESSAMENTO DAS ÁREAS ARDIDAS (Sentinel-2 dNBR)
# ---------------------------------------------------------------------------
today = datetime.utcnow()
yesterday = today - timedelta(days=1)
pre_start = yesterday - timedelta(days=10)

roi = ee.Geometry.Rectangle([-9.5, 36.9, -6.1, 42.1])

def mask_s2_clouds(image):
    qa = image.select('QA60')
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
    return image.updateMask(mask).divide(10000)

s2_base = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
    .filterBounds(roi) \
    .map(mask_s2_clouds)

s2_pos_col = s2_base.filterDate(yesterday.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
pos_count = s2_pos_col.size().getInfo()

if pos_count == 0:
    print("Aviso: Nenhuma imagem Sentinel-2 encontrada para as últimas 24h. Expandindo para os últimos 5 dias...")
    s2_pos_col = s2_base.filterDate((today - timedelta(days=5)).strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
    pos_count = s2_pos_col.size().getInfo()

if pos_count == 0:
    print("Aviso: Nenhuma imagem Sentinel-2 válida encontrada. A gerar GeoJSON vazio...")
    geojson_data = {
        "type": "FeatureCollection",
        "features": []
    }
else:
    img_pos = s2_pos_col.median()
    img_pre = s2_base.filterDate(pre_start.strftime('%Y-%m-%d'), yesterday.strftime('%Y-%m-%d')).median()

    nbr_pre = img_pre.normalizedDifference(['B8', 'B12'])
    nbr_pos = img_pos.normalizedDifference(['B8', 'B12'])

    dnbr = nbr_pre.subtract(nbr_pos)
    burned_mask = dnbr.gt(0.27)

    burned_vectors = burned_mask.selfMask().reduceToVectors(
        geometry=roi,
        crs='EPSG:4326',
        scale=20,
        geometryType='polygon',
        eightConnected=False,
        labelProperty='burned',
        maxPixels=1e9
    )

    geojson_data = burned_vectors.getInfo()

# ---------------------------------------------------------------------------
# GUARDAR FICHEIRO NA PASTA DO REPOSAITÓRIO (./outputs)
# ---------------------------------------------------------------------------
output_dir = os.path.join(os.getcwd(), 'outputs')
os.makedirs(output_dir, exist_ok=True)

filename = f"Perimetros_Ardidos_{today.strftime('%Y_%m_%d')}.geojson"
file_path = os.path.join(output_dir, filename)

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(geojson_data, f)

print(f"Sucesso! Ficheiro guardado com êxito em: {file_path}")
