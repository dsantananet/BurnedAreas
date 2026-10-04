# Deteção de áreas ardidas — GEE e Google Drive

Revisão: 04/10/2026. Repositório: https://github.com/dsantananet/BurnedAreas

## Falha identificada

A execução 37192111001 autenticou no Earth Engine e gerou o GeoJSON, mas o
envio falhou com HTTP 403 `storageQuotaExceeded`: contas de serviço não têm
quota no Meu disco. Rclone não altera a propriedade nem contorna esta regra.
Referência: https://rclone.org/drive/#service-account-support

## Autenticação

- `GEE_SERVICE_ACCOUNT_KEY`: secret existente, apenas para Earth Engine.
- `RCLONE_DRIVE_TOKEN`: JSON OAuth autorizado por anternative3@gmail.com.
- `RCLONE_DRIVE_CLIENT_ID` e `RCLONE_DRIVE_CLIENT_SECRET`: opcionais para
  cliente OAuth próprio; recomendados para independência do cliente do Rclone.
- Destino Drive: pasta `1BoyO9QNldRid_j2G8Q8qIS9GkpfSDI_X`.

Nunca guardar credenciais no repositório, documentação, artefactos ou memória.
Para configurar OAuth, executar `rclone authorize drive` num computador com
browser e guardar o JSON resultante diretamente no secret do GitHub.
Com cliente próprio, usar esse cliente na autorização e nos secrets correspondentes.

## Processamento

Sentinel-2 SR harmonizado, ROI [-9.5, 36.9, -6.1, 42.1], máscara QA60,
NBR B8/B12, limiar dNBR > 0.27 e vetorização a 20 metros.
Período pós: último dia UTC completo; fallback: últimos cinco dias completos.
Período pré: dez dias imediatamente anteriores ao início do período pós.
As janelas são contíguas e não se sobrepõem, incluindo no fallback.

`outputs/Perimetros_Ardidos_YYYY_MM_DD.geojson` contém as feições.
`outputs/run_status.json` regista janelas, contagens e estado:
`no_post_images`, `no_pre_images` ou `processed`.
Contagem de imagens não prova cobertura sem nuvens de todo o território.
Um ficheiro vazio por falta de imagens não significa ausência de incêndios.
As feições são candidatas espectrais, não perímetros oficiais validados.
O filtro global de nuvens <20% referido na documentação original não estava
implementado; mantém-se a máscara por pixel existente.

## Execução e recuperação

GitHub Actions: cron 03:00 UTC (início efetivo pode ser atrasado pelo GitHub).
Os resultados são conservados como artefactos durante 90 dias antes do envio.
O envio usa OAuth, seguido de `rclone check` para verificar a cópia.
Execução agendada e manual normal exigem OAuth; falhas de envio continuam
visíveis e não são convertidas em sucesso.

Para testar só o processamento enquanto OAuth está pendente:

```sh
gh workflow run daily_burned_areas.yml --repo dsantananet/BurnedAreas -f export_drive=false
```

Este modo não valida a entrega no Drive. Para testar o pipeline completo,
executar novamente com `export_drive=true` depois de configurar os secrets.

## Reutilização no QNAP

Guardar código, documentação e resultados verificados em diretório próprio
de investigação, sem substituir serviços IGNISPYRO existentes.
Documentar execução, commit, estado dos dados e hashes após a transferência.
A cópia no NAS não configura automaticamente uma tarefa agendada nesse servidor.
