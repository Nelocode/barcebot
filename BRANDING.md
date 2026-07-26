# Marca de los audios de Telegram

El repositorio de Barcelona incluye esta presentación inicial:

- título: `Las Fiesteras`;
- intérprete: `Caché Barcelona`;
- portada: `assets/audio-cover.jpg`.

El título y el nombre de la agencia pueden editarse desde **Configurar >
Presentación de los audios en Telegram**. El panel guarda ambos valores en
`data/telegram_audio_branding.json`, dentro del volumen persistente. El worker
lee ese archivo al preparar cada envío, por lo que el cambio se aplica al
próximo audio sin reiniciar Telegram ni redesplegar el servicio.

El repositorio de Madrid permanece separado y no lee este archivo de
configuración.

## Variables opcionales

| Variable | Respaldo incorporado |
| --- | --- |
| `TG_AUDIO_TITLE` | `Las Fiesteras` |
| `TG_AUDIO_PERFORMER` | `Caché Madrid` |
| `TG_AUDIO_COVER_PATH` | `assets/audio-cover.jpg` |

La precedencia para título e intérprete, de menor a mayor, es: respaldo del
código, valores empaquetados para Barcelona, variables de Easypanel y valor
guardado desde el panel. Por eso los valores elegidos en el panel no se pierden al
reiniciar o redesplegar.

Las rutas relativas de portada se resuelven desde la raíz de la aplicación
(`/app` dentro del contenedor). Las rutas absolutas también son válidas.

## Portada

Barcelona conserva la portada compartida. Si más adelante utiliza otra, hay
que añadir el JPEG al despliegue y configurar, por ejemplo,
`TG_AUDIO_COVER_PATH=assets/audio-cover-barcelona.jpg`. Nunca se debe apuntar a
una imagen que no exista: en ese caso Telegram enviará el audio sin portada.

No se deben añadir estas variables a `data/.env.local`: el cargador actual de
ese archivo está limitado deliberadamente a credenciales. Deben configurarse
como variables del servicio en Easypanel. El ajuste realizado desde el panel
usa su propio archivo JSON y no mezcla marca con credenciales.
