# Script de Transcripción de Audio/Video con OpenAI

Script CLI optimizado para transcribir archivos de audio y video usando la API de OpenAI con procesamiento paralelo, caché y reintentos automáticos.

## 🚀 Características Principales

- **Formatos soportados**: MP4, MOV, M4A, WAV, MP3, etc.
- **Extracción automática**: Convierte audio a WAV mono 16kHz con ffmpeg
- **Segmentación inteligente**: Divide archivos largos en chunks optimizados
- **Procesamiento paralelo**: Transcribe múltiples chunks simultáneamente
- **Orden cronológico garantizado**: La salida respeta siempre el orden real del audio, sin importar en qué orden terminen los chunks en paralelo
- **Anti-alucinación**: `temperature=0`, prompt de contexto y limpieza automática de bucles de repetición típicos de Whisper sobre silencios/ruido
- **Modelos disponibles**: GPT-4o-mini-transcribe (recomendado) y Whisper-1
- **Caché inteligente**: Evita reprocesamiento de metadatos
- **Reintentos automáticos**: Manejo robusto de errores con fallback
- **Limpieza automática**: Elimina archivos temporales después del procesamiento

## 📋 Requisitos Previos

- **Python 3.7+** instalado
- **ffmpeg** instalado y disponible en PATH
- **Variables de entorno** con `OPENAI_API_KEY` (usar archivo `.env`)
- **Dependencias Python**: `openai`, `python-dotenv`, `tqdm`

## 🔧 Instalación

1. Clona o descarga el repositorio
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Crea un archivo `.env` con tu API key:
   ```
   OPENAI_API_KEY=tu_api_key_aqui
   ```

## 📖 Uso Básico

### Comando mínimo requerido:
```bash
python transcribir_controlt.py --input "ruta/al/archivo.mp4"
```

### Comando completo con todos los parámetros:
```bash
python transcribir_controlt.py --input "ruta/al/archivo.mp4" --model "gpt-4o-mini-transcribe" --chunk-seconds 600 --max-workers 5 --use-cache --keep-chunks
```

## ⚙️ Parámetros Disponibles

### Parámetros Obligatorios
| Parámetro | Descripción | Ejemplo |
|-----------|-------------|---------|
| `--input` | Ruta al archivo de video/audio | `"C:/Videos/mi_video.mp4"` |

### Parámetros Opcionales
| Parámetro | Descripción | Default | Ejemplo |
|-----------|-------------|---------|---------|
| `--model` | Modelo de transcripción | `gpt-4o-mini-transcribe` | `whisper-1` |
| `--chunk-seconds` | Duración de cada chunk en segundos. Si se omite, se calcula automáticamente según la duración | *(auto)* | `600` |
| `--out-dir` | Directorio de salida | `salida_transcripcion` | `mis_transcripciones` |
| `--max-workers` | Número máximo de workers paralelos | `3` | `5` |
| `--use-cache` | Usar caché para metadatos | `False` | `--use-cache` |
| `--keep-chunks` | Mantener archivos de chunks | `False` | `--keep-chunks` |

## 🎯 Comandos de Optimización

### 1. **Comando Recomendado (Balance Óptimo)**
```bash
python transcribir_controlt.py --input "C:/Users/ealvarez/Videos/revisemos_aruba.mkv" --model "gpt-4o-mini-transcribe" --chunk-seconds 600 --max-workers 5 --use-cache --keep-chunks
```

**Explicación de optimizaciones:**
- **`--chunk-seconds 600`**: Chunks de 10 minutos para mejor calidad
- **`--max-workers 5`**: Procesamiento paralelo optimizado
- **`--use-cache`**: Caché de metadatos para futuras ejecuciones
- **`--keep-chunks`**: Mantiene chunks para debugging

### 2. **Comando Rápido**
```bash
python transcribir_controlt.py --input "C:/Users/edera/Videos/deploy_ap_aeroman.mp4" --model "whisper-1" --chunk-seconds 900 --max-workers 8
```

**Explicación:**
- **`--model "whisper-1"`**: Modelo más rápido
- **`--chunk-seconds 900`**: Chunks más grandes para mayor velocidad
- **`--max-workers 8`**: Máximo paralelismo para velocidad

> **Nota:** El orden cronológico de los chunks se preserva siempre, incluso con `--max-workers` alto. Las repeticiones en bucle de Whisper (típicas en silencios al inicio de reuniones) se filtran automáticamente.

### 3. **Comando Máxima Calidad (Más Lento)**
```bash
python transcribir_controlt.py --input "C:/Users/edera/Videos/CursoOWASP/ed_clase_1_OWASP Top 10 Mejores Prácticas de Seguridad en Aplicaciones Web.mp4" --model "gpt-4o-mini-transcribe" --chunk-seconds 300 --max-workers 3 --use-cache
```

**Explicación:**
- **`--chunk-seconds 300`**: Chunks pequeños (5 min) para máxima precisión
- **`--max-workers 3`**: Menos paralelismo para evitar sobrecarga
- **`--use-cache`**: Optimización de metadatos

## 📁 Estructura de Salida

