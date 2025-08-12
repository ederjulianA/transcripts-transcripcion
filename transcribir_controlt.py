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
  python transcribir_controlt.py --input "C:\Users\ealvarez\OneDrive - ACCION POINT SA\DocumentosAp\ETB\POC_ultima_milla_etb.mp4"

Requisitos:
  - ffmpeg instalado y disponible en PATH
  - Variables de entorno con OPENAI_API_KEY (usar .env)
"""
import argparse
import hashlib
import json
import os
import pickle
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

@retry_with_backoff(max_retries=3, base_delay=1)
def transcribe_file(client, file_path: Path, model_primary: str, language: str = "es") -> str:
    """Transcribe un archivo de audio y devuelve el texto con reintentos automáticos."""
    if USE_NEW_SDK:
        with open(file_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=model_primary,
                file=f,
                language=language
            )
        return resp.text
    else:
        with open(file_path, "rb") as f:
            resp = openai.Audio.transcriptions.create(
                model=model_primary,
                file=f,
                language=language
            )
        return resp["text"] if isinstance(resp, dict) else resp.text

def transcribe_chunk_parallel(args_tuple):
    """Función para procesamiento paralelo de chunks"""
    chunk_path, model, language, client = args_tuple
    try:
        txt = transcribe_file(client, chunk_path, model, language)
        return {"chunk": chunk_path.name, "file": chunk_path.name, "text": txt, "success": True}
    except Exception as e:
        # Reintento con whisper-1 si falla el modelo principal
        if model != "whisper-1":
            try:
                txt = transcribe_file(client, chunk_path, "whisper-1", language)
                return {"chunk": chunk_path.name, "file": chunk_path.name, "text": txt, "success": True, "fallback": True}
            except Exception as e2:
                return {"chunk": chunk_path.name, "file": chunk_path.name, "error": str(e2), "success": False}
        else:
            return {"chunk": chunk_path.name, "file": chunk_path.name, "error": str(e), "success": False}

def write_chunk_result_incremental(chunk_data: dict, output_file: Path, chunk_index: int, total_chunks: int):
    """Escribe resultados incrementalmente para optimizar memoria"""
    with open(output_file, "a", encoding="utf-8") as f:
        if total_chunks > 1:
            f.write(f"[Chunk {chunk_index+1}/{total_chunks} - {chunk_data['file']}]\n")
        f.write(chunk_data["text"].strip() + "\n\n")

def main():
    start_total_time = time.time()
    metrics = PerformanceMetrics()
    
    parser = argparse.ArgumentParser(description="Transcribir audio/video con OpenAI")
    parser.add_argument("--input", required=True, help="Ruta al archivo de video/audio")
    parser.add_argument("--model", default="gpt-4o-mini-transcribe",
                        help="Modelo a usar (ej: gpt-4o-mini-transcribe o whisper-1)")
    parser.add_argument("--chunk-seconds", type=int, default=900, help="Duración de cada chunk en segundos (default 900)")
    parser.add_argument("--out-dir", default="salida_transcripcion", help="Directorio de salida")
    parser.add_argument("--max-workers", type=int, default=3, help="Número máximo de workers paralelos")
    parser.add_argument("--use-cache", action="store_true", help="Usar caché para metadatos")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("ERROR: Falta OPENAI_API_KEY en variables de entorno (usa un .env).")

    check_ffmpeg()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        sys.exit(f"ERROR: No existe el archivo de entrada: {input_path}")

    out_dir = Path(args.out_dir).resolve()
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

    # 2) Calcular tamaño óptimo de chunk
    optimal_chunk_size = calculate_optimal_chunk_size(duration)
    if optimal_chunk_size != args.chunk_seconds:
        print(f"🔄 Ajustando tamaño de chunk a {optimal_chunk_size}s (óptimo para {duration}s)")

    # 3) Extraer y segmentar audio
    extraction_start = time.time()
    if duration > optimal_chunk_size:
        print(f"Audio largo. Segmentando en chunks de {optimal_chunk_size}s...")
        chunks_dir = out_dir / "chunks"
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
    
    # Limpiar archivo de salida
    txt_out.write_text("", encoding="utf-8")
    
    textos = []
    successful_chunks = 0
    
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        # Crear tareas para procesamiento paralelo
        future_to_chunk = {
            executor.submit(transcribe_chunk_parallel, (cp, args.model, "es", client)): cp 
            for cp in chunk_paths
        }
        
        # Procesar resultados a medida que se completan
        with tqdm(total=len(chunk_paths), desc="Chunks") as pbar:
            for future in as_completed(future_to_chunk):
                result = future.result()
                textos.append(result)
                
                if result["success"]:
                    successful_chunks += 1
                    # Escribir incrementalmente
                    write_chunk_result_incremental(result, txt_out, len(textos)-1, len(chunk_paths))
                    
                    if result.get("fallback"):
                        print(f"\n⚠️ Usado fallback 'whisper-1' para {result['file']}")
                else:
                    print(f"\n❌ Error en {result['file']}: {result['error']}")
                
                pbar.update(1)
    
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
    print(f"📁 Archivos generados:")
    print(f"   • TXT:  {txt_out}")
    print(f"   • JSON: {json_out}")

if __name__ == "__main__":
    main()
