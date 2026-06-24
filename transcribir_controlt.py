# transcribir_controlt.py
"""
Script CLI para transcribir audio/video usando la API de OpenAI.

Características:
- Acepta archivo de video o audio (mp4, mov, m4a, wav, mp3, etc.)
- Extrae audio a WAV mono 16 kHz con ffmpeg
- Si el audio es largo, lo divide en chunks (por defecto 900 s = 15 min)
- Transcribe cada chunk con el modelo 'gpt-4o-mini-transcribe' o 'whisper-1'
- Une todo en un solo .txt y un .json con metadatos
- OPTIMIZACIONES: Procesamiento paralelo, caché, reintentos automáticos

Uso:
  python transcribir_controlt.py --input "C:/Users/ealvarez/OneDrive - ACCION POINT SA/Eder/Cursos/CursoOWASP/ed_clase_1_OWASP Top 10 Mejores Prácticas de Seguridad en Aplicaciones Web.mp4"

Requisitos:
  - ffmpeg instalado y disponible en PATH
  - Variables de entorno con OPENAI_API_KEY (usar .env)
"""
import argparse
import hashlib
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from pathlib import Path

# En Windows la consola suele usar cp1252 y no puede imprimir emojis/acentos,
# lo que provoca UnicodeEncodeError. Forzamos UTF-8 en stdout/stderr.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from tqdm import tqdm

try:
    # SDK nuevo de OpenAI
    from openai import OpenAI
    USE_NEW_SDK = True
except Exception:
    USE_NEW_SDK = False
    import openai  # SDK clásico

@dataclass
class PerformanceMetrics:
    """Métricas de performance para monitoreo"""
    extraction_time: float = 0.0
    transcription_time: float = 0.0
    total_time: float = 0.0
    chunks_processed: int = 0
    avg_chunk_time: float = 0.0
    cache_hits: int = 0
    retry_attempts: int = 0

def track_performance(func):
    """Decorador para medir tiempo de ejecución"""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"⏱️ {func.__name__}: {end_time - start_time:.2f}s")
        return result
    return wrapper

def retry_with_backoff(max_retries=3, base_delay=1):
    """Decorador para reintentos con backoff exponencial"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    delay = base_delay * (2 ** attempt)
                    print(f"⚠️ Reintento {attempt + 1}/{max_retries} en {delay}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

def get_cached_duration(file_path: Path) -> float:
    """Obtiene duración del archivo con caché para evitar reprocesamiento"""
    cache_file = Path(f".cache_{hashlib.md5(str(file_path).encode()).hexdigest()}.pkl")
    if cache_file.exists():
        with open(cache_file, "rb") as f:
            return pickle.load(f)
    
    duration = ffprobe_duration(file_path)
    with open(cache_file, "wb") as f:
        pickle.dump(duration, f)
    return duration

def calculate_optimal_chunk_size(duration: float, max_chunks: int = 10) -> int:
    """Calcula el tamaño óptimo de chunk basado en la duración"""
    if duration <= 900:  # 15 minutos
        return int(duration)
    return max(300, int(duration / max_chunks))  # Mínimo 5 minutos

def robust_rmtree(path: Path, retries: int = 5, delay: float = 0.5) -> bool:
    """Elimina un directorio de forma robusta en Windows.

    `shutil.rmtree` falla con PermissionError (WinError 5) cuando algún archivo
    sigue bloqueado: OneDrive sincronizando, atributos de solo-lectura, o un
    handle aún abierto tras cerrar ffmpeg. Esta función:
      - reintenta varias veces con una pequeña espera (da tiempo a liberar handles)
      - en el handler de error, quita el flag de solo-lectura y reintenta el borrado

    Devuelve True si logró eliminarlo, False si no (sin lanzar excepción).
    """
    def _on_error(func, p, exc_info):
        # Quitar solo-lectura y reintentar la operación que falló.
        try:
            os.chmod(p, 0o777)
            func(p)
        except Exception:
            pass

    for attempt in range(retries):
        if not path.exists():
            return True
        try:
            shutil.rmtree(path, onexc=_on_error)
            if not path.exists():
                return True
        except (PermissionError, OSError):
            pass
        time.sleep(delay)

    return not path.exists()


def check_ffmpeg():
    for exe in ("ffmpeg", "ffprobe"):
        if shutil.which(exe) is None:
            sys.exit(f"ERROR: '{exe}' no está instalado o no está en el PATH.")

@track_performance
def ffprobe_duration(path: Path) -> float:
    """Obtiene duración en segundos con ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())

