import array
import io
import json
import math
import subprocess
import wave


class AudioError(Exception):
    pass


def run(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError("音频工具不可用或处理超时") from exc
    if result.returncode:
        raise AudioError("无法解析此音频，请使用有效的WAV、MP3、M4A、FLAC、OGG或WebM文件")
    return result.stdout


def inspect(path, settings):
    output = run([settings.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration:stream=codec_type,sample_rate,channels,duration", "-of", "json", str(path)], 30)
    value = json.loads(output)
    streams = [s for s in value.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise AudioError("文件中没有可用音轨")
    stream = streams[0]
    duration = float(value.get("format", {}).get("duration") or stream.get("duration") or 0)
    if not math.isfinite(duration) or duration < 0:
        raise AudioError("音频时长不合法")
    if duration > settings.max_seconds:
        raise AudioError("首版单文件最长支持3小时")
    return {"duration": duration, "channels": int(stream.get("channels", 1))}


def prepare(source, target, channel, settings):
    info = inspect(source, settings)
    if channel == "right" and info["channels"] < 2:
        raise AudioError("此文件只有一个声道，不能选择右声道")
    command = [settings.ffmpeg, "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:a:0", "-vn"]
    if channel in ("left", "right"):
        command += ["-af", "pan=mono|c0=c" + ("0" if channel == "left" else "1")]
    command += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-t", str(settings.max_seconds + 1), str(target)]
    run(command, 240)
    with wave.open(str(target), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if duration <= 0 or duration > settings.max_seconds:
            raise AudioError("音频为空或超过3小时时长上限")
        frames_per_bin = max(1, math.ceil(audio.getnframes() / 240))
        peaks = []
        while data := audio.readframes(frames_per_bin):
            values = array.array("h", data)
            peak = max((abs(v) for v in values[::16]), default=0) / 32768
            peaks.append(round(peak, 4))
    return duration, peaks


def segments(path, seconds):
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        index = 0
        while frames := source.readframes(rate * seconds):
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(frames)
            start = index * seconds
            yield index, start, start + len(frames) / (2 * rate), buffer.getvalue()
            index += 1
