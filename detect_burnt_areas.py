import os
import json
import tempfile
from datetime import datetime, timedelta
import ee
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------
DRIVE_FOLDER_ID = '1BoyO9QNldRid_j2G8Q8qIS9GkpfSDI_X'

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

# Verificar imagens disponíveis nas últimas 24h
s2_pos_col = s2_base.filterDate(yesterday.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'))
pos_count = s2_pos_col.size().getInfo()

# Se não houver passagens nas últimas 24h, expande para a janela dos últimos 5 dias
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

# Guardar em ficheiro temporário
filename = f"Perimetros_Ardidos_{today.strftime('%Y_%m_%d')}.geojson"
temp_dir = tempfile.gettempdir()
local_file_path = os.path.join(temp_dir, filename)

with open(local_file_path, 'w', encoding='utf-8') as f:
    json.dump(geojson_data, f)

print(f"GeoJSON gerado localmente: {local_file_path}")

# ---------------------------------------------------------------------------
# UPLOAD DIRETO PARA O GOOGLE DRIVE VIA API
# ---------------------------------------------------------------------------
drive_scopes = ['https://www.googleapis.com/auth/drive.file']
drive_creds = service_account.Credentials.from_service_account_info(
    key_dict, scopes=drive_scopes
)
drive_service = build('drive', 'v3', credentials=drive_creds)

file_metadata = {
    'name': filename,
    'parents': [DRIVE_FOLDER_ID]
}

media = MediaFileUpload(local_file_path, mimetype='application/geo+json')

uploaded_file = drive_service.files().create(
    body=file_metadata,
    media_body=media,
    fields='id, name'
).execute()

print(f"Sucesso! Ficheiro '{uploaded_file.get('name')}' enviado para o Google Drive com o ID: {uploaded_file.get('id')}")
