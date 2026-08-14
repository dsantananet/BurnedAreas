from datetime import datetime, timedelta
import json
import os
import ee

# 1. Autenticação no Earth Engine via Secret do GitHub
gee_key_fmt = os.environ.get('GEE_SERVICE_ACCOUNT_KEY')
if gee_key_fmt:
  key_dict = json.loads(gee_key_fmt)
  credentials = ee.ServiceAccountCredentials(
      key_dict['client_email'], key_data=gee_key_fmt
  )
  ee.Initialize(credentials)
else:
  ee.Initialize()

# 2. Janela temporal (Últimas 24h vs Referência dos últimos 10 dias)
today = datetime.utcnow().date()
yesterday = today - timedelta(days=1)
ref_start = today - timedelta(days=10)

# Bounding Box de Portugal Continental [LongMin, LatMin, LongMax, LatMax]
aoi = ee.Geometry.Rectangle([-9.5, 36.9, -6.1, 42.1])

# 3. Filtrar Sentinel-2 SR
s2 = (
    ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(aoi)
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
)

post_img = s2.filterDate(
    yesterday.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')
).median()
pre_img = s2.filterDate(
    ref_start.strftime('%Y-%m-%d'), yesterday.strftime('%Y-%m-%d')
).median()


def get_nbr(img):
  return img.normalizedDifference(['B8', 'B12'])


# 4. Calcular dNBR e Máscara de Área Ardida
dnbr = get_nbr(pre_img).subtract(get_nbr(post_img))
burnt_mask = dnbr.gt(0.27).selfMask()

# 5. Converter Raster para Vetor (Polígonos)
burnt_vectors = burnt_mask.reduceToVectors(
    geometry=aoi,
    crs=dnbr.projection(),
    scale=20,
    geometryType='polygon',
    eightConnected=False,
    labelProperty='burnt_flag',
    bestEffort=True,
    maxPixels=1e9,
)

# 6. EXPORTAR DIRETO PARA O TEU GOOGLE DRIVE
filename = f'Perimetros_Ardidos_{today.strftime("%Y_%m_%d")}'

task = ee.batch.Export.table.toDrive(
    collection=burnt_vectors,
    description=filename,
    folder='Areas_Ardidas_GEE',  # Pasta criada automaticamente no teu Drive
    fileNamePrefix=filename,
    fileFormat='GeoJSON',
)

task.start()
print(
    f'Tarefa enviada para o Earth Engine! O ficheiro será gravado na pasta'
    ' "Areas_Ardidas_GEE" do teu Google Drive.'
)
