from __future__ import annotations

from pathlib import Path


def srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def ass_time(ms: int) -> str:
    ms = max(0, int(ms))
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    centiseconds = (ms % 1000) // 10
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def ass_escape(text: str) -> str:
    # ASS treats {...} as style override blocks. Fullwidth braces keep visible text
    # from being parsed as a rendering command when model output contains braces.
    return (
        text.replace("\\", "\\\\")
        .replace("{", "｛")
        .replace("}", "｝")
        .replace("\r\n", "\\N")
        .replace("\n", "\\N")
    )


def wrap_ass_text(text: str, max_chars: int = 20) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text

    break_marks = "，,。！？!?；;、 "
    lines: list[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars and char in break_marks:
            lines.append(current.strip())
            current = ""
        elif len(current) >= max_chars + 6:
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    if len(lines) <= 2:
        return "\\N".join(lines)
    return "\\N".join([lines[0], "".join(lines[1:])])


def write_items_srt(items: list[dict], path: Path) -> None:
    blocks = []
    index = 1
    for item in items:
        text = str(item.get("text", "")).strip()
        start = int(item.get("start_ms", item.get("start_time_ms", 0)))
        end = int(item.get("end_ms", item.get("end_time_ms", start + 2500)))
        if not text or end <= start:
            continue
        blocks.append(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
        index += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


def write_items_ass(items: list[dict], path: Path, title: str = "StreamSense Subtitle Agent", variant: str = "clean") -> None:
    """导出带样式的 ASS 字幕。

    SRT 基本不支持样式；ASS 可以控制字体、描边、阴影和位置。
    这个样式偏视频成片使用：清晰、不抢画面、手机和桌面都容易看。
    """

    if variant == "creator":
        font_size = 58
        margin_v = 112
        outline = 4.2
        shadow = 1.4
        secondary = "&H0038BDF8"
    else:
        font_size = 52
        margin_v = 92
        outline = 3.4
        shadow = 1.1
        secondary = "&H00E5E7EB"

    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AgentMain, Microsoft YaHei UI, {font_size}, &H00FFFFFF, {secondary}, &H00101010, &H82000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, {outline}, {shadow}, 2, 170, 170, {margin_v}, 1
Style: AgentEmphasis, Microsoft YaHei UI, {font_size + 4}, &H00F9FAFB, &H00FACC15, &H00000000, &H90000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, {outline + 0.4}, {shadow + 0.2}, 2, 170, 170, {margin_v + 4}, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip()]
    for item in items:
        start = int(item.get("start_ms", item.get("start_time_ms", 0)))
        end = int(item.get("end_ms", item.get("end_time_ms", start + 2500)))
        text = wrap_ass_text(ass_escape(str(item.get("text", ""))))
        if not text or end <= start:
            continue
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},AgentMain,,0,0,0,,{text}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_items_text(items: list[dict], path: Path) -> None:
    lines = [str(item.get("text", "")).strip() for item in items if str(item.get("text", "")).strip()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