```
salida_transcripcion/
└── nombre_video/
    ├── nombre_video_transcripcion.txt   # Transcripción en texto plano (orden cronológico)
    ├── nombre_video_transcripcion.json  # Metadatos y transcripción estructurada
    └── chunks/                          # Chunks temporales (solo si se usa --keep-chunks)
        ├── chunk_000.wav
        ├── chunk_001.wav
        └── ...
```

## 🔍 Ejemplos de Uso por Caso

### **Transcripción de Clase/Curso (Recomendado)**
```bash
python transcribir_controlt.py --input "clase_seguridad.mp4" --chunk-seconds 600 --max-workers 5 --use-cache
```

### **Transcripción de Reunión/Call**
```bash
python transcribir_controlt.py --input "reunion_equipo.mp4" --chunk-seconds 900 --max-workers 3
```

### **Transcripción de Podcast/Entrevista**
```bash
python transcribir_controlt.py --input "entrevista.mp3" --chunk-seconds 1200 --max-workers 4
```

### **Transcripción con Chunks Personalizados**
```bash
python transcribir_controlt.py --input "video_largo.mp4" --chunk-seconds 1800 --max-workers 6
```

## ⚡ Consejos de Optimización

### **Sobre `--chunk-seconds`**
- Si **omites** el parámetro, el script calcula automáticamente el tamaño óptimo según la duración del archivo
- Si lo **especificas**, se respeta exactamente el valor que indiques

### **Para Archivos Cortos (< 15 min)**
- No es necesario especificar `--chunk-seconds`
- El archivo se procesa completo sin segmentación

### **Para Archivos Largos (> 15 min)**
- **Chunks pequeños (300-600s)**: Mayor calidad, más lento
- **Chunks medianos (600-900s)**: Balance calidad/velocidad
- **Chunks grandes (900-1800s)**: Mayor velocidad, menor calidad

### **Optimización de Workers**
- **Sistemas básicos**: `--max-workers 2-3`
- **Sistemas medios**: `--max-workers 4-5`
- **Sistemas potentes**: `--max-workers 6-8`

### **Uso de Caché**
- **Primera ejecución**: Sin caché (calcula duración)
- **Ejecuciones posteriores**: Con `--use-cache` para ahorrar tiempo

## 🚨 Solución de Problemas

### **Error: "ffmpeg no está instalado"**
```bash
# Windows (con chocolatey)
choco install ffmpeg

# macOS (con homebrew)
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt update && sudo apt install ffmpeg
```

### **Error: "Falta OPENAI_API_KEY"**
1. Crea archivo `.env` en el directorio del script
2. Agrega: `OPENAI_API_KEY=tu_api_key_aqui`
3. Asegúrate de que el archivo esté en la misma carpeta

### **Error de Codificación**
- Usa barras normales (`/`) en lugar de barras invertidas (`\`) en las rutas
- Evita caracteres especiales en nombres de archivos

## 📊 Métricas de Performance

El script muestra métricas detalladas al finalizar:
- **Tiempo total** de procesamiento
- **Tiempo de extracción** de audio
- **Tiempo de transcripción** por chunk
- **Chunks exitosos** vs. total
- **Tiempo promedio** por chunk

## 🔄 Reintentos y Fallback

- **Reintentos automáticos**: 3 intentos con backoff exponencial
- **Fallback automático**: Si falla el modelo principal, usa Whisper-1
- **Manejo de errores**: Continúa procesando otros chunks si uno falla

## 🎙️ Calidad de Transcripción

El script aplica varias defensas para maximizar la calidad y evitar artefactos comunes:

- **Orden cronológico garantizado**: aunque los chunks se transcriben en paralelo y terminan en cualquier orden, la salida final se reordena por índice de chunk para respetar la línea de tiempo del audio.
- **`temperature=0`**: salida determinística que reduce el riesgo de que el modelo diverja en texto inventado.
- **Prompt de contexto** (solo `whisper-1`): se envía una descripción del tipo de contenido (reunión en español) para anclar el estilo, la puntuación y el idioma.
- **Colapso de repeticiones**: Whisper tiende a entrar en bucles sobre silencio o ruido (p. ej. repetir *"Hola. ¿Cómo estás?"* decenas de veces). El script detecta estas secuencias repetidas —frases, patrones de varias frases y palabras sueltas en cadena— y las reduce automáticamente.

> Para máxima calidad en audio con muchos silencios, considera usar `--model "gpt-4o-transcribe"` (no el mini), que tiende a alucinar menos, aunque es más costoso.

## 📝 Notas Importantes

- **Directorio único**: Cada video genera su propio directorio de chunks
- **Limpieza automática**: Los chunks se eliminan al finalizar (a menos que uses `--keep-chunks`)
- **Formato de salida**: Archivos TXT para lectura y JSON para procesamiento posterior
- **Idioma**: Por defecto usa español (`es`), configurable en el código

## 🤝 Contribuciones

Para reportar bugs o sugerir mejoras, por favor:
1. Verifica que el problema no esté ya documentado
2. Incluye información del sistema operativo y versión de Python
3. Adjunta el comando exacto que causó el error
4. Incluye el mensaje de error completo

---

**Desarrollado para optimizar el proceso de transcripción de contenido educativo y profesional.**

