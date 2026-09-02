# dub_pipeline.py

import os
import subprocess
import torch
import pysrt
import ollama
from pydub import AudioSegment

# ==========================================
# 0. MODEL & PIPELINE CONFIGURATION
# ==========================================
OUTPUT_DIR = "output_run_7"  # Change this to your desired output directory
OLLAMA_MODEL_NAME = "qwen3.5:9b-instruct"

INPUT_VIDEO = "input_video.mov"

# Languages: Set both the full display name and the 2-letter ISO code
# XTTS-v2 supported codes: en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, ko, hu, hi
SOURCE_LANGUAGE = "Turkish"
SOURCE_LANG_CODE = "tr"

TARGET_LANGUAGE = "Hindi"
TARGET_LANG_CODE = "hi"

# Ensure output directory and temp audio slice directory exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
TEMP_SEGMENTS_DIR = os.path.join(OUTPUT_DIR, "temp_segments")
os.makedirs(TEMP_SEGMENTS_DIR, exist_ok=True)

# Define file paths inside the specified output directory
INTERMEDIATE_AUDIO = os.path.join(OUTPUT_DIR, "original_audio.wav")
ORIGINAL_SRT = os.path.join(OUTPUT_DIR, f"{SOURCE_LANGUAGE.lower()}_subtitles.srt")
TRANSLATED_SRT = os.path.join(OUTPUT_DIR, f"{TARGET_LANGUAGE.lower()}_subtitles.srt")
VOICE_SAMPLE_WAV = os.path.join(OUTPUT_DIR, "voice_sample.wav")
OUTPUT_DUBBED_AUDIO = os.path.join(OUTPUT_DIR, "dubbed_audio.wav")
FINAL_VIDEO = os.path.join(OUTPUT_DIR, "output_dubbed_video.mov")

# Set explicit FFmpeg binary paths for Apple Silicon Homebrew
if os.path.exists("/opt/homebrew/bin/ffmpeg"):
    AudioSegment.converter = "/opt/homebrew/bin/ffmpeg"
    AudioSegment.ffprobe = "/opt/homebrew/bin/ffprobe"
    FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
else:
    FFMPEG_BIN = "ffmpeg"

# Monkey-patch isin_mps_friendly for Coqui TTS compatibility
import transformers.pytorch_utils
if not hasattr(transformers.pytorch_utils, "isin_mps_friendly"):
    def isin_mps_friendly(elements, test_elements):
        return torch.isin(elements, test_elements)
    transformers.pytorch_utils.isin_mps_friendly = isin_mps_friendly

# --- FIX: Patch XTTS num2words crash for Hindi and unsupported languages ---
import TTS.tts.layers.xtts.tokenizer as xtts_tok
from num2words import num2words

def safe_expand_number(m, lang):
    try:
        return num2words(int(m.group(0)), lang=lang)
    except (NotImplementedError, KeyError):
        return m.group(0)

xtts_tok._expand_number = safe_expand_number
# ---------------------------------------------------------------------------

import whisper
from TTS.api import TTS

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"Using compute device: {DEVICE}")
print(f"Artifacts will be stored in: '{OUTPUT_DIR}/'")
print(f"Translation flow: {SOURCE_LANGUAGE} ({SOURCE_LANG_CODE}) -> {TARGET_LANGUAGE} ({TARGET_LANG_CODE})")


# 1. EXTRACT AUDIO VIA FFMPEG
def extract_audio(video_path, audio_path):
    print("\n--- Step 1: Extracting clean 16kHz WAV from video ---")
    cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# 2. TRANSCRIBE SPEECH & SAVE SRT
def transcribe_to_srt(audio_path, srt_output_path):
    print(f"\n--- Step 2: Transcribing {SOURCE_LANGUAGE} audio with Whisper ---")
    model = whisper.load_model("medium", device="cpu")
    result = model.transcribe(audio_path, language=SOURCE_LANG_CODE, task="transcribe")
    
    subs = pysrt.SubRipFile()
    for i, seg in enumerate(result["segments"], start=1):
        start = pysrt.SubRipTime(milliseconds=int(seg["start"] * 1000))
        end = pysrt.SubRipTime(milliseconds=int(seg["end"] * 1000))
        item = pysrt.SubRipItem(index=i, start=start, end=end, text=seg["text"].strip())
        subs.append(item)
    
    subs.save(srt_output_path, encoding="utf-8")
    print(f"Generated {SOURCE_LANGUAGE} subtitles saved to: {srt_output_path}")
    return subs