@track_performance
def extract_wav(input_path: Path, out_wav: Path):
    """Extrae audio WAV mono 16k."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_wav)
    ]
    subprocess.run(cmd, check=True)

def extract_and_segment_directly(input_path: Path, out_dir: Path, segment_seconds: int) -> list[Path]:
    """Extrae y segmenta en una sola operación para optimizar I/O"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1", str(pattern)
    ]
    subprocess.run(cmd, check=True)
    files = sorted(out_dir.glob("chunk_*.wav"))
    return files

# Prompt de contexto que ancla el estilo/idioma y reduce las alucinaciones.
# Whisper usa el campo `prompt` como "texto previo" para condicionar la salida.
DEFAULT_PROMPT_ES = (
    "Transcripción de una reunión de trabajo en español. "
    "Conversación natural con puntuación y mayúsculas correctas."
)


def collapse_repetitions(text: str, max_repeat: int = 2) -> str:
    """Colapsa bucles de alucinación de Whisper (frases repetidas en cadena).

    Whisper suele entrar en loops sobre silencio/ruido y repite la misma frase
    decenas de veces ('Hola. ¿Cómo estás? Hola. ¿Cómo estás?...'). Esta función
    detecta n-gramas consecutivos repetidos y los reduce a `max_repeat` apariciones.
    """
    if not text:
        return text

    # 1) Colapsar frases (separadas por puntuación) repetidas consecutivamente.
    #    Tokenizamos en "unidades" terminadas por . ! ? o salto de línea.
    units = re.findall(r'[^.!?\n]*[.!?\n]|\S[^.!?\n]*$', text)
    units = [u.strip() for u in units if u.strip()]
    norm_units = [u.lower() for u in units]

    n = len(units)
    cleaned = []
    i = 0
    while i < n:
        # Buscar el bloque repetido más largo que empiece en i: probamos
        # patrones de longitud L=1,2,3,... y vemos cuántas veces se repiten.
        # Esto captura loops como "A. B? A. B? A. B?" (patrón de longitud 2).
        best_len, best_run = 1, 1
        for L in range(1, min(8, (n - i) // 2 + 1) + 1):
            if i + 2 * L > n:
                break
            pattern = norm_units[i:i + L]
            run = 1
            j = i + L
            while j + L <= n and norm_units[j:j + L] == pattern:
                run += 1
                j += L
            # Preferimos el patrón que cubra más unidades repetidas.
            if run >= 2 and run * L > best_run * best_len:
                best_len, best_run = L, run

        if best_run >= 2:
            keep = min(best_run, max_repeat)
            cleaned.extend(units[i:i + best_len * keep])
            i += best_len * best_run
        else:
            cleaned.append(units[i])
            i += 1

    result = " ".join(cleaned)

    # 2) Colapsar palabras sueltas repetidas en cadena (p.ej. "Hola Hola Hola").
    def _collapse_word_runs(m):
        word = m.group(1)
        return (" " + word) * max_repeat

    result = re.sub(
        r'\b(\w+)(?:\s+\1\b){' + str(max_repeat) + r',}',
        _collapse_word_runs,
        result,
        flags=re.IGNORECASE,
    )

    return re.sub(r'\s{2,}', ' ', result).strip()


@retry_with_backoff(max_retries=3, base_delay=1)
def transcribe_file(client, file_path: Path, model_primary: str,
                    language: str = "es", prompt: str = DEFAULT_PROMPT_ES) -> str:
    """Transcribe un archivo de audio y devuelve el texto con reintentos automáticos.

    Usa temperature=0 (determinístico) y un prompt de contexto para reducir
    las alucinaciones en bucle típicas de Whisper sobre silencio/ruido.
    """
    params = {
        "model": model_primary,
        "language": language,
        "temperature": 0,
    }
    # `prompt` solo está soportado por whisper-1; los modelos gpt-4o-*-transcribe
    # lo rechazan, así que lo añadimos condicionalmente.
    if prompt and model_primary == "whisper-1":
        params["prompt"] = prompt

    if USE_NEW_SDK:
        with open(file_path, "rb") as f:
            resp = client.audio.transcriptions.create(file=f, **params)
        return resp.text
    else:
        with open(file_path, "rb") as f:
            resp = openai.Audio.transcriptions.create(file=f, **params)
        return resp["text"] if isinstance(resp, dict) else resp.text

def transcribe_chunk_parallel(args_tuple):
    """Función para procesamiento paralelo de chunks.

    Recibe el índice del chunk para poder reordenar al final, ya que los
    resultados llegan en orden de finalización (no de cronología del audio).
    """
    index, chunk_path, model, language, client = args_tuple
    try:
        txt = transcribe_file(client, chunk_path, model, language)
        txt = collapse_repetitions(txt)
        return {"index": index, "chunk": chunk_path.name, "file": chunk_path.name,
                "text": txt, "success": True}
    except Exception as e:
        # Reintento con whisper-1 si falla el modelo principal
        if model != "whisper-1":
            try:
                txt = transcribe_file(client, chunk_path, "whisper-1", language)
                txt = collapse_repetitions(txt)
                return {"index": index, "chunk": chunk_path.name, "file": chunk_path.name,
                        "text": txt, "success": True, "fallback": True}
            except Exception as e2:
                return {"index": index, "chunk": chunk_path.name, "file": chunk_path.name,
                        "error": str(e2), "success": False}
        else:
            return {"index": index, "chunk": chunk_path.name, "file": chunk_path.name,
                    "error": str(e), "success": False}

def main():
    start_total_time = time.time()
    metrics = PerformanceMetrics()
    
    parser = argparse.ArgumentParser(description="Transcribir audio/video con OpenAI")
    parser.add_argument("--input", required=True, help="Ruta al archivo de video/audio")
    parser.add_argument("--model", default="gpt-4o-mini-transcribe",
                        help="Modelo a usar (ej: gpt-4o-mini-transcribe o whisper-1)")
    parser.add_argument("--chunk-seconds", type=int, default=None,
                        help="Duración de cada chunk en segundos. Si se omite, se calcula automáticamente.")
    parser.add_argument("--out-dir", default="salida_transcripcion", help="Directorio de salida")
    parser.add_argument("--max-workers", type=int, default=3, help="Número máximo de workers paralelos")
    parser.add_argument("--use-cache", action="store_true", help="Usar caché para metadatos")
    parser.add_argument("--keep-chunks", action="store_true", help="Conservar archivos de chunks después de la transcripción")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: Falta OPENAI_API_KEY en variables de entorno (usa un .env).")

    check_ffmpeg()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        sys.exit(f"ERROR: No existe el archivo de entrada: {input_path}")

    # Crear directorio base de salida
    base_out_dir = Path(args.out_dir).resolve()
    base_out_dir.mkdir(parents=True, exist_ok=True)
    
    # Crear directorio específico para este video
    video_name = input_path.stem
    out_dir = base_out_dir / video_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Inicializar cliente
    if USE_NEW_SDK:
        client = OpenAI(api_key=api_key)
    else:
        openai.api_key = api_key
        client = None

    # 1) Obtener duración (con caché si está habilitado)
    if args.use_cache:
        duration = get_cached_duration(input_path)
        metrics.cache_hits += 1
    else:
        duration = ffprobe_duration(input_path)
    print(f"Duración del audio: {timedelta(seconds=round(duration))}")

    # 2) Determinar tamaño de chunk: respetar el valor del usuario si lo pasó
    #    explícitamente; si no, calcular el óptimo según la duración.
    if args.chunk_seconds is not None:
        optimal_chunk_size = args.chunk_seconds
        print(f"📏 Tamaño de chunk: {optimal_chunk_size}s (especificado por el usuario)")
    else:
        optimal_chunk_size = calculate_optimal_chunk_size(duration)
        print(f"📏 Tamaño de chunk: {optimal_chunk_size}s (calculado automáticamente)")

    # 3) Extraer y segmentar audio
    extraction_start = time.time()
    if duration > optimal_chunk_size:
        print(f"Audio largo. Segmentando en chunks de {optimal_chunk_size}s...")
        # Crear directorio de chunks dentro de la carpeta del video
        chunks_dir = out_dir / "chunks"
        # Limpiar directorio de chunks anterior si existe
        if chunks_dir.exists():
            if not robust_rmtree(chunks_dir):
                print(f"⚠️ No se pudo eliminar por completo {chunks_dir} "
                      f"(¿OneDrive sincronizando o archivo en uso?). Continuando de todos modos.")
        chunk_paths = extract_and_segment_directly(input_path, chunks_dir, optimal_chunk_size)
    else:
        # Para archivos cortos, extraer directamente
        wav_path = out_dir / (input_path.stem + ".wav")
        print("Extrayendo audio WAV...")
        extract_wav(input_path, wav_path)
        chunk_paths = [wav_path]
    
    metrics.extraction_time = time.time() - extraction_start

    # 4) Transcribir en paralelo
    print(f"Transcribiendo {len(chunk_paths)} archivo(s) con el modelo '{args.model}' (paralelo)...")
    transcription_start = time.time()
    
    txt_out = out_dir / (input_path.stem + "_transcripcion.txt")
    json_out = out_dir / (input_path.stem + "_transcripcion.json")

    textos = []
    successful_chunks = 0

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        # Crear tareas para procesamiento paralelo, pasando el índice de cada
        # chunk para poder reconstruir la cronología al final.
        future_to_chunk = {
            executor.submit(transcribe_chunk_parallel, (idx, cp, args.model, "es", client)): cp
            for idx, cp in enumerate(chunk_paths)
        }

        # Procesar resultados a medida que se completan (solo para feedback/progreso).
        with tqdm(total=len(chunk_paths), desc="Chunks") as pbar:
            for future in as_completed(future_to_chunk):
                result = future.result()
                textos.append(result)

                if result["success"]:
                    successful_chunks += 1
                    if result.get("fallback"):
                        print(f"\n⚠️ Usado fallback 'whisper-1' para {result['file']}")
                else:
                    print(f"\n❌ Error en {result['file']}: {result['error']}")

                pbar.update(1)

    # Reordenar por índice de chunk para preservar la cronología del audio,
    # independientemente del orden en que terminaron los hilos.
    textos.sort(key=lambda r: r["index"])

    # Escribir el .txt ya ordenado. Para 1 solo chunk, sin cabeceras.
    total_chunks = len(chunk_paths)
    with open(txt_out, "w", encoding="utf-8") as f:
        for result in textos:
            if not result["success"]:
                continue
            if total_chunks > 1:
                f.write(f"[Chunk {result['index']+1}/{total_chunks} - {result['file']}]\n")
            f.write(result["text"].strip() + "\n\n")

    metrics.transcription_time = time.time() - transcription_start
    metrics.chunks_processed = successful_chunks
    metrics.avg_chunk_time = metrics.transcription_time / len(chunk_paths) if chunk_paths else 0

    # 5) Guardar JSON con metadatos
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "input_file": str(input_path),
                "model_used": args.model,
                "chunks_processed": successful_chunks,
                "total_chunks": len(chunk_paths),
                "performance_metrics": {
                    "extraction_time": metrics.extraction_time,
                    "transcription_time": metrics.transcription_time,
                    "avg_chunk_time": metrics.avg_chunk_time,
                    "cache_hits": metrics.cache_hits
                }
            },
            "transcriptions": textos
        }, f, ensure_ascii=False, indent=2)

    metrics.total_time = time.time() - start_total_time

    print(f"\n✅ Transcripción completada!")
    print(f"📊 Métricas de Performance:")
    print(f"   • Tiempo total: {metrics.total_time:.2f}s")
    print(f"   • Extracción: {metrics.extraction_time:.2f}s")
    print(f"   • Transcripción: {metrics.transcription_time:.2f}s")
    print(f"   • Chunks exitosos: {successful_chunks}/{len(chunk_paths)}")
    print(f"   • Tiempo promedio por chunk: {metrics.avg_chunk_time:.2f}s")
    print(f"📁 Estructura de salida:")
    print(f"   • Carpeta del video: {out_dir}")
    print(f"   • TXT:  {txt_out}")
    print(f"   • JSON: {json_out}")
    if duration > optimal_chunk_size and args.keep_chunks:
        print(f"   • Chunks: {out_dir / 'chunks'}")
    
    # Limpiar chunks si no se especifica --keep-chunks
    if not args.keep_chunks and duration > optimal_chunk_size:
        chunks_dir = out_dir / "chunks"
        if chunks_dir.exists():
            print(f"🧹 Limpiando archivos de chunks...")
            if robust_rmtree(chunks_dir):
                print(f"   • Chunks eliminados: {chunks_dir}")
            else:
                print(f"   ⚠️ No se pudieron eliminar todos los chunks en {chunks_dir} "
                      f"(¿OneDrive o archivo en uso?). Bórralos manualmente si es necesario.")
    elif args.keep_chunks and duration > optimal_chunk_size:
        chunks_dir = out_dir / "chunks"
        if chunks_dir.exists():
            print(f"📁 Chunks conservados en: {chunks_dir}")

if __name__ == "__main__":
    main()
