# dub_pipeline.py

import os
import subprocess
import torch
import pysrt
import ollama
from pydub import AudioSegment

# Apple Silicon FFmpeg binary paths fallback
if os.path.exists("/opt/homebrew/bin/ffmpeg"):
    AudioSegment.converter = "/opt/homebrew/bin/ffmpeg"
    AudioSegment.ffprobe = "/opt/homebrew/bin/ffprobe"
    FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
else:
    FFMPEG_BIN = "ffmpeg"

# Monkey-patch isin_mps_friendly for modern transformers & Coqui
import transformers.pytorch_utils
if not hasattr(transformers.pytorch_utils, "isin_mps_friendly"):
    def isin_mps_friendly(elements, test_elements):
        return torch.isin(elements, test_elements)
    transformers.pytorch_utils.isin_mps_friendly = isin_mps_friendly

# Patch XTTS num2words missing languages
import TTS.tts.layers.xtts.tokenizer as xtts_tok
from num2words import num2words

def safe_expand_number(m, lang):
    try:
        return num2words(int(m.group(0)), lang=lang)
    except (NotImplementedError, KeyError):
        return m.group(0)

xtts_tok._expand_number = safe_expand_number

import whisper
from TTS.api import TTS

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def extract_audio(video_path, audio_path, log_fn=print):
    log_fn("Step 1: Extracting clean 16kHz WAV from video...")
    cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def transcribe_to_srt(audio_path, srt_output_path, src_lang_name, src_lang_code, log_fn=print):
    log_fn(f"Step 2: Transcribing {src_lang_name} speech with Whisper...")
    model = whisper.load_model("medium", device="cpu")
    result = model.transcribe(audio_path, language=src_lang_code, task="transcribe")

    subs = pysrt.SubRipFile()
    for i, seg in enumerate(result["segments"], start=1):
        start = pysrt.SubRipTime(milliseconds=int(seg["start"] * 1000))
        end = pysrt.SubRipTime(milliseconds=int(seg["end"] * 1000))
        item = pysrt.SubRipItem(index=i, start=start, end=end, text=seg["text"].strip())
        subs.append(item)

    subs.save(srt_output_path, encoding="utf-8")
    log_fn(f"Source subtitles saved to: {srt_output_path}")
    return subs


def translate_subtitles_ollama(subs, srt_output_path, model_name, src_lang_name, tgt_lang_name, log_fn=print):
    log_fn(f"Step 3: Translating segments with Ollama ({model_name})...")
    translated_subs = pysrt.SubRipFile()

    for item in subs:
        src_text = item.text.strip()
        if not src_text:
            continue

        response = ollama.chat(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a professional film translator. Translate this {src_lang_name} subtitle "
                        f"line directly into natural {tgt_lang_name}. "
                        f"CRITICAL: Always write all numbers, figures, and dates as spelled-out words in {tgt_lang_name} script "
                        f"(never use digits like 1, 2, 9, 10). "
                        "Return ONLY the translated line, without quotes, explanations, or notes."
                    ),
                },
                {"role": "user", "content": src_text},
            ],
            options={"temperature": 0.2},
        )

        tr_text = response["message"]["content"].strip()
        log_fn(f"[{src_lang_name[:2].upper()}]: {src_text} -> [{tgt_lang_name[:2].upper()}]: {tr_text}")

        tr_item = pysrt.SubRipItem(
            index=item.index,
            start=item.start,
            end=item.end,
            text=tr_text,
        )
        translated_subs.append(tr_item)

    translated_subs.save(srt_output_path, encoding="utf-8")
    log_fn(f"Translated subtitles saved to: {srt_output_path}")
    return translated_subs


def dub_with_xtts(translated_subs, reference_audio_path, output_audio_path, voice_sample_path, temp_dir, tgt_lang_code, log_fn=print):
    log_fn("Step 4: Synthesizing dubbed audio with cloned voice via XTTS-v2...")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)

    orig_audio = AudioSegment.from_wav(reference_audio_path)
    final_canvas = AudioSegment.silent(duration=len(orig_audio))

    sample_len = min(12000, len(orig_audio))
    orig_audio[0:sample_len].export(voice_sample_path, format="wav")

    for item in translated_subs:
        start_ms = (item.start.hours * 3600 + item.start.minutes * 60 + item.start.seconds) * 1000 + item.start.milliseconds
        end_ms = (item.end.hours * 3600 + item.end.minutes * 60 + item.end.seconds) * 1000 + item.end.milliseconds
        target_slot_len = end_ms - start_ms

        line = item.text.strip()
        if not line:
            continue

        temp_out = os.path.join(temp_dir, f"segment_{item.index}.wav")
        log_fn(f"Synthesizing [{item.index}/{len(translated_subs)}]: {line}")

        tts.tts_to_file(
            text=line,
            file_path=temp_out,
            speaker_wav=voice_sample_path,
            language=tgt_lang_code
        )

        synth_seg = AudioSegment.from_wav(temp_out)

        if len(synth_seg) > target_slot_len and target_slot_len > 0:
            speed_ratio = len(synth_seg) / target_slot_len
            if speed_ratio > 1.0:
                speed_ratio = min(speed_ratio, 1.3)
                synth_seg = synth_seg.speedup(playback_speed=speed_ratio)

        final_canvas = final_canvas.overlay(synth_seg, position=start_ms)

    final_canvas.export(output_audio_path, format="wav")
    log_fn(f"Dubbed audio rendered to: {output_audio_path}")


def remux_video(original_video, new_audio, output_file, log_fn=print):
    log_fn("Step 5: Remuxing audio track into video...")
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
    log_fn(f"Pipeline finished! Final output video: {output_file}")