# 3. TRANSLATE VIA OLLAMA
def translate_subtitles_ollama(subs):
    print(f"\n--- Step 3: Translating segments with Ollama ({OLLAMA_MODEL_NAME}) ---")
    translated_subs = pysrt.SubRipFile()

    for item in subs:
        src_text = item.text.strip()
        if not src_text:
            continue

        response = ollama.chat(
            model=OLLAMA_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a professional film translator. Translate this {SOURCE_LANGUAGE} subtitle "
                        f"line directly into natural {TARGET_LANGUAGE}. "
                        f"CRITICAL: Always write all numbers, figures, and dates as spelled-out words in {TARGET_LANGUAGE} script "
                        f"(never use digits like 1, 2, 9, 10). "
                        "Return ONLY the translated line, without quotes, explanations, or notes."
                    ),
                },
                {"role": "user", "content": src_text},
            ],
            options={"temperature": 0.2},
        )

        tr_text = response["message"]["content"].strip()
        print(f"[{SOURCE_LANG_CODE.upper()}]: {src_text} -> [{TARGET_LANG_CODE.upper()}]: {tr_text}")

        tr_item = pysrt.SubRipItem(
            index=item.index,
            start=item.start,
            end=item.end,
            text=tr_text,
        )
        translated_subs.append(tr_item)

    translated_subs.save(TRANSLATED_SRT, encoding="utf-8")
    print(f"{TARGET_LANGUAGE} subtitles saved to: {TRANSLATED_SRT}")
    return translated_subs


# 4. CLONE VOICE & DUB WITH XTTS-V2
def dub_with_xtts(translated_subs, reference_audio_path):
    print(f"\n--- Step 4: Synthesizing {TARGET_LANGUAGE} audio with cloned voice via XTTS-v2 ---")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)

    orig_audio = AudioSegment.from_wav(reference_audio_path)
    final_canvas = AudioSegment.silent(duration=len(orig_audio))

    sample_len = min(12000, len(orig_audio))
    orig_audio[0:sample_len].export(VOICE_SAMPLE_WAV, format="wav")

    for item in translated_subs:
        start_ms = (item.start.hours * 3600 + item.start.minutes * 60 + item.start.seconds) * 1000 + item.start.milliseconds
        end_ms = (item.end.hours * 3600 + item.end.minutes * 60 + item.end.seconds) * 1000 + item.end.milliseconds
        target_slot_len = end_ms - start_ms

        line = item.text.strip()
        if not line:
            continue

        temp_out = os.path.join(TEMP_SEGMENTS_DIR, f"segment_{item.index}.wav")
        
        tts.tts_to_file(
            text=line,
            file_path=temp_out,
            speaker_wav=VOICE_SAMPLE_WAV,
            language=TARGET_LANG_CODE
        )

        synth_seg = AudioSegment.from_wav(temp_out)
        
        if len(synth_seg) > target_slot_len and target_slot_len > 0:
            speed_ratio = len(synth_seg) / target_slot_len
            if speed_ratio > 1.0:
                speed_ratio = min(speed_ratio, 1.3)
                synth_seg = synth_seg.speedup(playback_speed=speed_ratio)

        final_canvas = final_canvas.overlay(synth_seg, position=start_ms)

    final_canvas.export(OUTPUT_DUBBED_AUDIO, format="wav")
    print(f"Dubbed audio timeline rendered to: {OUTPUT_DUBBED_AUDIO}")


# 5. MERGE DUBBED AUDIO WITH VIDEO
def remux_video(original_video, new_audio, output_file):
    print(f"\n--- Step 5: Remuxing new {TARGET_LANGUAGE} audio track into original video ---")
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", original_video,
        "-i", new_audio,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_file
    ]
    subprocess.run(cmd, check=True)
    print(f"\nFinal dubbed video successfully created: {output_file}")


def main():
    if not os.path.exists(INPUT_VIDEO):
        raise FileNotFoundError(f"Place your input video at: '{INPUT_VIDEO}'")

    extract_audio(INPUT_VIDEO, INTERMEDIATE_AUDIO)
    subs = transcribe_to_srt(INTERMEDIATE_AUDIO, ORIGINAL_SRT)
    translated_subs = translate_subtitles_ollama(subs)
    dub_with_xtts(translated_subs, INTERMEDIATE_AUDIO)
    remux_video(INPUT_VIDEO, OUTPUT_DUBBED_AUDIO, FINAL_VIDEO)


if __name__ == "__main__":
    main()