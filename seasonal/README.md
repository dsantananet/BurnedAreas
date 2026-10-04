# Áreas ardidas GEE — épocas maio–outubro

Base QNAP: `burned_areas_gee`, no PostGIS existente `postgis_core`.
Código NAS: `/share/homes/Dsantananet/PROJETOS/GEE_Areas_Ardidas/seasonal`.

## Fonte e âmbito

Fonte: [NASA MODIS MCD64A1.061](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD64A1),
produto mensal de áreas ardidas, resolução nominal 500m. É diferente dos
candidatos dNBR Sentinel-2 a20m do script diário original, que fica preservado.
O dia de queima é aproximado. A classificação não equivale a perímetros oficiais
nem garante deteção de pequenos incêndios.

Portugal corresponde ao continente, recortado pelos limites LSIB.
Europa usa países classificados Europa no LSIB2017, mais Turquia/Chipre,
recortados pela extensão operacional `[-25,34,60,72]`.
Esta definição inclui regiões transcontinentais dentro da extensão; não é um
limite geográfico preciso Europa/Ásia. Ilhas pequenas podem faltar no LSIB.

São aceites píxeis QA com terra e dados válidos, e BurnDate dentro da época.
Produtos mensais são combinados pela primeira data de queima por píxel, para
evitar contar várias vezes o mesmo píxel em meses adjacentes. A camada representa
a superfície que ardeu pelo menos uma vez; não separa uma segunda queima no mesmo
píxel. Vetorização em grelha nativa MODIS (~463m), processada em blocos de5°.
As contagens de polígonos não são contagens de incêndios.

## Disponibilidade verificada em04/10/2026

GEE: MODIS maio/junho/julho2026 disponíveis. Agosto–outubro ainda não disponíveis
neste produto. Imagens Sentinel-2 na Europa chegam a04/10/2026; esta disponibilidade
não significa que já exista extração validada de áreas ardidas desses meses.
`availability.json` em cada execução regista os meses e identificadores reais.
Uma época ainda incompleta mantém essa proveniência; não preencher meses ausentes
com área zero. O diário procura produtos novos automaticamente.

## Atualização diária

`daily_runner.py` faz uma extração inicial e depois uma atualização às04:30UTC.
Falhas são registadas e repetidas após uma hora. Antes de maio, continua a época
do ano anterior, permitindo concluir os produtos publicados com atraso.
O contentor `burned_areas_gee_daily` reinicia automaticamente com Docker/QNAP.
Memória limitada a1GiB e1CPU; não publica portas novas.
`start_daily_service.sh` cria/arranca esse serviço sem substituir um já existente.
`update_daily.sh 2026` permite atualização manual, com bloqueio PostgreSQL contra
execuções simultâneas. O acesso GEE e DB usa ficheiros privados externos ao código.

## Tabelas e vistas

- `runs`: execução, ano, datas pedidas, estado e meses disponíveis.
- `regions`: limites documentados.
- `burned_polygons`: geometrias WGS84, dia de queima, área raster e geométrica.
- `areas_europa`: última execução concluída de cada ano/fonte.
- `areas_portugal`: interseção geométrica com Portugal continental.
- `resumo_mensal`: hectares e polígonos por região/mês da data aproximada de queima.

Só execuções concluídas substituem a vista atual. Falhas não retiram dados válidos.
Cada snapshot fica identificado por UUID, evitando somar históricos como área nova.
As transações publicam uma época inteira de forma atómica.

```sql
SELECT * FROM resumo_mensal WHERE year=2026 ORDER BY region,burn_month;
SELECT id,status,latest_source_month,metadata FROM runs ORDER BY started_at DESC;
SELECT count(*),sum(area_ha) FROM areas_portugal WHERE year=2026;
```

Saídas por UUID: metadados, blocosGeoJSON, EuropaGeoJSON; depois da carga,
PortugalGeoJSON e resumo da base. Geometrias válidas e área geodésica calculadas
no PostGIS. Credenciais e palavras-passe não pertencem a estas saídas.
