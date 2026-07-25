# Marca de los audios de Telegram por despliegue

La tarjeta de audio de Telegram se configura mediante variables del servicio.
Si no se define ninguna, el comportamiento de Caché Madrid permanece intacto:

- título: `Las Fiesteras`;
- intérprete: `Caché Madrid`;
- portada: `assets/audio-cover.jpg`.

## Variables opcionales

| Variable | Valor predeterminado |
| --- | --- |
| `TG_AUDIO_TITLE` | `Las Fiesteras` |
| `TG_AUDIO_PERFORMER` | `Caché Madrid` |
| `TG_AUDIO_COVER_PATH` | `assets/audio-cover.jpg` |

Las rutas relativas de portada se resuelven desde la raíz de la aplicación
(`/app` dentro del contenedor). Las rutas absolutas también son válidas.

## Caché Barcelona

Añadir en **Environment** del servicio de Barcelona en Easypanel:

```text
TG_AUDIO_PERFORMER=Caché Barcelona
```

Barcelona conservará el título `Las Fiesteras` y la portada compartida. Si más
adelante utiliza otra portada, hay que añadir el JPEG al despliegue y configurar,
por ejemplo, `TG_AUDIO_COVER_PATH=assets/audio-cover-barcelona.jpg`. Nunca se
debe apuntar a una imagen que no exista: en ese caso Telegram enviará el audio
sin portada.

Después de cambiar las variables hay que reconstruir o redesplegar el servicio
y reiniciar Telegram. Los mensajes que Telegram ya recibió no se modifican.

No se deben añadir estas variables a `data/.env.local`: el cargador actual de
ese archivo está limitado deliberadamente a credenciales. Deben configurarse
como variables del servicio en Easypanel.
