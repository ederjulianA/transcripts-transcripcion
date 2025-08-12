# 🎵 Transcripción de Audio/Video con OpenAI

Script CLI optimizado para transcribir archivos de audio y video usando la API de OpenAI con procesamiento paralelo y optimizaciones de rendimiento.

## ✨ Características Principales

- **Formatos Soportados**: MP4, MOV, M4A, WAV, MP3 y más
- **Procesamiento Inteligente**: División automática en chunks para archivos largos
- **Transcripción Paralela**: Procesamiento simultáneo de múltiples segmentos
- **Modelos Flexibles**: Soporte para `gpt-4o-mini-transcribe` y `whisper-1`
- **Optimizaciones**: Caché, reintentos automáticos, métricas de rendimiento
- **Salida Múltiple**: Archivos TXT y JSON con metadatos completos

## 🚀 Instalación

### Prerrequisitos

- Python 3.8+
- FFmpeg instalado y disponible en PATH
- Cuenta de OpenAI con API key

### Dependencias

```bash
pip install -r requirements.txt
```

### Configuración

1. Crea un archivo `.env` en el directorio raíz:
```bash
OPENAI_API_KEY=tu_api_key_aqui
```

2. Asegúrate de que FFmpeg esté instalado:
   - **Windows**: Descarga desde [ffmpeg.org](https://ffmpeg.org/download.html)
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt install ffmpeg`

## 📖 Uso

### Comando Básico

```bash
python transcribir_controlt.py --input "ruta/al/archivo.mp4"
```

### Opciones Disponibles

```bash
python transcribir_controlt.py \
  --input "video.mp4" \
  --model "gpt-4o-mini-transcribe" \
  --chunk-seconds 900 \
  --out-dir "salida" \
  --max-workers 3 \
  --use-cache
```

### Parámetros

- `--input`: Ruta al archivo de audio/video (requerido)
- `--model`: Modelo de OpenAI a usar (default: `gpt-4o-mini-transcribe`)
- `--chunk-seconds`: Duración de cada chunk en segundos (default: 900)
- `--out-dir`: Directorio de salida (default: `salida_transcripcion`)
- `--max-workers`: Número máximo de workers paralelos (default: 3)
- `--use-cache`: Habilitar caché para metadatos

## 📊 Salida

El script genera dos archivos principales:

### Archivo TXT
Transcripción completa del audio/video en formato legible.

### Archivo JSON
```json
{
  "metadata": {
    "input_file": "ruta/al/archivo.mp4",
    "model_used": "gpt-4o-mini-transcribe",
    "chunks_processed": 5,
    "total_chunks": 5,
    "performance_metrics": {
      "extraction_time": 12.5,
      "transcription_time": 45.2,
      "avg_chunk_time": 9.04,
      "cache_hits": 1
    }
  },
  "transcriptions": [...]
}
```

## 🔧 Optimizaciones

- **División Inteligente**: Calcula automáticamente el tamaño óptimo de chunks
- **Procesamiento Paralelo**: Transcribe múltiples segmentos simultáneamente
- **Sistema de Caché**: Evita reprocesar metadatos de archivos
- **Reintentos Automáticos**: Manejo robusto de errores con backoff exponencial
- **Fallback Inteligente**: Cambia automáticamente a `whisper-1` si falla el modelo principal

## 📈 Métricas de Rendimiento

El script proporciona métricas detalladas:
- Tiempo total de procesamiento
- Tiempo de extracción de audio
- Tiempo de transcripción
- Número de chunks procesados
- Tiempo promedio por chunk
- Hits de caché

## 🛠️ Estructura del Proyecto

```
transcripts/
├── transcribir_controlt.py    # Script principal
├── requirements.txt            # Dependencias Python
├── .gitignore                 # Archivos a excluir
├── README.md                  # Este archivo
├── TorreC/                    # Archivos de entrada
└── salida_transcripcion/      # Archivos generados
```

## 🚨 Solución de Problemas

### Error: FFmpeg no encontrado
```bash
# Verificar instalación
ffmpeg -version
ffprobe -version

# Agregar al PATH si es necesario
```

### Error: API Key no válida
```bash
# Verificar archivo .env
cat .env

# Verificar variable de entorno
echo $OPENAI_API_KEY
```

### Archivos muy grandes
- El script divide automáticamente archivos largos
- Ajusta `--chunk-seconds` según tus necesidades
- Usa `--max-workers` para optimizar el paralelismo

## 🤝 Contribuciones

¡Las contribuciones son bienvenidas! Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## 🙏 Agradecimientos

- OpenAI por proporcionar las APIs de transcripción
- FFmpeg por las herramientas de procesamiento de audio/video
- La comunidad de Python por las librerías utilizadas

---

**Nota**: Este script está optimizado para archivos en español por defecto. Cambia el parámetro `language` en el código si necesitas otros idiomas.

